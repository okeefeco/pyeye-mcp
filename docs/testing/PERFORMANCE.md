# Performance Testing Guide

## Overview

Performance testing ensures the PyEye Server maintains acceptable response times and resource usage across different environments and load conditions.

## Performance Requirements

### Response Time Targets

| Operation | P50 (median) | P95 | P99 | Max |
|-----------|-------------|-----|-----|-----|
| Symbol Search | 50ms | 100ms | 200ms | 500ms |
| Goto Definition | 30ms | 75ms | 150ms | 300ms |
| Find References | 100ms | 200ms | 500ms | 1000ms |
| Cache Lookup | 0.1ms | 1ms | 5ms | 10ms |
| Project Load | 500ms | 1000ms | 2000ms | 5000ms |

### Throughput Targets

- **Concurrent Requests**: Handle 100 concurrent operations
- **Sustained Load**: 1000 requests/second for read operations
- **Burst Load**: Handle 5000 requests in 5 seconds
- **Project Capacity**: Manage 10 active projects simultaneously

### Resource Limits

- **Memory**: < 500MB for typical project
- **CPU**: < 50% on single core for steady state
- **Cache Size**: < 100MB per project
- **File Handles**: < 100 open files

## CI-Aware Thresholds

### The PerformanceThresholds Framework

```python
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

# Define CI-aware thresholds
search_threshold = PerformanceThresholds(
    base=100.0,      # Local development (fast machine)
    linux_ci=150.0,  # Linux CI (1.5x tolerance)
    macos_ci=300.0,  # macOS CI (3x tolerance - slower runners)
    windows_ci=300.0 # Windows CI (3x tolerance - variable performance)
)

# Use in test
def test_symbol_search_performance():
    start = time.perf_counter()
    results = find_symbol("TestClass")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert_performance_threshold(
        elapsed_ms,
        search_threshold,
        "Symbol search"
    )
```

### Common Thresholds

```python
from tests.utils.performance import CommonThresholds

# Pre-defined thresholds for common operations
CommonThresholds.SYMBOL_SEARCH_P95     # Symbol search 95th percentile
CommonThresholds.GOTO_DEFINITION_P95   # Goto definition 95th percentile
CommonThresholds.CACHE_LOOKUP_P99      # Cache operations
CommonThresholds.CONCURRENT_OPS_P95    # Concurrent operations
CommonThresholds.BURST_LOAD_P99        # Burst load handling
```

## Performance Test Categories

### 1. Microbenchmarks

Test individual operations in isolation:

```python
# tests/performance/benchmarks/test_symbol_search_benchmark.py
import pytest
from tests.utils.performance import measure_operation

def test_symbol_search_micro():
    """Benchmark symbol search operation."""
    project = create_minimal_project()

    # Warm up
    find_symbol("warmup", project)

    # Measure
    times = []
    for _ in range(100):
        elapsed = measure_operation(
            lambda: find_symbol("TestClass", project)
        )
        times.append(elapsed)

    # Assert percentiles
    assert percentile(times, 50) < 50  # P50 < 50ms
    assert percentile(times, 95) < 100  # P95 < 100ms
```

### 2. Integration Benchmarks

Test complete workflows:

```python
# tests/performance/benchmarks/test_refactoring_benchmark.py
def test_refactoring_workflow_performance():
    """Benchmark complete refactoring workflow."""
    project = create_large_project(modules=50)

    with timer() as t:
        # Find symbol
        symbols = find_symbol("OldName", project)

        # Get all references
        references = []
        for symbol in symbols:
            refs = find_references(symbol)
            references.extend(refs)

        # Perform rename
        for ref in references:
            rename_symbol(ref, "NewName")

    assert t.elapsed_ms < 2000  # Complete in < 2 seconds
```

### 3. Load Tests

Test system under sustained load:

```python
# tests/performance/load_tests/test_sustained_load.py
import asyncio
import concurrent.futures

def test_sustained_load():
    """Test sustained load handling."""
    project = create_project()
    operations = ["find_symbol", "goto_def", "find_refs"]

    def perform_operation():
        op = random.choice(operations)
        start = time.perf_counter()
        if op == "find_symbol":
            find_symbol("Class", project)
        elif op == "goto_def":
            goto_definition("function", project)
        else:
            find_references("variable", project)
        return time.perf_counter() - start

    # Run 1000 operations with 10 concurrent workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(perform_operation) for _ in range(1000)]
        times = [f.result() for f in futures]

    # Check performance
    assert percentile(times, 95) < 0.2  # P95 < 200ms
    assert max(times) < 1.0  # No operation > 1s
```

### 4. Stress Tests

Test system limits:

```python
# tests/performance/load_tests/test_stress.py
def test_burst_load():
    """Test burst load handling."""
    project = create_project()

    async def burst_requests():
        tasks = []
        for _ in range(500):
            tasks.append(async_find_symbol("Test", project))

        start = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        return elapsed, results

    elapsed, results = asyncio.run(burst_requests())

    assert elapsed < 5.0  # Handle 500 requests in < 5 seconds
    assert all(r is not None for r in results)  # All requests succeed
```

### 5. Memory Profiling

Test memory usage:

```python
# tests/performance/benchmarks/test_memory_usage.py
import tracemalloc

def test_memory_usage():
    """Test memory usage stays within limits."""
    tracemalloc.start()

    # Create large project
    project = create_large_project(modules=100)

    # Perform operations
    for _ in range(100):
        find_symbol("Class", project)
        cache_result("key", "value")

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Convert to MB
    peak_mb = peak / 1024 / 1024

    assert peak_mb < 500  # Peak memory < 500MB
```

## Performance Fixtures

```python
# tests/performance/conftest.py
import pytest
import time
from contextlib import contextmanager

@pytest.fixture
def timer():
    """Timer fixture for performance measurements."""
    @contextmanager
    def _timer():
        start = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start
        print(f"\nElapsed: {elapsed:.3f}s")
    return _timer

@pytest.fixture
def performance_project():
    """Create project for performance testing."""
    return create_large_project(
        modules=100,
        classes_per_module=10,
        methods_per_class=5
    )

@pytest.fixture
def profiler():
    """CPU profiler fixture."""
    import cProfile
    import pstats
    from io import StringIO

    profiler = cProfile.Profile()
    profiler.enable()

    yield

    profiler.disable()
    s = StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(10)
    print(s.getvalue())
```

## Benchmark Utilities

```python
# tests/utils/performance.py
import time
import statistics
from typing import Callable, List

def measure_operation(operation: Callable, iterations: int = 100) -> List[float]:
    """Measure operation performance over multiple iterations."""
    times = []

    # Warm up
    for _ in range(10):
        operation()

    # Measure
    for _ in range(iterations):
        start = time.perf_counter()
        operation()
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)  # Convert to ms

    return times

def calculate_percentiles(times: List[float]) -> dict:
    """Calculate performance percentiles."""
    sorted_times = sorted(times)
    return {
        "min": min(times),
        "p50": statistics.median(times),
        "p95": sorted_times[int(len(times) * 0.95)],
        "p99": sorted_times[int(len(times) * 0.99)],
        "max": max(times),
        "mean": statistics.mean(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0
    }

def assert_percentiles(times: List[float], p50: float, p95: float, p99: float):
    """Assert performance percentiles meet targets."""
    stats = calculate_percentiles(times)

    assert stats["p50"] < p50, f"P50 {stats['p50']:.2f}ms exceeds {p50}ms"
    assert stats["p95"] < p95, f"P95 {stats['p95']:.2f}ms exceeds {p95}ms"
    assert stats["p99"] < p99, f"P99 {stats['p99']:.2f}ms exceeds {p99}ms"
```

## pytest-benchmark Integration

```python
# tests/performance/benchmarks/test_with_pytest_benchmark.py
def test_symbol_search_benchmark(benchmark):
    """Benchmark symbol search using pytest-benchmark."""
    project = create_project()

    result = benchmark(find_symbol, "TestClass", project)

    assert result is not None
    assert benchmark.stats["mean"] < 0.1  # Mean < 100ms
    assert benchmark.stats["max"] < 0.5   # Max < 500ms

def test_cache_performance(benchmark):
    """Benchmark cache operations."""
    cache = Cache()

    # Setup test data
    for i in range(1000):
        cache.set(f"key_{i}", f"value_{i}")

    # Benchmark lookups
    def lookup():
        return cache.get(f"key_{random.randint(0, 999)}")

    result = benchmark(lookup)
    assert result is not None
```

## Regression Detection

```python
# tests/performance/test_regression.py
import json
from pathlib import Path

BASELINE_FILE = Path("tests/performance/baseline.json")

def load_baseline():
    """Load performance baseline."""
    if BASELINE_FILE.exists():
        return json.loads(BASELINE_FILE.read_text())
    return {}

def save_baseline(data):
    """Save performance baseline."""
    BASELINE_FILE.write_text(json.dumps(data, indent=2))

def test_no_performance_regression():
    """Ensure no performance regression from baseline."""
    baseline = load_baseline()
    current = {}

    # Measure current performance
    operations = {
        "symbol_search": lambda: find_symbol("Test"),
        "goto_def": lambda: goto_definition("func"),
        "find_refs": lambda: find_references("var")
    }

    for name, operation in operations.items():
        times = measure_operation(operation)
        stats = calculate_percentiles(times)
        current[name] = stats

        if name in baseline:
            # Check for regression (allow 10% tolerance)
            baseline_p95 = baseline[name]["p95"]
            current_p95 = stats["p95"]

            assert current_p95 < baseline_p95 * 1.1, \
                f"{name} regressed: {current_p95:.2f}ms vs {baseline_p95:.2f}ms baseline"

    # Update baseline if running with --update-baseline
    if pytest.config.getoption("--update-baseline"):
        save_baseline(current)
```

## Profiling Integration

### CPU Profiling

```python
# tests/performance/test_cpu_profiling.py
import cProfile
import pstats

def test_cpu_hotspots():
    """Identify CPU hotspots."""
    profiler = cProfile.Profile()

    profiler.enable()

    # Run performance-critical operations
    project = create_large_project()
    for _ in range(100):
        find_symbol("Class", project)

    profiler.disable()

    # Analyze results
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')

    # Get top functions by cumulative time
    top_functions = stats.get_stats_profile().func_profiles[:10]

    # Ensure no single function dominates
    total_time = sum(f.cumulative for f in top_functions)
    for func in top_functions:
        percentage = (func.cumulative / total_time) * 100
        assert percentage < 50, f"Function {func.func} uses {percentage:.1f}% of time"
```

### Memory Profiling

```python
# tests/performance/test_memory_profiling.py
from memory_profiler import profile

@profile
def test_memory_intensive_operation():
    """Profile memory usage of intensive operations."""
    projects = []

    # Create multiple projects
    for i in range(10):
        project = create_project(f"project_{i}")
        projects.append(project)

    # Perform operations
    for project in projects:
        symbols = find_all_symbols(project)
        cache_symbols(symbols)

    # Cleanup
    for project in projects:
        cleanup_project(project)
```

## CI Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/performance.yml
name: Performance Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  performance:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
          pip install pytest-benchmark

      - name: Run performance tests
        run: |
          pytest tests/performance/benchmarks \
            --benchmark-only \
            --benchmark-json=benchmark.json

      - name: Store benchmark result
        uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: 'pytest'
          output-file-path: benchmark.json
          github-token: ${{ secrets.GITHUB_TOKEN }}
          auto-push: true

      - name: Check for regression
        run: |
          python scripts/check_performance_regression.py
```

## Performance Monitoring

### Metrics Collection

```python
# tests/performance/test_metrics.py
from pyeye.unified_metrics import MetricsCollector

def test_metrics_collection():
    """Test metrics are collected properly."""
    collector = MetricsCollector()

    # Perform operations
    with collector.timer("symbol_search"):
        find_symbol("Test")

    with collector.timer("cache_lookup"):
        cache.get("key")

    # Check metrics
    metrics = collector.get_metrics()

    assert "symbol_search" in metrics
    assert metrics["symbol_search"]["count"] > 0
    assert metrics["symbol_search"]["mean"] < 100  # < 100ms
```

### Performance Dashboard

```python
# scripts/performance_report.py
import json
from pathlib import Path
import matplotlib.pyplot as plt

def generate_performance_report():
    """Generate performance report from test results."""

    # Load results
    results = json.loads(Path("benchmark.json").read_text())

    # Extract data
    operations = []
    p50_times = []
    p95_times = []

    for benchmark in results["benchmarks"]:
        operations.append(benchmark["name"])
        p50_times.append(benchmark["stats"]["median"] * 1000)
        p95_times.append(benchmark["stats"]["q95"] * 1000)

    # Create chart
    fig, ax = plt.subplots()
    x = range(len(operations))
    width = 0.35

    ax.bar([i - width/2 for i in x], p50_times, width, label='P50')
    ax.bar([i + width/2 for i in x], p95_times, width, label='P95')

    ax.set_xlabel('Operation')
    ax.set_ylabel('Time (ms)')
    ax.set_title('Performance Metrics')
    ax.set_xticks(x)
    ax.set_xticklabels(operations, rotation=45)
    ax.legend()

    plt.tight_layout()
    plt.savefig('performance_report.png')
```

## Best Practices

### DO

1. **Use CI-aware thresholds** - Account for slower CI environments
2. **Warm up before measuring** - Avoid JIT compilation effects
3. **Measure percentiles** - Not just averages
4. **Test with realistic data** - Use representative project sizes
5. **Track regression** - Compare against baselines
6. **Profile hotspots** - Identify optimization opportunities

### DON'T

1. **Don't use time.sleep()** - Makes tests slow and unreliable
2. **Don't test on tiny data** - Not representative of real usage
3. **Don't ignore variability** - Use multiple iterations
4. **Don't hardcode thresholds** - Use PerformanceThresholds
5. **Don't skip performance tests** - Run regularly to catch regressions

## Optimization Guidelines

### When to Optimize

1. **Measure first** - Profile before optimizing
2. **Focus on hotspots** - Optimize the slowest parts
3. **Set targets** - Define acceptable performance
4. **Verify improvements** - Measure after changes

### Common Optimizations

1. **Caching** - Cache expensive computations
2. **Batch operations** - Process multiple items together
3. **Async/concurrent** - Parallelize independent operations
4. **Lazy loading** - Defer expensive operations
5. **Index structures** - Use appropriate data structures

## References

- [Testing Strategy](./STRATEGY.md)
- [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)
- [Python Profiling](https://docs.python.org/3/library/profile.html)
- [Memory Profiler](https://pypi.org/project/memory-profiler/)
