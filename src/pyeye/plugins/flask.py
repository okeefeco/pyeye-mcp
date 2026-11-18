"""Flask framework plugin for code intelligence."""

import ast
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..async_utils import filtered_rglob, pruned_rglob
from ..path_utils import path_to_key, relative_within
from ..project_layout import module_name_for_file
from ..resolver import Resolved, resolve_item
from .base import AnalyzerPlugin, Scope

logger = logging.getLogger(__name__)


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
        # Check for common Flask entry points
        common_files = ["app.py", "application.py", "wsgi.py", "run.py"]
        for file_name in common_files:
            file_path = self.project_path / file_name
            if file_path.exists():
                content = self._read_text_or_skip(file_path)
                if content is not None and (
                    "from flask import" in content or "import flask" in content
                ):
                    return True

        # Check for Flask in requirements
        requirements_files = [
            "requirements.txt",
            "requirements/base.txt",
            "Pipfile",
            "pyproject.toml",
        ]
        for req_file in requirements_files:
            req_path = self.project_path / req_file
            if req_path.exists():
                content = self._read_text_or_skip(req_path)
                if content is not None and "flask" in content.lower():
                    return True

        # Check for Flask imports in any Python files
        for py_file in filtered_rglob("*.py", self.project_path):
            if py_file.is_file():
                content = self._read_text_or_skip(py_file)
                if content is not None and (
                    "from flask import" in content or "import flask" in content
                ):
                    return True

        return False

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

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "@" in content and _may_declare_routes(content):
                tree = self._parse_source(py_file, content)
                if tree is not None:
                    owners = _flask_route_owners(tree)
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

                                if route_path:
                                    routes.append(
                                        {
                                            "name": node.name,
                                            "file": py_file.as_posix(),
                                            "line": node.lineno,
                                            "path": route_path,
                                            "methods": methods,
                                            "type": "route",
                                        }
                                    )

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
        chain = _receiver_chain(receiver)
        if chain is None or chain[0] not in bindings:
            return False
        level, module, name = bindings[chain[0]]
        if level:
            analyzer = self._analyzer()
            importer = module_name_for_file(analyzer, py_file)
            module_abs = _absolute_module(level, module, importer, py_file.name == "__init__.py")
        else:
            module_abs = module
        if not module_abs:
            return False
        head = f"{module_abs}.{name}" if name else module_abs
        path = ".".join([head, *chain[1:]])
        if path not in placed:
            placed[path] = await self._binds_route_owner(path)
        return placed[path]

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

                            blueprints.append(
                                {
                                    "name": target,
                                    "blueprint_name": bp_name,
                                    "file": py_file.as_posix(),
                                    "line": line,
                                    "url_prefix": url_prefix,
                                    "type": "blueprint",
                                }
                            )

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
                                # Check for @app.cli.command() or @click.command()
                                if isinstance(decorator, ast.Call):
                                    if isinstance(decorator.func, ast.Attribute):
                                        if decorator.func.attr == "command":
                                            # Check if it's app.cli.command
                                            if isinstance(decorator.func.value, ast.Attribute):
                                                if decorator.func.value.attr == "cli":
                                                    command_name = node.name
                                                    # Try to get custom command name
                                                    if decorator.args:
                                                        command_name = (
                                                            _str_value(decorator.args[0])
                                                            or command_name
                                                        )

                                                    commands.append(
                                                        {
                                                            "name": command_name,
                                                            "function": node.name,
                                                            "file": py_file.as_posix(),
                                                            "line": node.lineno,
                                                            "type": "cli_command",
                                                        }
                                                    )
                                elif isinstance(decorator, ast.Name):
                                    # Handle @click.command without parentheses
                                    if decorator.id == "command":
                                        commands.append(
                                            {
                                                "name": node.name,
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
