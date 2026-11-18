---
date: "2026-11-18"
title: "The imports edge memoises its external re-resolutions per analyzer; misses and project answers are never cached (#925)"
issues: [925, 893, 817, 704, 623]
anchors: ["pyeye.resolver.resolve_external_item", "pyeye.scope_utils.ScopedCache.set", "pyeye.scope_utils.ScopedCache.get_recent", "pyeye.settings.PerformanceSettings.resolve_cache_max_entries", "tests/unit/core/test_external_resolve_cache.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — The imports edge memoises its external re-resolutions per analyzer; misses and project answers are never cached (#925)

**Friction:**

- The `imports` edge re-resolves every external import target through `resolve_item` (#623, #544), and each resolution builds a fresh synthetic `jedi.Script`.
- `trace` expands even its frontier nodes, to detect truncation. So a `trace(..., ["imports"], max_depth=2)` into the stdlib expanded `sys`, `os`, `io` and the rest, and re-resolved every target they import, on every hop and every call.
- Over three such traces on the multirepo fixture there were 482 resolutions of 178 distinct targets. A warm repeat of `test_trace_expand_agree[multirepo_namespace]`'s cases took as long as a cold one (#893).

**Decision:**

- `resolver.resolve_external_item(path, analyzer)` is `resolve_item` memoised in the analyzer's `scoped_cache`, in the `resolve:external` scope. The two `imports` call sites (`_stdlib_import_target`, `_canonical_import_targets`) use it.
- **Only a `Resolved` whose scope is `external` is stored.**
  - A miss is never cached. It stays honest per item (#704).
  - A project answer is never cached. Project code is what the watcher reports changes to.
- **Invalidation:**
  - The watcher's `_on_files_changed` already calls `scoped_cache.invalidate_all()` on every analyzer that reads from the changed root. That covers the one project edit that changes an external answer: a new module that shadows a stdlib name.
  - The value is stored with the #817 epoch guard, so an answer computed across an invalidation isn't kept.
  - Stdlib and site-packages files aren't watched. They change only when the environment does, which needs a restart anyway.
- **Bound:** an LRU of `PYEYE_RESOLVE_CACHE_MAX_ENTRIES` (default 1000). For this, `ScopedCache.set` gained `max_entries=` and `get_recent` marks a hit most recently used. Other scopes stay unbounded.
- **Measured** with Python 3.12, `MemoryMax=2G`, two interleaved rounds against main at `ea9e6452`:

  | Measure | main | #925 |
  |---|---|---|
  | `test_trace_expand_agree[multirepo_namespace]` | 25.2 s / 25.8 s | 14.1 s / 14.5 s |
  | `test_trace_expand_agree[cross_tool]` | 12.6 s / 11.8 s | 9.6 s / 9.6 s |
  | `tests/test_cross_tool_invariants.py` (pytest time) | 136 s / 126 s | 113 s / 117 s |
  | the same file's max RSS | 339 MB / 347 MB | 356 MB / 355 MB |
  | `trace("corp.core.models", ["imports"], max_depth=2)`, repeated | 6.9 s | 1.0 s |
  | django probes (pyeye-scenarios): wall time / max RSS | 60.6 s / 334 MB, 58.2 s / 332 MB | 58.5 s / 332 MB, 58.3 s / 332 MB |
  | django round-trip (`django.db.models.base`): wall time / max RSS | 44.1 s / 352 MB, 44.5 s / 356 MB | 42.7 s / 357 MB, 42.0 s / 357 MB |

  - The django probe results are identical on both builds, and 57 of 57 stubs round-trip.
  - The cached anchors are light: at most +17 MB on the fixture file, and flat on django. So caching the `Resolved` with its anchor stands, and the (handle, scope)-only fallback wasn't needed.
- **Rejected:**
  - Memoising inside `resolve_item` for every caller. Only the `imports` edge was profiled, and `resolve`/`inspect` of one subject gain little.
  - Reading the agreement test's expands from the sweep cache (#893 option b). That compares `trace` with a different analyzer's `expand`.
  - Lowering the test's `max_depth`. It checks the edges out of depth-1 nodes, so lowering it would drop assertions.

**Anchor:** `pyeye.resolver.resolve_external_item`; `ScopedCache.set` / `get_recent`; `PerformanceSettings.resolve_cache_max_entries`; `tests/unit/core/test_external_resolve_cache.py`; #925.

**Applies-to:**

- `pyeye.resolver.resolve_external_item` and its two callers in `pyeye.mcp.operations.edges` (`_stdlib_import_target`, `_canonical_import_targets`).
- `pyeye.scope_utils.ScopedCache.set` (`max_entries`) and `ScopedCache.get_recent`.
- `PerformanceSettings.resolve_cache_max_entries` and its row in `docs/reference/env-vars.md`.

**Verify:** gold — `uv run pytest tests/unit/core/test_external_resolve_cache.py` passes. It checks:

- an external answer is resolved once, and a hit returns the same object;
- misses and project answers are resolved every time;
- `invalidate_all` and a watcher batch both drop the answers;
- a project module that shadows `logging` is seen, as project scope, after the event;
- an answer computed across an invalidation isn't stored;
- the LRU cap comes from settings, and the least recently used entry goes first;
- a repeated `expand(imports)` re-resolves nothing;
- the setting's default and override.
