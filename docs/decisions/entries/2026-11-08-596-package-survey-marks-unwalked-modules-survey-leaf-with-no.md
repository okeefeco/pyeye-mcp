---
date: "2026-11-08"
title: "Package survey marks unwalked modules `survey_leaf`, with no per-leaf count (#596)"
issues: [596, 423, 598]
anchors: ["pyeye.mcp.operations.outline.outline", "tests/test_outline_survey_leaf.py::TestSurveyLeafNodes", "TestSubmodulelessPackageRoot"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-08 — Package survey marks unwalked modules `survey_leaf`, with no per-leaf count (#596)

**Friction:** `outline` on a package (survey mode, #423) walks `submodules`, never `members`, yet it returned unwalked modules as `children: []`, which Contract 1 defines as measured-empty. On real code at the time, `outline("jaraco")` said `jaraco.context` was empty when it defined 21 members; the package's own `__init__` members disappeared without any sign. The `namespace-jaraco` baseline had recorded that shape as expected. The `pyeye-verify` rubric (absence vs zero, cross-primitive agreement with `inspect`) caught it.
**Decision:** A survey node with members that the survey doesn't walk is `truncated: true, truncation_reason: "survey_leaf"` with `children` absent (recovery: `outline` that module); one cheap emptiness check keeps a genuinely empty module `children: []`. No per-leaf `member_count`: that's one `resolve_members` per leaf, too costly on a large survey (django), and the flag only has to stop the false "empty". A package root with no submodules is outlined by its members, because `survey_leaf` on the root would point back at the same call. Rejected: reusing `max_depth` (raising `max_depth` never walks members in survey mode, so the reason would point to a fix that doesn't work); listing `__init__` members beside the submodules (changes the #423 shape and complicates ordering and the budget). The members are disclosed as a count instead (see the #599 entry).
**Anchor:** `pyeye.mcp.operations.outline.outline` — `truncation_reason: "survey_leaf"` (linter rule O.2 enum); `tests/test_outline_survey_leaf.py::TestSurveyLeafNodes` / `TestSubmodulelessPackageRoot`; #596, #423, PR #598.
**Verify:** gold — those two test classes pass: in a package survey, a module with members is `survey_leaf` with `children` and any count absent, at the depth limit, unbounded, and under an exhausted budget; a module with no members is `children: []`; a package root with no submodules lists its members. Real-code check: PARTIAL — against the `namespace-jaraco` scenario, no node of `outline("jaraco")` that has members is `children: []` [needs the scenario provisioned at its pinned commits; see the `pyeye-scenarios` skill].
