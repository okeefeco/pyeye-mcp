"""Pydantic framework plugin for enhanced model intelligence."""

import ast
import logging
from collections.abc import Callable
from typing import Any

from ..async_utils import read_file_async, rglob_async
from .base import AnalyzerPlugin

logger = logging.getLogger(__name__)


class PydanticPlugin(AnalyzerPlugin):
    """Plugin for Pydantic-specific code intelligence."""

    def name(self) -> str:
        """Return the plugin name."""
        return "Pydantic"

    def detect(self) -> bool:
        """Detect if this project uses Pydantic."""
        # Check for Pydantic imports in any Python file
        # Note: Using sync I/O here as detect() is called during initialization
        for py_file in self.project_path.rglob("*.py"):
            if py_file.stat().st_size > 1000000:  # Skip very large files
                continue
            try:
                content = py_file.read_text()
                if "from pydantic import" in content or "import pydantic" in content:
                    return True
            except Exception:
                pass

        # Check requirements files
        req_files = ["requirements.txt", "pyproject.toml", "Pipfile"]
        for req_file in req_files:
            req_path = self.project_path / req_file
            if req_path.exists():
                try:
                    content = req_path.read_text().lower()
                    if "pydantic" in content:
                        return True
                except Exception:
                    pass

        return False

    def register_tools(self) -> dict[str, Callable]:
        """Register Pydantic-specific tools."""
        return {
            "find_pydantic_models": self.find_models,
            "get_model_schema": self.get_model_schema,
            "find_validators": self.find_validators,
            "find_field_validators": self.find_field_validators,
            "find_model_config": self.find_model_config,
            "trace_model_inheritance": self.trace_model_inheritance,
            "find_computed_fields": self.find_computed_fields,
        }

    async def find_models(self) -> list[dict[str, Any]]:
        """Find all Pydantic models in the project."""
        models = []

        py_files = await rglob_async("*.py", self.project_path)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "BaseModel" not in content and "pydantic" not in content.lower():
                    continue  # Quick filter

                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        # Check if it inherits from BaseModel or any Pydantic base
                        if self._is_pydantic_model(node, content):
                            model_info = {
                                "name": node.name,
                                "file": str(py_file),
                                "line": node.lineno,
                                "type": "pydantic_model",
                                "fields": self._extract_fields(node),
                                "validators": self._extract_validators(node),
                                "config": self._extract_config(node),
                                "base_classes": [self._get_base_name(base) for base in node.bases],
                            }
                            models.append(model_info)

            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")

        return models

    async def get_model_schema(self, model_name: str) -> dict[str, Any] | None:
        """Get the schema for a specific Pydantic model."""
        models = await self.find_models()

        for model in models:
            if model["name"] == model_name:
                schema = {
                    "model": model_name,
                    "fields": model["fields"],
                    "required": [],
                    "optional": [],
                    "validators": model["validators"],
                    "computed_fields": [],
                    "config": model["config"],
                }

                # Categorize fields
                for field in model["fields"]:
                    if field.get("required", True):
                        schema["required"].append(field)
                    else:
                        schema["optional"].append(field)

                return schema

        return None

    async def find_validators(self) -> list[dict[str, Any]]:
        """Find all Pydantic validators in the project."""
        validators = []

        py_files = await rglob_async("*.py", self.project_path)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "validator" not in content and "field_validator" not in content:
                    continue

                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # Check for validator decorators
                        for decorator in node.decorator_list:
                            if self._is_validator_decorator(decorator):
                                validator_info = {
                                    "name": node.name,
                                    "file": str(py_file),
                                    "line": node.lineno,
                                    "type": self._get_validator_type(decorator),
                                    "fields": self._get_validator_fields(decorator),
                                    "mode": self._get_validator_mode(decorator),
                                }
                                validators.append(validator_info)

            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")

        return validators

    async def find_field_validators(self) -> list[dict[str, Any]]:
        """Find all field-specific validators."""
        all_validators = await self.find_validators()
        return [v for v in all_validators if v["type"] == "field_validator"]

    async def find_model_config(self) -> list[dict[str, Any]]:
        """Find all model configurations."""
        configs = []

        py_files = await rglob_async("*.py", self.project_path)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "Config" not in content and "model_config" not in content:
                    continue

                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        # Look for Config inner class or model_config
                        for item in node.body:
                            if isinstance(item, ast.ClassDef) and item.name == "Config":
                                config_info = {
                                    "model": node.name,
                                    "file": str(py_file),
                                    "line": item.lineno,
                                    "settings": self._extract_config_settings(item),
                                }
                                configs.append(config_info)
                            elif isinstance(item, ast.Assign):
                                for target in item.targets:
                                    if isinstance(target, ast.Name) and target.id == "model_config":
                                        configs.append(
                                            {
                                                "model": node.name,
                                                "file": str(py_file),
                                                "line": item.lineno,
                                                "settings": self._extract_config_dict(item.value),
                                            }
                                        )

            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")

        return configs

    async def trace_model_inheritance(self, model_name: str) -> dict[str, Any]:
        """Trace the inheritance hierarchy of a Pydantic model."""
        models = await self.find_models()

        hierarchy: dict[str, Any] = {
            "model": model_name,
            "parents": [],
            "children": [],
            "mro": [],  # Method Resolution Order
        }

        # Find the target model and its parents
        for model in models:
            if model["name"] == model_name:
                hierarchy["parents"] = model["base_classes"]
                hierarchy["fields_inherited"] = []
                hierarchy["fields_own"] = model["fields"]

            # Check if this model inherits from our target
            if model_name in model["base_classes"]:
                hierarchy["children"].append(
                    {
                        "name": model["name"],
                        "file": model["file"],
                        "line": model["line"],
                    }
                )

        return hierarchy

    async def find_computed_fields(self) -> list[dict[str, Any]]:
        """Find all computed fields (properties, computed_field decorator)."""
        computed_fields = []

        py_files = await rglob_async("*.py", self.project_path)
        for py_file in py_files:
            try:
                content = await read_file_async(py_file)
                if "computed_field" not in content and "@property" not in content:
                    continue

                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        for decorator in node.decorator_list:
                            if self._is_computed_field_decorator(decorator):
                                computed_fields.append(
                                    {
                                        "name": node.name,
                                        "file": str(py_file),
                                        "line": node.lineno,
                                        "type": "computed_field",
                                        "return_type": self._get_return_type(node),
                                    }
                                )

            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")

        return computed_fields

    # Helper methods

    def _is_pydantic_model(self, node: ast.ClassDef, content: str) -> bool:
        """Check if a class is a Pydantic model."""
        _ = content  # Will be used for more advanced checks in future
        for base in node.bases:
            base_name = self._get_base_name(base)
            if base_name in ["BaseModel", "BaseSettings", "RootModel"]:
                return True
            # Check for pydantic.BaseModel
            if isinstance(base, ast.Attribute) and base.attr in ["BaseModel", "BaseSettings"]:
                return True
        return False

    def _get_base_name(self, base: Any) -> str:
        """Extract base class name from AST node."""
        if isinstance(base, ast.Name):
            return base.id
        elif isinstance(base, ast.Attribute):
            return base.attr
        return str(base)

    def _extract_fields(self, node: ast.ClassDef) -> list[dict[str, Any]]:
        """Extract field definitions from a Pydantic model."""
        fields = []

        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_info = {
                    "name": item.target.id,
                    "type": (
                        ast.unparse(item.annotation)
                        if hasattr(ast, "unparse")
                        else str(item.annotation)
                    ),
                    "required": item.value is None,
                    "line": item.lineno,
                }

                # Check for Field() usage
                if item.value and isinstance(item.value, ast.Call):
                    if self._is_field_call(item.value):
                        field_info["has_field_config"] = True
                        field_info["default"] = None if item.value is None else "Field(...)"
                elif item.value:
                    field_info["default"] = (
                        ast.unparse(item.value) if hasattr(ast, "unparse") else str(item.value)
                    )

                fields.append(field_info)

        return fields

    def _is_field_call(self, node: ast.Call) -> bool:
        """Check if a call is to Field()."""
        return (isinstance(node.func, ast.Name) and node.func.id == "Field") or (
            isinstance(node.func, ast.Attribute) and node.func.attr == "Field"
        )

    def _extract_validators(self, node: ast.ClassDef) -> list[str]:
        """Extract validator method names from a model."""
        validators = []

        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                for decorator in item.decorator_list:
                    if self._is_validator_decorator(decorator):
                        validators.append(item.name)

        return validators

    def _is_validator_decorator(self, decorator: Any) -> bool:
        """Check if decorator is a Pydantic validator."""
        if isinstance(decorator, ast.Name):
            return decorator.id in [
                "validator",
                "field_validator",
                "root_validator",
                "model_validator",
            ]
        if isinstance(decorator, ast.Attribute):
            return decorator.attr in [
                "validator",
                "field_validator",
                "root_validator",
                "model_validator",
            ]
        if isinstance(decorator, ast.Call):
            return self._is_validator_decorator(decorator.func)
        return False

    def _get_validator_type(self, decorator: Any) -> str:
        """Get the type of validator from decorator."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        if isinstance(decorator, ast.Attribute):
            return decorator.attr
        if isinstance(decorator, ast.Call) and isinstance(
            decorator.func, (ast.Name, ast.Attribute)
        ):
            return self._get_validator_type(decorator.func)
        return "unknown"

    def _get_validator_fields(self, decorator: Any) -> list[str]:
        """Extract field names from validator decorator."""
        fields = []

        if isinstance(decorator, ast.Call) and decorator.args:
            for arg in decorator.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    fields.append(arg.value)
                elif isinstance(arg, ast.Str):  # Python < 3.8
                    fields.append(arg.s)

        return fields

    def _get_validator_mode(self, decorator: Any) -> str:
        """Get validator mode (before/after)."""
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "mode":
                    if isinstance(keyword.value, ast.Constant) and isinstance(
                        keyword.value.value, str
                    ):
                        return keyword.value.value
        return "after"  # default

    def _extract_config(self, node: ast.ClassDef) -> dict[str, Any]:
        """Extract Config class or model_config from a model."""
        config = {}

        for item in node.body:
            if isinstance(item, ast.ClassDef) and item.name == "Config":
                config = self._extract_config_settings(item)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "model_config":
                        config = self._extract_config_dict(item.value)

        return config

    def _extract_config_settings(self, config_class: ast.ClassDef) -> dict[str, Any]:
        """Extract settings from Config class."""
        settings = {}

        for item in config_class.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        settings[target.id] = (
                            ast.unparse(item.value) if hasattr(ast, "unparse") else str(item.value)
                        )

        return settings

    def _extract_config_dict(self, node: Any) -> dict[str, Any]:
        """Extract settings from model_config dictionary."""
        settings = {}

        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    settings[key.value] = (
                        ast.unparse(value) if hasattr(ast, "unparse") else str(value)
                    )

        return settings

    def _is_computed_field_decorator(self, decorator: Any) -> bool:
        """Check if decorator is computed_field or property."""
        if isinstance(decorator, ast.Name):
            return decorator.id in ["computed_field", "property"]
        if isinstance(decorator, ast.Attribute):
            return decorator.attr in ["computed_field", "property"]
        return False

    def _get_return_type(self, node: ast.FunctionDef) -> str | None:
        """Get return type annotation from function."""
        if node.returns:
            return ast.unparse(node.returns) if hasattr(ast, "unparse") else str(node.returns)
        return None
