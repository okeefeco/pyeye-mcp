---
date: "2026-11-15"
title: "One project-roots policy and one file↔module mapper, both named after Jedi's `full_name` (#625)"
issues: [625, 619]
anchors: ["pyeye.project_layout.project_roots", "RootsBoundary", "module_name_for_file", "file_for_module", "JediAnalyzer._get_import_path_for_file", "_index_module_name", "canonicalization.find_module_file"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-19-858-every-configured-package-is-on-jedis-sys-path-in-one-root-order.md", "2026-11-20-1047-a-module-name-matches-its-file-in-exact-case.md", "2026-11-21-1041-a-standalone-script-is-named-from-its-dir-unless-shadowed.md"]
superseded_by: []
---

## 2026-11-15 — One project-roots policy and one file↔module mapper, both named after Jedi's `full_name` (#625)

**Friction:** Project roots were assembled in seven places with five different subsets, and files were mapped to module names by four helpers with different rules. The shared `_get_import_path_for_file` left out the root-package prefix and returned `None` for additional-package files. Only the name index's `_index_module_name` matched Jedi. As a result, in a project whose root is itself a package, `imported_by` and `resolve(<file>)` returned `b` instead of `rootpkg.b`, and `find_module_file("rootpkg.a")` found nothing. Importers in configured additional packages were silently dropped from `imported_by` (#619). The re-export scan named files from source roots and the project only, so it dropped re-exports inside additional packages.
**Decision:** `pyeye.project_layout` holds the only roots policy and the only mapper pair. It is pure path logic: no Jedi, no `pyeye.mcp`, no handle resolution. #623 builds on it.

- `project_roots(analyzer, RootsBoundary.X)` names each subset once:
  - `SCOPE` (project, source_roots, additional_paths), unchanged; #623 decides whether it widens to namespace roots;
  - `TOP_LEVEL_PACKAGE` (project, source_roots);
  - `MODULE_LOOKUP` (source_roots, project, additional_paths);
  - `NAMESPACE_PORTIONS` (adds added_sys_path).
- `module_name_for_file` / `file_for_module` are inverses that follow Jedi's `full_name`. They include the root-package prefix, treat additional paths as sys.path roots, and apply the namespace no-double-prefix rule.
- Rejected: keeping a prefix-free mapper for "other callers". Its live callers (`find_importers`, `resolve(<file>)`, `find_subclasses`) all compare against Jedi names, so prefix-free names were wrong for them. The legacy `find_reexports` now reports prefixed import paths for root-package projects.
**Anchor:** `pyeye.project_layout.project_roots`, `RootsBoundary`, `module_name_for_file`, `file_for_module`; `JediAnalyzer._get_import_path_for_file` (now a delegate; `_index_module_name` removed); `canonicalization.find_module_file` (delegate); #625, #619.
**Applies-to:** every roots list and every file↔module mapping in `src/pyeye`:
- the roots sites: `classify_scope`, `resolve._is_top_level_package`, `canonicalization.find_namespace_package_dirs`, `find_module_file`, `_scan_package_for_handle`, `JediAnalyzer._find_init_file`;
- the forward-mapper callers: `find_importers`, `_resolve_file_only`, `find_subclasses`, the name index, `find_reexports`.

Not yet consolidated:

- the dead `JediAnalyzer.find_imports` / `list_packages` / `list_modules`, `ImportAnalyzer.get_module_name` and `populate_dependencies`, which go with #628;
- search-scope path resolution (`_resolve_scope_to_paths` ×2, `SmartScopeResolver`), deferred;
- a bare `JediAnalyzer` still doesn't detect `src/` without config (#625 slice 3).

**Verify:** gold. `uv run pytest tests/test_decision_invariants_fitness.py::test_project_roots_come_from_one_helper tests/test_project_layout.py` passes:

- an AST scan of all of `src/pyeye` finds exactly one function that builds a roots list from `project_path` + `source_roots` (`project_layout.project_roots`), plus the three #628-owned dead copies;
- the mapper round-trips both ways on flat, src, root-package and additional-package layouts;
- the root-package and additional-package regressions hold through `expand(imported_by)`, `resolve(<file>)`, `find_module_file` and the re-export scan.
