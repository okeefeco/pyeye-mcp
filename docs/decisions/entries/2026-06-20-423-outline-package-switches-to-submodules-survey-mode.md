---
date: "2026-06-20"
title: "outline(package) switches to submodules survey mode"
issues: [423]
anchors: ["outline._is_package", "outline._child_adjacents", "outline._is_expandable", "pyeye.mcp.operations.outline", "edges.resolve_submodules"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-20 — outline(package) switches to submodules survey mode

**Friction:** Removing the legacy `list_packages`/`list_modules`/`list_project_structure` tools left no top-down "what's in this package/project" primitive; every new primitive needed a handle you already knew, forcing a cold-start agent out to `ls`/grep to orient before pyeye could help (#423).
**Decision:** `outline(<package handle>)` now walks the new `submodules` containment edge instead of `members`: it lists child modules/subpackages, treats plain modules as leaves (members not walked), and defaults to depth-1 when `max_depth` is `None`. Module/class roots are unchanged (members mode, `max_depth=None` stays unbounded) — the kind-dependent default-depth split is deliberate. Rejected: a separate `survey`/`structure` primitive (kept it inside `outline` so progressive disclosure composes via one tool).
**Anchor:** `outline._is_package` / `outline._child_adjacents` / `outline._is_expandable` (`pyeye.mcp.operations.outline`); `edges.resolve_submodules`; #423.
**Verify:** gold — `outline("mypkg", analyzer)` over `tests/fixtures/containment/regular` returns root children handles == {`mypkg.alpha`, `mypkg.beta`, `mypkg.sub`}, with `mypkg.sub` truncated (`truncation_reason="max_depth"`, no `children`) at the depth-1 default and `mypkg.alpha`/`beta` as `children==[]` leaves; `outline("mypkg.alpha", analyzer)` still walks members (contains `mypkg.alpha.A`). Covered by `tests/test_outline_packages.py`.
