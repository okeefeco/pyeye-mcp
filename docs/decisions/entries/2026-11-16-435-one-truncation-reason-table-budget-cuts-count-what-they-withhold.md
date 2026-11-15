---
date: "2026-11-16"
title: "One truncation-reason table; budget cuts count what they withhold, and outline summarises its reasons (#435)"
issues: [435, 629, 599, 358]
anchors: ["pyeye.mcp.operations.completeness.TRUNCATION_REASONS", "pyeye.mcp.operations.outline.outline", "pyeye.mcp.operations.outline._summarise_truncation", "pyeye.mcp.operations.trace.trace", "tests/conformance/response_linter.py", "tests/test_completeness_registry.py"]
status: "active"
amends: ["2026-06-23-358-outline-max-nodes-truncation-reserve-before-expand-member.md", "2026-11-08-599-outline-counts-are-named-for-their-edge-and-mirror-inspect.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — One truncation-reason table; budget cuts count what they withhold, and outline summarises its reasons (#435)

**Friction:** Truncation reasons lived in four uncoordinated lists: trace's code, outline's code, and the linter's two closed sets. A new reason could ship in one and not the others, and the tool descriptions and the skill were never checked against any of them. #435 also found two consumer gaps:

- An outline survey marks almost every leaf `survey_leaf`, so a real `max_nodes` cut, where data was actually withheld, hides among them unless the agent walks every node.
- A `max_depth` cut says "there's more" but not how much, although the frontier peek has already counted it.

**Decision:** `completeness.TRUNCATION_REASONS` is the one table. Each reason has a class, a recovery and the tools that emit it.

- **budget:** `max_depth`, `max_nodes`. Recovery: raise the limit. A per-node budget cut carries exactly one edge-named count of what it withheld, so this **amends** #358 and #599, which gave `max_depth` no count. The count is free: the peek already built the list.
- **boundary:** `external`, `survey_leaf`. Out of the view by design. Recovery: call again on that node. No count, because one would cost a walk per node.
- **unmeasured:** reserved for pyeye failing to measure at all; #703's `unparseable` joins it when it lands.
- The code reads its reason names from the table.
- The linter keeps its own hardcoded sets, because it is an independent oracle. A test pins them equal to the table.
- A test checks that the outline and trace tool descriptions, and the skill, name every reason the tool emits.

**outline gains a result-level `truncation_reasons`** on the root: the sorted set of every node's `truncation_reason`, absent when nothing was cut, and named like trace's.

- It deliberately has **no result-level `truncated`**: outline's root dict is also the root node, whose `truncated` already means "the root itself was cut off". The per-node fields are unchanged.
- The linter enforces the summary (O.7): root only, equal to the union of node reasons, and never `[]`.

Everything is additive in 2.x: no field is renamed or removed.

**Anchor:** `pyeye.mcp.operations.completeness` (`TRUNCATION_REASONS`, `reasons_emitted_by`, `reasons_of_class`); `outline.outline` and `_summarise_truncation`; `trace.trace`; `tests/conformance/response_linter.py` (`_BUDGET_REASONS`, O.5–O.7); `tests/test_completeness_registry.py`; #435.
**Applies-to:**

- every truncation reason any primitive emits: today outline's four and trace's two;
- `expand` and `resolve` once slice B adds caps, and #703's `unparseable`;
- every per-node budget cut in outline (`max_depth`, `max_nodes`, in member and survey mode).

trace's budget truncation is result-level, on a graph, so it carries no single edge count. That is the one documented exception to "a budget cut counts what it withheld".

**Verify:** gold.

- `uv run pytest tests/test_completeness_registry.py` sweeps the whole table against the linter's sets, the tool descriptions and the skill.
- `tests/test_outline_truncation_summary.py` and the conformance linter (applied to every outline response in the suite) check the summary and the budget counts. The `max_depth` count equals `inspect().edge_counts`.
