"""Pydantic framework plugin for enhanced model intelligence."""

import ast
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import resolver
from ..project_layout import module_name_for_file
from .base import AnalyzerPlugin, Scope
from .detection import Detection, declares, scan_for_imports

#: The implicit last base of every class (#870's static C3 ``mro``).
_OBJECT = "builtins.object"


def _installed_api(handle: str, anchor: Any) -> str | None:
    """The pydantic API an installed root implies, from its package's ``version.py`` (#913).

    Reads the literal ``VERSION = '…'`` statically (no import) from the root's
    top-level package directory. ``None`` when it can't be read: the rules are
    then ambiguous.
    """
    module_path = getattr(anchor, "module_path", None)
    if module_path is None:
        return None
    top = handle.split(".", 1)[0]
    for directory in Path(module_path).parents:
        if directory.name != top:
            continue
        version_file = directory / "version.py"
        try:
            tree = ast.parse(version_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return None
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                major = node.value.value.split(".", 1)[0]
                return {"1": _V1, "2": _V2}.get(major)
        return None
    return None


def _compiled_values(anchor: Any) -> list[Any]:
    """The Jedi compiled values behind *anchor*, if it is (or names) a compiled class.

    Uses Jedi internals (``Name._name.infer()`` and ``CompiledValue``);
    ``tests/unit/plugins/test_pydantic_plugin.py::TestCompiledBases`` pins them,
    so a Jedi upgrade that moves them fails loudly rather than silently.
    """
    from jedi.inference.compiled.value import CompiledValue  # type: ignore[import-untyped,unused-ignore]

    if isinstance(anchor, CompiledValue):
        return [anchor]
    inner = getattr(anchor, "_name", None)
    if inner is None or not hasattr(inner, "infer"):
        return []
    values = list(inner.infer())
    if values and all(isinstance(v, CompiledValue) and v.api_type == "class" for v in values):
        return values
    return []


def _compiled_bases(anchor: Any) -> list[tuple[str, Any]] | None:
    """A compiled class's direct bases as ``(handle, value)`` pairs, or ``None`` if not compiled.

    Read from the server interpreter's runtime class through Jedi's compiled
    introspection (``py__bases__``), because a compiled class has no source to
    read (#870). The handle is the base's module plus its qualified name, so
    ``object`` is ``builtins.object``.
    """
    values = _compiled_values(anchor)
    if not values:
        return None
    pairs: list[tuple[str, Any]] = []
    for lazy in values[0].py__bases__():
        # A lazy wrapper in some Jedi paths, the value itself in others.
        for base in lazy.infer() if hasattr(lazy, "infer") else [lazy]:
            module = base.get_root_context().py__name__()
            qualified = ".".join(base.get_qualified_names() or (base.py__name__(),))
            pairs.append((f"{module}.{qualified}", base))
    return pairs


def _c3(start: str, bases: dict[str, list[str]]) -> list[str] | None:
    """The C3 linearisation of *start* over *bases*, or ``None`` if it's inconsistent."""
    memo: dict[str, list[str] | None] = {}

    def linearise(cls: str) -> list[str] | None:
        if cls in memo:
            return memo[cls]
        memo[cls] = None  # a cycle stays None
        heads = [linearise(b) for b in bases.get(cls, [])]
        if any(h is None for h in heads):
            return None
        sequences = [list(h) for h in heads if h] + [list(bases.get(cls, []))]
        result = [cls]
        while any(sequences):
            candidate = next(
                (
                    seq[0]
                    for seq in sequences
                    if seq and not any(seq[0] in other[1:] for other in sequences)
                ),
                None,
            )
            if candidate is None:
                return None  # no consistent order: Python would raise TypeError
            result.append(candidate)
            sequences = [seq[1:] if seq and seq[0] == candidate else seq for seq in sequences]
        memo[cls] = result
        return result

    return linearise(start)


if TYPE_CHECKING:
    from ..analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

#: Which pydantic API a root implies, and so which field rules its models
#: follow (#913): ``"v1"``, ``"v2"``, or ``"installed"`` (read the major version
#: from the resolved root's own package, ``pydantic/version.py``).
_V1, _V2, _INSTALLED = "v1", "v2", "installed"

#: The Pydantic roots a model subclasses (#664): the base name user code writes,
#: each dotted path it can be imported from with the API it implies, and whether
#: an unresolvable root may fall back to matching that base NAME. The
#: ``pydantic.v1`` compatibility roots (#935) never fall back by name: v2's
#: ``BaseModel`` has the same name.
_ROOTS: tuple[tuple[str, tuple[tuple[str, str], ...], bool], ...] = (
    ("BaseModel", (("pydantic.BaseModel", _INSTALLED),), True),
    ("RootModel", (("pydantic.RootModel", _V2),), True),
    (
        "BaseSettings",
        (("pydantic_settings.BaseSettings", _V2), ("pydantic.BaseSettings", _INSTALLED)),
        True,
    ),
    ("GenericModel", (("pydantic.generics.GenericModel", _INSTALLED),), False),
    ("BaseModel", (("pydantic.v1.BaseModel", _V1),), False),
    ("BaseSettings", (("pydantic.v1.BaseSettings", _V1),), False),
    ("GenericModel", (("pydantic.v1.generics.GenericModel", _V1),), False),
)

#: ``x = <call to one of these>`` is not a pydantic v1 field (its ignored types).
_V1_IGNORED_CALLS = frozenset(
    {"property", "classmethod", "staticmethod", "cached_property", "PrivateAttr"}
)


class PydanticPlugin(AnalyzerPlugin):
    """Plugin for Pydantic-specific code intelligence."""

    def name(self) -> str:
        """Return the plugin name."""
        return "Pydantic"

    def detect(self) -> bool:
        """Detect if this project uses Pydantic."""
        return self.detection() == "detected"

    def detection(self) -> Detection:
        """Pydantic declared as a dependency, else imported in a bounded scan (#1143)."""
        if declares(self.project_path, "pydantic"):
            return "detected"
        return scan_for_imports(
            self.project_path, ("from pydantic import", "import pydantic"), self._read_text_or_skip
        )

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

    async def find_models(
        self, scope: Scope = "main", max_unplaced: int | None = 50
    ) -> list[dict[str, Any]]:
        """Find all Pydantic models in the project, direct and indirect (#664).

        A model is a project class that subclasses a Pydantic root
        (``BaseModel``, ``RootModel``, ``BaseSettings``, ``GenericModel``, and
        the ``pydantic.v1`` compatibility classes, #935) directly or through
        other project classes. Models are found by DEFINITION SITE through the
        one class graph (``JediAnalyzer.find_subclasses``, cached per
        generation, #397), so two models with the same name stay distinct and a
        local class that merely shares a root's name is not a model.

        Each model's ``fields`` follow its own pydantic API, from the root it
        descends from (#913): a ``pydantic.v1`` root uses v1 rules, and
        ``pydantic.BaseModel`` uses the installed major version. Under v1 an
        un-annotated public attribute (``x = 1``) is a field, and its record has
        no ``type`` (absent when the field has no annotation). ``fields`` is
        omitted when it can't be known: the API is unknown, or a v1 value can't
        be classified.

        **Unplaced classes (with ``envelope=true``):** a class whose base is an
        expression (``make_base()``, a conditional) has no static base, so it
        can't be placed and isn't reported as a model. The envelope lists every
        such class in the searched scope, pydantic-looking or not, in
        ``unplaced_classes`` (``{name, file, line, base}``, ``[]`` when none; a
        subscripted base like ``Box[int]`` names its class and is placed).
        ``max_unplaced`` (default 50, ``None`` for all) caps that list only:
        when it cuts, the envelope carries ``truncated: true``,
        ``truncation_reasons: ["max_unplaced"]`` and ``total`` (the number of
        unplaced classes), and those refer to ``unplaced_classes`` alone.
        ``results`` is never capped. Without the envelope, ``max_unplaced`` has
        no effect.

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
            max_unplaced: Most ``unplaced_classes`` entries the envelope returns
                (default 50; ``None`` for all). Envelope only.
        """
        _ = max_unplaced  # read by envelope_extras, never by the walk
        analyzer = self._analyzer()
        await self._warn_unreadable_sources(scope)
        roots, unresolved_names = self._resolve_roots(analyzer)

        # Each model follows the API of the root it descends from (#913); a class
        # reached from roots of different APIs, or by base name, is ambiguous (None).
        queue: list[tuple[dict[str, Any], str | None]] = []
        for handle, api in roots.items():
            queue.extend((s, api) for s in await self._direct_subclasses(analyzer, handle, scope))
        if unresolved_names:
            seeds = await self._name_matched_seeds(unresolved_names, scope, analyzer)
            queue.extend((s, None) for s in seeds)

        found: dict[str, tuple[dict[str, Any], str | None]] = {}
        while queue:
            sub, api = queue.pop(0)
            if sub["full_name"] in found:
                if found[sub["full_name"]][1] != api:
                    found[sub["full_name"]] = (found[sub["full_name"]][0], None)
                continue
            found[sub["full_name"]] = (sub, api)
            children = await self._direct_subclasses(analyzer, sub["full_name"], scope)
            queue.extend((child, api) for child in children)

        models = []
        for sub, api in sorted(
            found.values(), key=lambda pair: (Path(pair[0]["file"]).as_posix(), pair[0]["line"])
        ):
            record = await self._model_record(Path(sub["file"]), sub["line"], api)
            if record is not None:
                models.append(record)
        return models

    async def envelope_extras(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """``find_pydantic_models``' ``unplaced_classes``, capped by ``max_unplaced`` (#921)."""
        if tool_name != "find_pydantic_models":
            return {}
        from ..mcp.operations.completeness import DEFAULT_MAX_UNPLACED, MAX_UNPLACED, cap_items

        cap = arguments.get("max_unplaced", DEFAULT_MAX_UNPLACED)
        unplaced = await self._unplaced_classes(arguments.get("scope", "main"))
        kept, truncation = cap_items(unplaced, cap, MAX_UNPLACED, "max_unplaced")
        return {"unplaced_classes": kept, **truncation}

    async def _unplaced_classes(self, scope: Scope) -> list[dict[str, Any]]:
        """Every class in *scope* with a base that can't be placed statically (#921).

        After subscripts are removed, a base that isn't a name or an attribute
        (a call, a conditional, any other expression) has no static class, the
        rule the class graph and ``superclass_bases`` use (#930). One entry per
        class, with its first such base's source text, sorted by file and line.
        """
        from .._ast_targets import unsubscripted

        entries: list[dict[str, Any]] = []
        for py_file in await self.get_project_files("*.py", scope):
            content = await self._read_source(py_file)
            tree = self._parse_source(py_file, content) if content is not None else None
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                base = next(
                    (
                        b
                        for b in node.bases
                        if not isinstance(unsubscripted(b), ast.Name | ast.Attribute)
                    ),
                    None,
                )
                if base is not None:
                    entries.append(
                        {
                            "name": node.name,
                            "file": py_file.as_posix(),
                            "line": node.lineno,
                            "base": ast.unparse(base),
                        }
                    )
        return sorted(entries, key=lambda e: (e["file"], e["line"]))

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

    @staticmethod
    def _resolve_roots(analyzer: "JediAnalyzer") -> tuple[dict[str, str | None], frozenset[str]]:
        """Each resolvable root's definition-site handle with its API, and the unresolved names.

        A name counts as unresolved (for the by-name fallback) only when none of
        the roots that may fall back under it resolves.
        """
        roots: dict[str, str | None] = {}
        fallback_found: dict[str, bool] = {}
        for name, paths, fallback in _ROOTS:
            hit = False
            for path, api in paths:
                found = resolver.resolve_handle(path, analyzer)
                if isinstance(found, resolver.Resolved):
                    hit = True
                    roots.setdefault(
                        found.handle,
                        _installed_api(found.handle, found.anchor) if api == _INSTALLED else api,
                    )
            if fallback:
                fallback_found[name] = fallback_found.get(name, False) or hit
        unresolved = frozenset(name for name, ok in fallback_found.items() if not ok)
        return roots, unresolved

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

    async def _model_record(
        self, py_file: Path, line: int, api: str | None = None
    ) -> dict[str, Any] | None:
        """The ``find_models`` record for the class defined at *py_file*:*line*.

        *api* is the pydantic API its lineage follows (#913). ``fields`` is
        omitted when it can't be fully known under that API.
        """
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
            **self._fields_entry(self._extract_fields(node, api, py_file)),
            "validators": self._extract_validators(node),
            **self._config_entry(self._extract_config(node)),
            "base_classes": [self._get_base_name(base) for base in node.bases],
        }

    async def get_model_schema(
        self, model_name: str, scope: Scope = "main"
    ) -> dict[str, Any] | None:
        """Get the schema for a specific Pydantic model.

        Args:
            model_name: The model to get the schema for: the model's class name, or its canonical handle (a dotted name,
                as ``find_pydantic_models`` returns it) to pick one when several
                models share the name. No match gives the shared not-found shape
                (``found: false``); several give resolve's ambiguous shape
                (``ambiguous: true`` with ``candidates``).
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
                return await self.schema_for(model)

        return None

    async def schema_for(self, model: dict[str, Any]) -> dict[str, Any]:
        """Build the schema answer for one ``find_models`` record.

        Selecting *which* model (by name or handle, and reporting a miss or an
        ambiguity) is the MCP layer's job (#627); this only shapes the answer.
        ``computed_fields`` are the model's own ``@computed_field`` members, read
        from its class body (#870); a plain ``@property`` isn't one.
        """
        schema: dict[str, Any] = {
            "model": model["name"],
            # Where the model is defined, so the result can carry a handle (#627).
            "file": model["file"],
            "line": model["line"],
            "validators": model["validators"],
            "computed_fields": await self._own_computed_fields(Path(model["file"]), model["line"]),
            **({"config": model["config"]} if "config" in model else {}),
        }

        # Categorize fields; all three are omitted when fields aren't known (#913).
        if "fields" in model:
            schema["fields"] = model["fields"]
            schema["required"] = [f for f in model["fields"] if f.get("required", True)]
            schema["optional"] = [f for f in model["fields"] if not f.get("required", True)]

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
                        elif (value := self._model_config_value(item)) is not None:
                            configs.append(
                                {
                                    "model": node.name,
                                    "file": py_file.as_posix(),
                                    "line": item.lineno,
                                    **self._config_entry(
                                        self._extract_config_dict(value), key="settings"
                                    ),
                                }
                            )

        return configs

    async def trace_model_inheritance(
        self, model_name: str, scope: Scope = "main"
    ) -> dict[str, Any]:
        """Trace the inheritance hierarchy of a Pydantic model.

        ``children`` are the model's direct subclasses by definition site (#664),
        so two models with the same name each list only their own children.

        ``mro`` (deprecated, removed in v3.0, #749) is the static C3 order and
        ``fields_inherited`` the fields the model inherits, each with the
        ``defined_in`` handle of the class that declares it. Both come from the
        statically resolved bases, project or installed (#870). Each is OMITTED
        when it can't be computed: a base that doesn't resolve to a class, or no
        consistent order; ``fields_inherited`` also when an ancestor's class body
        can't be read, or its fields can't be known under the model's own pydantic
        API (v1 or v2, #913).

        Args:
            model_name: The model to trace: the model's class name, or its canonical handle (a dotted name,
                as ``find_pydantic_models`` returns it) to pick one when several
                models share the name. No match gives the shared not-found shape
                (``found: false``); several give resolve's ambiguous shape
                (``ambiguous: true`` with ``candidates``).
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
        }

        if target is not None:
            hierarchy["parents"] = target["base_classes"]
            # Where the model is defined, so the result can carry a handle (#627).
            hierarchy["file"] = target["file"]
            hierarchy["line"] = target["line"]
            hierarchy.update(self._fields_entry(target.get("fields"), key="fields_own"))

        if target is not None:
            analyzer = self._analyzer()
            module = module_name_for_file(analyzer, Path(target["file"]))
            # mro and fields_inherited (#870, the maintainer's Q3 ruling): from the
            # statically resolved bases, project or installed; each is OMITTED
            # when it can't be computed, never [] or partial.
            mro = self._mro(analyzer, f"{module}.{target['name']}") if module else None
            if mro is not None:
                hierarchy["mro"] = [handle for handle, _ in mro]  # deprecated (#749)
                own = target.get("fields")
                api = self._mro_api(analyzer, [handle for handle, _ in mro])
                inherited = await self._inherited_fields(mro, own, api) if own is not None else None
                if inherited is not None:
                    hierarchy["fields_inherited"] = inherited
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

    @staticmethod
    def _mro(analyzer: "JediAnalyzer", handle: str) -> list[tuple[str, Any]] | None:
        """*handle*'s static C3 method resolution order, as ``(handle, anchor)`` pairs.

        Each declared base is resolved by the ``superclasses`` edge's own walk
        (:func:`~pyeye.mcp.operations.edges.superclass_bases`, #624), wherever
        it lives: the project, an installed package, or the stdlib (#870's Q3
        ruling, no hard-coded terminals). A class with no bases ends in
        ``builtins.object``. ``None`` (omit, never partial) when a base doesn't
        resolve to a class (a dynamic base, a missing package), a file in the
        walk can't be parsed, or the bases have no consistent C3 order.
        """
        # Imported here, as the docs-facts extractor does: pyeye.mcp's package
        # __init__ imports the server, which imports the plugins.
        from ..mcp.operations.edges import UnparseableSource, superclass_bases

        found = resolver.resolve_handle(handle, analyzer)
        if not isinstance(found, resolver.Resolved):
            return None
        anchors: dict[str, Any] = {found.handle: found.anchor}
        bases: dict[str, list[str]] = {}
        todo = [found.handle]
        while todo:
            current = todo.pop()
            if current in bases:
                continue
            if current == _OBJECT:
                bases[current] = []
                continue
            compiled = _compiled_bases(anchors[current])
            if compiled is not None:
                # A compiled class (no source file, e.g. ``_typing.Generic``):
                # its bases come from Jedi's introspection of the server
                # interpreter's runtime class. No user code runs (#870).
                for base, value in compiled:
                    anchors.setdefault(base, value)
                    todo.append(base)
                bases[current] = [base for base, _ in compiled] or [_OBJECT]
                continue
            try:
                declared = superclass_bases(anchors[current], analyzer)
            except UnparseableSource:
                return None
            if declared is None:
                return None
            names: list[str] = []
            for _text, pair, _detail in declared:
                if pair is None or getattr(pair[1], "type", None) != "class":
                    return None  # unresolved, or resolved to a non-class (a factory call)
                base = str(pair[0])
                anchors.setdefault(base, pair[1])
                names.append(base)
                todo.append(base)
            bases[current] = names or [_OBJECT]
        order = _c3(found.handle, bases)
        return None if order is None else [(h, anchors.get(h)) for h in order]

    async def _inherited_fields(
        self, mro: list[tuple[str, Any]], own: list[dict[str, Any]], api: str | None
    ) -> list[dict[str, Any]] | None:
        """Fields the model inherits, in MRO order, each with its ``defined_in`` handle.

        Read from each ancestor's own class body by the one field rule
        (:meth:`_is_model_field`), installed bases included, so ``BaseModel``
        contributes none and ``RootModel`` contributes ``root``. A name the model
        or a nearer ancestor declares isn't inherited from further up. Each body
        is read under the model's own pydantic API (*api*, #913). ``None`` when an
        ancestor's body can't be read or its fields can't be known under *api*.
        """
        seen = {f["name"] for f in own}
        inherited: list[dict[str, Any]] = []
        for handle, anchor in mro[1:]:
            if handle == _OBJECT or _compiled_bases(anchor) is not None:
                continue  # a compiled class can't declare pydantic fields
            node = await self._class_node(anchor)
            if node is None:
                return None
            module_path = getattr(anchor, "module_path", None)
            fields = self._extract_fields(node, api, Path(module_path) if module_path else None)
            if fields is None:
                return None
            for field in fields:
                if field["name"] not in seen:
                    seen.add(field["name"])
                    inherited.append({**field, "defined_in": handle})
        return inherited

    async def _class_node(self, anchor: Any) -> ast.ClassDef | None:
        """The ``ClassDef`` a Jedi class name points at, from its own (cached) file."""
        module_path = getattr(anchor, "module_path", None)
        line = getattr(anchor, "line", None)
        if module_path is None or line is None:
            return None
        path = Path(module_path)
        content = await self._read_source(path)
        tree = self._parse_source(path, content) if content is not None else None
        if tree is None:
            return None
        return next(
            (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.lineno == line), None
        )

    def _mro_api(self, analyzer: "JediAnalyzer", mro: list[str]) -> str | None:
        """The pydantic API of the first root in *mro*, or ``None`` if none is a root (#913)."""
        roots, _ = self._resolve_roots(analyzer)
        return next((roots[handle] for handle in mro if handle in roots), None)

    @staticmethod
    def _fields_entry(fields: list[dict[str, Any]] | None, key: str = "fields") -> dict[str, Any]:
        """``{key: fields}``, or ``{}`` when the fields can't be known (#913)."""
        return {} if fields is None else {key: fields}

    @staticmethod
    def _is_model_field(item: ast.stmt, api: str | None = _V2) -> bool:
        """Pydantic's field rule for one annotated class-body statement (#870).

        A ``name: T [= value]`` with a plain name, except a ``ClassVar``
        annotation, a private or dunder name (``_x``), and (outside v1, where it
        isn't special) ``model_config``.
        """
        if not (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)):
            return False
        name = item.target.id
        if name.startswith("_") or (name == "model_config" and api != _V1):
            return False
        annotation = item.annotation
        if isinstance(annotation, ast.Subscript):
            annotation = annotation.value
        outer = (
            annotation.id if isinstance(annotation, ast.Name) else getattr(annotation, "attr", None)
        )
        return outer != "ClassVar"

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

    def _extract_fields(
        self, node: ast.ClassDef, api: str | None = _V2, path: Path | None = None
    ) -> list[dict[str, Any]] | None:
        """A model body's fields, in source order, under pydantic *api* (#913).

        Annotated fields follow :meth:`_is_model_field`. A public un-annotated
        ``x = value`` is a field only under v1, which infers its type: its record
        has no ``type`` (absent, never a guess). It isn't a field when the value
        is a lambda, a call to one of v1's ignored types (``property`` …) or
        resolves to a class or function. ``None`` when such an assignment can't
        be classified: the API is unknown, or the value doesn't resolve.
        """
        fields = []

        for item in node.body:
            unannotated = self._public_unannotated_target(item)
            if unannotated is not None:
                assert isinstance(item, ast.Assign)  # noqa: S101 - narrowed above
                if api == _V2:
                    continue  # v2 never makes an un-annotated assignment a field
                verdict = self._v1_value_is_field(item.value, path) if api == _V1 else None
                if verdict is None:
                    return None
                if verdict:
                    fields.append(self._unannotated_field(unannotated, item))
                continue
            if self._is_model_field(item, api) and isinstance(item, ast.AnnAssign):
                assert isinstance(item.target, ast.Name)  # noqa: S101 - narrowed by the rule
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

    @staticmethod
    def _public_unannotated_target(item: ast.stmt) -> str | None:
        """The name of a public, single-name, un-annotated class-level assignment."""
        if (
            isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and not item.targets[0].id.startswith("_")
            and item.targets[0].id not in ("model_config", "Config")
        ):
            return item.targets[0].id
        return None

    def _unannotated_field(self, name: str, item: ast.Assign) -> dict[str, Any]:
        """A v1 field record for ``name = value``: no ``type``, since it isn't annotated."""
        field: dict[str, Any] = {"name": name, "required": False, "line": item.lineno}
        if isinstance(item.value, ast.Call) and self._is_field_call(item.value):
            field["has_field_config"] = True
            field["default"] = "Field(...)"
        else:
            field["default"] = ast.unparse(item.value)
        return field

    def _v1_value_is_field(self, value: ast.expr, path: Path | None) -> bool | None:
        """Whether pydantic v1 makes ``x = value`` a field; ``None`` if it can't be told."""
        if isinstance(value, ast.Lambda):
            return False
        if isinstance(value, ast.Call):
            func = value.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            return name not in _V1_IGNORED_CALLS
        if isinstance(value, ast.Name | ast.Attribute):
            # A type or a function is ignored by v1; anything else is a field.
            kind = self._resolved_kind(value, path)
            if kind is None:
                return None
            return kind not in ("class", "function")
        return True  # a literal or another expression: a field with an inferred type

    def _resolved_kind(self, value: ast.expr, path: Path | None) -> str | None:
        """The Jedi kind (``class``, ``function``, ``statement`` …) *value* names, or ``None``.

        ``None`` when the name doesn't resolve, and for a module: v1's treatment
        of a module-valued attribute isn't one we can state, so it's ambiguous.
        """
        if path is None:
            return None
        from .. import file_artifact_cache
        from .._ast_targets import attr_target_position
        from .._goto import goto_target

        script = file_artifact_cache.get_script(path, self._analyzer().project)
        line, col = attr_target_position(value)
        target = goto_target(script, line, col)
        if target is None:
            return None
        kind = getattr(target, "type", None)
        return None if kind == "module" else kind

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

    async def _own_computed_fields(self, py_file: Path, line: int) -> list[dict[str, Any]]:
        """The ``@computed_field`` members defined in the class at *py_file*:*line* (#870)."""
        content = await self._read_source(py_file)
        tree = self._parse_source(py_file, content) if content is not None else None
        node = next(
            (
                n
                for n in (ast.walk(tree) if tree is not None else ())
                if isinstance(n, ast.ClassDef) and n.lineno == line
            ),
            None,
        )
        if node is None:
            return []
        return [
            {"name": item.name, "line": item.lineno, "return_type": self._get_return_type(item)}
            for item in node.body
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            and any(self._names_computed_field(d) for d in item.decorator_list)
        ]

    @staticmethod
    def _names_computed_field(decorator: Any) -> bool:
        """True for ``@computed_field``, ``@pydantic.computed_field`` or the called form."""
        if isinstance(decorator, ast.Call):
            decorator = decorator.func
        if isinstance(decorator, ast.Name):
            return decorator.id == "computed_field"
        return isinstance(decorator, ast.Attribute) and decorator.attr == "computed_field"

    def _extract_config(self, node: ast.ClassDef) -> dict[str, Any] | None:
        """Extract Config class or model_config from a model.

        ``{}`` when the model sets no config; ``None`` when its ``model_config``
        can't be fully read (#870), so the record omits ``config``.
        """
        config: dict[str, Any] | None = {}

        for item in node.body:
            if isinstance(item, ast.ClassDef) and item.name == "Config":
                config = self._extract_config_settings(item)
            elif (value := self._model_config_value(item)) is not None:
                config = self._extract_config_dict(value)

        return config

    @staticmethod
    def _model_config_value(item: ast.stmt) -> ast.expr | None:
        """The value assigned to ``model_config`` by *item*, plain or annotated (#870)."""
        if isinstance(item, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "model_config" for t in item.targets
        ):
            return item.value
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and item.target.id == "model_config"
        ):
            return item.value
        return None

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

    def _extract_config_dict(self, node: Any) -> dict[str, Any] | None:
        """The settings of a ``model_config`` value, or ``None`` if it can't be fully read.

        Fully read (#870, the maintainer's ruling on Q1) means a dict literal or a
        ``ConfigDict(…)`` / ``SettingsConfigDict(…)`` call, plain or
        module-qualified, whose every entry has a plain key: a string-literal
        dict key, or a keyword argument. A ``**`` splat, a non-literal or
        non-string dict key, a positional argument, or any other expression (a
        function call, a name, a subscript) is unread, and the caller omits the
        config: a partial or empty dict would read as "these are all the
        settings". Values are unparsed source text, as before.
        """
        if isinstance(node, ast.Call) and self._is_config_dict_call(node):
            if node.args or any(keyword.arg is None for keyword in node.keywords):
                return None
            return {
                keyword.arg: ast.unparse(keyword.value) for keyword in node.keywords if keyword.arg
            }
        if isinstance(node, ast.Dict):
            settings: dict[str, Any] = {}
            for key, value in zip(node.keys, node.values, strict=True):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    return None  # a ``**`` splat (key None) or a non-literal key
                settings[key.value] = ast.unparse(value)
            return settings
        return None

    @staticmethod
    def _config_entry(config: dict[str, Any] | None, key: str = "config") -> dict[str, Any]:
        """``{key: config}``, or ``{}`` when the config couldn't be fully read (#870)."""
        return {} if config is None else {key: config}

    @staticmethod
    def _is_config_dict_call(node: ast.Call) -> bool:
        """True for ``ConfigDict(...)`` / ``SettingsConfigDict(...)``, bare or qualified."""
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        return name in ("ConfigDict", "SettingsConfigDict")

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

    def _get_return_type(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        """Get return type annotation from function."""
        if node.returns:
            return ast.unparse(node.returns) if hasattr(ast, "unparse") else str(node.returns)
        return None
