"""Performance regression tests to catch performance degradation."""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pycodemcp.analyzers.jedi_analyzer import JediAnalyzer
from pycodemcp.cache import GranularCache, ProjectCache
from pycodemcp.metrics import MetricsCollector


@pytest.fixture
def temp_project():
    """Create a temporary project with test files."""
    with TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create test Python files
        test_file = project_path / "test_module.py"
        test_file.write_text(
            """
class TestClass:
    def method1(self):
        return "test"

    def method2(self, arg):
        return arg * 2

def test_function(x, y):
    return x + y

TEST_CONSTANT = 42
"""
        )

        # Create another file for cross-file testing
        other_file = project_path / "other_module.py"
        other_file.write_text(
            """
from test_module import TestClass, test_function

def use_imports():
    obj = TestClass()
    return test_function(1, 2)
"""
        )

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

        # Warm up
        await search()

        # Measure multiple runs
        for _ in range(10):
            await search()

        stats = collector.get_stats("symbol_search")

        # Performance requirements
        assert stats["p95_ms"] < 100, f"Symbol search p95 ({stats['p95_ms']}ms) exceeds 100ms"
        assert stats["p50_ms"] < 50, f"Symbol search p50 ({stats['p50_ms']}ms) exceeds 50ms"

    @pytest.mark.asyncio
    async def test_goto_definition_performance(self, temp_project):
        """Test that goto definition meets performance requirements."""
        analyzer = JediAnalyzer(str(temp_project))
        collector = MetricsCollector()

        test_file = temp_project / "other_module.py"

        @collector.measure("goto_definition")
        async def goto():
            return await analyzer.goto_definition(str(test_file), 4, 10)

        # Warm up
        await goto()

        # Measure multiple runs
        for _ in range(10):
            await goto()

        stats = collector.get_stats("goto_definition")

        # Performance requirements
        assert stats["p95_ms"] < 75, f"Goto definition p95 ({stats['p95_ms']}ms) exceeds 75ms"
        assert stats["p50_ms"] < 30, f"Goto definition p50 ({stats['p50_ms']}ms) exceeds 30ms"

    def test_cache_lookup_performance(self):
        """Test that cache lookups are fast."""
        cache = ProjectCache()
        collector = MetricsCollector()

        # Populate cache
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}")

        @collector.measure("cache_lookup")
        def lookup():
            return cache.get("key_500")

        # Measure lookups
        for _ in range(1000):
            lookup()

        stats = collector.get_stats("cache_lookup")

        # Cache lookups should be very fast
        assert stats["p99_ms"] < 1, f"Cache lookup p99 ({stats['p99_ms']}ms) exceeds 1ms"
        assert stats["p50_ms"] < 0.1, f"Cache lookup p50 ({stats['p50_ms']}ms) exceeds 0.1ms"

    def test_granular_cache_invalidation_performance(self):
        """Test that granular cache invalidation is efficient."""
        cache = GranularCache()
        collector = MetricsCollector()

        # Populate cache with file associations
        for i in range(100):
            file_path = Path(f"/test/file_{i}.py")
            for j in range(10):
                cache.set(f"key_{i}_{j}", f"value_{i}_{j}", file_path=file_path)

        @collector.measure("cache_invalidation")
        def invalidate():
            return cache.invalidate_file(Path("/test/file_50.py"))

        # Measure invalidations
        for _ in range(10):
            # Re-populate for next invalidation
            for j in range(10):
                cache.set(f"key_50_{j}", f"value_50_{j}", file_path=Path("/test/file_50.py"))
            invalidate()

        stats = collector.get_stats("cache_invalidation")

        # Invalidation should be fast even with many entries
        assert stats["p95_ms"] < 5, f"Cache invalidation p95 ({stats['p95_ms']}ms) exceeds 5ms"

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

        # Metrics overhead should be less than 5ms per operation (relaxed for CI environments)
        assert overhead_ms < 5, f"Metrics overhead ({overhead_ms}ms) exceeds 5ms per operation"

    def test_concurrent_operations_performance(self):
        """Test performance under concurrent load."""
        import threading

        collector = MetricsCollector()
        cache = GranularCache()

        @collector.measure("concurrent_op")
        def operation(thread_id):
            # Mix of cache operations
            for i in range(100):
                key = f"thread_{thread_id}_key_{i}"
                cache.set(key, f"value_{i}")
                cache.get(key)
            return thread_id

        # Run concurrent operations
        threads = []
        start = time.perf_counter()

        for i in range(10):
            t = threading.Thread(target=operation, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        total_time = time.perf_counter() - start

        stats = collector.get_stats("concurrent_op")

        # Should handle 10 threads × 100 operations efficiently
        assert total_time < 2.0, f"Concurrent operations took {total_time}s (exceeds 2s)"
        assert stats["p95_ms"] < 200, f"Concurrent op p95 ({stats['p95_ms']}ms) exceeds 200ms"


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

    def test_cache_memory_efficiency(self):
        """Test that cache doesn't grow unbounded."""
        cache = GranularCache(ttl_seconds=1)  # Use short TTL for test

        # Add many entries
        for i in range(100):  # Reduce number for faster test
            cache.set(f"key_{i}", f"value_{i}" * 100)  # Larger values

        # Check that old entries are evicted (via TTL)
        time.sleep(1.1)  # Wait for TTL to expire

        # Access should trigger cleanup - get will return None for expired entries
        result = cache.get("key_0")
        assert result is None, "Cache entry should have expired"

        # Try to get another expired entry to verify cleanup
        result = cache.get("key_50")
        assert result is None, "Cache entry should have expired"


class TestPerformanceUnderLoad:
    """Test performance characteristics under various load conditions."""

    @pytest.mark.asyncio
    async def test_burst_load_handling(self, temp_project):
        """Test handling of burst requests."""
        analyzer = JediAnalyzer(str(temp_project))
        collector = MetricsCollector()

        @collector.measure("burst_operation")
        async def operation():
            return await analyzer.find_symbol("test_function")

        # Simulate burst of 50 requests
        start = time.perf_counter()
        tasks = [operation() for _ in range(50)]
        await asyncio.gather(*tasks)
        burst_time = time.perf_counter() - start

        stats = collector.get_stats("burst_operation")

        # Should handle burst efficiently
        assert burst_time < 5.0, f"Burst of 50 requests took {burst_time}s (exceeds 5s)"
        assert stats["p99_ms"] < 500, f"Burst p99 ({stats['p99_ms']}ms) exceeds 500ms"

    def test_sustained_load_performance(self):
        """Test performance under sustained load."""
        collector = MetricsCollector()
        cache = ProjectCache()

        # Populate cache
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}")

        @collector.measure("sustained_op")
        def operation():
            # Mix of operations
            cache.get(f"key_{time.time_ns() % 1000}")
            cache.set(f"new_key_{time.time_ns()}", "value")

        # Sustained load for 2 seconds
        start = time.perf_counter()
        operations_count = 0

        while time.perf_counter() - start < 2.0:
            operation()
            operations_count += 1

        stats = collector.get_stats("sustained_op")

        # Should maintain good performance under sustained load
        assert operations_count > 1000, f"Only {operations_count} ops in 2s (expected >1000)"
        assert stats["p95_ms"] < 10, f"Sustained load p95 ({stats['p95_ms']}ms) exceeds 10ms"


# Performance baseline configuration for CI
PERFORMANCE_BASELINES = {
    "symbol_search": {"p50_ms": 50, "p95_ms": 100, "p99_ms": 200},
    "goto_definition": {"p50_ms": 30, "p95_ms": 75, "p99_ms": 150},
    "find_references": {"p50_ms": 100, "p95_ms": 250, "p99_ms": 500},
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
