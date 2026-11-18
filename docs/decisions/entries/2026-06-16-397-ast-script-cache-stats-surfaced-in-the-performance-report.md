---
date: "2026-06-16"
title: "AST/Script cache stats surfaced in the performance report"
issues: [397]
anchors: ["MetricsCollector.get_performance_report", "MetricsCollector.export_prometheus", "e9e47d5"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-19-401-artifact-cache-evictions-split-by-cause.md"]
superseded_by: []
---

## 2026-06-16 — AST/Script cache stats surfaced in the performance report

**Friction:** The `file_artifact_cache` (AST/Script) cache — the one that actually accelerates navigation — was wired to no report. `get_performance_metrics` surfaced only the result/scoped cache, so a healthy run and a cap-thrashing run reported *identically* (both `1 hit, 1 miss`); the eviction signal that distinguishes them was invisible. Root cause: four disconnected `CacheMetrics` objects, only one of them reported.
**Decision:** Surface `file_artifact_cache.stats()` as a distinct top-level `artifact_cache` section in `MetricsCollector.get_performance_report()` and as `pyeye_artifact_cache_{hits,misses,evictions}` Prometheus series. Kept *separate* from the existing `cache` block (not merged) so the metric fragmentation stays visible rather than hidden.
**Anchor:** `MetricsCollector.get_performance_report` ; `MetricsCollector.export_prometheus` ; commit `e9e47d5` ; #397
**Verify:** gold — `tests/test_artifact_cache_metrics_surface.py` asserts the report exposes `artifact_cache` reflecting real hits/misses/evictions, and that an over-cap run (evictions>0) is now distinguishable from an under-cap run (evictions==0) — the exact blind spot this closes.
