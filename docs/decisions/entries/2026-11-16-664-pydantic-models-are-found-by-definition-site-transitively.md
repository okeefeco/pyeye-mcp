---
date: "2026-11-16"
title: "Pydantic models are found by definition site, transitively; base names only for an unresolvable root (#664)"
issues: [664, 627, 720, 397]
anchors: ["pyeye.plugins.pydantic.PydanticPlugin.find_models", "_resolve_roots", "_name_matched_seeds", "_direct_subclasses", "inheritance_for", "_ROOTS", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.find_subclasses"]
status: "active"
amends: ["2026-11-15-627-plugin-results-get-handles-only-from-the-shared-resolver-an.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Pydantic models are found by definition site, transitively; base names only for an unresolvable root (#664)

**Friction:** `_is_pydantic_model` counted a class as a model only when a DIRECT base was named `BaseModel` / `BaseSettings` / `RootModel`.

- `class User(Timestamped)`, where `Timestamped(BaseModel)`, was missing from `find_pydantic_models`, `get_model_schema` and `trace_model_inheritance`, with no signal.
- `trace_model_inheritance` matched children by base NAME, so with two models named `User` a child of either was listed under both. #720 documented that and didn't fix it.

**Decision:**

- **Models are found by definition site, transitively.** A model is a project class that subclasses a Pydantic root, directly or through project classes.
  - `find_models` resolves each root in `_ROOTS` to its definition site (`pydantic.BaseModel` → `pydantic.main.BaseModel`).
  - It then walks `JediAnalyzer.find_subclasses` breadth-first, over the one class graph cached per generation (#397), so each hop is a lookup.
  - Same-named models stay distinct, and a local class that merely shares a root's name (`class BaseModel: …`) is not a model.
- **Children by definition site too.** `trace_model_inheritance`'s `children` are the target's direct subclasses by definition site.
- **A weaker fallback, only for an unresolvable root.** When a root's package isn't importable where pyeye analyses (for example, when pydantic-settings isn't importable, BaseSettings subclasses are found by direct base name), that root's direct subclasses are matched by the base name in the class statement. The walk continues from them by definition site. Name matching never applies to a root that resolves.
  - The tool docstrings say so. No field marks which models were found by name, because the record shape is unchanged in v2.x.
- **The plugin contract is kept.** A Pydantic-looking file that can't be read or parsed is still skipped with a warning (#637), because the class graph skips it silently (#729).
- The analyzer comes from `pyeye.project_manager`, the server's instance, so the plugin reads the same layout and never imports `pyeye.mcp`.
- A v2.x Fixed: more models, and children no longer conflated. No field, tool or argument changes.

**Anchor:** `pyeye.plugins.pydantic.PydanticPlugin.find_models`, `_resolve_roots`, `_name_matched_seeds`, `_direct_subclasses`, `inheritance_for`, `_ROOTS`; `JediAnalyzer.find_subclasses`; #664, #720, #397.
**Applies-to:**

- `PydanticPlugin.find_models` and everything that reads it: `get_model_schema`, `find_validators`, `find_field_validators`, `find_model_config`, and `pyeye.mcp.server._lookup_model`;
- `PydanticPlugin.inheritance_for` (`trace_model_inheritance`'s `children`);
- the tests `tests/test_pydantic_indirect_models.py`.

**Verify:** gold. `uv run pytest tests/test_pydantic_indirect_models.py` passes:

- indirect models (two hops) are found, and a local `BaseModel` lookalike is not;
- records keep their shape;
- the two `User` models each list only their own children;
- `BaseSettings` subclasses are found by name when `pydantic_settings.BaseSettings` doesn't resolve;
- name matching is never invoked for a root that resolves.
