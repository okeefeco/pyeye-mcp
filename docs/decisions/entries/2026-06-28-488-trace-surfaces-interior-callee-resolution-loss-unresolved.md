---
date: "2026-06-28"
title: "trace() surfaces interior callee-resolution loss (unresolved_call_sites) (#488)"
issues: [488]
anchors: ["pyeye.mcp.operations.trace.trace", "pyeye.mcp.operations.trace._single_hop"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-28 — trace() surfaces interior callee-resolution loss (unresolved_call_sites) (#488)

**Friction:** `unresolved_roots` made the ROOT layer honest, but the same goto non-determinism (#419) plus inherently-dynamic calls leave INTERIOR callee walks incomplete — and `trace` silently dropped the per-node unresolved-call-site count that `expand(callees)` already reports. A populated, `unresolved_roots: []` subgraph could still be quietly lossy and read as complete.
**Decision:** Carry `EdgeResult.unresolved_call_sites` through `_single_hop` and surface a `{source_handle: count}` map on the Subgraph. Chose PRESENT-IFF-CALLEES-TRACED (not always-present like `unresolved_roots`): call sites are only measured when `callees` is followed, so an absent key is the honest "not measured" (absence-vs-zero), `{}` = traced and all resolved, and only count > 0 nodes appear. Same invariant as `unresolved_roots` applied correctly to a *conditionally*-measured fact rather than an always-measured one. Does not cover non-callees edges (mostly deterministic AST) or whole-walk determinism (#419 / #333) — scoped explicitly in the docstrings.
**Anchor:** `pyeye.mcp.operations.trace.trace`, `pyeye.mcp.operations.trace._single_hop`; response_linter rule T.7; #488 (PR pending).
**Verify:** gold — `trace("mypackage._core.callees_fixture.orchestrate", ["callees"], analyzer)["unresolved_call_sites"] == {"mypackage._core.callees_fixture.orchestrate": 1}`; a members-only trace omits the key; linter T.7 rejects non-dict / non-int / count < 1. Covered by `tests/unit/mcp/operations/test_trace.py::TestTraceUnresolvedCallSites` and `tests/conformance/test_linter_adversarial_trace.py::TestTraceUnresolvedCallSites`.
