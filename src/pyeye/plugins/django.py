"""Django framework plugin for code intelligence."""

import ast
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..async_utils import filtered_rglob, pruned_rglob
from ..path_utils import path_to_key
from ..project_layout import module_name_for_file
from .base import AnalyzerPlugin, Scope

logger = logging.getLogger(__name__)

#: The ``framework`` of a view record (#947).
DJANGO = "django"
REST_FRAMEWORK = "rest_framework"

#: The module and package names whose files ``find_django_views`` reads (#941, #947).
_VIEW_MODULES = frozenset({"views", "viewsets", "api"})

#: A requirement line that names Django itself (#940): ``django``, ``Django==4.2``,
#: ``django>=3.2``, ``django[argon2]``, or a Pipfile's ``django = "*"``. A package
#: that merely starts with the name (``django-environ``, ``djangorestframework``)
#: is not Django, and a comment never counts.
_DJANGO_REQUIREMENT = re.compile(
    r"""^\s*["']?django["']?\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;@,]|$)""",
    re.IGNORECASE | re.MULTILINE,
)
_COMMENT = re.compile(r"#.*$", re.MULTILINE)


def requires_django(text: str) -> bool:
    """Whether a requirements file or Pipfile *text* names Django as a requirement."""
    return _DJANGO_REQUIREMENT.search(_COMMENT.sub("", text)) is not None


class DjangoPlugin(AnalyzerPlugin):
    """Plugin for Django-specific code intelligence."""

    def name(self) -> str:
        """Return the plugin name."""
        return "Django"

    def detect(self) -> bool:
        """Detect if this is a Django project: Django is required or imported (#940).

        A ``manage.py`` alone is not evidence: other tools use the name
        (Flask-Script). Django's own generated ``manage.py`` imports Django, so
        the import check below finds it.
        """
        # Check for Django in requirements
        requirements_files = ["requirements.txt", "requirements/base.txt", "Pipfile"]
        for req_file in requirements_files:
            req_path = self.project_path / req_file
            if req_path.exists():
                content = self._read_text_or_skip(req_path)
                if content is not None and requires_django(content):
                    return True

        # Check for Django imports in Python files
        for py_file in self.project_path.glob("*.py"):
            content = self._read_text_or_skip(py_file)
            if content is not None and ("from django" in content or "import django" in content):
                return True

        return False

    def register_tools(self) -> dict[str, Callable]:
        """Register Django-specific tools."""
        return {
            "find_django_models": self.find_models,
            "find_django_views": self.find_views,
            "find_django_urls": self.find_urls,
            "find_django_templates": self.find_templates,
            "find_django_migrations": self.find_migrations,
        }

    async def find_models(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Django models in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        models = []

        # Look for models.py files
        models_files = await self.get_project_files("models.py", scope)
        for models_file in models_files:
            content = await self._read_source(models_file)
            if content is not None and (
                "from django.db import models" in content or "Model" in content
            ):
                tree = self._parse_source(models_file, content)
                if tree is not None:

                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            # Check if it inherits from Model
                            for base in node.bases:
                                if (isinstance(base, ast.Name) and base.id == "Model") or (
                                    isinstance(base, ast.Attribute) and base.attr == "Model"
                                ):
                                    models.append(
                                        {
                                            "name": node.name,
                                            "file": models_file.as_posix(),
                                            "line": node.lineno,
                                            "type": "django_model",
                                        }
                                    )

        return models

    async def find_views(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Django and Django REST framework views in the project.

        Every record carries ``framework``: ``"django"`` or ``"rest_framework"``
        (#947). The files read are each ``views.py``, ``viewsets.py`` and
        ``api.py``, and every module of a ``views``, ``viewsets`` or ``api``
        package, when the file imports ``django`` or ``rest_framework``.

        Class views are classes with a base the module imports from Django
        (#941) or from ``rest_framework`` (``APIView``, the generic views,
        the ``ViewSet`` classes, #947), and the project classes that subclass those,
        directly or through other project classes (#942). A subclass of a
        ``rest_framework`` view is ``rest_framework``. Function views are
        functions decorated with ``rest_framework``'s ``@api_view``, and
        functions, ``async`` or not, whose first parameter is ``request``.

        Cost: following subclasses uses the project's class graph, the one
        ``expand(subclasses)`` and ``find_pydantic_models`` share. The first
        call that needs it builds it, a scan of every file in scope; later calls
        reuse it until a file changes. A project with no class views never
        builds it.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        views: list[dict[str, Any]] = []
        seeds: dict[str, dict[str, Any]] = {}  # direct class views' handles -> records (#942)
        for views_file in await self._views_files(scope):
            content = await self._read_source(views_file)
            if content is None:
                continue
            tree = self._parse_source(views_file, content)
            if tree is None:
                continue
            django = _bindings(tree, DJANGO)
            drf = _bindings(tree, REST_FRAMEWORK)
            if not django.imports and not drf.imports:
                continue  # the file imports neither framework (#941, #947)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if any(_is_api_view(d, drf) for d in node.decorator_list):
                        views.append(
                            _view_record(node, views_file, "function_view", REST_FRAMEWORK)
                        )
                    elif node.args.args and node.args.args[0].arg == "request":
                        views.append(_view_record(node, views_file, "function_view", DJANGO))
                elif isinstance(node, ast.ClassDef):
                    framework = _class_view_framework(node, django, drf)
                    if framework is None:
                        continue
                    record = _view_record(node, views_file, "class_view", framework)
                    views.append(record)
                    handle = self._class_handle(views_file, node.name) if node in tree.body else ""
                    if handle:
                        seeds[handle] = record
        views.extend(await self._indirect_class_views(seeds, views, scope))
        return views

    def _class_handle(self, path: Path, name: str) -> str:
        """The dotted handle of top-level class *name* in *path*, or ``""`` if unnameable."""
        module = module_name_for_file(self._analyzer(), path)
        return f"{module}.{name}" if module else ""

    async def _indirect_class_views(
        self, seeds: dict[str, dict[str, Any]], direct: list[dict[str, Any]], scope: Scope
    ) -> list[dict[str, Any]]:
        """Project classes that subclass a class view, at any depth, by definition site (#942).

        Walks the shared class graph (``JediAnalyzer.find_subclasses``), as
        ``find_pydantic_models`` does (#664). A subclass defined in any module
        counts, not only in views files. Each subclass inherits its ancestor's
        ``framework``; one that descends from a ``rest_framework`` view is
        ``rest_framework``, the more specific, even if it is also a direct Django
        view (#947). Returns the new records, ordered by file, then line; the
        direct records' ``framework`` may be raised in place.
        """
        if not seeds:
            return []
        analyzer = self._analyzer()
        # Keyed by path_to_key: the class graph may spell a file differently.
        by_place = {(path_to_key(v["file"]), v["line"]): v for v in direct}
        records = dict(seeds)
        queue = list(seeds)
        found: list[dict[str, Any]] = []
        while queue:
            parent = queue.pop(0)
            framework = records[parent]["framework"]
            result = await analyzer.find_subclasses(parent, scope=scope)
            for sub in result.get("subclasses", []):
                # None for a class with no handle (defined in a function, or in a
                # file with no module path): still a view, found by its site, but
                # not walked further, since no FQN names its subclasses (#1006).
                handle = sub["full_name"]
                record = records.get(handle) if handle is not None else None
                if record is None:
                    where = (path_to_key(sub["file"]), sub["line"])
                    record = by_place.get(where)
                    if record is None:
                        record = {
                            "name": sub["name"],
                            "file": Path(sub["file"]).as_posix(),
                            "line": sub["line"],
                            "type": "class_view",
                            "framework": framework,
                        }
                        by_place[where] = record
                        found.append(record)
                    if handle is not None:
                        records[handle] = record
                        queue.append(handle)
                if framework == REST_FRAMEWORK and record["framework"] != REST_FRAMEWORK:
                    record["framework"] = REST_FRAMEWORK
                    if handle is not None:  # carry the upgrade to its own subclasses
                        queue.append(handle)
        return sorted(found, key=lambda v: (v["file"], v["line"]))

    async def _views_files(self, scope: Scope) -> list[Path]:
        """Every views, viewsets or api module, and every module of such a package (#941, #947)."""
        files = await self.get_project_files("*.py", scope)
        return [f for f in files if f.stem in _VIEW_MODULES or _in_views_package(f)]

    async def find_urls(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all URL patterns in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        urls = []

        # Look for urls.py files
        urls_files = await self.get_project_files("urls.py", scope)
        for urls_file in urls_files:
            urls.append(
                {
                    "file": urls_file.as_posix(),
                    "type": "url_config",
                }
            )

        return urls

    async def find_templates(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Django templates in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        templates = []
        seen_files = set()  # Track unique files to avoid duplicates

        # Common template directories
        template_dirs = ["templates", "*/templates"]
        project_roots = await self._get_scope_roots(scope)

        for root in project_roots:
            for pattern in template_dirs:
                for template_dir in root.glob(pattern):
                    if template_dir.is_dir():
                        for template_file in pruned_rglob("*.html", template_dir):
                            file_str = template_file.as_posix()
                            if file_str not in seen_files:
                                seen_files.add(file_str)
                                templates.append(
                                    {
                                        "file": file_str,
                                        "name": template_file.name,
                                        "type": "template",
                                    }
                                )

        return templates

    async def find_migrations(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Django migrations in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        migrations = []
        seen_files = set()  # Track unique files to avoid duplicates
        project_roots = await self._get_scope_roots(scope)

        for root in project_roots:
            for migration_file in filtered_rglob("migrations/*.py", root):
                if migration_file.name != "__init__.py":
                    file_str = migration_file.as_posix()
                    if file_str not in seen_files:
                        seen_files.add(file_str)
                        migrations.append(
                            {
                                "file": file_str,
                                "name": migration_file.stem,
                                "app": migration_file.parent.parent.name,
                                "type": "migration",
                            }
                        )

        return migrations

    def get_framework_components(self) -> dict[str, list[str]]:
        """Get Django framework components."""
        return {
            "models": [f.as_posix() for f in filtered_rglob("models.py", self.project_path)],
            "views": [f.as_posix() for f in filtered_rglob("views.py", self.project_path)],
            "urls": [f.as_posix() for f in filtered_rglob("urls.py", self.project_path)],
            "serializers": [
                f.as_posix() for f in filtered_rglob("serializers.py", self.project_path)
            ],
            "admin": [f.as_posix() for f in filtered_rglob("admin.py", self.project_path)],
            "forms": [f.as_posix() for f in filtered_rglob("forms.py", self.project_path)],
        }


def _in_views_package(path: Path) -> bool:
    """Whether *path* is a module inside a ``views``, ``viewsets`` or ``api`` package.

    Or a subpackage of one. Walks up only through package directories (those
    with ``__init__.py``), so an unrelated directory higher up the filesystem
    doesn't count.
    """
    directory = path.parent
    while (directory / "__init__.py").is_file():
        if directory.name in _VIEW_MODULES:
            return True
        if directory.parent == directory:
            return False
        directory = directory.parent
    return False


@dataclass(frozen=True)
class _Bindings:
    """What a module binds from one top-level package's imports.

    Attributes:
        bound: Each local name -> the dotted path it was imported from
            (``from django.views.generic import ListView as LV`` maps ``LV`` to
            ``django.views.generic.ListView``; ``import django.views`` maps
            ``django`` to ``django``).
        star_others: ``None`` when nothing is star-imported from the package.
            Otherwise the names the module binds some OTHER way (other imports,
            module-level classes, functions and assignments): a name outside it
            may come from the star.
        star_modules: The modules star-imported from the package, in order.
    """

    bound: dict[str, str]
    star_others: set[str] | None
    star_modules: tuple[str, ...] = ()

    @property
    def imports(self) -> bool:
        """Whether the module imports the package at all."""
        return bool(self.bound) or self.star_others is not None

    def dotted(self, expr: ast.expr) -> list[str]:
        """The dotted paths *expr* may name in the package; ``[]`` if it isn't from it.

        ``generic.ListView`` -> ``django.views.generic.ListView`` when
        ``generic`` came from ``django.views``; an aliased ``LV`` -> its source.
        Under a star import, a bare name the module binds no other way may be
        any star-imported module's, so each is a candidate.
        """
        chain: list[str] = []
        while isinstance(expr, ast.Attribute):
            chain.insert(0, expr.attr)
            expr = expr.value
        if not isinstance(expr, ast.Name):
            return []  # a call, a subscript: not a name we can trace to an import
        root = expr.id
        if root in self.bound:
            return [".".join([self.bound[root], *chain])]
        if self.star_others is not None and not chain and root not in self.star_others:
            return [f"{module}.{root}" for module in self.star_modules]
        return []

    def names(self, expr: ast.expr) -> str | None:
        """The imported name *expr* ends in, if it comes from the package; else ``None``."""
        paths = self.dotted(expr)
        return paths[0].rsplit(".", 1)[-1] if paths else None


def _bindings(tree: ast.Module, package: str) -> _Bindings:
    """What *tree* binds from imports of top-level *package* (``django``, ``rest_framework``).

    ``from django.views.generic import ListView`` binds ``ListView``;
    ``from django.views import generic`` binds ``generic``;
    ``import django.views.generic as g`` binds ``g``; ``import django.views``
    binds ``django``. Relative imports never count, and *package* must be the
    top level: ``from myapp.rest_framework import APIView`` is not
    ``rest_framework``.
    """

    def ours(module: str) -> bool:
        return module == package or module.startswith(f"{package}.")

    bound: dict[str, str] = {}
    other: set[str] = set()
    stars: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                if ours(alias.name):
                    bound[name] = alias.name if alias.asname else name
                else:
                    other.add(name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            is_ours = node.level == 0 and ours(module)
            for alias in node.names:
                if alias.name == "*":
                    if is_ours:
                        stars.append(module)
                elif is_ours:
                    bound[alias.asname or alias.name] = f"{module}.{alias.name}"
                else:
                    other.add(alias.asname or alias.name)
    for stmt in tree.body:
        if isinstance(stmt, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            other.add(stmt.name)
        elif isinstance(stmt, ast.Assign | ast.AnnAssign):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            other.update(
                n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)
            )
    return _Bindings(bound, (other - set(bound)) if stars else None, tuple(stars))


def _is_view_base(base: ast.expr, package: _Bindings) -> bool:
    """Whether *base* is a view class from *package*, by the module's own imports.

    Its name must contain ``View`` (``ListView``, ``APIView``, ``ModelViewSet``)
    and it must come from the package (#941, #947). A project class whose name
    contains ``View`` doesn't count; a subclass of a project view is found
    through the class graph instead (#942). A mixin alone isn't a view.
    """
    name = package.names(base)
    return name is not None and "View" in name


def _class_view_framework(node: ast.ClassDef, django: _Bindings, drf: _Bindings) -> str | None:
    """The framework of class view *node*, by its own bases, or ``None`` if it isn't one.

    A ``rest_framework`` base wins: a DRF view is the more specific.
    """
    if any(_is_view_base(base, drf) for base in node.bases):
        return REST_FRAMEWORK
    if any(_is_view_base(base, django) for base in node.bases):
        return DJANGO
    return None


#: Where Django REST framework defines its function-view decorator.
_API_VIEW = "rest_framework.decorators.api_view"


def _is_api_view(decorator: ast.expr, drf: _Bindings) -> bool:
    """Whether *decorator* is ``rest_framework.decorators.api_view``, called or not (#947).

    Matched on the full dotted path, so another ``api_view`` (a project's, or a
    name reached through another ``rest_framework`` module) doesn't count.
    """
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return _API_VIEW in drf.dotted(target)


def _view_record(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    path: Path,
    kind: str,
    framework: str,
) -> dict[str, Any]:
    return {
        "name": node.name,
        "file": path.as_posix(),
        "line": node.lineno,
        "type": kind,
        "framework": framework,
    }
