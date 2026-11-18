---
date: "2026-11-18"
title: "Pydantic field rules follow each model's own API, from its root; pydantic.v1 roots are models (#913, #935)"
issues: [913, 935, 870, 568]
anchors: ["pyeye.plugins.pydantic._ROOTS", "pyeye.plugins.pydantic._installed_api", "pyeye.plugins.pydantic.PydanticPlugin._resolve_roots", "pyeye.plugins.pydantic.PydanticPlugin.find_models", "pyeye.plugins.pydantic.PydanticPlugin._extract_fields", "pyeye.plugins.pydantic.PydanticPlugin._v1_value_is_field", "pyeye.plugins.pydantic.PydanticPlugin._inherited_fields", "pyeye.plugins.pydantic.PydanticPlugin._mro_api"]
status: "active"
amends: ["2026-11-18-870-pydantic-mro-and-inherited-fields-from-statically-resolved-bases.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — Pydantic field rules follow each model's own API, from its root; pydantic.v1 roots are models (#913, #935)

**Friction:** pydantic v1 makes an un-annotated public class attribute (`x = 1`) a field, and v2 doesn't. `fields_own` read only annotated entries, so a v1 model's list was partial. #870's Q3 ruling dealt with the same ambiguity in `fields_inherited` by omitting the key whenever an ancestor had such an attribute. Pydantic 2 also ships the v1 API as `pydantic.v1`, so one install can hold both kinds of model, and `find_pydantic_models` found no `pydantic.v1` models at all (#935).

**Decision** (approved by the coordinator on the maintainer's #870 rulings, 2026-11-18):

- **The rules are a property of the model's lineage, not the install.** Each root records the API it implies:
  - `pydantic.v1.BaseModel`, `BaseSettings` and `GenericModel` imply v1;
  - `pydantic_settings.BaseSettings` and `pydantic.RootModel` imply v2;
  - `pydantic.BaseModel`, `pydantic.BaseSettings` and `pydantic.generics.GenericModel` imply the installed major version. That version is read statically from the literal `VERSION` in the resolved root's own `version.py`, with no import.

  A model takes the API of the root it descends from. A class reached from roots of different APIs, or only by base-name fallback, has an unknown API.
- **`pydantic.v1` roots are model roots.** They never fall back by base name, because v2's `BaseModel` has the same name.
- **The v1 field rule:** a public, single-name, un-annotated class-level assignment is a field unless its value is a lambda, a call to one of v1's ignored types (`property`, `classmethod`, `staticmethod`, `cached_property`, `PrivateAttr`), or a name that resolves to a class or a function. v1 also doesn't treat `model_config` specially. An un-annotated v1 field's record has **no `type`**: absent when the field has no annotation, never a guess. This is consistent with the Q1 ruling on #870.
- **Omit on ambiguity.** `fields` (and the schema's `fields`, `required` and `optional`, and `fields_own`) is omitted when such an assignment can't be classified, either because the API is unknown or because the value doesn't resolve (for example a name from a missing package, or a module).
- **`fields_inherited` uses the same rules,** under the API of the first root in the model's `mro`. This amends #870's Q3 entry: its blanket omission when an ancestor has an un-annotated attribute is replaced. A v2 model's inherited list skips such attributes, and a v1 model's includes them.
- Classified `Fixed`, and additive: models and fields that were missing appear, and `type` is absent only on records that never existed before.

**Anchor:** `pyeye.plugins.pydantic._ROOTS`, `_installed_api`, `_V1_IGNORED_CALLS`; `PydanticPlugin._resolve_roots`, `find_models`, `_model_record`, `_extract_fields`, `_v1_value_is_field`, `_resolved_kind`, `_inherited_fields`, `_mro_api`, `schema_for`; amends `2026-11-18-870-pydantic-mro-and-inherited-fields-from-statically-resolved-bases.md`; #913, #935, #870, #568.
**Applies-to:**

- the roots and their APIs: `pyeye.plugins.pydantic._ROOTS`, `pyeye.plugins.pydantic._installed_api`, `pyeye.plugins.pydantic.PydanticPlugin._resolve_roots`, and the lineage walk in `pyeye.plugins.pydantic.PydanticPlugin.find_models`;
- the field rules: `pyeye.plugins.pydantic.PydanticPlugin._extract_fields`, `pyeye.plugins.pydantic.PydanticPlugin._v1_value_is_field`, `pyeye.plugins.pydantic.PydanticPlugin._is_model_field`;
- where they're reported: `pyeye.plugins.pydantic.PydanticPlugin._model_record` (`find_pydantic_models`), `pyeye.plugins.pydantic.PydanticPlugin.schema_for` (`get_model_schema`), `pyeye.plugins.pydantic.PydanticPlugin.inheritance_for` and `pyeye.plugins.pydantic.PydanticPlugin._inherited_fields` (`trace_model_inheritance`).

**Verify:** GOLD. `uv run pytest tests/unit/plugins/test_pydantic_plugin.py -k "V1 or unannotated"` covers:

- v1 models under a v2 install, and a mixed project;
- v1 own fields, including un-annotated ones with no `type`, and the ignored values;
- a v1 child inheriting un-annotated fields;
- an unclassifiable value omitting `fields` and the schema's three keys;
- a v2 model ignoring un-annotated assignments, in its own and inherited fields;
- an installed pydantic 1.x read from its `version.py`.
