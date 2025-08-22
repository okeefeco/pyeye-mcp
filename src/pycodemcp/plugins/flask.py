"""Flask framework plugin for code intelligence."""

import ast
import logging
from collections.abc import Callable
from typing import Any

from ..async_utils import read_file_async
from .base import AnalyzerPlugin, Scope

logger = logging.getLogger(__name__)


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
                try:
                    content = file_path.read_text()
                    if "from flask import" in content or "import flask" in content:
                        return True
                except Exception:
                    pass

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
                try:
                    content = req_path.read_text().lower()
                    if "flask" in content:
                        return True
                except Exception:
                    pass

        # Check for Flask imports in any Python files
        for py_file in self.project_path.glob("**/*.py"):
            if py_file.is_file():
                try:
                    content = py_file.read_text()
                    if "from flask import" in content or "import flask" in content:
                        return True
                except Exception:
                    pass

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
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
        """
        routes = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "@" in content and "route" in content:
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
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
                                    if decorator.args and isinstance(
                                        decorator.args[0], ast.Constant
                                    ):
                                        route_path = decorator.args[0].value
                                    elif decorator.args and isinstance(decorator.args[0], ast.Str):
                                        route_path = decorator.args[0].s

                                    # Extract methods if specified
                                    for keyword in decorator.keywords:
                                        if keyword.arg == "methods" and isinstance(
                                            keyword.value, ast.List
                                        ):
                                            methods = []
                                            for elt in keyword.value.elts:
                                                if isinstance(elt, (ast.Str, ast.Constant)):
                                                    if isinstance(elt, ast.Str):
                                                        methods.append(elt.s)
                                                    elif isinstance(
                                                        elt, ast.Constant
                                                    ) and isinstance(elt.value, str):
                                                        methods.append(elt.value)

                                if route_path:
                                    routes.append(
                                        {
                                            "name": node.name,
                                            "file": str(py_file),
                                            "line": node.lineno,
                                            "path": route_path,
                                            "methods": methods,
                                            "type": "route",
                                        }
                                    )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

        return routes

    async def find_blueprints(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Flask blueprints in the project.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
        """
        blueprints = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "Blueprint" in content:
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Assign):
                            # Check for Blueprint instantiation
                            if isinstance(node.value, ast.Call) and (
                                isinstance(node.value.func, ast.Name)
                                and node.value.func.id == "Blueprint"
                            ):
                                # Get blueprint name
                                if node.targets and isinstance(node.targets[0], ast.Name):
                                    bp_name = None
                                    url_prefix = None

                                    # Extract blueprint name from args
                                    if node.value.args and isinstance(
                                        node.value.args[0], (ast.Str, ast.Constant)
                                    ):
                                        bp_name = (
                                            node.value.args[0].s
                                            if isinstance(node.value.args[0], ast.Str)
                                            else node.value.args[0].value
                                        )

                                    # Extract url_prefix if specified
                                    for keyword in node.value.keywords:
                                        if keyword.arg == "url_prefix":
                                            if isinstance(keyword.value, (ast.Str, ast.Constant)):
                                                url_prefix = (
                                                    keyword.value.s
                                                    if isinstance(keyword.value, ast.Str)
                                                    else keyword.value.value
                                                )

                                    blueprints.append(
                                        {
                                            "name": node.targets[0].id,
                                            "blueprint_name": bp_name,
                                            "file": str(py_file),
                                            "line": node.lineno,
                                            "url_prefix": url_prefix,
                                            "type": "blueprint",
                                        }
                                    )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

        return blueprints

    async def find_views(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Flask view functions and classes.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
        """
        views = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "flask" in content.lower():
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        # Find MethodView classes
                        if isinstance(node, ast.ClassDef):
                            for base in node.bases:
                                if (
                                    isinstance(base, ast.Name)
                                    and base.id == "MethodView"
                                    or isinstance(base, ast.Attribute)
                                    and base.attr == "MethodView"
                                ):
                                    views.append(
                                        {
                                            "name": node.name,
                                            "file": str(py_file),
                                            "line": node.lineno,
                                            "type": "method_view",
                                        }
                                    )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

        return views

    async def find_templates(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Flask templates and render_template calls.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
        """
        templates = []
        render_calls = []

        # Find template files
        template_dirs = ["templates", "*/templates", "app/templates"]
        project_roots = await self._get_scope_roots(scope)

        for root in project_roots:
            for pattern in template_dirs:
                for template_dir in root.glob(pattern):
                    if template_dir.is_dir():
                        for template_file in template_dir.rglob("*.html"):
                            templates.append(
                                {
                                    "file": str(template_file),
                                    "name": template_file.relative_to(template_dir).as_posix(),
                                    "type": "template",
                                }
                            )
                        for template_file in template_dir.rglob("*.jinja2"):
                            templates.append(
                                {
                                    "file": str(template_file),
                                    "name": template_file.relative_to(template_dir).as_posix(),
                                    "type": "template",
                                }
                            )

        # Find render_template calls
        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "render_template" in content:
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        if (
                            isinstance(node, ast.Call)
                            and (
                                isinstance(node.func, ast.Name)
                                and node.func.id == "render_template"
                            )
                            and node.args
                            and isinstance(node.args[0], (ast.Str, ast.Constant))
                        ):
                            template_name = (
                                node.args[0].s
                                if isinstance(node.args[0], ast.Str)
                                else node.args[0].value
                            )
                            render_calls.append(
                                {
                                    "template": template_name,
                                    "file": str(py_file),
                                    "line": node.lineno,
                                    "type": "render_call",
                                }
                            )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

        return [{"templates": templates, "render_calls": render_calls}]

    async def find_extensions(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find Flask extensions in use.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
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
            try:
                content = await read_file_async(py_file)
                for ext in common_extensions:
                    if f"from {ext}" in content or f"import {ext}" in content:
                        # Parse to get more details
                        tree = ast.parse(content)
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.Import, ast.ImportFrom)):
                                if isinstance(node, ast.ImportFrom):
                                    if node.module and ext in node.module:
                                        extensions.append(
                                            {
                                                "extension": ext,
                                                "file": str(py_file),
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
                                                    "file": str(py_file),
                                                    "line": node.lineno,
                                                    "type": "import",
                                                }
                                            )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

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
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
        """
        configs = []

        # Look for config files
        config_patterns = ["config.py", "settings.py", "*/config.py", "*/settings.py"]
        for pattern in config_patterns:
            for config_file in self.project_path.glob(pattern):
                if config_file.is_file():
                    configs.append({"file": str(config_file), "type": "config_file"})

        # Find app.config usage
        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "app.config" in content or "current_app.config" in content:
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        # Look for config access patterns
                        if isinstance(node, ast.Attribute):
                            if isinstance(node.value, ast.Name) and (
                                node.value.id in ["app", "current_app"] and node.attr == "config"
                            ):
                                configs.append(
                                    {
                                        "file": str(py_file),
                                        "line": str(getattr(node, "lineno", 0)),
                                        "type": "config_access",
                                    }
                                )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

        return configs

    async def find_error_handlers(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find error handler functions.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
        """
        handlers = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "errorhandler" in content:
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            for decorator in node.decorator_list:
                                # Check for @app.errorhandler()
                                if isinstance(decorator, ast.Call):
                                    if isinstance(decorator.func, ast.Attribute):
                                        if decorator.func.attr == "errorhandler":
                                            error_code = None
                                            if decorator.args:
                                                if isinstance(decorator.args[0], ast.Constant):
                                                    error_code = decorator.args[0].value
                                                elif isinstance(decorator.args[0], ast.Num):
                                                    error_code = decorator.args[0].n
                                                elif isinstance(decorator.args[0], ast.Name):
                                                    error_code = decorator.args[0].id

                                            handlers.append(
                                                {
                                                    "name": node.name,
                                                    "file": str(py_file),
                                                    "line": node.lineno,
                                                    "error_code": error_code,
                                                    "type": "error_handler",
                                                }
                                            )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

        return handlers

    async def find_cli_commands(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find Flask CLI commands.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project (default for plugins)
                - "all": Include configured namespaces
                - "namespace:name": Specific namespace
        """
        commands = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "@" in content and "cli" in content:
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
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
                                                    if decorator.args and isinstance(
                                                        decorator.args[0], (ast.Str, ast.Constant)
                                                    ):
                                                        if isinstance(decorator.args[0], ast.Str):
                                                            command_name = decorator.args[0].s
                                                        elif isinstance(
                                                            decorator.args[0], ast.Constant
                                                        ) and isinstance(
                                                            decorator.args[0].value, str
                                                        ):
                                                            command_name = decorator.args[0].value

                                                    commands.append(
                                                        {
                                                            "name": command_name,
                                                            "function": node.name,
                                                            "file": str(py_file),
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
                                                "file": str(py_file),
                                                "line": node.lineno,
                                                "type": "cli_command",
                                            }
                                        )

            except Exception as e:
                logger.warning(f"Error parsing {py_file}: {e}")

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
        for py_file in self.project_path.rglob("*.py"):
            try:
                content = py_file.read_text()
                if "@" in content and "route" in content:
                    components["routes"].append(str(py_file))
            except Exception:
                pass

        # Find blueprint files
        for py_file in self.project_path.rglob("*.py"):
            try:
                content = py_file.read_text()
                if "Blueprint" in content:
                    components["blueprints"].append(str(py_file))
            except Exception:
                pass

        # Find template directories
        for template_dir in self.project_path.glob("**/templates"):
            if template_dir.is_dir():
                components["templates"].append(str(template_dir))

        # Find static directories
        for static_dir in self.project_path.glob("**/static"):
            if static_dir.is_dir():
                components["static"].append(str(static_dir))

        # Find models (SQLAlchemy)
        for models_file in self.project_path.rglob("models.py"):
            components["models"].append(str(models_file))

        # Find forms (WTForms)
        for forms_file in self.project_path.rglob("forms.py"):
            components["forms"].append(str(forms_file))

        return components
