---
date: "2026-11-19"
title: "Artifact-cache evictions are counted by cause: cap pressure vs staleness; evictions stays the total (#401)"
issues: [401, 397, 713, 959]
anchors: ["pyeye.file_artifact_cache.FileArtifactCache.stats", "pyeye.file_artifact_cache.FileArtifactCache._enforce_ast_cap", "pyeye.metrics.MetricsCollector.export_prometheus", "tests/unit/core/test_artifact_cache_eviction_causes.py"]
status: "active"
amends: ["2026-06-16-397-ast-script-cache-stats-surfaced-in-the-performance-report.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — Artifact-cache evictions are counted by cause: cap pressure vs staleness; evictions stays the total (#401)

**Friction:** The #397 entry surfaced one `evictions` counter so that "a cap-thrashing run is visible". That held only for a cold run with no edits. On an edited or watched repo, every file change also raised `evictions`, so the counter couldn't tell cap thrash from healthy churn. And cap thrash is what it was meant to show: should the cap be raised?

**Decision:**

- `FileArtifactCache` counts evictions by cause, and `stats()` gains two keys:
  - **`cap_evictions`:** every entry `_enforce_ast_cap` drops, under both the Script cap (#713) and the combined cap.
  - **`stale_evictions`:** every entry dropped because its file changed (`_evict_stale_ast`, `_evict_stale_script`), or by an invalidation (`invalidate(path)`, `invalidate_all()`). A clear is an invalidation, not cap pressure.
- **`evictions` stays, as the total.** The invariant `evictions == cap_evictions + stale_evictions` is tested. Renaming or removing it would break the existing key and Prometheus series.
- **Surfacing:**
  - the performance report's `artifact_cache` section embeds `stats()`, so it carries both keys;
  - `export_prometheus` adds the counter families `pyeye_artifact_cache_cap_evictions` and `pyeye_artifact_cache_stale_evictions`, each with its own `HELP` and `TYPE` block, in #959's per-family structure.
- **Not split further:** a cap eviction isn't broken down by which cap fired (Script vs combined). Nobody needs it yet.

**Anchor:** `FileArtifactCache.stats` / `_enforce_ast_cap` / `_evict_stale_*` / `_evict_all_for_resolved` / `invalidate_all`; `MetricsCollector.export_prometheus`; `tests/unit/core/test_artifact_cache_eviction_causes.py`; #401.

**Applies-to:**

- `pyeye.file_artifact_cache.FileArtifactCache`: `stats`, `invalidate_all`, `_evict_stale_ast`, `_evict_stale_script`, `_evict_all_for_resolved` and `_enforce_ast_cap`.
- `pyeye.metrics.MetricsCollector.export_prometheus` and `get_performance_report`.
- `docs/architecture/caching.md` (Parsed-file cache).

**Verify:** gold — `uv run pytest tests/unit/core/test_artifact_cache_eviction_causes.py tests/unit/utils/test_metrics_prometheus.py tests/test_artifact_cache_metrics_surface.py` passes. It checks:

- each cap counts as cap, and a changed file, `invalidate(path)` and `invalidate_all()` count as stale;
- the sum invariant;
- the three eviction series parse as separate counter families with `prometheus_client`'s parser;
- the report carries both keys.
