---
date: "2026-06-28"
title: "imports edge surfaces unresolvable imports instead of dropping them (#494)"
issues: [494]
anchors: ["pyeye.mcp.operations.edges.resolve_imports", "EdgeResult.unresolved_imports", "pyeye.mcp.operations.edges._import_from_target"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-28 — imports edge surfaces unresolvable imports instead of dropping them (#494)

**Friction:** `expand(imports)` silently omitted a statically-present `from X import Y` (`resolve._normalise_kind`), surfaced by 3 auditor agents during the #492 review. Root-caused to a transient forward-`goto` miss in `_resolve_call_target` (the #419 non-determinism family), NOT a deterministic logic bug: it does not reproduce cold (fresh process), warm (57-module sweep), or on the live server now (healed); feat/492's resolver code is byte-identical to main. So determinism is a backend concern (#419 / #333); the shippable fix is the honesty floor — never silently drop a statically-present import.
**Decision:** Add `unresolved_imports` to `EdgeResult` + the imports edge. A `goto`-unresolvable import is recorded by its statically-derived intended dotted target (`_import_from_target` reconstructs `from X import Y` → `"X.Y"`, relative dots preserved) rather than dropped. Chose a LIST of nameable targets (not a count like `unresolved_call_sites`) because imports ARE nameable from the AST. `expand(imports)`: always-present list (`[]` = all resolved), imports-only (mirrors callees-only `unresolved_call_sites`). `trace`: per-node `{handle: [target, ...]}` map, present iff imports traced (absence-vs-zero: absent = not measured). Wildcard `import *` stays skipped (can't enumerate), not counted as unresolved.
**Anchor:** `pyeye.mcp.operations.edges.resolve_imports`, `EdgeResult.unresolved_imports`, `pyeye.mcp.operations.edges._import_from_target`; response_linter rules E.5 / T.8; #494 (PR pending).
**Verify:** gold — `expand("mypackage._core.unresolved_imports_fixture", "imports", analyzer)["unresolved_imports"] == ["_nonexistent_pkg_494.missing_symbol", "os._made_up_attr_494"]`; an all-resolved module yields `[]`; a non-imports edge omits the key; `trace(follow=["imports"])` yields `{handle: [target, ...]}`; linter E.5/T.8 reject misplacement / bad types. Covered by `tests/unit/mcp/operations/test_edges.py::TestResolveImportsUnresolved`, `test_expand.py::TestExpandImportsUnresolved`, `test_trace.py::TestTraceUnresolvedImports`, and the E.5/T.8 adversarial classes.
