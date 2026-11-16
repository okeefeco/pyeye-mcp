---
date: "2026-11-17"
title: "The re-export binding index is cached per package, so a new handle doesn't re-index its package (#803)"
issues: [803, 795, 393, 712, 704]
anchors: ["pyeye.canonicalization._package_binding_index", "pyeye.canonicalization._build_binding_index", "pyeye.canonicalization.invalidate_re_exports", "pyeye.canonicalization.re_export_scan"]
status: "active"
amends: ["2026-11-16-393-re-exports-is-an-expand-edge-the-inspect-field-is-deprecated.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — The re-export binding index is cached per package, so a new handle doesn't re-index its package (#803)

**Friction:** #797 (#795) made one re-export scan index each package file once, however many BFS hops it walks. But the scan runs for every new handle, and #393's cache is keyed by handle. So each new handle still re-indexed its whole package: on django, all 907 files under `django/`, about 885 artifact-cache misses at the default cap of 500. A cold `inspect` took 13–15 s per project handle (profiled on #803). Two handles from the same module each paid the full cost.

**Decision:**

- **Cache the index per package.** `canonicalization._package_binding_index` caches `_build_binding_index`'s result and the files it couldn't parse.
  - The key is `(path_to_key(project root), layout_key(analyzer), path_to_key(package root))`, the same project and layout parts as #393's scan cache.
  - It sits beside that cache under the same lock, and `invalidate_re_exports` clears both: the watcher's `ProjectManager._on_files_changed`, `configure_packages`, and the test reset. So staleness works exactly as for #393's cache.
- **Compact facts, bounded.** The cache holds `source -> [(binding, public)]` tuples, never ASTs (#780). On django that's 2,153 sources and 5,978 bindings, about 1.3 MB as a deep upper bound, with RSS unchanged. It is LRU-bounded at 32 packages.
- **One build per package.** The build is synchronous, with no await between the check and the store, so coroutines on the Jedi worker loop can't interleave mid-build. A per-key build lock makes threads share one build too.
- **No stale store, per project.** Invalidating a project bumps that project's generation, and a global invalidation bumps an epoch. A build that overlapped an invalidation of **its own** project is returned to its caller but not stored. Another project's invalidation leaves it alone: with one global counter (this PR's first cut), steady watcher traffic on any project kept every in-flight build from being stored, which quietly undid the cache. The merge queue caught that on macOS.
- **Parse failures** are cached with the index. A caller collecting them (`re_export_scan`) gets them for every handle. The strict mode, with no list, still raises the real `SyntaxError` (#704), because `get_ast` never caches a failure.
- **No contract change.** `inspect.re_exports` (deprecated, #749) and the edge answer exactly as before. Making the field lazy was considered and rejected: with the index cached, it costs milliseconds after the first handle in a package.

**Anchor:** `canonicalization._package_binding_index` / `_build_binding_index` / `invalidate_re_exports` / `re_export_scan`; #803, #795, #393.
**Applies-to:**

- the cache: `canonicalization._package_binding_index` (`_binding_index_cache`), read by `_collect_re_exports_impl`;
- its invalidation: `canonicalization.invalidate_re_exports`, called by `ProjectManager._on_files_changed`, `server.configure_packages` and the `tests/conftest.py` reset;
- the readers it speeds up, both unchanged in output: `inspect.inspect` (`re_exports`) and `edges.resolve_re_exports`.

**Verify:** gold. `uv run pytest tests/test_re_exports_index_cache.py tests/test_re_exports_single_pass.py tests/test_re_exports_edge.py tests/test_public_reexports.py` passes. The pins: the second handle in a package does zero `get_ast` calls; one build per package, including under concurrent and threaded first calls; watcher add and remove plus `configure_packages` invalidation; per-project invalidation; no store across an invalidation of the same project, while another project's invalidation doesn't block the store; the bound. The cache-content tests seed entries directly, so live watchers can't make them flaky.
