---
date: "2026-11-15"
title: "trace walks exactly what expand supports: one hop = one `expand` (#621)"
issues: [621]
anchors: ["pyeye.mcp.operations.expand.expand_resolved", "pyeye.mcp.operations.trace.trace"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — trace walks exactly what expand supports: one hop = one `expand` (#621)

**Friction:** `trace` and `expand` walked the same edges under different contracts. trace queued the Jedi `Name` each edge carried, so it walked interior handles `expand` refuses as unresolved (`logging`, `io`; #602). That walk reached Jedi's ~1500-frame `follow_imports` recursion on `io`/`weakref`, which killed the process on Windows/CPython 3.11 (#650). A resolver's wrong-kind `None` became `[]`, so `trace(SomeClass, ["imports"])` answered `unresolved_imports: {}, unsupported_edges: []`: "measured, all resolved" for something never measured. And `max_nodes` filled one adjacent at a time, so a hop could silently keep 2 of 7 members.
**Decision:** Every trace hop is `expand_resolved(name, handle, edge)`, the body of `expand` after source resolution. `expand` is now "resolve, then `expand_resolved`", so there is one copy of the expandability logic.

- Roots and interior nodes both resolve through `resolver.resolve_handle` (#623), the resolver `expand` uses; interior nodes are resolved when popped. A node that doesn't resolve is not walked and is listed in the new always-present `unresolved_nodes` (Added; it parallels `unresolved_roots`, because #545's not-found decision left trace's list shape in place).
- A wrong-kind hop adds `{edge, reason, detail}` to `unsupported_edges` with `expand`'s own values, de-duplicated. In a mixed-kind walk an entry means "not walked for nodes of the kind named in `detail`", not "the edge is unsupported".
- `unresolved_call_sites` / `unresolved_imports` are present iff their edge was actually walked on at least one node, not merely requested.
- Hops are all-or-nothing (reserve before expand, the #358 outline rule). If any new adjacent would be cut by `max_depth` or `max_nodes`, the hop adds and records nothing (cycle edges included) and sets the truncation reason. A recorded hop is always complete; an unrecorded one is covered by `truncation_reasons`, within the existing fields.
- Rejected: copying expand's checks into trace (a third copy); filling partially and adding a per-node truncation field (new shape for what reserve-before-expand already makes honest); leaving unresolvable interior nodes silently unwalked (the measured-empty lie again).
- Not fixed here: a direct `expand("io", "imports")` still recurses ~1500 frames inside Jedi. #650 guards it at the server layer (all Jedi work on one large-stack worker thread), so it raises RecursionError, caught as an unresolved import, rather than crashing; code calling the operations directly on the main thread is not covered.
**Anchor:** `pyeye.mcp.operations.expand.expand_resolved`; `pyeye.mcp.operations.trace.trace`; response_linter rule T.9.
**Applies-to:** every place trace decides what to walk or how to report it:
- `trace` root hops and interior hops (both through `expand_resolved`);
- the Subgraph fields `unsupported_edges`, `unresolved_nodes`, `unresolved_call_sites`, `unresolved_imports` and `truncation_reasons`;
- the documented shape in `trace.py`'s module docstring, the `trace` tool docstring in `server.py`, and `skills/python-explore/SKILL.md`;
- linter rules T.4–T.9.
- Out of scope: the single edge-applicability table (#626), which will replace the resolvers' `None` signal that `expand_resolved` reads.
**Verify:** gold. `uv run pytest tests/unit/mcp/operations/test_trace.py tests/conformance/test_linter_adversarial_trace.py tests/test_cross_tool_invariants.py::test_trace_expand_agree` passes:
- `TestTraceInteriorNodesFollowExpand`: with the shared resolver rejecting `textwrap`, it is a node, is listed in `unresolved_nodes`, and the imports edge resolver is never run on it; a node the resolver finds is walked exactly as `expand` walks it;
- `TestTraceWrongKindIsUnsupported`: the entry equals `expand`'s `{reason, detail}`, and `unresolved_imports` is absent;
- `TestTraceHopBudgetIsAllOrNothing`: every recorded hop equals `expand`'s stub set for `max_nodes` ∈ {1, 2, 3, 4, 6, 9, 50};
- the #614 fitness test has no `trace_expand` allow-list entries left.
