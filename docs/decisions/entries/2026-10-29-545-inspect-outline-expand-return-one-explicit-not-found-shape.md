---
date: "2026-10-29"
title: "inspect/outline/expand return one explicit not-found shape; expand resolves before the edge registry (#545)"
issues: [545]
anchors: ["pyeye.mcp.operations.not_found.not_found", "inspect.inspect", "outline.outline", "expand.expand"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-15-626-one-not-found-shape-for-all-five-primitives-the-lookup-echo.md"]
superseded_by: []
---

## 2026-10-29 — inspect/outline/expand return one explicit not-found shape; expand resolves before the edge registry (#545)

**Friction:** An unresolvable handle produced a fabricated answer: `inspect`/`outline` returned a `kind:"variable"`, `scope:"external"` placeholder (indistinguishable from a real variable except by an empty `file`), and `expand` returned `stubs: []` — its own "measured, none found" — plus a synthesized `unresolved_call_sites: 0`. Dogfooding hit it with a mistyped handle; pre-#529 it masked real classes (`asyncio.Queue`). `expand`'s docstring called this deliberate ("callers rule ghosts out upstream"), but that upstream guard was `inspect`, itself fabricating.
**Decision:** One shape from one helper — `{found:false, handle, reason:"unresolved", detail}` (+`edge` for expand) — and `found:true` on every success (outline: root only), so consumers branch on a value, not key presence. `reason` reuses `resolve`'s vocabulary; `detail` is an actionable `resolve('<leaf>')` step, not fuzzy suggestions. `expand` resolves the source before consulting the edge registry so `found:true` is never stamped on an unresolved handle (ghost + `callers` → not-found, not unsupported). Rejected: folding not-found into expand's `unsupported` branch as a new reason (conflates "symbol doesn't exist" with "edge isn't built"); `found` on failures only (key-presence branching). `trace` unchanged — `unresolved_roots` was already honest.
**Anchor:** `pyeye.mcp.operations.not_found.not_found`; `inspect.inspect`, `outline.outline`, `expand.expand`; response_linter Check N (N.1–N.3); #545.
**Verify:** gold — over `tests/fixtures/resolve_project`: `inspect("mypackage._core.no_such_module.Widget") == not_found("mypackage._core.no_such_module.Widget")`; `expand(<ghost>, "callees") == not_found(<ghost>, edge="callees")` (no `stubs`, no `unresolved_call_sites`); `expand(<ghost>, "callers")["found"] is False`; successes carry `found is True`; linter N.1 rejects a missing `found`, N.2 rejects any node/tree/stubs field beside `found:false`. Covered by `tests/unit/mcp/operations/test_not_found.py` and `tests/conformance/test_linter_adversarial_not_found.py`.
