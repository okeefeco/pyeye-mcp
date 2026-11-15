---
date: "2026-11-16"
title: "Class-body bindings are `attribute`; enum members are `enum_member` (#695)"
issues: [695, 623, 643]
anchors: ["pyeye.kinds.KINDS", "pyeye.kinds.normalise_kind_from_name", "pyeye.kinds.class_body_kind", "pyeye.mcp.operations.inspect.inspect"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Class-body bindings are `attribute`; enum members are `enum_member` (#695)

**Friction:** every class-body binding reported `kind: "variable"`, the same as a module- or function-level name. `attribute` was in the closed vocabulary (#643) but was never emitted. An enum member such as `Color.RED` was also a `variable`, and its value's type read as `int`, so an agent couldn't tell a class attribute or an enum member from a local without another call.

**Decision:** (the user's, recorded on #695.) The refinement happens in one seam, `pyeye.kinds.normalise_kind_from_name`, after the Jedi-type mapping. It covers only a `statement` whose enclosing scope is a class (`class_body_kind`).

- **`attribute`** for every class-body binding: assigned, annotated, or `ClassVar[...]`. Module- and function-level names stay `variable`. This conforms to the documented vocabulary, so it's `Fixed`.
- **`enum_member`**, a new kind (`Added`), when the enclosing class is a **transitive `enum.Enum` subclass** and the binding is a member by Python's rules.
  - Detection walks the class's **own** MRO as Jedi infers it (typeshed's `IntEnum` / `StrEnum` / `Flag` and project-defined enum bases included), with no project-wide scan. An unresolvable base truncates that MRO, so the class isn't an enum and the binding falls back to `attribute`.
  - Never a member, so `attribute`: `_sunder_` and `__dunder__` names; names listed in a literal `_ignore_` (a non-literal `_ignore_` makes every binding `attribute`); `nonmember(...)`, `property(...)`, `staticmethod(...)`, `classmethod(...)`; lambdas; values inferred as functions, classes or properties; an annotation with no value; a value Jedi can't infer.
  - `member(...)` is a member. Methods and nested classes keep `method` / `class`.
  - The honest direction: wherever membership can't be decided statically the answer is `attribute`, never `enum_member`.
- `inspect` gives `enum_member` the attribute fields. `default` is the member's literal value. `type` comes only from an annotation, never from the value's inferred type (`RED = 1` is a `Color`, not an `int`).
- Rejected: keeping `variable` with the context left to the parent handle. That costs an agent a second call to tell an attribute from a local.
- Rejected: a project-wide search for enum subclasses, which would make `inspect` expensive by default.

**Anchor:** `pyeye.kinds.KINDS` / `normalise_kind_from_name` / `class_body_kind`; `pyeye.mcp.operations.inspect` (kind-dependent fields); `docs/api-redesign.md` (the `kind` row); the conformance linter's K.1 vocabulary; #695, #623, #643.
**Applies-to:**

- the seam, `pyeye.kinds.normalise_kind_from_name` and `class_body_kind` with its helpers, and its four callers, which inherit it: `pyeye.resolver.resolve_handle` (the `kind` of `resolve` / `resolve_at` / `inspect`), `pyeye.mcp.operations.stubs.build_stub` (`outline` / `expand` / `trace` stubs), `pyeye.mcp.operations.edges.edge_kind` (edge applicability: `enum_member` is in `KINDS`, so `enclosing_scope` applies to it) and `pyeye.resolver.handle_for_anchor` (a module check only, unaffected);
- `pyeye.mcp.operations.inspect`'s kind-dependent fields;
- the closed vocabulary's other copies: `KINDS`, `docs/api-redesign.md`, the linter's K.1 set, `tests/unit/test_kinds.py`, the `inspect` tool description and the python-explore skill.

**Verify:** gold. `uv run pytest tests/integration/test_attribute_enum_member_kinds.py tests/unit/test_kinds.py tests/integration/test_kind_vocabulary.py tests/conformance` passes:

- the class-attribute forms are `attribute` in `resolve` and `inspect` (which agree), and in `expand(members)` stubs;
- module and function names stay `variable`;
- enum members under `Enum` (also `auto()`), `IntEnum`, `StrEnum`, `Flag`, a project-defined enum base and `member(...)` are `enum_member`;
- every non-member case is `attribute`, one test each;
- enum methods and nested classes keep their kinds;
- unresolvable bases (dynamic, missing) fall back to `attribute`;
- `inspect` of an enum member shows its value and no inferred `type`;
- the vocabulary includes `enum_member`.
