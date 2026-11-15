---
date: "2026-11-16"
title: "expand stubs and resolve's ambiguous candidates are capped by default; a cut is left out or fully disclosed (#435)"
issues: [435, 422, 508, 629]
anchors: ["pyeye.mcp.operations.completeness.cap_items", "pyeye.mcp.operations.completeness.check_cap", "pyeye.mcp.operations.completeness.DEFAULT_MAX_STUBS", "pyeye.mcp.operations.completeness.DEFAULT_MAX_CANDIDATES", "pyeye.mcp.operations.expand.expand", "pyeye.mcp.operations.resolve.resolve", "tests/test_default_caps.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — expand stubs and resolve's ambiguous candidates are capped by default; a cut is left out or fully disclosed (#435)

**Friction:** `expand` had no cap, no `truncated` and no count. A wide edge (`imported_by` on a hub module, `members` of a large module, the old 962-wide `subclasses`, #422) over-produced, and the MCP harness truncated or spilled it silently, so pyeye never knew. An ambiguous bare-name `resolve` was uncapped too; #508's member fallback widened it, and names like `get` or `save` can match hundreds of symbols on a large project.

**Decision (the user's, on #435):**

- **Caps are on by default.** `expand(..., max_stubs=200)` and `resolve(..., max_candidates=50)`. `None` lifts a cap.
  - It's classified non-breaking under #629's 2.x rule: no field or argument is removed, and a cut is always disclosed.
  - The fragment states the new defaults prominently.
- **Leave out, never false.** When nothing is cut, there is no `truncated`, `truncation_reasons` or `total`. When a cap cuts, all three appear: `truncated: true`, `truncation_reasons: ["max_stubs"]` (or `["max_candidates"]`), and `total`, the exact full size. That size is free, because the list was already built.
  - `completeness.cap_items` is the single place that decides this, so flipping the rule would be one line.
  - `trace` keeps its pre-#435 always-present `truncated`, because removing a key is barred in 2.x.
- **What a cut keeps:** the first items in their existing order. That is the edge's order for `expand` and the sorted order for candidates.
- **Counts:** `total`, not an edge-named count. `expand` walks one edge per call, so `total` is unambiguous, while the edge names don't singularise cleanly (`imported_by`, `enclosing_scope`). `outline` keeps its #599 edge-named counts, because one tree mixes edges and modes.
- **Where the cap applies:** stubs are capped **before** they are built, in `expand_resolved`. `trace` calls that with no cap, because it has its own node budget.
- **Invalid caps:** a cap that isn't a positive int or `None` raises `ValidationError` before any work. Slice C makes that an MCP tool error naming the parameter.
- **Registry:** `max_stubs` and `max_candidates` join `TRUNCATION_REASONS` as budget reasons.

**Rejected:**

- opt-in caps (default unlimited), which leave the silent harness spill in place;
- a cap on `resolve` only;
- an edge-named count on `expand`.

**Anchor:** `pyeye.mcp.operations.completeness` (`cap_items`, `check_cap`, `DEFAULT_MAX_STUBS`, `DEFAULT_MAX_CANDIDATES`, the `max_stubs` / `max_candidates` reasons); `expand.expand` / `expand_resolved`; `resolve.resolve` / `_resolve_bare_name`; the `expand` and `resolve` MCP tools; linter L.1 (`_LIST_CAPS`); #435.
**Applies-to:** every flat list a primitive returns that can grow with the project:

- `expand`'s `stubs` (every edge);
- `resolve`'s ambiguous `candidates`, which today come only from the bare-name path.

Not capped this way:

- `trace`, which has its own `max_nodes`;
- `outline`, which has `max_nodes`;
- the per-edge disclosure lists (`unresolved_*`), which are bounded by the source they describe.

A new capped list must go through `cap_items` and add its reason to the table.

**Verify:** gold. `uv run pytest tests/test_default_caps.py` covers:

- both defaults, on a generated 250-member module;
- `None` lifting the cap;
- an uncut list, which has none of the fields;
- order preserved on a cut;
- `trace` unaffected;
- invalid caps raising `ValidationError` and reaching the client as a tool error.

`tests/test_completeness_registry.py` pins the linter's `_LIST_CAPS` to the table. Linter L.1 checks all-or-nothing on every `expand` and `resolve` response in the suite.
