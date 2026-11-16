---
date: "2026-11-17"
title: "A watched change drops every build input before any generation moves; file listings carry a per-project epoch (#817)"
issues: [817, 617, 397, 803, 816, 788]
anchors: ["pyeye.project_manager.ProjectManager._on_files_changed", "pyeye.scope_utils.ScopedCache.set", "pyeye.scope_utils.ScopedCache.epoch", "pyeye.scope_utils.ScopedCache.invalidate_all", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.get_project_files", "tests/test_invalidation_order.py"]
status: "active"
amends: ["2026-11-16-397-the-resolved-class-graph-is-cached-per-project-layout-scope.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — A watched change drops every build input before any generation moves; file listings carry a per-project epoch (#817)

**Friction:** #617's guard (recorded in #397's entry) snapshots `project_graph.generation` before listing files and caches a build only if the generation is unchanged. That is sound only if the listing is fresh. But `_on_files_changed` bumped the generation **first** and cleared the analyzer's file listings (`scoped_cache`) **last**, after the TypeRef and re-export invalidations. A lookup in between took the new generation, read the stale cached listing, and cached an index without the new file under the new generation. The guard passed, and the new class stayed invisible until some other file changed. #816's burst test hit it on Windows CI: `burst_a.py` and `extra.py` were delivered in one batch, and `Gamma` never resolved. A deterministic repro (stall the invalidation after the bump, look up inside the window) confirmed it.

**Decision:**

- **Inputs first, generations second.** `_on_files_changed` drops everything an index or graph build reads before it bumps any generation. That is the changed paths' `file_artifact_cache` entries, then every affected analyzer's `scoped_cache`. Only then does it call `project_graph.invalidate`, `typeref.invalidate_project` and `canonicalization.invalidate_re_exports`. A build that sees the new generation therefore lists fresh files.
- **Audit of build inputs.** The name and member indices, unparseable list, class graph and import graph read:
  - the file listing (`get_project_files` → `scoped_cache`), the only input that is **not** self-validating;
  - ASTs and Jedi Scripts (`file_artifact_cache`), keyed on `(path, (mtime_ns, size))` and re-checked on every read;
  - `project_layout.module_name_for_file`, which is uncached.
  The other two invalidation sites were already correct: eviction (`_cleanup_project`) and `configure_packages` both drop the analyzer, and with it its `scoped_cache`, before bumping.
- **The residual window closes with an epoch.** A listing can start before the clear and be stored after it. `ScopedCache` now has an epoch, bumped by `invalidate_all`. `get_project_files` takes it before listing and passes it to `set`, which stores only if the epoch is unchanged; the check and the store are atomic against `invalidate_all` under one lock. A raced listing is returned to its caller but not cached: the #617 pattern, applied to the input.
- **Per project, by construction.** Each analyzer owns its `ScopedCache`, so the epoch is per project. Another project's invalidation never moves it, avoiding #803's global-counter failure, where steady watcher traffic on any project discarded every build. A global epoch was rejected for that reason.
- **No contract change.** `ScopedCache.set` gains a keyword-only `epoch` (default `None`: always store, as before) and returns whether it stored. Lookups answer exactly as before, minus the stale window.

**Anchor:** `ProjectManager._on_files_changed`; `ScopedCache.set` / `epoch` / `invalidate_all`; `JediAnalyzer.get_project_files`; `tests/test_invalidation_order.py`; #817, #617, #397, #803.
**Applies-to:**

- the ordering: `pyeye.project_manager.ProjectManager._on_files_changed`;
- the epoch: `pyeye.scope_utils.ScopedCache.set`, `ScopedCache.epoch`, `ScopedCache.invalidate_all`;
- its one epoch-guarded writer: `pyeye.analyzers.jedi_analyzer.JediAnalyzer.get_project_files`;
- the builds it protects, unchanged: `JediAnalyzer._project_index` (name and member indices, unparseable), `JediAnalyzer.find_subclasses` (class graph), and the import-graph build in `JediAnalyzer`.

**Verify:** gold. `uv run pytest tests/test_invalidation_order.py` passes:

- a lookup inside the stalled invalidation window still finds the new class, during and after;
- the file listing is already empty when `project_graph.invalidate` runs;
- a listing raced by its own project's invalidation is returned but not cached;
- another project's invalidation mid-listing still stores;
- `ScopedCache.set` refuses a stale epoch and stores a current one or none.

All interleavings are forced with events, never timing. Against the pre-fix code, the window repro, the ordering pin and the raced-listing test fail.
