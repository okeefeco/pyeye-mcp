"""The AST/Script (file_artifact_cache) stats must be visible in the
performance report.

Regression guard for the metrics-fragmentation gap found while investigating
#397: ``get_performance_metrics`` surfaced only the result/scoped cache, so a
healthy run and a cap-thrashing run reported identically. The artifact cache —
the one that actually accelerates navigation — was wired to no report.
"""

from __future__ import annotations

import pytest

from pyeye import file_artifact_cache
from pyeye.metrics import MetricsCollector


@pytest.fixture()
def fresh_artifact_cache():
    """Swap in a clean default cache and restore the original afterwards."""
    original = file_artifact_cache._default_cache
    file_artifact_cache._default_cache = file_artifact_cache.FileArtifactCache(ast_max_entries=500)
    try:
        yield file_artifact_cache
    finally:
        file_artifact_cache._default_cache = original


def test_performance_report_surfaces_artifact_cache_stats(tmp_path, fresh_artifact_cache):
    """A miss-then-hit on the artifact cache shows up in the performance report."""
    src = tmp_path / "m.py"
    src.write_text("class A:\n    pass\n", encoding="utf-8")

    fresh_artifact_cache.get_ast(src)  # miss (cold)
    fresh_artifact_cache.get_ast(src)  # hit (unchanged mtime)

    report = MetricsCollector().get_performance_report()

    assert "artifact_cache" in report, "performance report omits the AST/Script cache"
    assert report["artifact_cache"] == fresh_artifact_cache.stats()
    assert report["artifact_cache"]["hits"] == 1
    assert report["artifact_cache"]["misses"] == 1
    assert report["artifact_cache"]["evictions"] == 0


def test_prometheus_export_surfaces_artifact_cache(tmp_path, fresh_artifact_cache):
    """Artifact-cache counters are exported as Prometheus series too."""
    src = tmp_path / "p.py"
    src.write_text("class B:\n    pass\n", encoding="utf-8")
    fresh_artifact_cache.get_ast(src)  # miss
    fresh_artifact_cache.get_ast(src)  # hit

    text = MetricsCollector().export_prometheus()

    assert "pyeye_artifact_cache_hits 1" in text
    assert "pyeye_artifact_cache_misses 1" in text
    assert "pyeye_artifact_cache_evictions 0" in text


def test_report_makes_cap_thrash_visible(tmp_path):
    """Over-cap eviction thrash is now visible in the report; under-cap is not.

    Before this fix the surfaced metric was identical for both regimes — the
    core blind spot from the #397 investigation. This pins the new behaviour:
    parsing more distinct files than the cap allows produces evictions in the
    report, while a cap that fits the working set does not.
    """
    files = []
    for i in range(10):
        f = tmp_path / f"f{i}.py"
        f.write_text(f"class C{i}:\n    pass\n", encoding="utf-8")
        files.append(f)

    original = file_artifact_cache._default_cache
    try:
        # Under cap: working set (10) fits -> no evictions.
        file_artifact_cache._default_cache = file_artifact_cache.FileArtifactCache(
            ast_max_entries=50
        )
        for f in files:
            file_artifact_cache.get_ast(f)
        healthy = MetricsCollector().get_performance_report()["artifact_cache"]

        # Over cap: working set (10) exceeds cap (3) -> eviction thrash.
        file_artifact_cache._default_cache = file_artifact_cache.FileArtifactCache(
            ast_max_entries=3
        )
        for f in files:
            file_artifact_cache.get_ast(f)
        thrashing = MetricsCollector().get_performance_report()["artifact_cache"]
    finally:
        file_artifact_cache._default_cache = original

    assert healthy["evictions"] == 0
    assert thrashing["evictions"] > 0
    # The distinguishing signal the old surfaced metric could not show.
    assert thrashing["evictions"] != healthy["evictions"]
