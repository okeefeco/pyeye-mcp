---
date: "2026-11-18"
title: "An unread Pydantic model_config is omitted, not empty; get_model_schema counts @computed_field only (#870)"
issues: [870, 568]
anchors: ["pyeye.plugins.pydantic.PydanticPlugin._extract_config_dict", "pyeye.plugins.pydantic.PydanticPlugin._extract_config", "pyeye.plugins.pydantic.PydanticPlugin._config_entry", "pyeye.plugins.pydantic.PydanticPlugin.find_model_config", "pyeye.plugins.pydantic.PydanticPlugin.schema_for", "pyeye.plugins.pydantic.PydanticPlugin._own_computed_fields"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — An unread Pydantic model_config is omitted, not empty; get_model_schema counts @computed_field only (#870)

**Friction:** #870 found three Pydantic fields that came back empty when they shouldn't. Fixing the `ConfigDict(...)` reader (#908) left a case it can't fix: a `model_config` that static analysis can't read in full (`make_config()`, `ConfigDict(**BASE, frozen=True)`). Reporting `{}` or the literal keys reads as "these are all the settings", which breaks the absence-vs-zero contract (#568). Separately, "computed fields" had two possible meanings: pydantic's `@computed_field`, or any `@property`, as `find_computed_fields` documents.

**Decision** (the maintainer's rulings on #870's Q1 and Q2, 2026-11-18):

- **Q1: omit when unread.** A model's `config` (in `find_pydantic_models` and `get_model_schema`) and `find_model_config`'s `settings` are present only when the `model_config` value is **fully read**. That means a dict literal or a `ConfigDict(…)` / `SettingsConfigDict(…)` call (bare or module-qualified) whose every entry has a plain key: a string-literal dict key, or a keyword argument. A `**` splat, a non-literal or non-string key, a positional argument, or any other right-hand side (a function call, a name, a subscript) counts as unread, and the key is omitted. Wrong data is worse than none. Values stay unparsed source strings. A model with no configuration at all is measured: `{}`.
- A form the reader ought to handle but doesn't is a reader bug, filed separately. It isn't a reason to report partial settings.
- The key stays in the contract, present whenever measured, so this is classified `Fixed`, not breaking.
- **Q2: `get_model_schema`'s `computed_fields` counts `@computed_field` members only** (bare, qualified or called), from the model's own class body: what pydantic serialises. `find_computed_fields` keeps its documented contract, which also lists a plain `@property`.
- Q3 (`mro`, `fields_inherited`) is decided separately.

**Anchor:** `pyeye.plugins.pydantic.PydanticPlugin._extract_config_dict`, `_extract_config`, `_config_entry`, `find_model_config`, `schema_for`, `_own_computed_fields`; #870 (Q1, Q2), #568, #908.
**Applies-to:**

- the config reader and the two places that report it: `pyeye.plugins.pydantic.PydanticPlugin._extract_config_dict`, `pyeye.plugins.pydantic.PydanticPlugin._extract_config` (the `find_models` records, and so `find_pydantic_models` and `get_model_schema`), and `pyeye.plugins.pydantic.PydanticPlugin.find_model_config`;
- the schema's computed fields: `pyeye.plugins.pydantic.PydanticPlugin.schema_for`, `pyeye.plugins.pydantic.PydanticPlugin._own_computed_fields`.

**Verify:** GOLD. `uv run pytest tests/unit/plugins/test_pydantic_plugin.py -k "ModelConfigForms or SchemaComputedFields"` covers every readable form, each unread form omitting `settings` and `config` (call, name, subscript, call with `**`, call with a positional argument, dict with `**`, dict with a name key and with an int key), `{}` for a model with no config, and computed fields excluding a plain `@property` and another class's members.
