"""Pydantic framework plugin for enhanced model intelligence."""

import ast
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import resolver
from ..async_utils import filtered_rglob
from ..project_layout import module_name_for_file
from .base import AnalyzerPlugin, Scope

if TYPE_CHECKING:
    from ..analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

#: The Pydantic roots a model subclasses: the base name user code writes, and
#: the dotted paths it can be imported from (#664).
_ROOTS: dict[str, tuple[str, ...]] = {
    "BaseModel": ("pydantic.BaseModel",),
    "RootModel": ("pydantic.RootModel",),
    "BaseSettings": ("pydantic_settings.BaseSettings", "pydantic.BaseSettings"),
}


class PydanticPlugin(AnalyzerPlugin):
    """Plugin for Pydantic-specific code intelligence."""

    def name(self) -> str:
        """Return the plugin name."""
        return "Pydantic"

    def detect(self) -> bool:
        """Detect if this project uses Pydantic."""
        # Check for Pydantic imports in any Python file
        # Note: Using sync I/O here as detect() is called during initialization
        for py_file in filtered_rglob("*.py", self.project_path):
            try:
                if py_file.stat().st_size > 1000000:  # Skip very large files
                    continue
            except OSError as e:
                logger.warning(f"Plugin {self.name()}: error reading {py_file.as_posix()}: {e}")
                continue
            content = self._read_text_or_skip(py_file)
            if content is not None and (
                "from pydantic import" in content or "import pydantic" in content
            ):
                return True

        # Check requirements files
        req_files = ["requirements.txt", "pyproject.toml", "Pipfile"]
        for req_file in req_files:
            req_path = self.project_path / req_file
            if req_path.exists():
                content = self._read_text_or_skip(req_path)
                if content is not None and "pydantic" in content.lower():
                    return True

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

    async def find_models(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Pydantic models in the project, direct and indirect (#664).

        A model is a project class that subclasses a Pydantic root
        (``BaseModel``, ``RootModel``, ``BaseSettings``) directly or through
        other project classes. Models are found by DEFINITION SITE through the
        one class graph (``JediAnalyzer.find_subclasses``, cached per
        generation, #397), so two models with the same name stay distinct and a
        local class that merely shares a root's name is not a model.

        **Weaker fallback:** a root that doesn't resolve is matched by direct base
        NAME instead. For example, when pydantic-settings isn't importable,
        BaseSettings subclasses are found by direct base name; the walk then
        continues from them by definition site. This applies ONLY to a root that
        doesn't resolve.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        analyzer = self._analyzer()
        await self._warn_unreadable_sources(scope)
        root_handles, unresolved_names = self._resolve_roots(analyzer)

        queue: list[dict[str, Any]] = []
        for handle in root_handles:
            queue.extend(await self._direct_subclasses(analyzer, handle, scope))
        if unresolved_names:
            queue.extend(await self._name_matched_seeds(unresolved_names, scope, analyzer))

        found: dict[str, dict[str, Any]] = {}
        while queue:
            sub = queue.pop(0)
            if sub["full_name"] in found:
                continue
            found[sub["full_name"]] = sub
            queue.extend(await self._direct_subclasses(analyzer, sub["full_name"], scope))

        models = []
        for sub in sorted(found.values(), key=lambda s: (Path(s["file"]).as_posix(), s["line"])):
            record = await self._model_record(Path(sub["file"]), sub["line"])
            if record is not None:
                models.append(record)
        return models

    async def _warn_unreadable_sources(self, scope: Scope) -> None:
        """Warn about every Pydantic-looking file that can't be read or parsed (#637).

        The class graph skips such a file silently (#729), so this keeps the
        plugin contract: broken user code is skipped WITH a warning. Reading and
        parsing log the warning themselves.
        """
        for py_file in await self.get_project_files("*.py", scope):
            content = await self._read_source(py_file)
            if content is not None and ("BaseModel" in content or "pydantic" in content.lower()):
                self._parse_source(py_file, content)

    def _analyzer(self) -> "JediAnalyzer":
        """The project's shared analyzer (the server's instance; no ``pyeye.mcp`` import)."""
        from ..project_manager import get_project_manager

        return get_project_manager().get_analyzer(self.project_path.as_posix())

    @staticmethod
    def _resolve_roots(analyzer: "JediAnalyzer") -> tuple[list[str], frozenset[str]]:
        """The roots' definition-site handles, and the root names that don't resolve."""
        handles: list[str] = []
        unresolved: set[str] = set()
        for name, paths in _ROOTS.items():
            resolved = [resolver.resolve_handle(p, analyzer) for p in paths]
            hits = [r.handle for r in resolved if isinstance(r, resolver.Resolved)]
            if hits:
                handles.extend(dict.fromkeys(hits))
            else:
                unresolved.add(name)
        return handles, frozenset(unresolved)

    @staticmethod
    async def _direct_subclasses(
        analyzer: "JediAnalyzer", handle: str, scope: Scope
    ) -> list[dict[str, Any]]:
        """*handle*'s direct project subclasses, by definition site (the class graph)."""
        result = await analyzer.find_subclasses(handle, scope=scope)
        return [s for s in result.get("subclasses", []) if s.get("full_name")]

    async def _name_matched_seeds(
        self, names: frozenset[str], scope: Scope, analyzer: "JediAnalyzer"
    ) -> list[dict[str, Any]]:
        """Classes whose DIRECT base is named one of *names* (the unresolvable-root fallback)."""
        seeds: list[dict[str, Any]] = []
        for py_file in await self.get_project_files("*.py", scope):
            content = await self._read_source(py_file)
            if content is None or not any(n in content for n in names):
                continue
            tree = self._parse_source(py_file, content)
            module = module_name_for_file(analyzer, py_file) if tree is not None else None
            if tree is None or module is None:
                continue
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and any(
                    self._base_leaf(base) in names for base in node.bases
                ):
                    seeds.append(
                        {"full_name": f"{module}.{node.name}", "file": py_file, "line": node.lineno}
                    )
        return seeds

    @staticmethod
    def _base_leaf(base: ast.expr) -> str | None:
        if isinstance(base, ast.Name):
            return base.id
        if isinstance(base, ast.Attribute):
            return base.attr
        return None

    async def _model_record(self, py_file: Path, line: int) -> dict[str, Any] | None:
        """The ``find_models`` record for the class defined at *py_file*:*line*."""
        content = await self._read_source(py_file)
        tree = self._parse_source(py_file, content) if content is not None else None
        if tree is None:
            return None
        node = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.lineno == line), None
        )
        if node is None:
            return None
        return {
            "name": node.name,
            "file": py_file.as_posix(),
            "line": node.lineno,
            "type": "pydantic_model",
            "fields": self._extract_fields(node),
            "validators": self._extract_validators(node),
            "config": self._extract_config(node),
            "base_classes": [self._get_base_name(base) for base in node.bases],
        }

    async def get_model_schema(
        self, model_name: str, scope: Scope = "main"
    ) -> dict[str, Any] | None:
        """Get the schema for a specific Pydantic model.

        Args:
            model_name: Name of the model to get schema for
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        models = await self.find_models(scope)

        for model in models:
            if model["name"] == model_name:
                return self.schema_for(model)

        return None

    @staticmethod
    def schema_for(model: dict[str, Any]) -> dict[str, Any]:
        """Build the schema answer for one ``find_models`` record.

        Selecting *which* model (by name or handle, and reporting a miss or an
        ambiguity) is the MCP layer's job (#627); this only shapes the answer.
        """
        schema: dict[str, Any] = {
            "model": model["name"],
            # Where the model is defined, so the result can carry a handle (#627).
            "file": model["file"],
            "line": model["line"],
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

    async def find_validators(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all Pydantic validators in the project.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        validators = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is None:
                continue
            if "validator" not in content and "field_validator" not in content:
                continue

            tree = self._parse_source(py_file, content)
            if tree is None:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check for validator decorators
                    for decorator in node.decorator_list:
                        if self._is_validator_decorator(decorator):
                            validator_info = {
                                "name": node.name,
                                "file": py_file.as_posix(),
                                "line": node.lineno,
                                "type": self._get_validator_type(decorator),
                                "fields": self._get_validator_fields(decorator),
                                "mode": self._get_validator_mode(decorator),
                            }
                            validators.append(validator_info)

        return validators

    async def find_field_validators(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all field-specific validators.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        all_validators = await self.find_validators(scope)
        return [v for v in all_validators if v["type"] == "field_validator"]

    async def find_model_config(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all model configurations.

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        configs = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is None:
                continue
            if "Config" not in content and "model_config" not in content:
                continue

            tree = self._parse_source(py_file, content)
            if tree is None:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Look for Config inner class or model_config
                    for item in node.body:
                        if isinstance(item, ast.ClassDef) and item.name == "Config":
                            config_info = {
                                "model": node.name,
                                "file": py_file.as_posix(),
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
                                            "file": py_file.as_posix(),
                                            "line": item.lineno,
                                            "settings": self._extract_config_dict(item.value),
                                        }
                                    )

        return configs

    async def trace_model_inheritance(
        self, model_name: str, scope: Scope = "main"
    ) -> dict[str, Any]:
        """Trace the inheritance hierarchy of a Pydantic model.

        ``children`` are the model's direct subclasses by definition site (#664),
        so two models with the same name each list only their own children.

        Args:
            model_name: Name of the model to trace
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        models = await self.find_models(scope)
        target = next((m for m in models if m["name"] == model_name), None)
        return await self.inheritance_for(model_name, target, models, scope)

    async def inheritance_for(
        self,
        model_name: str,
        target: dict[str, Any] | None,
        models: list[dict[str, Any]],
        scope: Scope = "main",
    ) -> dict[str, Any]:
        """Build the inheritance answer for *target* (a ``find_models`` record).

        ``children`` are the target's DIRECT subclasses by definition site, from
        the one class graph (#664). With two models of the same name, each lists
        only its own children (#720's note, fixed).
        """
        hierarchy: dict[str, Any] = {
            "model": model_name,
            "parents": [],
            "children": [],
            "mro": [],  # Method Resolution Order
        }

        if target is not None:
            hierarchy["parents"] = target["base_classes"]
            # Where the model is defined, so the result can carry a handle (#627).
            hierarchy["file"] = target["file"]
            hierarchy["line"] = target["line"]
            hierarchy["fields_inherited"] = []
            hierarchy["fields_own"] = target["fields"]

        if target is not None:
            analyzer = self._analyzer()
            module = module_name_for_file(analyzer, Path(target["file"]))
            if module is not None:
                children = await self._direct_subclasses(
                    analyzer, f"{module}.{target['name']}", scope
                )
                hierarchy["children"] = [
                    {"name": c["name"], "file": Path(c["file"]).as_posix(), "line": c["line"]}
                    for c in sorted(children, key=lambda c: (Path(c["file"]).as_posix(), c["line"]))
                ]
        _ = models  # kept for the callers' signature; children come from the graph

        return hierarchy

    async def find_computed_fields(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """Find all computed fields (properties, computed_field decorator).

        Args:
            scope: One scope or a list of scopes (default: this tool's
                ``scope_defaults.methods`` entry in the project config, else
                ``scope_defaults.global``, else <<fact:scope.default.plugin>>):
                <<fact:scopes.options:bullets>>
                A name from the project's ``scope_aliases`` config expands to the
                scopes it lists.
        """
        computed_fields = []

        py_files = await self.get_project_files("*.py", scope)
        for py_file in py_files:
            content = await self._read_source(py_file)
            if content is None:
                continue
            if "computed_field" not in content and "@property" not in content:
                continue

            tree = self._parse_source(py_file, content)
            if tree is None:
                continue

            for node in ast.walk(tree):
                # One record per field (#672): the standard Pydantic v2 spelling
                # stacks @computed_field over @property, and both match.
                if isinstance(node, ast.FunctionDef) and any(
                    self._is_computed_field_decorator(d) for d in node.decorator_list
                ):
                    computed_fields.append(
                        {
                            "name": node.name,
                            "file": py_file.as_posix(),
                            "line": node.lineno,
                            "type": "computed_field",
                            "return_type": self._get_return_type(node),
                        }
                    )

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
        if isinstance(decorator, ast.Call):
            # The called form, e.g. @computed_field(repr=False) (#672).
            return self._is_computed_field_decorator(decorator.func)
        return False

    def _get_return_type(self, node: ast.FunctionDef) -> str | None:
        """Get return type annotation from function."""
        if node.returns:
            return ast.unparse(node.returns) if hasattr(ast, "unparse") else str(node.returns)
        return None
