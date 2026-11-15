---
date: "2026-11-15"
title: "One edge-applicability table; every wrong kind answers `not_applicable` (#626)"
issues: [626, 657, 614]
anchors: ["pyeye.mcp.operations.edges.EDGE_APPLIES_TO", "edge_applies", "edge_kind", "not_applicable_detail", "STATUS_NOT_APPLICABLE", "pyeye.mcp.operations.expand.expand_resolved", "inspect._build_edge_counts", "outline._CONTAINER_KINDS"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — One edge-applicability table; every wrong kind answers `not_applicable` (#626)

**Friction:** each resolver decided for itself whether its edge applied, and there were two policies. `imports` and `imported_by` returned `None`, which `expand` reported as unsupported `not_yet_implemented` "in this slice" (a misreport, since they *are* implemented). The other six edges returned a measured `[]` for a wrong kind, which reads as "has none". The kind was re-derived by 7 inline `normalise_kind(getattr(name, "type", None))` copies in edges.py and 2 in expand.py. And `submodules` ran for a symbol defined in a package `__init__`: `expand("pkg.__all__", "submodules")` enumerated the package directory and invented `pkg.__all__.<child>` handles (25 entries in #614's `KNOWN_GAPS`).
**Decision:** `pyeye.mcp.operations.edges.EDGE_APPLIES_TO` is the one table of which kinds each edge applies to, keyed on `edge_kind()` (methods promoted, #406):

- `members` → class, module; `callees` → function, method;
- `imports`, `imported_by`, `submodules` → module; `subclasses`, `superclasses` → class;
- `enclosing_scope` → every kind but module.

Every reader asks `edge_applies(edge, name)` before calling a resolver, and the resolvers carry no kind gates. That covers `expand_resolved` (and so `trace`'s hops, root and interior, including the frontier peek), `inspect`'s `edge_counts` and `outline`'s container check. A wrong kind is the unsupported branch with the new reason **`not_applicable`** (decided by the user; Added), with a `detail` naming the kind and the kinds the edge applies to. It is never a measured `[]`. `not_applicable` depends on the handle, so `edge_status()` (edge-only) never returns it. The pre-#626 wrong-kind branch's `report_issues` is kept, because no field is removed in 2.x. `submodules` stays a measured `[]` for a plain module. Rejected: keeping per-resolver gates that read the table (still N copies), and keeping `not_yet_implemented` for wrong kinds (it claims missing work).
**Anchor:** `pyeye.mcp.operations.edges.EDGE_APPLIES_TO`, `edge_applies`, `edge_kind`, `not_applicable_detail`, `STATUS_NOT_APPLICABLE`; `pyeye.mcp.operations.expand.expand_resolved`; `inspect._build_edge_counts`; `outline._CONTAINER_KINDS`; response_linter rule E; #626, #657, #614.
**Applies-to:** all 8 implemented edges in `EDGE_RESOLVERS`, and every reader that decides whether to run one: `expand`/`expand_resolved`, `trace` (through `expand_resolved`), `inspect.edge_counts` and `outline` (members). Not covered: `_SCOPE_BOUNDARY_NODES` / `_NESTED_SCOPE_TYPES` (the same AST node set defined twice in edges.py) are left for a later #626 cleanup, to keep this diff clear of #624's concurrent edges.py work. #626 slice C (the error channel) is separate.
**Verify:** gold. `uv run pytest tests/test_edge_applicability.py tests/test_cross_tool_invariants.py` passes:

- the table covers exactly `EDGE_RESOLVERS`, uses only `KINDS`, and equals the decided mapping;
- an AST scan finds exactly one kind derivation in edges.py (`edge_kind`) and none in expand.py or trace.py;
- every edge on a wrong kind answers `not_applicable` with the table's detail and passes the linter;
- `expand("mypackage.__all__", "submodules")` is `not_applicable` while the package still enumerates;
- inspect counts only applicable edges;
- #614's round-trip sweep passes with its 25 `pkg.__all__.*` / `init_fn.*` entries deleted, and trace and expand agree on wrong kinds.
