"""Tests for the metrics module."""

import time
from unittest.mock import Mock, patch

import pytest
from pycodemcp.metrics import CacheMetrics, MetricsCollector, MetricStats


class TestMetricStats:
    """Test the MetricStats class."""

    def test_add_value(self):
        """Test adding values to metric stats."""
        stats = MetricStats(name="test_metric")

        # Add some values
        stats.add_value(10.0)
        stats.add_value(20.0)
        stats.add_value(30.0)

        assert stats.count == 3
        assert stats.total_ms == 60.0
        assert stats.min_ms == 10.0
        assert stats.max_ms == 30.0
        assert len(stats.recent_values) == 3

    def test_add_error(self):
        """Test recording errors."""
        stats = MetricStats(name="test_metric")

        stats.add_error("Error 1")
        stats.add_error("Error 2")

        assert stats.errors == 2
        assert stats.last_error == "Error 2"

    def test_get_percentile(self):
        """Test percentile calculation."""
        stats = MetricStats(name="test_metric")

        # Add values from 1 to 100
        for i in range(1, 101):
            stats.add_value(float(i))

        # Test various percentiles (allowing for small rounding differences)
        assert abs(stats.get_percentile(50) - 50.0) <= 1
        assert abs(stats.get_percentile(95) - 95.0) <= 1
        assert abs(stats.get_percentile(99) - 99.0) <= 1

    def test_get_percentile_empty(self):
        """Test percentile with no values."""
        stats = MetricStats(name="test_metric")
        assert stats.get_percentile(50) == 0.0

    def test_get_stats(self):
        """Test getting comprehensive statistics."""
        stats = MetricStats(name="test_metric")

        # Empty stats
        empty_stats = stats.get_stats()
        assert empty_stats["count"] == 0
        assert empty_stats["errors"] == 0
        assert empty_stats["avg_ms"] == 0

        # Add some values
        stats.add_value(10.0)
        stats.add_value(20.0)
        stats.add_value(30.0)
        stats.add_error("Test error")

        result = stats.get_stats()
        assert result["count"] == 3
        assert result["errors"] == 1
        assert result["avg_ms"] == 20.0
        assert result["min_ms"] == 10.0
        assert result["max_ms"] == 30.0
        assert result["last_error"] == "Test error"
        assert 0 <= result["error_rate"] <= 1


class TestCacheMetrics:
    """Test the CacheMetrics class."""

    def test_hit_rate(self):
        """Test cache hit rate calculation."""
        cache = CacheMetrics()

        # No hits or misses
        assert cache.hit_rate == 0.0

        # Add some hits and misses
        cache.hits = 75
        cache.misses = 25

        assert cache.hit_rate == 0.75

    def test_get_stats(self):
        """Test getting cache statistics."""
        cache = CacheMetrics()
        cache.hits = 100
        cache.misses = 50
        cache.evictions = 10
        cache.size_bytes = 1024 * 1024  # 1MB

        stats = cache.get_stats()
        assert stats["hits"] == 100
        assert stats["misses"] == 50
        assert stats["evictions"] == 10
        assert stats["hit_rate"] == pytest.approx(0.666666, rel=1e-3)
        assert stats["size_mb"] == 1.0


class TestMetricsCollector:
    """Test the MetricsCollector class."""

    def test_measure_decorator(self):
        """Test the measure decorator."""
        collector = MetricsCollector()

        @collector.measure("test_function")
        def slow_function():
            time.sleep(0.01)  # 10ms
            return "result"

        # Call the function
        result = slow_function()
        assert result == "result"

        # Check metrics were recorded
        stats = collector.get_stats("test_function")
        assert stats["count"] == 1
        assert stats["min_ms"] > 0  # Should have some duration
        assert stats["max_ms"] > 0  # Should have some duration
        # Note: We can't guarantee exact sleep times across platforms

    def test_measure_decorator_with_exception(self):
        """Test the measure decorator with exceptions."""
        collector = MetricsCollector()

        @collector.measure("failing_function")
        def failing_function():
            time.sleep(0.01)
            raise ValueError("Test error")

        # Call should raise but still record metrics
        with pytest.raises(ValueError):
            failing_function()

        stats = collector.get_stats("failing_function")
        assert stats["count"] == 1
        assert stats["errors"] == 1
        assert stats["min_ms"] > 0  # Should have some duration

    def test_timer_context_manager(self):
        """Test the timer context manager."""
        collector = MetricsCollector()

        with collector.timer("test_operation"):
            time.sleep(0.01)

        stats = collector.get_stats("test_operation")
        assert stats["count"] == 1
        assert stats["min_ms"] > 0  # Should have some duration

    def test_cache_metrics_recording(self):
        """Test cache hit/miss recording."""
        collector = MetricsCollector()

        # Record some cache operations
        collector.record_cache_hit()
        collector.record_cache_hit()
        collector.record_cache_miss()
        collector.update_cache_size(1024 * 1024)

        assert collector.cache_metrics.hits == 2
        assert collector.cache_metrics.misses == 1
        assert collector.cache_metrics.hit_rate == pytest.approx(0.666666, rel=1e-3)
        assert collector.cache_metrics.size_bytes == 1024 * 1024

    @patch("psutil.Process")
    def test_get_memory_stats(self, mock_process_class):
        """Test memory statistics retrieval."""
        # Mock memory info
        mock_process = Mock()
        mock_process.memory_info.return_value = Mock(rss=100 * 1024 * 1024, vms=200 * 1024 * 1024)
        mock_process.memory_percent.return_value = 5.5
        mock_process_class.return_value = mock_process

        collector = MetricsCollector()
        memory_stats = collector.get_memory_stats()

        assert memory_stats["rss_mb"] == 100.0
        assert memory_stats["vms_mb"] == 200.0
        assert memory_stats["percent"] == 5.5

    def test_get_performance_report(self):
        """Test comprehensive performance report."""
        collector = MetricsCollector()

        # Add various metrics
        @collector.measure("symbol_search")
        def search():
            time.sleep(0.01)

        @collector.measure("file_read")
        def read():
            time.sleep(0.005)

        # Execute operations
        search()
        search()
        read()

        # Add cache metrics
        collector.record_cache_hit()
        collector.record_cache_miss()

        # Get report
        report = collector.get_performance_report()

        assert "uptime_seconds" in report
        assert "memory" in report
        assert "cache" in report
        assert "operations" in report
        assert "summary" in report

        # Check operations are categorized
        ops = report["operations"]
        assert "symbol_search" in ops
        assert "file_operations" in ops

        # Check summary
        summary = report["summary"]
        assert summary["total_operations"] == 3
        assert summary["total_errors"] == 0
        assert len(summary["slowest_operations"]) > 0
        assert len(summary["most_frequent_operations"]) > 0

    def test_export_prometheus(self):
        """Test Prometheus format export."""
        collector = MetricsCollector()

        # Add some metrics
        collector.metrics["test_op"].add_value(10.0)
        collector.metrics["test_op"].add_value(20.0)
        collector.record_cache_hit()

        prometheus_output = collector.export_prometheus()

        # Check format
        assert "# HELP" in prometheus_output
        assert "# TYPE" in prometheus_output
        assert "pycodemcp_operation_count" in prometheus_output
        assert "pycodemcp_operation_duration_ms" in prometheus_output
        assert "pycodemcp_cache_hits" in prometheus_output
        assert 'quantile="0.5"' in prometheus_output
        assert 'quantile="0.95"' in prometheus_output

    def test_reset(self):
        """Test resetting all metrics."""
        collector = MetricsCollector()

        # Add some data
        collector.metrics["test"].add_value(10.0)
        collector.record_cache_hit()

        # Reset
        collector.reset()

        assert len(collector.metrics) == 0
        assert collector.cache_metrics.hits == 0

    def test_get_stats_nonexistent_metric(self):
        """Test getting stats for a nonexistent metric."""
        collector = MetricsCollector()

        stats = collector.get_stats("nonexistent")
        assert stats == {"error": "Metric 'nonexistent' not found"}

    def test_measure_decorator_default_name(self):
        """Test measure decorator using function name as default."""
        collector = MetricsCollector()

        @collector.measure()
        def my_function():
            return "test"

        my_function()

        # Should use module.function_name as metric name
        all_stats = collector.get_stats()
        assert any("my_function" in key for key in all_stats)


class TestIntegration:
    """Integration tests for metrics in real scenarios."""

    def test_concurrent_metric_recording(self):
        """Test thread-safe metric recording."""
        import threading

        collector = MetricsCollector()

        @collector.measure("concurrent_op")
        def operation(delay):
            time.sleep(delay)

        # Run operations concurrently
        threads = []
        for _ in range(10):
            t = threading.Thread(target=operation, args=(0.001,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        stats = collector.get_stats("concurrent_op")
        assert stats["count"] == 10

    def test_percentile_accuracy(self):
        """Test percentile calculations are accurate."""
        stats = MetricStats(name="test")

        # Add 1000 values with known distribution
        values = list(range(1, 1001))
        for v in values:
            stats.add_value(float(v))

        # Recent values only keeps last 1000
        assert len(stats.recent_values) == 1000

        # Check percentiles
        assert abs(stats.get_percentile(50) - 500) <= 5  # Allow small margin
        assert abs(stats.get_percentile(95) - 950) <= 5
        assert abs(stats.get_percentile(99) - 990) <= 5
