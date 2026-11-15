---
date: "2026-11-16"
title: "A parse failure on the source's own file is unsupported or omitted, never measured-empty (#703)"
issues: [703, 704, 729, 629]
anchors: ["pyeye.mcp.operations.edges.UnparseableSource", "pyeye.mcp.operations.edges.parse_own_source", "pyeye.mcp.operations.edges.STATUS_UNPARSEABLE", "pyeye.mcp.operations.expand.expand_resolved", "pyeye.mcp.operations.outline.outline", "pyeye.mcp.operations.inspect._get_superclasses"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — A parse failure on the source's own file is unsupported or omitted, never measured-empty (#703)

**Friction:** When pyeye runs on an older interpreter than the analysed code (a 3.14 t-string or unparenthesised `except` on a 3.12 server), `file_artifact_cache.get_ast` raises `SyntaxError`. The per-file resolvers wrapped it in `except Exception: return []`. The result was `outline` → `children: []`, `expand(members)` → `stubs: []`, `edge_counts.members: 0`, and a class's `superclasses: []`. Each of those is a measured-empty claim about code pyeye never read, which breaks the absence-vs-zero invariant.

**Decision:** one signal, `UnparseableSource(path, lineno, msg)`, raised by `parse_own_source` only for `SyntaxError` on the source's own file. The resolvers no longer swallow it. Each operation reuses an existing honest shape and adds only a reason value:

- **`expand`:** the unsupported branch, with `reason: "unparseable"` and a `detail` naming the file, the line, the server's Python version and the next step (Read the file, or run pyeye on a newer Python), plus `report_issues`.
- **`trace`:** the same answer per hop, through `expand_resolved`, so it lands in `unsupported_edges`.
- **`outline`:** `children` absent, `truncated: true`, `truncation_reason: "unparseable"`, with no count. A survey package whose `__init__` doesn't parse omits `member_count`.
- **`inspect`:** the count is omitted from `edge_counts`, and a class's `superclasses` field is omitted. `return_type` stays absent.
- **Unchanged:** the not-found shape. The handle resolves, so `found: false` would be a different lie.
- **Narrowed to parse errors:** any other exception keeps its existing handling, which is left for #704.

**Anchor:** `pyeye.mcp.operations.edges` (`UnparseableSource`, `parse_own_source`, `STATUS_UNPARSEABLE`, and the three call sites: `_module_members`, `superclass_bases`, `resolve_imports`); `expand.expand_resolved`; `outline.outline` / `_mark_unparseable` / `_disclose_unlisted_members`; `inspect._get_superclasses` / `_build_class_fields`; the closed reason sets in `tests/conformance/response_linter.py`; #703.
**Applies-to:** every resolver that needs the AST of the source's OWN file: `_module_members` (module `members`), `superclass_bases` (the `superclasses` edge, the `inspect` field and the count) and `resolve_imports` (`imports`). Each reaches `expand`, `trace`, `outline` and `inspect.edge_counts` through `expand_resolved`, `outline`'s walk and `_measure_with_budget`.

Not covered, and still divergent:

- the project-wide AST scans (`project_graph` name index, `find_subclasses`, the `imported_by` scan, `_ast_targets`), which skip an unparseable file without saying so (#729);
- `inspect`'s `return_type` / attribute `type` extraction, which already answers "absent".

**Verify:** partial. `uv run pytest tests/test_unparseable_source.py` covers:

- `members`, `imports` and `superclasses` on a file that's invalid on every interpreter (expand, inspect counts and field, outline root and survey, trace);
- a parseable sibling, unaffected;
- `SyntaxError` as the only mapped error;
- the 3.14-syntax modules on an older server.

The residue is the project-wide scans named above (#729).
