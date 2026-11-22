"""Flask framework plugin for code intelligence."""

import ast
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analyzers import project_graph
from ..analyzers.jedi_analyzer import _scope_key
from ..async_utils import filtered_rglob, pruned_rglob
from ..path_utils import path_to_key, relative_within
from ..project_layout import module_name_for_file
from ..resolver import Resolved, resolve_item
from .base import AnalyzerPlugin, Scope
from .detection import Detection, declares, scan_for_imports

logger = logging.getLogger(__name__)

#: The url registry's kind in ``project_graph``'s store (#1034).
_URL_REGISTRY = "flask_url_registry"


def _str_value(node: ast.AST) -> str | None:
    """Return the value of a string-literal node, else ``None``.

    Uses ``ast.Constant`` only: the legacy string/number node classes were
    removed in Python 3.14 (#622).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


# A handler may be ``async def`` (Flask 2.0+); both are scanned (#873).
_FUNCTION_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)

# Flask 2.0's route shortcuts: ``@app.get(path)`` is ``route(path, methods=["GET"])`` (#905).
_ROUTE_SHORTCUTS = frozenset({"get", "post", "put", "delete", "patch"})

_BLUEPRINT = frozenset({"Blueprint"})
# What a route shortcut's receiver must be bound to, in the same file (#905).
_FLASK_ROUTE_OWNERS = frozenset({"Flask", "Blueprint"})


def _may_declare_routes(content: str) -> bool:
    """Cheap text pre-filter: could *content* hold a route decorator?"""
    return "route" in content or any(f".{m}(" in content for m in _ROUTE_SHORTCUTS)


# Config files: at a scope root or one directory below it (#873).
_CONFIG_FILE_PATTERNS = ("config.py", "settings.py", "*/config.py", "*/settings.py")


def _constructor_assignment(
    node: ast.AST, classes: frozenset[str]
) -> tuple[str, ast.Call, int] | None:
    """``(target, call, line)`` when *node* binds a name to a call of one of *classes*.

    Accepts ``bp = Blueprint(...)``, ``bp = <module>.Blueprint(...)`` (such as
    ``flask.Blueprint`` or an aliased import) and the annotated forms of both
    (#873). An annotation with no value binds nothing and is not a match.
    """
    if isinstance(node, ast.Assign) and node.targets:
        target, value = node.targets[0], node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target, value = node.target, node.value
    else:
        return None
    if not (isinstance(target, ast.Name) and isinstance(value, ast.Call)):
        return None
    func = value.func
    if (isinstance(func, ast.Name) and func.id in classes) or (
        isinstance(func, ast.Attribute) and func.attr in classes
    ):
        return target.id, value, target.lineno
    return None


def _flask_route_owners(tree: ast.AST) -> set[str]:
    """Names this file binds, anywhere, to a ``Flask(...)`` or ``Blueprint(...)`` call.

    Covers module-level objects and the app factory's local ``app``. A
    blueprint or app imported from another module is not among them (#905).
    """
    owners = set()
    for node in ast.walk(tree):
        found = _constructor_assignment(node, _FLASK_ROUTE_OWNERS)
        if found is not None:
            owners.add(found[0])
    return owners


def _import_bindings(tree: ast.AST) -> dict[str, tuple[int, str, str | None]]:
    """Names this file binds by import: ``local -> (level, module, imported name)``.

    ``import a.b`` binds ``a`` to ``(0, "a", None)``; ``import a.b as c`` binds
    ``c`` to ``(0, "a.b", None)``; ``from .m import x as y`` binds ``y`` to
    ``(1, "m", "x")``. A star import binds nothing nameable.
    """
    bindings: dict[str, tuple[int, str, str | None]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = (0, alias.name, None)
                else:
                    top = alias.name.split(".")[0]
                    bindings[top] = (0, top, None)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = (
                        node.level,
                        node.module or "",
                        alias.name,
                    )
    return bindings


def _receiver_chain(receiver: ast.expr) -> list[str] | None:
    """``["blueprints", "bp"]`` for ``blueprints.bp``; ``None`` unless names all the way down."""
    parts: list[str] = []
    while isinstance(receiver, ast.Attribute):
        parts.append(receiver.attr)
        receiver = receiver.value
    if not isinstance(receiver, ast.Name):
        return None
    parts.append(receiver.id)
    return parts[::-1]


def _flask_bindings(tree: ast.AST) -> dict[str, str | None]:
    """The names a module binds from Flask imports (#951).

    Maps each local name to the Flask name it was imported as, or to ``None``
    for a module (whose attributes are Flask names): ``from flask import
    render_template as rt`` binds ``rt -> "render_template"``, ``import flask``
    binds ``flask -> None``, ``import flask.views as fv`` binds ``fv -> None``,
    and ``from flask import views`` binds ``views -> "views"`` (an attribute of
    it is still a Flask name). Relative imports are never Flask.
    """
    bound: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "flask" or alias.name.startswith("flask."):
                    bound[alias.asname or alias.name.split(".", 1)[0]] = None
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module == "flask" or module.startswith("flask."):
                for alias in node.names:
                    if alias.name != "*":
                        bound[alias.asname or alias.name] = alias.name
    return bound


def _names_flask(expr: ast.expr, name: str, bound: dict[str, str | None]) -> bool:
    """Whether *expr* refers to Flask's *name*, by the module's own imports (#951).

    A bare name imported from Flask as *name* (through an alias too), or an
    attribute chain ending in *name* whose root was imported from Flask
    (``flask.render_template``, ``fv.MethodView``). A local definition that
    merely shares the name doesn't count.
    """
    if isinstance(expr, ast.Name):
        return bound.get(expr.id, "") == name
    chain = _receiver_chain(expr) if isinstance(expr, ast.Attribute) else None
    return chain is not None and chain[-1] == name and chain[0] in bound


def _template_argument(call: ast.Call) -> str | None:
    """The template a ``render_template`` call names: first positional, or the keyword."""
    if call.args:
        return _str_value(call.args[0])
    keyword = next((k for k in call.keywords if k.arg == "template_name_or_list"), None)
    return _str_value(keyword.value) if keyword is not None else None


#: A prefix option that isn't a string literal (#952): its value can't be known.
_DYNAMIC = "<dynamic>"


@dataclass(frozen=True)
class _Owner:
    """A ``Flask(...)`` app or a ``Blueprint(...)``: its constructor prefix (#952)."""

    is_app: bool
    prefix: str | None  # the literal, None when absent, or _DYNAMIC
    subdomain: bool


def _prefix_option(call: ast.Call) -> tuple[str | None, bool]:
    """The ``url_prefix`` a constructor or ``register_blueprint`` call gives, and any subdomain.

    A string literal, ``None`` when absent or a literal ``None``, else
    :data:`_DYNAMIC`; a ``**`` splat may set either, so it is dynamic too.
    """
    prefix: str | None = None
    subdomain = False
    for keyword in call.keywords:
        if keyword.arg is None:
            return _DYNAMIC, True
        if keyword.arg == "url_prefix":
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value is None:
                prefix = None
            else:
                literal = _str_value(value)
                prefix = literal if literal is not None else _DYNAMIC
        elif keyword.arg == "subdomain":
            subdomain = True
    return prefix, subdomain


def _join(prefix: str | None, rule: str) -> str:
    """Flask's join of a prefix and a rule (``BlueprintSetupState.add_url_rule``)."""
    if prefix is None:
        return rule
    return "/".join((prefix.rstrip("/"), rule.lstrip("/"))) if rule else prefix


class _UrlRegistry:
    """Each blueprint's registrations, and the served prefixes they give (#952).

    Composition follows Flask: a registration's ``url_prefix`` overrides the
    blueprint's own; a nested blueprint joins its parent's prefix. A prefix is
    known only when EVERY registration of the blueprint and of each parent is a
    string literal (or absent) on a placed app or blueprint, with no subdomain
    and no cycle; otherwise it is ``None`` (omitted, never partial). A
    registration whose blueprint can't be placed makes every answer unknown,
    since it might be any of them.
    """

    def __init__(self, owners: dict[str, _Owner]) -> None:
        self.owners = owners
        self._registrations: dict[str, list[tuple[str | None, str | None, bool]]] = {}
        self._unplaced_registration = False

    def register(
        self, child: str | None, parent: str | None, prefix: str | None, subdomain: bool
    ) -> None:
        if child is None:
            self._unplaced_registration = True
            return
        self._registrations.setdefault(child, []).append((parent, prefix, subdomain))

    def prefixes(self, key: str, seen: frozenset[str] = frozenset()) -> list[str | None] | None:
        """The effective prefixes of *key*, or ``None`` if unknown; a ``None`` entry means no prefix."""
        owner = self.owners.get(key)
        if owner is None or self._unplaced_registration or key in seen:
            return None
        if owner.is_app:
            return [None]
        if owner.subdomain or owner.prefix == _DYNAMIC:
            return None
        registrations = self._registrations.get(key)
        if not registrations:
            return None  # never registered in scope: maybe elsewhere, maybe not served
        found: list[str | None] = []
        for parent, prefix, subdomain in registrations:
            if parent is None or subdomain or prefix == _DYNAMIC:
                return None
            own = prefix if prefix is not None else owner.prefix
            parents = self.prefixes(parent, seen | {key})
            if parents is None:
                return None
            for outer in parents:
                if outer is not None and own is not None:
                    found.append(outer.rstrip("/") + "/" + own.lstrip("/"))
                else:
                    found.append(own if own is not None else outer)
        return found

    def urls(self, owner: str | None, rule: str) -> list[str] | None:
        """The served URLs of a route with *rule* on *owner*, sorted, or ``None`` if unknown."""
        prefixes = self.prefixes(owner) if owner is not None else None
        if prefixes is None:
            return None
        return sorted({_join(prefix, rule) for prefix in prefixes})


def _cli_command_name(decorator: ast.expr, function: str) -> str | None:
    """The CLI command *decorator* registers for *function*, or ``None`` if it isn't one.

    Recognised: ``@<app or blueprint>.cli.command`` with or without a call
    (#980), named by its first argument when that is a string literal, else by
    the function; and a bare ``@command`` (Click's, imported by name).
    """
    call = decorator if isinstance(decorator, ast.Call) else None
    target = call.func if call is not None else decorator
    if (
        isinstance(target, ast.Attribute)
        and target.attr == "command"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "cli"
    ):
        if call is not None and call.args:
            return _str_value(call.args[0]) or function
        return function
    if call is None and isinstance(decorator, ast.Name) and decorator.id == "command":
        return function
    return None


def _absolute_module(level: int, module: str, importer: str | None, is_package: bool) -> str | None:
    """The absolute module a ``from`` import of *level* names, or ``None`` if it can't be named."""
    if level == 0:
        return module
    if importer is None:
        return None
    package = importer.split(".") if is_package else importer.split(".")[:-1]
    drop = level - 1  # each extra dot climbs one package
    if drop >= len(package):
        return None
    base = package[: len(package) - drop]
    return ".".join([*base, module] if module else base)


def _template_name(template_file: Path, template_dir: Path) -> str:
    """A template's name: its path below the templates directory, POSIX form (#717)."""
    rel = relative_within(template_file, template_dir)
    return rel.as_posix() if rel is not None else template_file.name


class FlaskPlugin(AnalyzerPlugin):
    """Plugin for Flask-specific code intelligence."""

    def name(self) -> str:
        """Return the plugin name."""
        return "Flask"

    def detect(self) -> bool:
        """Detect if this is a Flask project."""
        return self.detection() == "detected"

    def detection(self) -> Detection:
        """Flask imported by an entry point or declared, else imported in a bounded scan (#1143)."""
        markers = ("from flask import", "import flask")
        for file_name in ("app.py", "application.py", "wsgi.py", "run.py"):
            file_path = self.project_path / file_name
            if file_path.exists():
                content = self._read_text_or_skip(file_path)
                if content is not None and any(marker in content for marker in markers):
                    return "detected"
        if declares(self.project_path, "flask"):
            return "detected"
        return scan_for_imports(self.project_path, markers, self._read_text_or_skip)

    def register_tools(self) -> dict[str, Callable]:
        """Register Flask-specific tools."""
        return {
            "find_flask_routes": self.find_routes,
            "find_flask_blueprints": self.find_blueprints,
            "find_flask_views": self.find_views,
            "find_flask_templates": self.find_templates,
            "find_flask_extensions": self.find_extensions,
            "find_flask_config": self.find_config,
            "find_error_handlers": self.find_error_handlers,
            "find_cli_commands": self.find_cli_commands,
        }

    async def find_routes(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Flask routes in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        routes = []
        placed: dict[str, bool] = {}  # imported receiver path -> is a Flask owner (#910)
        registry = await self._url_registry(scope)  # served URLs (#952)
        analyzer = self._analyzer()

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "@" in content and _may_declare_routes(content):
                tree = self._parse_source(py_file, content)
                if tree is not None:
                    owners = _flask_route_owners(tree)
                    module = module_name_for_file(analyzer, py_file)
                    bindings: dict[str, tuple[int, str, str | None]] | None = None
                    for node in ast.walk(tree):
                        if isinstance(node, _FUNCTION_DEFS):
                            # Check for route decorators
                            for decorator in node.decorator_list:
                                route_path = None
                                methods = ["GET"]  # Default method

                                # Handle @app.route() or @blueprint.route()
                                if (
                                    isinstance(decorator, ast.Call)
                                    and isinstance(decorator.func, ast.Attribute)
                                    and decorator.func.attr == "route"
                                ):
                                    # Extract route path
                                    if decorator.args:
                                        route_path = _str_value(decorator.args[0])

                                    # Extract methods if specified
                                    for keyword in decorator.keywords:
                                        if keyword.arg == "methods" and isinstance(
                                            keyword.value, ast.List
                                        ):
                                            methods = []
                                            for elt in keyword.value.elts:
                                                method = _str_value(elt)
                                                if method is not None:
                                                    methods.append(method)

                                # @app.get("/p"), .post, .put, .delete, .patch (#905):
                                # route() with one fixed method. Only on a receiver
                                # bound to Flask(...) or Blueprint(...), in this file
                                # or, through an import, in the module it names
                                # (#910). So FastAPI's @router.get or @cache.get("k")
                                # is not a route; and the path must be a string.
                                elif (
                                    isinstance(decorator, ast.Call)
                                    and isinstance(decorator.func, ast.Attribute)
                                    and decorator.func.attr in _ROUTE_SHORTCUTS
                                    and decorator.args
                                    and _str_value(decorator.args[0]) is not None
                                ):
                                    receiver = decorator.func.value
                                    is_owner = isinstance(receiver, ast.Name) and (
                                        receiver.id in owners
                                    )
                                    if not is_owner:
                                        if bindings is None:
                                            bindings = _import_bindings(tree)
                                        is_owner = await self._imported_route_owner(
                                            receiver, bindings, py_file, placed
                                        )
                                    if is_owner:
                                        route_path = _str_value(decorator.args[0])
                                        methods = [decorator.func.attr.upper()]

                                # "" is a valid rule on a blueprint: the prefix itself.
                                if route_path is not None:
                                    route: dict[str, Any] = {
                                        "name": node.name,
                                        "file": py_file.as_posix(),
                                        "line": node.lineno,
                                        "path": route_path,
                                        "methods": methods,
                                        "type": "route",
                                    }
                                    if bindings is None:
                                        bindings = _import_bindings(tree)
                                    assert isinstance(decorator, ast.Call)  # noqa: S101
                                    assert isinstance(decorator.func, ast.Attribute)  # noqa: S101
                                    owner = (
                                        self._owner_key(
                                            decorator.func.value,
                                            module,
                                            owners,
                                            bindings,
                                            py_file,
                                            registry.owners,
                                        )
                                        if module is not None
                                        else None
                                    )
                                    urls = registry.urls(owner, route_path)
                                    if urls is not None:
                                        route["urls"] = urls
                                    routes.append(route)

        return routes

    async def _imported_route_owner(
        self,
        receiver: ast.expr,
        bindings: dict[str, tuple[int, str, str | None]],
        py_file: Path,
        placed: dict[str, bool],
    ) -> bool:
        """Is *receiver* an imported name for a ``Flask(...)`` or ``Blueprint(...)`` binding? (#910).

        ``bp`` from ``from .blueprints import bp`` or ``blueprints.bp`` from
        ``from . import blueprints`` names a dotted path, which the canonical
        resolver places (following re-exports). The definition it lands on must
        itself bind a ``Flask``/``Blueprint`` call, checked on that file's AST, so
        an imported FastAPI router or cache stays out. Results are memoised in
        *placed* for the call. A receiver that isn't imported (a function
        parameter, say) is never placed.
        """
        path = self._imported_path(receiver, bindings, py_file)
        if path is None:
            return False
        if path not in placed:
            placed[path] = await self._binds_route_owner(path)
        return placed[path]

    def _imported_path(
        self, expr: ast.expr, bindings: dict[str, tuple[int, str, str | None]], py_file: Path
    ) -> str | None:
        """The dotted path an imported name (or an attribute of one) names, or ``None``."""
        chain = _receiver_chain(expr)
        if chain is None or chain[0] not in bindings:
            return None
        level, module, name = bindings[chain[0]]
        if level:
            importer = module_name_for_file(self._analyzer(), py_file)
            module_abs = _absolute_module(level, module, importer, py_file.name == "__init__.py")
        else:
            module_abs = module
        if not module_abs:
            return None
        head = f"{module_abs}.{name}" if name else module_abs
        return ".".join([head, *chain[1:]])

    async def _url_registry(self, scope: Scope) -> "_UrlRegistry":
        """The url registry for *scope*, built once per project generation (#1034).

        Cached in ``project_graph`` beside the class and import graphs, so the
        watcher, eviction and ``configure_packages`` drop it with them. It used
        to be rebuilt on every call, which made a warm ``find_flask_routes``
        ~2.3x slower (#957).
        """
        analyzer = self._analyzer()
        root = analyzer.project_path.as_posix()
        keys = {"layout_key": analyzer.layout_key, "scope_key": _scope_key(scope)}
        cached = project_graph.cached_graph(_URL_REGISTRY, root, **keys)
        if isinstance(cached, _UrlRegistry):
            return cached
        generation = project_graph.generation(root)  # before the build lists files
        registry = await self._build_url_registry(scope)
        project_graph.store_graph(_URL_REGISTRY, root, registry, generation, **keys)
        return registry

    async def _build_url_registry(self, scope: Scope) -> "_UrlRegistry":
        """Every Flask app and blueprint in *scope*, and each blueprint's registrations (#952)."""
        analyzer = self._analyzer()
        self._owner_paths: dict[str, str | None] = {}  # re-export -> handle, per call
        owners: dict[str, _Owner] = {}
        sites: list[tuple[Path, ast.AST, str, set[str]]] = []
        for py_file in await self.get_project_files("*.py", scope):
            content = await self._read_source(py_file)
            if content is None or ("Flask" not in content and "Blueprint" not in content):
                continue
            tree = self._parse_source(py_file, content)
            module = module_name_for_file(analyzer, py_file) if tree is not None else None
            if tree is None or module is None:
                continue
            names: set[str] = set()
            for node in ast.walk(tree):
                found = _constructor_assignment(node, _FLASK_ROUTE_OWNERS)
                if found is None:
                    continue
                target, call, _line = found
                func = call.func
                kind = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                prefix, subdomain = _prefix_option(call)
                owners[f"{module}.{target}"] = _Owner(kind == "Flask", prefix, subdomain)
                names.add(target)
            sites.append((py_file, tree, module, names))
        registry = _UrlRegistry(owners)
        for site_file, site_tree, site_module, site_names in sites:
            bindings: dict[str, tuple[int, str, str | None]] | None = None
            for node in ast.walk(site_tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "register_blueprint"
                ):
                    continue
                if bindings is None:
                    bindings = _import_bindings(site_tree)
                blueprint_expr = (
                    node.args[0]
                    if node.args
                    else next((k.value for k in node.keywords if k.arg == "blueprint"), None)
                )
                child = (
                    self._owner_key(
                        blueprint_expr, site_module, site_names, bindings, site_file, owners
                    )
                    if blueprint_expr is not None
                    else None
                )
                parent = self._owner_key(
                    node.func.value, site_module, site_names, bindings, site_file, owners
                )
                prefix, subdomain = _prefix_option(node)
                registry.register(child, parent, prefix, subdomain)
        return registry

    def _owner_key(
        self,
        expr: ast.expr,
        module: str,
        names: set[str],
        bindings: dict[str, tuple[int, str, str | None]],
        py_file: Path,
        owners: dict[str, "_Owner"],
    ) -> str | None:
        """The definition-site key of the app or blueprint *expr* names, or ``None``."""
        if isinstance(expr, ast.Name) and expr.id in names:
            key = f"{module}.{expr.id}"
            return key if key in owners else None
        path = self._imported_path(expr, bindings, py_file)
        if path is None:
            return None
        if path in owners:
            return path  # names its definition site directly: no resolver needed
        # A re-export: place it once per path per call, through the resolver.
        memo = self._owner_paths
        if path not in memo:
            found = resolve_item(path, self._analyzer())
            memo[path] = found.handle if isinstance(found, Resolved) else None
        handle = memo[path]
        return handle if handle in owners else None

    async def _binds_route_owner(self, path: str) -> bool:
        """Does the definition *path* resolves to bind a ``Flask``/``Blueprint`` call?"""
        found = resolve_item(path, self._analyzer())
        if not isinstance(found, Resolved):
            return False
        module_path = getattr(found.anchor, "module_path", None)
        line = getattr(found.anchor, "line", None)
        if module_path is None or not isinstance(line, int):
            return False
        target_file = Path(module_path)
        content = await self._read_source(target_file)
        tree = self._parse_source(target_file, content) if content is not None else None
        if tree is None:
            return False
        name = found.handle.rsplit(".", 1)[-1]
        for node in ast.walk(tree):
            match = _constructor_assignment(node, _FLASK_ROUTE_OWNERS)
            if match is not None and match[0] == name and match[2] == line:
                return True
        return False

    async def find_blueprints(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Flask blueprints in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        blueprints = []
        registry = await self._url_registry(scope)  # effective prefixes (#952)
        analyzer = self._analyzer()

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "Blueprint" in content:
                tree = self._parse_source(py_file, content)
                if tree is not None:
                    for node in ast.walk(tree):
                        found = _constructor_assignment(node, _BLUEPRINT)
                        if found is not None:
                            target, call, line = found
                            bp_name = _str_value(call.args[0]) if call.args else None
                            url_prefix = None
                            for keyword in call.keywords:
                                if keyword.arg == "url_prefix":
                                    url_prefix = _str_value(keyword.value)

                            record: dict[str, Any] = {
                                "name": target,
                                "blueprint_name": bp_name,
                                "file": py_file.as_posix(),
                                "line": line,
                                "url_prefix": url_prefix,
                                "type": "blueprint",
                            }
                            module = module_name_for_file(analyzer, py_file)
                            prefixes = registry.prefixes(f"{module}.{target}") if module else None
                            if prefixes is not None:
                                record["url_prefixes"] = sorted({p or "" for p in prefixes})
                            blueprints.append(record)

        return blueprints

    async def find_views(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Flask view functions and classes.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        # Seeds: classes whose base is Flask's MethodView by the module's own
        # imports (an alias or a module attribute too). Then every project class
        # below them through the one class graph, by definition site (#951).
        analyzer = self._analyzer()
        found: dict[str, dict[str, Any]] = {}
        queue: list[dict[str, Any]] = []
        for py_file in await self.get_project_files("*.py", scope):
            content = await self._read_source(py_file)
            if content is None or "flask" not in content:
                continue
            tree = self._parse_source(py_file, content)
            module = module_name_for_file(analyzer, py_file) if tree is not None else None
            if tree is None or module is None:
                continue
            bound = _flask_bindings(tree)
            if not bound:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(
                    _names_flask(base, "MethodView", bound) for base in node.bases
                ):
                    queue.append(
                        {
                            "name": node.name,
                            "full_name": f"{module}.{node.name}",
                            "file": py_file.as_posix(),
                            "line": node.lineno,
                        }
                    )
        while queue:
            view = queue.pop(0)
            if view["full_name"] in found:
                continue
            found[view["full_name"]] = view
            result = await analyzer.find_subclasses(view["full_name"], scope=scope)
            queue.extend(s for s in result.get("subclasses", []) if s.get("full_name"))

        return [
            {
                "name": view["name"],
                "file": Path(view["file"]).as_posix(),
                "line": view["line"],
                "type": "method_view",
            }
            for view in sorted(
                found.values(), key=lambda v: (Path(v["file"]).as_posix(), v["line"])
            )
        ]

    async def find_templates(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Flask templates and render_template calls.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        templates = []
        render_calls = []
        seen_templates: set[str] = set()  # app/templates matches two patterns (#951)

        # Find template files
        template_dirs = ["templates", "*/templates", "app/templates"]
        project_roots = await self._get_scope_roots(scope)

        for root in project_roots:
            for pattern in template_dirs:
                for template_dir in root.glob(pattern):
                    if template_dir.is_dir():
                        for template_file in pruned_rglob("*.html", template_dir):
                            if path_to_key(template_file) in seen_templates:
                                continue
                            seen_templates.add(path_to_key(template_file))
                            templates.append(
                                {
                                    "file": template_file.as_posix(),
                                    "name": _template_name(template_file, template_dir),
                                    "type": "template",
                                }
                            )
                        for template_file in pruned_rglob("*.jinja2", template_dir):
                            if path_to_key(template_file) in seen_templates:
                                continue
                            seen_templates.add(path_to_key(template_file))
                            templates.append(
                                {
                                    "file": template_file.as_posix(),
                                    "name": _template_name(template_file, template_dir),
                                    "type": "template",
                                }
                            )

        # Find render_template calls
        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "render_template" in content:
                tree = self._parse_source(py_file, content)
                bound = _flask_bindings(tree) if tree is not None else {}
                if tree is not None and bound:
                    for node in ast.walk(tree):
                        # Flask's render_template by this module's imports: bare,
                        # aliased or module-qualified; positional or keyword (#951).
                        if (
                            isinstance(node, ast.Call)
                            and _names_flask(node.func, "render_template", bound)
                            and (template_name := _template_argument(node)) is not None
                        ):
                            render_calls.append(
                                {
                                    "template": template_name,
                                    "file": py_file.as_posix(),
                                    "line": node.lineno,
                                    "type": "render_call",
                                }
                            )

        return [{"templates": templates, "render_calls": render_calls}]

    async def find_extensions(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find Flask extensions in use.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        extensions: list[dict[str, Any]] = []
        common_extensions = [
            "flask_sqlalchemy",
            "flask_migrate",
            "flask_login",
            "flask_wtf",
            "flask_cors",
            "flask_mail",
            "flask_restful",
            "flask_marshmallow",
            "flask_jwt_extended",
            "flask_socketio",
            "flask_admin",
            "flask_limiter",
        ]

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is None:
                continue
            for ext in common_extensions:
                if f"from {ext}" in content or f"import {ext}" in content:
                    # Parse to get more details
                    tree = self._parse_source(py_file, content)
                    if tree is not None:
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.Import, ast.ImportFrom)):
                                if isinstance(node, ast.ImportFrom):
                                    if node.module and ext in node.module:
                                        extensions.append(
                                            {
                                                "extension": ext,
                                                "file": py_file.as_posix(),
                                                "line": node.lineno,
                                                "type": "import",
                                            }
                                        )
                                elif isinstance(node, ast.Import):
                                    for alias in node.names:
                                        if ext in alias.name:
                                            extensions.append(
                                                {
                                                    "extension": ext,
                                                    "file": py_file.as_posix(),
                                                    "line": node.lineno,
                                                    "type": "import",
                                                }
                                            )

        # Remove duplicates
        seen: set[str] = set()
        unique_extensions: list[dict[str, Any]] = []
        for ext_info in extensions:
            if isinstance(ext_info, dict):
                key = f"{ext_info.get('extension', '')}:{ext_info.get('file', '')}"
                if key not in seen:
                    seen.add(key)
                    unique_extensions.append(ext_info)

        return unique_extensions

    async def find_config(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find Flask configuration files and app.config usage.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        configs: list[dict[str, Any]] = []

        # Config files: depth <= 1 below each root the scope names (#873)
        seen: set[str] = set()
        roots = sorted(await self._resolve_scope_to_paths(scope), key=path_to_key)
        for root in roots:
            for pattern in _CONFIG_FILE_PATTERNS:
                for config_file in sorted(root.glob(pattern)):
                    key = path_to_key(config_file)
                    if config_file.is_file() and key not in seen:
                        seen.add(key)
                        configs.append({"file": config_file.as_posix(), "type": "config_file"})

        # Find app.config usage
        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and ("app.config" in content or "current_app.config" in content):
                tree = self._parse_source(py_file, content)
                if tree is not None:
                    for node in ast.walk(tree):
                        # Look for config access patterns
                        # ``app.config`` / ``current_app.config``, also reached
                        # through an attribute (``self.app.config``,
                        # ``flask.current_app.config``, #951).
                        if isinstance(node, ast.Attribute) and node.attr == "config":
                            receiver = node.value
                            receiver_name = (
                                receiver.id
                                if isinstance(receiver, ast.Name)
                                else getattr(receiver, "attr", None)
                            )
                            if receiver_name in ("app", "current_app"):
                                configs.append(
                                    {
                                        "file": py_file.as_posix(),
                                        "line": node.lineno,
                                        "type": "config_access",
                                    }
                                )

        return configs

    async def find_error_handlers(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find error handler functions.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        handlers = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "errorhandler" in content:
                tree = self._parse_source(py_file, content)
                if tree is not None:
                    for node in ast.walk(tree):
                        if isinstance(node, _FUNCTION_DEFS):
                            for decorator in node.decorator_list:
                                # Check for @app.errorhandler()
                                if isinstance(decorator, ast.Call):
                                    if isinstance(decorator.func, ast.Attribute):
                                        if decorator.func.attr == "errorhandler":
                                            error_code = None
                                            if decorator.args:
                                                if isinstance(decorator.args[0], ast.Constant):
                                                    error_code = decorator.args[0].value
                                                elif isinstance(decorator.args[0], ast.Name):
                                                    error_code = decorator.args[0].id

                                            handlers.append(
                                                {
                                                    "name": node.name,
                                                    "file": py_file.as_posix(),
                                                    "line": node.lineno,
                                                    "error_code": error_code,
                                                    "type": "error_handler",
                                                }
                                            )

        return handlers

    async def find_cli_commands(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find Flask CLI commands.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        commands = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "@" in content and "cli" in content:
                tree = self._parse_source(py_file, content)
                if tree is not None:
                    for node in ast.walk(tree):
                        if isinstance(node, _FUNCTION_DEFS):
                            for decorator in node.decorator_list:
                                command_name = _cli_command_name(decorator, node.name)
                                if command_name is not None:
                                    commands.append(
                                        {
                                            "name": command_name,
                                            "function": node.name,
                                            "file": py_file.as_posix(),
                                            "line": node.lineno,
                                            "type": "cli_command",
                                        }
                                    )

        return commands

    def get_framework_components(self) -> dict[str, list[str]]:
        """Get Flask framework components."""
        components: dict[str, list[str]] = {
            "routes": [],
            "blueprints": [],
            "templates": [],
            "static": [],
            "models": [],
            "forms": [],
        }

        # Find route files
        for py_file in filtered_rglob("*.py", self.project_path):
            content = self._read_text_or_skip(py_file)
            if content is not None and "@" in content and "route" in content:
                components["routes"].append(py_file.as_posix())

        # Find blueprint files
        for py_file in filtered_rglob("*.py", self.project_path):
            content = self._read_text_or_skip(py_file)
            if content is not None and "Blueprint" in content:
                components["blueprints"].append(py_file.as_posix())

        # Find template directories
        for template_dir in filtered_rglob("templates", self.project_path):
            if template_dir.is_dir():
                components["templates"].append(template_dir.as_posix())

        # Find static directories
        for static_dir in filtered_rglob("static", self.project_path):
            if static_dir.is_dir():
                components["static"].append(static_dir.as_posix())

        # Find models (SQLAlchemy)
        for models_file in filtered_rglob("models.py", self.project_path):
            components["models"].append(models_file.as_posix())

        # Find forms (WTForms)
        for forms_file in filtered_rglob("forms.py", self.project_path):
            components["forms"].append(forms_file.as_posix())

        return components
