"""Django framework plugin for code intelligence."""

import ast
import logging
from collections.abc import Callable
from typing import Any

from ..async_utils import filtered_rglob
from .base import AnalyzerPlugin, Scope

logger = logging.getLogger(__name__)


class DjangoPlugin(AnalyzerPlugin):
    """Plugin for Django-specific code intelligence."""

    def name(self) -> str:
        """Return the plugin name."""
        return "Django"

    def detect(self) -> bool:
        """Detect if this is a Django project."""
        # Check for manage.py
        if (self.project_path / "manage.py").exists():
            return True

        # Check for Django in requirements
        requirements_files = ["requirements.txt", "requirements/base.txt", "Pipfile"]
        for req_file in requirements_files:
            req_path = self.project_path / req_file
            if req_path.exists():
                content = self._read_text_or_skip(req_path)
                if content is not None and "django" in content.lower():
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
        views = []

        # Look for views.py files
        views_files = await self.get_project_files("views.py", scope)
        for views_file in views_files:
            content = await self._read_source(views_file)
            if content is not None and "from django" in content:
                tree = self._parse_source(views_file, content)
                if tree is not None:

                    for node in ast.walk(tree):
                        # Find function-based views
                        if isinstance(node, ast.FunctionDef):
                            # Simple heuristic: functions with request parameter
                            if node.args.args and node.args.args[0].arg == "request":
                                views.append(
                                    {
                                        "name": node.name,
                                        "file": views_file.as_posix(),
                                        "line": node.lineno,
                                        "type": "function_view",
                                    }
                                )

                        # Find class-based views
                        elif isinstance(node, ast.ClassDef):
                            for base in node.bases:
                                if isinstance(base, ast.Name) and "View" in base.id:
                                    views.append(
                                        {
                                            "name": node.name,
                                            "file": views_file.as_posix(),
                                            "line": node.lineno,
                                            "type": "class_view",
                                        }
                                    )

        return views

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
                        for template_file in template_dir.rglob("*.html"):
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
