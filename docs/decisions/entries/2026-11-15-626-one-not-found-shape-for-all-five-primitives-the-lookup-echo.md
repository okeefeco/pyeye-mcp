---
date: "2026-11-15"
title: "One not-found shape for all five primitives: the lookup echo, a per-operation reason set, and `detail` (#626, amends #545)"
issues: [626, 545, 615]
anchors: ["pyeye.mcp.operations.not_found.not_found_for", "NOT_FOUND_SPEC", "not_found", "pyeye.mcp.operations.resolve.resolve", "resolve_at", "_Miss"]
status: "active"
amends: ["2026-10-29-545-inspect-outline-expand-return-one-explicit-not-found-shape.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — One not-found shape for all five primitives: the lookup echo, a per-operation reason set, and `detail` (#626, amends #545)

**Friction:** #545 unified the not-found response for inspect, outline and expand only. `resolve` and `resolve_at` still returned a bare `{found: false, reason}`, so an agent got no echo of what missed and no next step. #545 also defined `handle` as "the echoed input" and said `reason` "reuses resolve's vocabulary". Applied to resolve and resolve_at, that would put an identifier or a file path in `handle`, where agents feed it to `inspect`. And it would collapse `file_not_found` / `no_symbol_at_position` into prose, so a missing file would read as a spelling miss. The user decided the target shape (on #626).
**Decision:** every primitive's miss is `{found: false, <lookup-argument echo>, reason, detail}`, built in one place: `pyeye.mcp.operations.not_found.not_found_for(operation, echo, reason, detail=None)` from the per-operation `NOT_FOUND_SPEC`.

- The echo carries the **lookup** arguments under their own parameter names. Tuning arguments (`max_depth`, `project_path`) are not echoed.
  - inspect and outline echo `handle`; expand echoes `handle` and `edge`. Their reason set is `{unresolved}`.
  - resolve echoes `identifier`. resolve_at echoes flat `file`, `line` and `column`. Their reason set is `{unresolved, file_not_found, no_symbol_at_position}`.
- `handle` appears only where the input is a handle.
- `detail` is always present, with a reason-specific next step.
- The builder raises `ValueError` on an echo key or reason outside the operation's spec, so drift fails at build time.
- `resolve.py`'s helpers return an internal `_Miss(reason)`, and `resolve()` / `resolve_at()` render it once. `_NotFoundResult` is gone.
- `trace` stays out of scope: it lists misses in `unresolved_roots`.
- Rejected: folding `file_not_found` / `no_symbol_at_position` into `detail` (agents would parse prose); echoing paths in `handle`.

**Anchor:** `pyeye.mcp.operations.not_found.not_found_for`, `NOT_FOUND_SPEC`, `not_found`; `pyeye.mcp.operations.resolve.resolve`, `resolve_at`, `_Miss`; response_linter Check N (N.2 per operation, N.4); #626, #545, #615.
**Applies-to:**

- the five primitives: `inspect`, `outline`, `expand` (via `not_found()`), and `resolve`, `resolve_at` (via `not_found_for()`);
- the response linter's Check N, whose N.2 table mirrors `NOT_FOUND_SPEC` independently;
- the #615 N.4 legacy allow-list, now empty and kept as a guard.

Not covered: `trace` (`unresolved_roots`), and the error channel for invalid arguments or a missing project, which raise an MCP tool error (#626 slice C). #623 slice 3 renders its resolver `NotFound(reason, detail)` through `not_found_for`.
**Verify:** gold. `uv run pytest tests/test_not_found_shape.py tests/conformance/test_linter_adversarial_not_found.py tests/test_decision_invariants_fitness.py` passes:

- every resolve miss path (bare name, dotted name, missing file, missing file:line, blank line, a file outside the project) and every resolve_at miss path (missing file, blank line, past the end) renders the exact per-operation shape and passes Check N, also through the MCP tool layer;
- the builder rejects foreign echo keys and reasons;
- Check N rejects a `handle` echo on resolve and resolve_at, a nested resolve_at echo, non-int `line`/`column`, a position reason on a handle operation, and the legacy two-key shape (the N.4 list is empty).
