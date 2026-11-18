"""Flask framework plugin for code intelligence."""

import ast
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..async_utils import filtered_rglob
from ..path_utils import path_to_key, relative_within
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

# Config files: at a scope root or one directory below it (#873).
_CONFIG_FILE_PATTERNS = ("config.py", "settings.py", "*/config.py", "*/settings.py")


def _blueprint_assignment(node: ast.AST) -> tuple[str, ast.Call, int] | None:
    """``(target, call, line)`` when *node* binds a name to a ``Blueprint(...)`` call.

    Accepts ``bp = Blueprint(...)``, ``bp = <module>.Blueprint(...)`` (such as
    ``flask.Blueprint`` or an aliased import) and the annotated forms of both
    (#873). An annotation with no value binds nothing and is not a blueprint.
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
    if (isinstance(func, ast.Name) and func.id == "Blueprint") or (
        isinstance(func, ast.Attribute) and func.attr == "Blueprint"
    ):
        return target.id, value, target.lineno
    return None


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

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "@" in content and "route" in content:
                tree = self._parse_source(py_file, content)
                if tree is not None:
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
                        found = _blueprint_assignment(node)
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
        views = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is not None and "flask" in content.lower():
                tree = self._parse_source(py_file, content)
                if tree is not None:
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
                                            "file": py_file.as_posix(),
                                            "line": node.lineno,
                                            "type": "method_view",
                                        }
                                    )

        return views

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
                                    "file": template_file.as_posix(),
                                    "name": _template_name(template_file, template_dir),
                                    "type": "template",
                                }
                            )
                        for template_file in template_dir.rglob("*.jinja2"):
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
                if tree is not None:
                    for node in ast.walk(tree):
                        if (
                            isinstance(node, ast.Call)
                            and (
                                isinstance(node.func, ast.Name)
                                and node.func.id == "render_template"
                            )
                            and node.args
                            and (template_name := _str_value(node.args[0])) is not None
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
                        if isinstance(node, ast.Attribute):
                            if isinstance(node.value, ast.Name) and (
                                node.value.id in ["app", "current_app"] and node.attr == "config"
                            ):
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
