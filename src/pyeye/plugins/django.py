"""Django framework plugin for code intelligence."""

import ast
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..async_utils import filtered_rglob, pruned_rglob
from .base import AnalyzerPlugin, Scope

logger = logging.getLogger(__name__)

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
        """Find all Django views in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        views: list[dict[str, Any]] = []
        for views_file in await self._views_files(scope):
            content = await self._read_source(views_file)
            if content is None:
                continue
            tree = self._parse_source(views_file, content)
            if tree is None:
                continue
            bound, star_others = _django_bindings(tree)
            if not bound and star_others is None:
                continue  # the file doesn't import Django (#941)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if node.args.args and node.args.args[0].arg == "request":
                        views.append(_view_record(node, views_file, "function_view"))
                elif isinstance(node, ast.ClassDef):
                    if any(_is_django_view_base(base, bound, star_others) for base in node.bases):
                        views.append(_view_record(node, views_file, "class_view"))
        return views

    async def _views_files(self, scope: Scope) -> list[Path]:
        """Every ``views.py``, and every module of a ``views`` package (#941)."""
        files = await self.get_project_files("*.py", scope)
        return [f for f in files if f.name == "views.py" or _in_views_package(f)]

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
    """Whether *path* is a module inside a package named ``views`` (or a subpackage of one).

    Walks up only through package directories (those with ``__init__.py``), so
    an unrelated ``views`` directory higher up the filesystem doesn't count.
    """
    directory = path.parent
    while (directory / "__init__.py").is_file():
        if directory.name == "views":
            return True
        if directory.parent == directory:
            return False
        directory = directory.parent
    return False


def _django_bindings(tree: ast.Module) -> tuple[dict[str, str], set[str] | None]:
    """The names a module binds from Django imports, and what a Django star import may bind.

    The first value maps each local name to the name it was imported as
    (``ListView as LV`` maps ``LV`` to ``ListView``).

    The second value is ``None`` when nothing is star-imported from Django.
    Otherwise it is the set of names the module binds some OTHER way (other
    imports, module-level classes, functions and assignments): a name outside
    it may come from the star.

    ``from django.views.generic import ListView`` binds ``ListView``;
    ``from django.views import generic`` binds ``generic``;
    ``import django.views.generic as g`` binds ``g``; ``import django.views``
    binds ``django``. Relative imports are never Django.
    """
    bound: dict[str, str] = {}
    other: set[str] = set()
    star = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "django" or alias.name.startswith("django."):
                    bound[name] = alias.name.rsplit(".", 1)[-1] if alias.asname else name
                else:
                    other.add(name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            is_django = node.level == 0 and (module == "django" or module.startswith("django."))
            for alias in node.names:
                if alias.name == "*":
                    star = star or is_django
                elif is_django:
                    bound[alias.asname or alias.name] = alias.name
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
    return bound, (other - set(bound)) if star else None


def _base_parts(base: ast.expr) -> tuple[str, str] | None:
    """A base's (root name, last name): ``generic.ListView`` -> (generic, ListView)."""
    last = base.attr if isinstance(base, ast.Attribute) else None
    while isinstance(base, ast.Attribute):
        base = base.value
    if not isinstance(base, ast.Name):
        return None  # a call, a subscript: not a name we can trace to an import
    return base.id, last or base.id


def _is_django_view_base(
    base: ast.expr, bound: dict[str, str], star_others: set[str] | None
) -> bool:
    """Whether *base* is a Django view class, by the module's own imports (#941).

    Its name must contain ``View`` and it must come from Django: imported from
    a ``django`` module, or an attribute of a name that was (``generic.ListView``).
    Under a ``from django... import *`` a bare name the module binds no other
    way counts too, since the star may have bound it. A project class whose name contains
    ``View`` doesn't count, nor does a subclass of a project view (#942).
    """
    parts = _base_parts(base)
    if parts is None:
        return False
    root, last = parts
    if isinstance(base, ast.Name):
        last = bound.get(root, root)  # the name it was imported as, through an alias
    if "View" not in last:
        return False
    if root in bound:
        return True
    return star_others is not None and isinstance(base, ast.Name) and root not in star_others


def _view_record(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, path: Path, kind: str
) -> dict[str, Any]:
    return {"name": node.name, "file": path.as_posix(), "line": node.lineno, "type": kind}
