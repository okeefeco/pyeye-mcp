---
date: "2026-06-23"
title: "outline `max_nodes` truncation: reserve-before-expand + `member_count` signpost (#358)"
issues: [358]
anchors: ["pyeye.mcp.operations.outline.outline", "tests.conformance.response_linter._check_outline_tree_node"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-23 — outline `max_nodes` truncation: reserve-before-expand + `member_count` signpost (#358)

**Friction:** When the node budget was exhausted *mid-enumeration* of a container's children, `outline` `break`-ed the loop and assigned the **partial** `children` list with no truncation marker — a consumer read a partial set as the *complete* direct-member set (a Contract-1 honesty violation). The conformance linter could not catch it (a partial list is shape-valid), and the worst case — all dropped siblings are leaves — left ZERO truncation markers anywhere in the tree (#358).
**Decision:** Reserve-before-expand: a container is expanded only if the remaining budget can admit ALL its direct members; otherwise it is cut off **whole** (`truncated: "max_nodes"`, `children` omitted) and carries a fresh `member_count` (the count of withheld direct members). Never a partial `children` list. `member_count` is added to the `max_nodes`-family truncations only; `external`/`max_depth` caps are left as-is (no peek, no count). Rejected option-1 (expand-then-discard-partial): same output but wastes stub builds and would enqueue orphan nodes. Consequence accepted: a container larger than the remaining budget now surfaces zero members + a count, recoverable by raising `max_nodes` or targeting the subtree.
**Anchor:** `pyeye.mcp.operations.outline.outline` (reserve check + member_count); linter rule O.5 in `tests.conformance.response_linter._check_outline_tree_node`; #358; spec `docs/superpowers/specs/2026-06-22-bounded-response-firehose-contract-design.md` §4.
**Verify:** gold — `outline("pkg.mod", JediAnalyzer("tests/fixtures/outline_flat_leaves"), max_nodes=3)` returns the root with `truncated == True`, `truncation_reason == "max_nodes"`, `member_count == 5`, and NO `children`; for every budget over `tests/fixtures/nested_class_inspect`, no node carrying `children` is missing a direct member; a truncated node's `member_count == inspect(handle).edge_counts["members"]`. Covered by `tests/unit/mcp/operations/test_outline.py::TestOutlineMidExpansionTruncation` and the O.5 adversarial tests in `tests/conformance/test_linter_adversarial_outline.py`.
