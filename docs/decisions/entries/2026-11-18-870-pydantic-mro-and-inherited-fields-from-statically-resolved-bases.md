---
date: "2026-11-18"
title: "Pydantic mro and fields_inherited come from statically resolved bases, project or installed, and are omitted when not computable (#870)"
issues: [870, 749, 568, 921, 922]
anchors: ["pyeye.plugins.pydantic.PydanticPlugin._mro", "pyeye.plugins.pydantic.PydanticPlugin._inherited_fields", "pyeye.plugins.pydantic.PydanticPlugin._is_model_field", "pyeye.plugins.pydantic.PydanticPlugin._has_unannotated_public_assignment", "pyeye.plugins.pydantic._compiled_bases", "pyeye.plugins.pydantic._c3", "pyeye.plugins.pydantic.PydanticPlugin.inheritance_for"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-18-913-pydantic-field-rules-follow-the-models-own-api.md"]
superseded_by: []
---

## 2026-11-18 — Pydantic mro and fields_inherited come from statically resolved bases, project or installed, and are omitted when not computable (#870)

**Friction:** `trace_model_inheritance`'s `mro` and `fields_inherited` were always `[]`, which a caller can't tell from "none" (#568). Read literally, "in-project ancestors only" would omit both for every real model, because `pydantic.BaseModel` is installed code. Hard-coding pydantic's base classes as known stopping points fails too: v1 and v2 differ, and `RootModel` brings in `typing.Generic`.

**Decision** (the maintainer's ruling on #870's Q3, as amended, 2026-11-18):

- **Statically resolvable, not in-project.** Each declared base is resolved by the `superclasses` edge's own walk (`superclass_bases`, #624), wherever it lives: the project, an installed package (pyeye's external scope), or the stdlib. There are no hard-coded terminals.
- **`mro` is the static C3 linearisation.** A class with no bases ends in `builtins.object`.
- **`fields_inherited` lists each ancestor's fields** in MRO order, read from its own class body. Each entry has `fields_own`'s shape plus `defined_in`, the declaring class's handle. A name the model or a nearer ancestor declares isn't inherited from further up.
- **One field rule for own and inherited fields.** A field is a class-body `name: T [= v]` with a plain name. Excluded: a `ClassVar` annotation, a private or dunder name (`_x`), and `model_config`. So pydantic's `BaseModel` contributes no fields and `RootModel` contributes `root`. Applying the rule to `fields_own` too removes wrong entries (`model_config`, `ClassVar` attributes), which is a fix (#629).
- **Omitted, never `[]` or partial.** Both fields are omitted when:
  - a base doesn't resolve to a class: a dynamic base (whose expression resolves to a function, #922), a missing package, or an import that won't resolve;
  - a file in the walk can't be parsed;
  - C3 finds no consistent order.

  `fields_inherited` alone is also omitted when an ancestor's body has an un-annotated public class-level assignment. Pydantic v1 makes such an attribute a field and v2 doesn't, so the list can't be known. `fields_own` keeps its existing behaviour for that v1 case (a separate issue).
- **Compiled bases.** A base with no source file, such as `_typing.Generic` from the C `_typing` module, gets its bases from Jedi's compiled introspection (`py__bases__`). This reads the server interpreter's runtime class for compiled bases only. It's still static resolution in the maintainer's sense, because no user code runs. A compiled class can't declare pydantic fields, so it contributes none. A test pins the Jedi internals this uses.
- **`mro` is deprecated,** for removal in v3.0 under #749, and classified `Fixed` with a deprecation note.
- **Cost:** the walk runs per model in `trace_model_inheritance` only; no listing tool computes it. The first hop into an installed package costs a cold Jedi inference, and warm calls are bounded (a PerformanceThresholds test).

**Anchor:** `pyeye.plugins.pydantic.PydanticPlugin._mro`, `_inherited_fields`, `_is_model_field`, `_has_unannotated_public_assignment`, `inheritance_for`; `pyeye.plugins.pydantic._compiled_bases`, `_c3`; `pyeye.mcp.operations.edges.superclass_bases`; #870 (Q3), #749, #568, #624, #921, #922.
**Applies-to:**

- the base walk and the C3 order: `pyeye.plugins.pydantic.PydanticPlugin._mro`, `pyeye.plugins.pydantic._c3`, `pyeye.plugins.pydantic._compiled_bases`;
- inherited fields: `pyeye.plugins.pydantic.PydanticPlugin._inherited_fields`, `pyeye.plugins.pydantic.PydanticPlugin._has_unannotated_public_assignment`;
- the field rule, for own and inherited fields: `pyeye.plugins.pydantic.PydanticPlugin._is_model_field`, through `pyeye.plugins.pydantic.PydanticPlugin._extract_fields`;
- the answer: `pyeye.plugins.pydantic.PydanticPlugin.inheritance_for` (`trace_model_inheritance`).

**Verify:** GOLD. `uv run pytest tests/unit/plugins/test_pydantic_plugin.py -k "FieldRule or Inheritance or Compiled"` covers:

- the C3 order through installed pydantic v2;
- inherited fields with `defined_in` and overrides;
- `RootModel` inheriting `root` through the compiled `Generic`;
- the v1-shaped fixture package;
- omission for a dynamic base, a missing package, an inconsistent order and a v1-style assignment;
- the own-field exclusions;
- the pinned Jedi internals;
- the warm-cost bound.
