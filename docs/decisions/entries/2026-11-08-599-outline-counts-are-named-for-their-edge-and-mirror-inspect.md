---
date: "2026-11-08"
title: "Outline counts are named for their edge and mirror `inspect().edge_counts` (#599)"
issues: [599, 596, 435, 598]
anchors: ["pyeye.mcp.operations.outline.outline", "member_count", "submodule_count", "tests/conformance/response_linter.py", "tests/test_outline_survey_leaf.py::TestCountInvariant"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-16-435-one-truncation-reason-table-budget-cuts-count-what-they-withhold.md"]
superseded_by: []
---

## 2026-11-08 — Outline counts are named for their edge and mirror `inspect().edge_counts` (#599)

**Friction:** Both `max_nodes` paths in `outline` wrote `member_count = len(adjacents)`. In package survey mode the adjacents are *submodules*, so a survey package cut by the budget reported its submodule count as `member_count` (at the time, the `svpkg` fixture: 6, while `inspect` said members 1 / submodules 6). That breaks the #358 invariant below. The linter checks shape only, and existing tests missed it because on nested nodes the two counts are often equal. #596 was about to add a third count (`init_member_count`), which would have spread the ambiguity further.
**Decision:** Every outline count is named `<edge>_count` for the edge it measures (`member_count` ↔ `members`, `submodule_count` ↔ `submodules`) and equals `inspect(h).edge_counts[<edge>]`, in every mode. What a count *means* comes from the node's state, not its name: on a `max_nodes` truncation it counts what the cap withheld (exactly one count: the walked edge, so `submodule_count` in survey mode); on a walked node it counts what is not in this view (a survey package's `__init__` members → `member_count`, only when > 0). Other truncations carry no count. Rejected: purpose-named keys (`init_member_count`). `init_member_count` was dropped before release. Generalises the #358 entry's `member_count == edge_counts["members"]` from member mode to every mode. From review on #435, whose disclosure envelope should adopt the same scheme.
**Anchor:** `pyeye.mcp.operations.outline.outline` — response fields `member_count` / `submodule_count`; linter rules O.5/O.6 in `tests/conformance/response_linter.py`; `tests/test_outline_survey_leaf.py::TestCountInvariant`; #599, #596, #435, PR #598.
**Verify:** gold — `uv run pytest tests/test_outline_survey_leaf.py::TestCountInvariant tests/test_outline_survey_leaf.py::TestSurveyMaxNodesCount` passes. The invariant: for every node of every outline in the sweep (survey and member roots, several depths and budgets), each `member_count` / `submodule_count` present equals `inspect(<that node's handle>).edge_counts["members"]` / `["submodules"]`. A survey root cut by `max_nodes` carries `submodule_count` and no `member_count`, on a fixture whose members and submodules counts differ (asserted, so a coincidence can't make it pass).
