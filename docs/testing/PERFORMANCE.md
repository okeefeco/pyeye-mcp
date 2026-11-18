# Performance Testing Guide

## Overview

Performance tests guard against slowdowns in the PyEye Server. They live in
[`tests/performance/benchmarks/`](../../tests/performance/benchmarks/) and run in
the ordinary test job, so the same `uv run pytest` that runs the rest of the suite
runs them too (see [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)).

The helpers they share are in
[`tests/utils/performance.py`](../../tests/utils/performance.py). Read that module
for the current API rather than relying on names copied into this page.

## Why the Tests Look the Way They Do

### CI Runners Are Slower and Noisier

A limit that suits a developer machine fails on a shared CI runner, and macOS and
Windows runners vary more than Linux ones. A single hard-coded number is either
too loose to catch a regression locally or too tight to pass in CI.

`PerformanceThresholds` holds one limit per environment (local, Linux CI, macOS
CI, Windows CI) and picks the one that applies when the test runs.
`assert_performance_threshold` compares a measurement against it and reports the
environment in the failure message.

### Warm Medians Beat Percentiles on Few Samples

A high percentile taken over a handful of samples is effectively the slowest
single call, so one garbage-collection pause or disk hiccup decides the result.
The benchmarks instead time repeated warm calls, take each run's median, and keep
the best of several runs. A scheduler stall then moves nothing, while a real
slowdown in the code still moves every run.

The regression tests also check that the guard can fail: they slow the measured
call down on purpose and assert that the threshold catches it. A threshold that a
deliberately slower implementation still passes protects nothing.

## Writing a Performance Test

### Assert Through PerformanceThresholds

```python
import statistics
import time

from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

THRESHOLD = PerformanceThresholds(
    base=100.0,       # local development
    linux_ci=150.0,   # Linux CI
    macos_ci=300.0,   # macOS CI
    windows_ci=300.0, # Windows CI
)


def test_operation_performance():
    perform_operation()  # warm up first

    samples = []
    for _ in range(20):
        start = time.perf_counter()
        perform_operation()
        samples.append((time.perf_counter() - start) * 1000)

    assert_performance_threshold(statistics.median(samples), THRESHOLD, "Operation median")
```

`perform_operation` stands for the call under test. Pick the threshold values from
measurements on each platform, not by guesswork.

### Reuse Shared Thresholds

`CommonThresholds` collects the thresholds that several tests share. The limits
the suite enforces are the `CommonThresholds` entries the benchmarks use. See
[`tests/utils/performance.py`](../../tests/utils/performance.py) for the current
names and the comments that explain them.

### A Worked Example

[`tests/performance/benchmarks/test_performance_regression.py`](../../tests/performance/benchmarks/test_performance_regression.py)
is the reference: it measures warm medians, asserts against `CommonThresholds`,
measures the overhead of `pyeye.metrics.MetricsCollector`, and includes the
"slowed on purpose" tests that prove each guard can fail.
[`tests/performance/benchmarks/test_scope_performance.py`](../../tests/performance/benchmarks/test_scope_performance.py)
covers the scoped cache and parallel search.

## Profiling

Profiling is for finding where time goes, not for asserting on it. The standard
library is enough.

### CPU Profiling

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()
run_workload()  # the code you want to profile
profiler.disable()

pstats.Stats(profiler).sort_stats("cumulative").print_stats(10)
```

### Memory Profiling

```python
import tracemalloc

tracemalloc.start()
run_workload()
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

print(f"current={current / 1024 / 1024:.1f} MiB, peak={peak / 1024 / 1024:.1f} MiB")
```

## Best Practices

### DO

1. **Use CI-aware thresholds** - Assert through `PerformanceThresholds`
2. **Warm up before measuring** - The first call pays for imports and caches
3. **Prefer medians over repeated runs** - Not single timings or high percentiles of a few samples
4. **Prove the guard can fail** - Slow the call on purpose and check the test catches it
5. **Profile before optimizing** - Measure where the time goes first

### DON'T

1. **Don't write `assert elapsed < limit`** - Use `assert_performance_threshold`
2. **Don't use `time.sleep()`** - It makes tests slow and unreliable
3. **Don't trust one sample** - Repeat the measurement
4. **Don't copy threshold names from docs** - Read them from `tests/utils/performance.py`

## References

- [Testing Strategy](./STRATEGY.md)
- [Testing Conventions](./CONVENTIONS.md)
- [Python Profiling](https://docs.python.org/3/library/profile.html)
- [tracemalloc](https://docs.python.org/3/library/tracemalloc.html)
