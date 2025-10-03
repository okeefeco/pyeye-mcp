"""Performance monitoring and metrics collection for Python Code Intelligence MCP."""

import functools
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar, cast

import psutil

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class MetricStats:
    """Statistics for a single metric."""

    name: str
    count: int = 0
    total_ms: float = 0
    min_ms: float = float("inf")
    max_ms: float = 0
    recent_values: deque = field(default_factory=lambda: deque(maxlen=1000))
    errors: int = 0
    last_error: str | None = None

    def add_value(self, duration_ms: float) -> None:
        """Add a new duration value."""
        self.count += 1
        self.total_ms += duration_ms
        self.min_ms = min(self.min_ms, duration_ms)
        self.max_ms = max(self.max_ms, duration_ms)
        self.recent_values.append(duration_ms)

    def add_error(self, error: str) -> None:
        """Record an error."""
        self.errors += 1
        self.last_error = error

    def get_percentile(self, percentile: float) -> float:
        """Calculate percentile from recent values."""
        if not self.recent_values:
            return 0.0
        sorted_values = sorted(self.recent_values)
        index = int(len(sorted_values) * percentile / 100)
        return float(sorted_values[min(index, len(sorted_values) - 1)])

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive statistics."""
        if self.count == 0:
            return {
                "count": 0,
                "errors": 0,
                "avg_ms": 0,
                "min_ms": 0,
                "max_ms": 0,
                "p50_ms": 0,
                "p95_ms": 0,
                "p99_ms": 0,
            }

        return {
            "count": self.count,
            "errors": self.errors,
            "error_rate": (
                self.errors / (self.count + self.errors) if (self.count + self.errors) > 0 else 0
            ),
            "avg_ms": self.total_ms / self.count if self.count > 0 else 0,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "p50_ms": self.get_percentile(50),
            "p95_ms": self.get_percentile(95),
            "p99_ms": self.get_percentile(99),
            "last_error": self.last_error,
        }


@dataclass
class CacheMetrics:
    """Metrics for cache performance."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size_bytes: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": self.hit_rate,
            "size_mb": self.size_bytes / (1024 * 1024),
        }


class MetricsCollector:
    """Centralized metrics collection and reporting."""

    def __init__(self) -> None:
        """Initialize metrics collector."""
        self.metrics: dict[str, MetricStats] = defaultdict(lambda: MetricStats(name=""))
        self.cache_metrics = CacheMetrics()
        self.start_time = datetime.now()
        self._process = psutil.Process()

    def measure(self, name: str | None = None) -> Callable[[F], F]:
        """Decorator to measure function execution time.

        Args:
            name: Optional metric name (defaults to function name)

        Returns:
            Decorated function
        """
        import asyncio

        def decorator(func: F) -> F:
            metric_name = name or f"{func.__module__}.{func.__name__}"

            # Check if the function is async
            if asyncio.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    start = time.perf_counter()
                    try:
                        result = await func(*args, **kwargs)
                        duration_ms = (time.perf_counter() - start) * 1000
                        self.metrics[metric_name].add_value(duration_ms)
                        return result
                    except Exception as e:
                        duration_ms = (time.perf_counter() - start) * 1000
                        self.metrics[metric_name].add_value(duration_ms)
                        self.metrics[metric_name].add_error(str(e))
                        raise

                return cast(F, async_wrapper)
            else:

                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    start = time.perf_counter()
                    try:
                        result = func(*args, **kwargs)
                        duration_ms = (time.perf_counter() - start) * 1000
                        self.metrics[metric_name].add_value(duration_ms)
                        return result
                    except Exception as e:
                        duration_ms = (time.perf_counter() - start) * 1000
                        self.metrics[metric_name].add_value(duration_ms)
                        self.metrics[metric_name].add_error(str(e))
                        raise

                return cast(F, sync_wrapper)

        return decorator

    @contextmanager
    def timer(self, name: str) -> Any:
        """Context manager to measure execution time.

        Args:
            name: Metric name

        Example:
            with metrics.timer('database_query'):
                results = db.query(...)
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.metrics[name].add_value(duration_ms)

    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_metrics.hits += 1

    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        self.cache_metrics.misses += 1

    def record_cache_eviction(self) -> None:
        """Record a cache eviction."""
        self.cache_metrics.evictions += 1

    def update_cache_size(self, size_bytes: int) -> None:
        """Update cache size in bytes."""
        self.cache_metrics.size_bytes = size_bytes

    def get_memory_stats(self) -> dict[str, float]:
        """Get current memory usage statistics."""
        memory_info = self._process.memory_info()
        return {
            "rss_mb": memory_info.rss / (1024 * 1024),
            "vms_mb": memory_info.vms / (1024 * 1024),
            "percent": self._process.memory_percent(),
        }

    def get_stats(self, metric_name: str | None = None) -> dict[str, Any]:
        """Get statistics for a specific metric or all metrics.

        Args:
            metric_name: Optional specific metric name

        Returns:
            Statistics dictionary
        """
        if metric_name:
            if metric_name not in self.metrics:
                return {"error": f"Metric '{metric_name}' not found"}
            return self.metrics[metric_name].get_stats()

        # Return all metrics
        return {name: metric.get_stats() for name, metric in self.metrics.items()}

    def get_performance_report(self) -> dict[str, Any]:
        """Get comprehensive performance report.

        Returns:
            Full performance report including all metrics
        """
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()

        # Group metrics by category
        symbol_metrics = {}
        cache_metrics = {}
        file_metrics = {}
        other_metrics = {}

        for name, metric in self.metrics.items():
            stats = metric.get_stats()
            if "symbol" in name.lower() or "find" in name.lower():
                symbol_metrics[name] = stats
            elif "cache" in name.lower():
                cache_metrics[name] = stats
            elif "file" in name.lower() or "read" in name.lower() or "write" in name.lower():
                file_metrics[name] = stats
            else:
                other_metrics[name] = stats

        return {
            "uptime_seconds": uptime_seconds,
            "memory": self.get_memory_stats(),
            "cache": self.cache_metrics.get_stats(),
            "operations": {
                "symbol_search": symbol_metrics,
                "file_operations": file_metrics,
                "cache_operations": cache_metrics,
                "other": other_metrics,
            },
            "summary": self._calculate_summary(),
        }

    def _calculate_summary(self) -> dict[str, Any]:
        """Calculate summary statistics across all metrics."""
        total_operations = sum(m.count for m in self.metrics.values())
        total_errors = sum(m.errors for m in self.metrics.values())
        total_time_ms = sum(m.total_ms for m in self.metrics.values())

        # Find slowest operations
        slowest_ops = sorted(
            [(name, m.max_ms) for name, m in self.metrics.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        # Find most frequent operations
        most_frequent = sorted(
            [(name, m.count) for name, m in self.metrics.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        return {
            "total_operations": total_operations,
            "total_errors": total_errors,
            "error_rate": total_errors / total_operations if total_operations > 0 else 0,
            "total_time_ms": total_time_ms,
            "avg_operation_ms": total_time_ms / total_operations if total_operations > 0 else 0,
            "slowest_operations": [{"name": name, "max_ms": ms} for name, ms in slowest_ops],
            "most_frequent_operations": [
                {"name": name, "count": count} for name, count in most_frequent
            ],
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self.metrics.clear()
        self.cache_metrics = CacheMetrics()
        self.start_time = datetime.now()

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []
        lines.append("# HELP pyeye_operation_duration_ms Operation duration in milliseconds")
        lines.append("# TYPE pyeye_operation_duration_ms histogram")

        for name, metric in self.metrics.items():
            stats = metric.get_stats()
            safe_name = name.replace(".", "_").replace("-", "_")
            lines.append(f'pyeye_operation_count{{operation="{safe_name}"}} {stats["count"]}')
            lines.append(
                f'pyeye_operation_duration_ms{{operation="{safe_name}",quantile="0.5"}} {stats["p50_ms"]}'
            )
            lines.append(
                f'pyeye_operation_duration_ms{{operation="{safe_name}",quantile="0.95"}} {stats["p95_ms"]}'
            )
            lines.append(
                f'pyeye_operation_duration_ms{{operation="{safe_name}",quantile="0.99"}} {stats["p99_ms"]}'
            )

        # Cache metrics
        lines.append("# HELP pyeye_cache_hits Cache hits")
        lines.append("# TYPE pyeye_cache_hits counter")
        lines.append(f"pyeye_cache_hits {self.cache_metrics.hits}")

        lines.append("# HELP pyeye_cache_misses Cache misses")
        lines.append("# TYPE pyeye_cache_misses counter")
        lines.append(f"pyeye_cache_misses {self.cache_metrics.misses}")

        # Memory metrics
        memory = self.get_memory_stats()
        lines.append("# HELP pyeye_memory_mb Memory usage in MB")
        lines.append("# TYPE pyeye_memory_mb gauge")
        lines.append(f"pyeye_memory_mb {{type=\"rss\"}} {memory['rss_mb']}")

        return "\n".join(lines)


# Global metrics instance
metrics = MetricsCollector()


# Convenience exports
measure = metrics.measure
timer = metrics.timer
get_stats = metrics.get_stats
get_performance_report = metrics.get_performance_report
