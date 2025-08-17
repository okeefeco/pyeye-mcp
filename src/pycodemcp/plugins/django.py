"""Django framework plugin for code intelligence."""

import logging
from collections.abc import Callable
from typing import Any

from .base import AnalyzerPlugin

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
                try:
                    content = req_path.read_text().lower()
                    if "django" in content:
                        return True
                except Exception:
                    pass

        # Check for Django imports in Python files
        for py_file in self.project_path.glob("*.py"):
            try:
                content = py_file.read_text()
                if "from django" in content or "import django" in content:
                    return True
            except Exception:
                pass

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

    def find_models(self) -> list[dict[str, Any]]:
        """Find all Django models in the project."""
        models = []

        # Look for models.py files
        for models_file in self.project_path.rglob("models.py"):
            try:
                content = models_file.read_text()
                if "from django.db import models" in content or "Model" in content:
                    # Simple heuristic - could be enhanced with AST parsing
                    import ast

                    tree = ast.parse(content)

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
                                            "file": str(models_file),
                                            "line": node.lineno,
                                            "type": "django_model",
                                        }
                                    )

            except Exception as e:
                logger.warning(f"Error parsing {models_file}: {e}")

        return models

    def find_views(self) -> list[dict[str, Any]]:
        """Find all Django views in the project."""
        views = []

        # Look for views.py files
        for views_file in self.project_path.rglob("views.py"):
            try:
                content = views_file.read_text()
                if "from django" in content:
                    import ast

                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        # Find function-based views
                        if isinstance(node, ast.FunctionDef):
                            # Simple heuristic: functions with request parameter
                            if node.args.args and node.args.args[0].arg == "request":
                                views.append(
                                    {
                                        "name": node.name,
                                        "file": str(views_file),
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
                                            "file": str(views_file),
                                            "line": node.lineno,
                                            "type": "class_view",
                                        }
                                    )

            except Exception as e:
                logger.warning(f"Error parsing {views_file}: {e}")

        return views

    def find_urls(self) -> list[dict[str, Any]]:
        """Find all URL patterns in the project."""
        urls = []

        # Look for urls.py files
        for urls_file in self.project_path.rglob("urls.py"):
            urls.append(
                {
                    "file": str(urls_file),
                    "type": "url_config",
                }
            )

        return urls

    def find_templates(self) -> list[dict[str, Any]]:
        """Find all Django templates in the project."""
        templates = []

        # Common template directories
        template_dirs = ["templates", "*/templates"]

        for pattern in template_dirs:
            for template_dir in self.project_path.glob(pattern):
                if template_dir.is_dir():
                    for template_file in template_dir.rglob("*.html"):
                        templates.append(
                            {
                                "file": str(template_file),
                                "name": template_file.name,
                                "type": "template",
                            }
                        )

        return templates

    def find_migrations(self) -> list[dict[str, Any]]:
        """Find all Django migrations in the project."""
        migrations = []

        for migration_file in self.project_path.rglob("migrations/*.py"):
            if migration_file.name != "__init__.py":
                migrations.append(
                    {
                        "file": str(migration_file),
                        "name": migration_file.stem,
                        "app": migration_file.parent.parent.name,
                        "type": "migration",
                    }
                )

        return migrations

    def get_framework_components(self) -> dict[str, list[str]]:
        """Get Django framework components."""
        return {
            "models": [str(f) for f in self.project_path.rglob("models.py")],
            "views": [str(f) for f in self.project_path.rglob("views.py")],
            "urls": [str(f) for f in self.project_path.rglob("urls.py")],
            "serializers": [str(f) for f in self.project_path.rglob("serializers.py")],
            "admin": [str(f) for f in self.project_path.rglob("admin.py")],
            "forms": [str(f) for f in self.project_path.rglob("forms.py")],
        }
