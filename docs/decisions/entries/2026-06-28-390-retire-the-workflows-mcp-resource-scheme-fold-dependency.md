---
date: "2026-06-28"
title: "Retire the `workflows://` MCP resource scheme; fold dependency methodology into the python-explore skill (#390)"
issues: [390, 376, 470, 374, 237]
anchors: ["load_workflow", "pyeye.mcp.server"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-28 — Retire the `workflows://` MCP resource scheme; fold dependency methodology into the python-explore skill (#390)

**Friction:** The 7 `workflows://*` MCP Resources (#237) had become a second source of navigation/review guidance that drifts from the conformance-tested `python-explore` skill — the exact #374 single-source-of-truth rot, one level over in MCP Resources. #470 (2.0) flagged them as teaching *removed* tools; PR #376 had already slimmed them onto the primitives, but they still duplicated the skill's domain and leaned on a deprecated tool (`analyze_dependencies`), a built-in future re-break.
**Decision:** Retire all 7 workflow resources — delete the `.md` files, the `@mcp.resource("workflows://…")` registrations, the `load_workflow` helper, the README "## Workflow Resources" section, and the `tests/test_resources.py` feature test. Before deleting `dependency_analysis.md`, migrate its genuinely-unique methodology (coupling metrics fan-in/out/instability, cycle detection, architecture-shape reading) into `skills/python-explore/SKILL.md`, reframed off the deprecated `analyze_dependencies` onto supported edges only (`expand(imports/imported_by)`, `trace(follow=["imports"])`). The conformance-guarded `python-explore` skill is now the single source of truth for navigation guidance; `/code-review` and `/security-review` own review guidance. Only `pyeye://about` remains as an MCP resource. Rejected: updating the resources in place — keeps the second source alive, the rot #374 warns about.
**Anchor:** removed `@mcp.resource("workflows://*")` registrations + `load_workflow` in `pyeye.mcp.server`; new "Dependency & Coupling Analysis" section in `skills/python-explore/SKILL.md`; #390 (re-scoped per PR #376), #470, #374, #237.
**Verify:** gold — `grep -rn '@mcp.resource("workflows://' src/` returns nothing and `src/pyeye/workflows/` no longer exists; exactly one `@mcp.resource` remains in `src/pyeye/mcp/server.py` (`pyeye://about`); `tests/test_python_explore_skill_conformance.py` passes (6 tests, edge anchor intact); `grep -n "Dependency & Coupling Analysis" skills/python-explore/SKILL.md` matches. Full suite green (2271 passed, 8 skipped, 87.5% coverage).
