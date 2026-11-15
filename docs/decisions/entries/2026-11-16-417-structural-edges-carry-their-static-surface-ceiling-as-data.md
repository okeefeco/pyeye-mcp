---
date: "2026-11-16"
title: "Structural edges carry their static-surface ceiling as data, from one table (#417)"
issues: [417, 435, 568, 629]
anchors: ["pyeye.mcp.operations.edges.EDGE_CEILINGS", "pyeye.mcp.operations.edges.CEILING_MEANINGS", "pyeye.mcp.operations.edges.EXACT_EDGES", "pyeye.mcp.operations.expand.expand_resolved", "pyeye.mcp.operations.outline.outline", "pyeye.mcp.operations.trace.trace", "tests/test_static_ceiling.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Structural edges carry their static-surface ceiling as data, from one table (#417)

**Friction:** pyeye's structural edges are complete over what is written in source, not over the runtime. Here is what each one misses:

- `members` misses `self.x` instance attributes and anything a metaclass injects;
- `subclasses` misses `type()`-built classes;
- `imports` misses `importlib` with a computed name.

Issue #568 stated this as one rule in the prose ("a returned list is complete only over its stated scope"). But an agent reads the JSON, not the docstring, on every call, so a bare `stubs: [...]` still reads as exhaustive. `imported_by` documented its ceiling; the other edges didn't.

**Decision:** one table, `edges.EDGE_CEILINGS`, beside `EDGE_APPLIES_TO`, gives each implemented edge **one** ceiling id, whatever the source's kind:

| edge | ceiling id |
|---|---|
| `members` | `static_definitions` |
| `subclasses` | `literal_subclassing` |
| `superclasses` | `declared_bases` |
| `imports`, `imported_by` | `static_imports` |
| `callees` | `static_calls` |
| `submodules` | `on_disk_modules` |

- `CEILING_MEANINGS` gives each id its one definition, which the tool descriptions and the skill quote verbatim.
- `enclosing_scope` is exact (lexical nesting has no runtime half) and listed in `EXACT_EDGES`. Every implemented edge is in exactly one of the two.
- The value is a constant per edge, so it costs nothing to compute.

Where it appears:

- **expand:** `ceiling` on the supported branch.
- **outline:** `ceiling` on the **root only** (one constant for the whole tree): the members walk's id, or `on_disk_modules` for a package survey. Absent for a non-container root.
- **trace:** `ceilings: {edge: id}` for each walked edge that has one. It is left out when there are none, never `{}`, following #435.

**Rejected:**

- docs and skill only, which leaves the JSON consumer blind;
- ids that depend on kind (e.g. `class_body` vs `module_scope`), which would make trace's per-edge map ambiguous.

**Anchor:** `pyeye.mcp.operations.edges` (`EDGE_CEILINGS`, `EXACT_EDGES`, `CEILING_MEANINGS`); `expand.expand_resolved`; `outline.outline`; `trace.trace`; linter `_EDGE_CEILINGS` / `_check_ceilings` (C.1–C.3); `tests/test_static_ceiling.py`; the expand, outline and trace tool descriptions; the `python-explore` skill; #417.
**Applies-to:**

- every implemented edge in `edges._IMPLEMENTED_EDGES`: each is either in `EDGE_CEILINGS` or in `EXACT_EDGES`, and a test sweeps both;
- every response that returns a structural edge's result: `expand`'s supported branch, `outline`'s root and `trace`'s result.

A new edge must be added to one of the two tables, or the test fails.

**Verify:** gold. `uv run pytest tests/test_static_ceiling.py` sweeps:

- the table against `_IMPLEMENTED_EDGES`, `CEILING_MEANINGS` and the linter's independent copy;
- every id's definition in the expand description and the skill;
- live expand responses for every edge;
- the outline root in member, survey and non-container cases;
- trace with and without ceiling-bearing edges.

The conformance linter (C.1–C.3) then checks the field's value and placement on every response in the suite.
