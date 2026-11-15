---
date: "2026-11-07"
title: "`outline` defaults to depth-1 for every root kind; `max_depth=None` means unbounded (#474)"
issues: [474, 423, 358]
anchors: ["pyeye.mcp.operations.outline.outline", "max_depth", "pyeye.mcp.server.outline", "tests/unit/mcp/operations/test_outline.py::TestOutlineDefaultDepth", "tests/test_outline_packages.py::TestOutlinePackageSurvey::test_max_depth_none_is_unbounded_survey"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-07 — `outline` defaults to depth-1 for every root kind; `max_depth=None` means unbounded (#474)

**Friction:** `outline`'s default depth depended on the root kind. Package roots defaulted to depth 1 (#423), but module and class roots defaulted to an unbounded walk, limited only by `max_nodes=200`. An unbounded member walk by default is the firehose vector: it is what makes the `max_nodes` truncation paths (#358) fire, and it takes over `trace`'s job (multi-hop traversal). It also meant `None` did two jobs, "use the default" and "unbounded", so a package could never be surveyed recursively.
**Decision:** The `max_depth` default is the integer `1` in both the operation and the MCP tool signature, for every root kind, and `None` always means unbounded. The kind-dependent `effective_max_depth` special case is gone. That gives each primitive one job: `inspect` = counts, `expand` = one edge, one hop, `outline` = one scope's direct structure as a tree, `trace` = multi-hop. Rejected: keep `None` as the default sentinel and add a separate "unbounded" value such as `-1`. It is a less obvious contract for MCP clients, and the tool schema would hide the real default. The #358 reserve-before-expand logic stays: a module with more than 200 direct members still overflows at depth 1. Breaking change, so it shipped in 2.0 instead of costing a 3.0.
**Anchor:** #474 ; refs #423, #358 ; `pyeye.mcp.operations.outline.outline` (`max_depth` default) ; `pyeye.mcp.server.outline` ; `tests/unit/mcp/operations/test_outline.py::TestOutlineDefaultDepth` ; `tests/test_outline_packages.py::TestOutlinePackageSurvey::test_max_depth_none_is_unbounded_survey`.
**Verify:** gold — `uv run pytest tests/unit/mcp/operations/test_outline.py tests/test_outline_packages.py` passes. Both signatures default `max_depth` to `1`. `outline("pkg.mod")` over `tests/fixtures/nested_class_inspect` lists direct members with `pkg.mod.Outer` truncated (`max_depth`) and the empty `pkg.mod.Empty` as a `children: []` leaf, identical to `max_depth=1`. `outline("pkg.mod.Outer")` truncates `Inner`. `outline("mypkg", max_depth=None)` walks `mypkg.sub` fully.
