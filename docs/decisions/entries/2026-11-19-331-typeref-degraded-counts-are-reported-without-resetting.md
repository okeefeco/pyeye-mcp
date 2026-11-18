---
date: "2026-11-19"
title: "Typeref degraded-path counts are reported by get_performance_metrics, without resetting (#331)"
issues: [331, 397, 402]
anchors: ["pyeye.mcp.operations.typeref.degraded_counts_snapshot", "MetricsCollector.get_performance_report", "MetricsCollector.export_prometheus", "tests/unit/utils/test_metrics_typeref_degraded.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — Typeref degraded-path counts are reported by get_performance_metrics, without resetting (#331)

**Friction:** `typeref` counted the annotation shapes it degrades to `{raw: ...}`, so that proper recursion could be prioritised by data, but only tests read the counter. In a running server the counts were unreachable.

**Decision:**

- `get_performance_report()` gains a top-level `typeref_degraded` section, `{kind: count}`, beside `artifact_cache` (the #397 precedent: a distinct section, not merged into another).
- `export_prometheus()` gains one counter family, `pyeye_typeref_degraded_total{kind="..."}`, in #402's one-family-per-group layout, with label values escaped. With no counts the family has HELP and TYPE but no samples.
- **Reading never resets.** Both read `degraded_counts_snapshot()`, a copy. The report had no reset semantics, and a scrape or a report call must not consume data another reader needs (coordinator's call). `get_and_reset_degraded_counts()` stays for tests.

**Applies-to:**

- `pyeye.mcp.operations.typeref.degraded_counts_snapshot` and `get_and_reset_degraded_counts`.
- `MetricsCollector.get_performance_report` and `MetricsCollector.export_prometheus`.
- `docs/api-redesign.md` (Telemetry).

**Verify:** gold — `uv run pytest tests/unit/utils/test_metrics_typeref_degraded.py` passes. It checks the section and the counter by kind, that reading either leaves the counts in place, that the section is a copy, the empty case, label escaping, and that the export still parses with `prometheus_client`.
