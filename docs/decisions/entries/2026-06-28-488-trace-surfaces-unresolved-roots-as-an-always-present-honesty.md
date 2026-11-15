---
date: "2026-06-28"
title: "trace() surfaces unresolved roots as an always-present honesty field (#488)"
issues: [488]
anchors: ["pyeye.mcp.operations.trace.trace"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-28 — trace() surfaces unresolved roots as an always-present honesty field (#488)

**Friction:** trace()'s first (cold) call returned a clean `nodes: {}` for a root that silently failed to resolve (#488 / #419 cold-start non-determinism) — an agent reads that as "this root has no neighbours," a false-confident negative in the primitive whose entire value is honesty.
**Decision:** Add `unresolved_roots` to the Subgraph. Chose ALWAYS-PRESENT (`[]` when every root resolved, the failed handles otherwise) over the initially-implemented conditional / non-empty-only form: root resolution is always measured, so under the absence-vs-zero invariant absence must mean "not measured," never "all resolved." Made it symmetric with its sibling `unsupported_edges` (same Subgraph, same input-honesty role), NOT with the conditional `report_issues`. Absence is therefore a conformance violation (a broken trace), not a signal. Rejected: conditional presence — it overloads absence with the everyday "all resolved" value and makes a field-dropping bug indistinguishable from a healthy trace.
**Anchor:** `pyeye.mcp.operations.trace.trace`; response_linter rule T.6; #488 (PR pending).
**Verify:** gold — `trace("does.not.exist.Sym", ["members"], analyzer)["unresolved_roots"] == ["does.not.exist.Sym"]`; a resolvable root yields `["unresolved_roots"] == []`; linter T.6 raises on a trace response missing the key. Covered by `tests/unit/mcp/operations/test_trace.py::TestTraceUnresolvedRoots` and `tests/conformance/test_linter_adversarial_trace.py::TestTraceUnresolvedRoots`.
