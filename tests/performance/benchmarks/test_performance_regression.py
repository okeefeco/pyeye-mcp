"""Performance regression tests to catch performance degradation."""

import asyncio
import statistics
import time
import timeit
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
        """Warm symbol search stays fast, measured robustly (#385, #773).

        It used to assert p95/p50 over 10 samples: one scheduler stall on a
        shared runner was the p95.  Now the statistic is the minimum, across
        repeated runs, of each run's median (see :func:`_warm_median_ms`).  The
        cold first call (jedi import + parse, #383) is excluded by warming up.
        """
        analyzer = JediAnalyzer(str(temp_project))
        await analyzer.find_symbol("TestClass")  # warm-up, not measured

        median_ms = await _warm_median_ms(lambda: analyzer.find_symbol("TestClass"))
        assert_performance_threshold(
            median_ms, CommonThresholds.WARM_FIND_SYMBOL_MS, "Warm symbol search median"
        )

    def test_metrics_overhead(self):
        """``MetricsCollector.measure`` adds only microseconds per call (#741).

        Times a NO-OP wrapped by the decorator against the bare no-op, so the
        difference is the decorator's own cost.  (It used to subtract two loops
        of ``time.sleep(0.01)``, which measured sleep jitter: macOS CI overshoots
        by milliseconds.)  Many calls per sample and the minimum of several
        repeats reject scheduler noise, as ``timeit`` recommends.
        """
        overhead_us = _measure_overhead_us(MetricsCollector().measure("test_op"))
        assert_performance_threshold(
            overhead_us,
            CommonThresholds.METRICS_OVERHEAD_US,
            "Metrics overhead",
            unit="us per call",
        )

    def test_metrics_overhead_catches_a_10x_slower_decorator(self):
        """The guard is real: a decorator ten times as expensive fails it.

        The injected cost is a fixed busy-wait of 9x the calibrated baseline
        (on top of the real cost), not a multiple of this run's measurement,
        so a fast runner can't make the slowed decorator look cheap.
        """
        collector = MetricsCollector()
        spin_s = CommonThresholds.METRICS_OVERHEAD_BASELINE_US * 9 / 1e6

        def slow_measure(func):
            wrapped = collector.measure("slow")(func)

            def slower(*args, **kwargs):
                end = time.perf_counter() + spin_s
                while time.perf_counter() < end:
                    pass
                return wrapped(*args, **kwargs)

            return slower

        slow_us = _measure_overhead_us(slow_measure)
        assert slow_us > CommonThresholds.METRICS_OVERHEAD_US.get_threshold()


def _noop() -> None:
    return None


def _measure_overhead_us(decorate, calls: int = 10_000, repeats: int = 7) -> float:
    """Per-call cost in microseconds that *decorate* adds around a no-op."""
    wrapped = decorate(_noop)
    bare_s = min(timeit.repeat(_noop, number=calls, repeat=repeats))
    wrapped_s = min(timeit.repeat(wrapped, number=calls, repeat=repeats))
    return (wrapped_s - bare_s) / calls * 1e6


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

        # Warm per-call latency, sequential so no call waits behind another.  The
        # p99 of 50 calls measured scheduler stalls (235 ms on macOS CI, #773); the
        # minimum of repeated medians doesn't.
        median_ms = await _warm_median_ms(lambda: analyzer.find_symbol("test_function"))
        assert_performance_threshold(
            median_ms, CommonThresholds.WARM_FIND_SYMBOL_MS, "Warm find_symbol median"
        )

    @pytest.mark.asyncio
    async def test_warm_find_symbol_guard_catches_a_5x_slowdown(self, temp_project):
        """The guard is real: a find_symbol five times as slow fails it (#773).

        The injected cost is a fixed busy-wait of 4x this platform's calibrated
        baseline, on top of the real call: at least 5x the baseline whatever the
        runner's speed, so a fast runner can't make it pass vacuously.
        """
        analyzer = JediAnalyzer(str(temp_project))
        await analyzer.find_symbol("test_function")
        spin_s = CommonThresholds.WARM_FIND_SYMBOL_BASELINE_MS.get_threshold() * 4 / 1000

        async def slowed():
            end = time.perf_counter() + spin_s
            while time.perf_counter() < end:
                pass
            return await analyzer.find_symbol("test_function")

        median_ms = await _warm_median_ms(slowed)
        assert median_ms > CommonThresholds.WARM_FIND_SYMBOL_MS.get_threshold()


async def _warm_median_ms(call, calls: int = 40, repeats: int = 5) -> float:
    """Per-call latency of *call*, robust to scheduler stalls (#773).

    Times *calls* sequential awaits per run and takes each run's median (a few
    stalled calls can't move it), then the minimum over *repeats* runs (a run
    slowed throughout by a noisy neighbour can't either), as ``timeit`` advises.
    """
    medians = []
    for _ in range(repeats):
        samples = []
        for _ in range(calls):
            start = time.perf_counter()
            await call()
            samples.append((time.perf_counter() - start) * 1000)
        medians.append(statistics.median(samples))
    return min(medians)


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
