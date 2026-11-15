"""Performance regression tests to catch performance degradation."""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.metrics import MetricsCollector
from tests.utils.performance import (
    CommonThresholds,
    PerformanceThresholds,
    assert_performance_threshold,
)


@pytest.fixture
def temp_project():
    """Create a temporary project with test files."""
    with TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create test Python files
        test_file = project_path / "test_module.py"
        test_file.write_text("""
class TestClass:
    def method1(self):
        return "test"

    def method2(self, arg):
        return arg * 2

def test_function(x, y):
    return x + y

TEST_CONSTANT = 42
""")

        # Create another file for cross-file testing
        other_file = project_path / "other_module.py"
        other_file.write_text("""
from test_module import TestClass, test_function

def use_imports():
    obj = TestClass()
    return test_function(1, 2)
""")

        yield project_path


class TestPerformanceBaselines:
    """Test that critical operations meet performance baselines."""

    @pytest.mark.asyncio
    async def test_symbol_search_performance(self, temp_project):
        """Test that symbol search meets performance requirements."""
        analyzer = JediAnalyzer(str(temp_project))
        collector = MetricsCollector()

        @collector.measure("symbol_search")
        async def search():
            return await analyzer.find_symbol("TestClass")

        # Warm up the analyzer's caches WITHOUT recording the call. The first call is
        # cold (jedi import + initial parse) and on slow CI runners takes 400-500ms;
        # counting it would dominate p95 over only ~10 samples and deterministically
        # fail macOS CI (#383). Warm up via the analyzer directly so the collector
        # only records steady-state, warm runs.
        await analyzer.find_symbol("TestClass")

        # Measure multiple warm runs
        for _ in range(10):
            await search()

        stats = collector.get_stats("symbol_search")

        # Performance requirements (platform-aware thresholds — see tests/utils/performance.py).
        # The AST fallback for inheritance detection (fix #234) adds overhead, and CI runners
        # (especially macOS) are slow and variable, so naive flat caps deterministically fail
        # on macOS CI (#383). CommonThresholds carries the macos_ci tier for exactly this.
        assert_performance_threshold(
            stats["p95_ms"], CommonThresholds.SYMBOL_SEARCH_P95, "Symbol search p95"
        )
        assert_performance_threshold(
            stats["p50_ms"], CommonThresholds.SYMBOL_SEARCH_P50, "Symbol search p50"
        )

    def test_metrics_overhead(self):
        """Test that metrics collection itself has minimal overhead."""
        collector = MetricsCollector()

        # Function with known duration
        @collector.measure("test_op")
        def operation():
            time.sleep(0.01)  # 10ms

        # Function without metrics
        def operation_no_metrics():
            time.sleep(0.01)  # 10ms

        # Measure with metrics
        start = time.perf_counter()
        for _ in range(100):
            operation()
        with_metrics_time = time.perf_counter() - start

        # Measure without metrics
        start = time.perf_counter()
        for _ in range(100):
            operation_no_metrics()
        without_metrics_time = time.perf_counter() - start

        # Calculate overhead
        overhead_ms = ((with_metrics_time - without_metrics_time) / 100) * 1000

        # Metrics overhead should be minimal
        assert_performance_threshold(
            overhead_ms,
            CommonThresholds.METRICS_OVERHEAD,
            "Metrics overhead",
            unit="ms per operation",
        )


class TestMemoryEfficiency:
    """Test memory usage stays within bounds."""

    def test_metrics_memory_footprint(self):
        """Test that metrics collection doesn't leak memory."""
        collector = MetricsCollector()

        # Initial memory
        initial_memory = collector.get_memory_stats()["rss_mb"]

        # Generate many metrics
        for i in range(1000):
            metric_name = f"metric_{i}"
            for j in range(100):
                collector.metrics[metric_name].add_value(float(j))

        # Check memory after
        final_memory = collector.get_memory_stats()["rss_mb"]
        memory_increase = final_memory - initial_memory

        # Memory increase should be reasonable (less than 50MB for this test)
        assert memory_increase < 50, f"Memory increased by {memory_increase}MB (exceeds 50MB)"

        # Recent values are capped at 1000 per metric
        for metric in collector.metrics.values():
            assert len(metric.recent_values) <= 1000


class TestPerformanceUnderLoad:
    """Test performance characteristics under various load conditions."""

    @pytest.mark.asyncio
    async def test_burst_load_handling(self, temp_project):
        """A burst of concurrent requests completes, and warm calls stay fast (#486).

        Two separate measurements, because the old single ``p99 < 500ms`` assert
        measured neither:

        * **Cold burst, whole.** 50 ``find_symbol`` calls are gathered on a fresh
          analyzer. They run one after another on one event loop, so each call's
          own latency includes waiting behind the others; the p99 of that set is
          really the time for the whole cold burst (index build included). This
          asserts that total under a ``PerformanceThresholds`` budget set from CI
          numbers (about 700-740 ms on ubuntu 3.11 with coverage).
        * **Warm per-call latency.** With the index built, calls are timed one at
          a time, so p99 is a real per-request latency.
        """
        analyzer = JediAnalyzer(str(temp_project))

        # Cold burst: total wall time for 50 concurrent requests.
        start = time.perf_counter()
        results = await asyncio.gather(*(analyzer.find_symbol("test_function") for _ in range(50)))
        burst_ms = (time.perf_counter() - start) * 1000
        assert all(results), "every burst request must find test_function"
        cold_burst_threshold = PerformanceThresholds(
            base=1000.0,  # ~100-150 ms locally
            linux_ci=2500.0,  # ~700-740 ms observed on ubuntu 3.11 CI with coverage
            macos_ci=5000.0,
            windows_ci=5000.0,
        )
        assert_performance_threshold(burst_ms, cold_burst_threshold, "Cold burst of 50 requests")

        # Warm per-call latency: sequential, so no call waits behind another.
        collector = MetricsCollector()

        @collector.measure("warm_find_symbol")
        async def operation():
            return await analyzer.find_symbol("test_function")

        for _ in range(50):
            await operation()
        stats = collector.get_stats("warm_find_symbol")
        warm_p99_threshold = PerformanceThresholds(
            base=50.0,  # ~2-3 ms locally
            linux_ci=100.0,
            macos_ci=200.0,
            windows_ci=200.0,
        )
        assert_performance_threshold(stats["p99_ms"], warm_p99_threshold, "Warm find_symbol p99")


# Performance baseline configuration for CI
PERFORMANCE_BASELINES = {
    "symbol_search": {"p50_ms": 50, "p95_ms": 100, "p99_ms": 200},
    "cache_lookup": {"p50_ms": 0.1, "p95_ms": 0.5, "p99_ms": 1.0},
    "cache_invalidation": {"p50_ms": 2, "p95_ms": 5, "p99_ms": 10},
}


def check_performance_against_baselines(metrics: dict, operation: str) -> list[str]:
    """Check if metrics meet baseline requirements.

    Returns:
        List of failure messages, empty if all pass
    """
    failures = []
    if operation not in PERFORMANCE_BASELINES:
        return failures

    baseline = PERFORMANCE_BASELINES[operation]

    for metric, threshold in baseline.items():
        if metric in metrics and metrics[metric] > threshold:
            failures.append(
                f"{operation} {metric}: {metrics[metric]}ms exceeds baseline {threshold}ms"
            )

    return failures
