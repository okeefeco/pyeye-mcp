---
date: "2026-11-15"
title: "Process-wide caches of layout-dependent results key on the effective layout, not the project root (#618)"
issues: [618, 617, 625]
anchors: ["pyeye.project_layout.layout_key", "JediAnalyzer.layout_key", "pyeye.analyzers.project_graph.get_name_index", "pyeye.analyzers.project_graph.invalidate", "pyeye.file_artifact_cache._project_key", "tests/test_layout_keyed_caches.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — Process-wide caches of layout-dependent results key on the effective layout, not the project root (#618)

**Friction:** The name index bakes module names in when it's built, and a module's name depends on the analyzer's layout: its source roots, sys.path additions, packages and namespaces. The index was keyed on the project root alone, so the first analyzer to build it fixed the names for every later analyzer on that root. A bare analyzer and a configured one on the same project returned each other's handles, or "not found", depending on which ran first (worker-3's repro on #618, and #614's tools-agree tests, which had to move to private fixture copies to stay stable). Jedi `Script`s in `file_artifact_cache` were likewise keyed on the root, so two Projects with different `added_sys_path` shared import resolution.
**Decision:** A process-wide cache whose entries depend on the layout keys on `pyeye.project_layout.layout_key(analyzer)`, alongside the root.

- `layout_key` is pure and Jedi-free, next to `project_roots`, as the single home for "the effective layout" (#625). It covers the resolved root, whether the root is itself a package, `source_roots`, `added_sys_path` (in order, since precedence matters), `additional_paths`, `standalone_paths`, and namespaces (sorted).
- `JediAnalyzer.layout_key` computes it on each access, not cached, because the `set_*` methods change the layout after construction.
- **Invalidation stays root-keyed and drops every layout under that root.** A file change, or `configure_packages`, can't know which layouts are affected, and rebuilding is cheap next to a stale entry.
- Rejected:
  - Making the index layout-independent, by storing files and computing module names at lookup. That's a larger change, and it would move cost to every lookup.
  - Invalidating on every analyzer construction. Two analyzers alive at once would then still evict each other.
**Anchor:** `pyeye.project_layout.layout_key`; `JediAnalyzer.layout_key`; `pyeye.analyzers.project_graph.get_name_index(..., layout_key=)` / `invalidate`; `pyeye.file_artifact_cache._project_key`; `tests/test_layout_keyed_caches.py`; #618, #617, #625.
**Applies-to:**
- The project_graph **name index**, keyed `root → layout_key → index`.
- The `file_artifact_cache` **Script** store, keyed on root + `added_sys_path` + smart sys path. That is the `jedi.Project` view of the same layout; `get_script(path, project)` is unchanged.
- **Not layout-keyed:** the AST store, keyed on path + mtime, is content-only and layout-independent. The **TypeRef** cache (#620) is keyed on the root and is invalidated per root, both on watched changes (#617) and by `configure_packages`. That's correct only while its entries don't depend on the layout; key it on `layout_key` if that changes.
- Any new process-wide cache holding module names or handles must follow this rule.
**Verify:** gold — `uv run pytest tests/test_layout_keyed_caches.py` passes, and so do these checks:
- **Leak tests:** bare→managed, managed→bare, and both analyzers alive and interleaved, on one root whose source root (`code/`) only `.pyeye.json` declares. Each analyzer's answer equals its answer in a clean process, and a guard asserts that the two layouts really differ.
- **Mutation check:** with `JediAnalyzer.layout_key` forced to a constant (`property(lambda self: "")`), managed→bare, both-alive and invalidate-all **fail**. On this fixture, bare→managed is masked by `resolve` re-deriving the handle through the managed analyzer's mapper.
- **Key tests:** each of the 6 layout fields changes the key; equal layouts give equal keys.
- **Script test:** different `added_sys_path` gives different Scripts.
