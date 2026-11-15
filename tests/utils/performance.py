"""Utilities for performance testing with CI tolerance."""

import os
import platform
from dataclasses import dataclass


@dataclass
class PerformanceThresholds:
    """Performance thresholds with CI tolerance."""

    base: float
    linux_ci: float
    macos_ci: float
    windows_ci: float

    def get_threshold(self) -> float:
        """Get the appropriate threshold based on the environment."""
        is_ci = os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"

        if not is_ci:
            return self.base

        system = platform.system()
        if system == "Darwin":
            return self.macos_ci
        elif system == "Windows":
            return self.windows_ci
        else:  # Linux or other
            return self.linux_ci


def get_ci_tolerance_factor() -> float:
    """Get a multiplier for CI environments.

    Returns:
        float: Multiplier for timing thresholds (1.0 for local, higher for CI)
    """
    is_ci = os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"

    if not is_ci:
        return 1.0

    system = platform.system()
    if system == "Darwin":
        # macOS CI runners are particularly slow and variable
        return 3.0
    elif system == "Windows":
        # Windows CI also has high variability
        return 3.0
    else:  # Linux or other
        # Linux CI is more stable but still needs some tolerance
        return 1.5


def is_ci_environment() -> bool:
    """Check if running in a CI environment."""
    return os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"


def get_platform_name() -> str:
    """Get a human-readable platform name."""
    system = platform.system()
    platform_names = {
        "Darwin": "macOS",
        "Windows": "Windows",
        "Linux": "Linux",
    }
    return platform_names.get(system, system)


def format_threshold_message(
    metric_name: str, actual_value: float, threshold: float, unit: str = "ms"
) -> str:
    """Format a consistent threshold violation message.

    Args:
        metric_name: Name of the metric (e.g., "Symbol search p95")
        actual_value: The actual measured value
        threshold: The threshold that was exceeded
        unit: Unit of measurement (default: "ms")

    Returns:
        str: Formatted error message
    """
    env_info = ""
    if is_ci_environment():
        env_info = f" on {get_platform_name()} CI"

    return (
        f"{metric_name} ({actual_value:.2f}{unit}) exceeds threshold "
        f"({threshold:.2f}{unit}){env_info}"
    )


# Common threshold definitions for reuse across tests
class CommonThresholds:
    """Common performance thresholds used across tests."""

    # Metrics overhead per call, in MICROSECONDS (#741): MetricsCollector.measure
    # around a no-op, minus the bare no-op.  Calibrated against
    # METRICS_OVERHEAD_BASELINE_US, so a 10x slower decorator (~19us) fails
    # every limit below.
    METRICS_OVERHEAD_BASELINE_US = 1.9
    METRICS_OVERHEAD_US = PerformanceThresholds(
        base=8.0,
        linux_ci=10.0,
        macos_ci=15.0,
        windows_ci=15.0,
    )

    # Symbol search performance.
    # p95 over only ~10 warm samples is effectively the slowest single call, so a single
    # GC/disk hiccup can spike it (~98ms observed locally against the old 100ms base).
    # These tiers carry headroom for that jitter; macOS/Windows runners get a 3x margin.
    # Warm find_symbol, per call, in MILLISECONDS (#773, #385): the minimum over
    # repeated runs of each run's MEDIAN, so a scheduler stall moves nothing.
    # The baseline is the expected cost on each platform (~2 ms measured
    # locally); the limit is 3x it, so a 5x slower find_symbol fails everywhere.
    WARM_FIND_SYMBOL_BASELINE_MS = PerformanceThresholds(
        base=2.5, linux_ci=3.5, macos_ci=6.0, windows_ci=6.0
    )
    WARM_FIND_SYMBOL_MS = PerformanceThresholds(
        base=7.5, linux_ci=10.5, macos_ci=18.0, windows_ci=18.0
    )

    # Goto definition performance
    GOTO_DEFINITION_P95 = PerformanceThresholds(
        base=75.0, linux_ci=112.0, macos_ci=225.0, windows_ci=225.0
    )

    GOTO_DEFINITION_P50 = PerformanceThresholds(
        base=30.0, linux_ci=45.0, macos_ci=90.0, windows_ci=90.0
    )

    # Cache operations
    CACHE_LOOKUP_P99 = PerformanceThresholds(base=1.0, linux_ci=1.5, macos_ci=3.0, windows_ci=3.0)

    CACHE_LOOKUP_P50 = PerformanceThresholds(base=0.1, linux_ci=0.15, macos_ci=0.3, windows_ci=0.3)

    CACHE_INVALIDATION_P95 = PerformanceThresholds(
        base=5.0, linux_ci=7.5, macos_ci=15.0, windows_ci=15.0
    )

    # Concurrent operations
    CONCURRENT_OPS_P95 = PerformanceThresholds(
        base=200.0, linux_ci=300.0, macos_ci=600.0, windows_ci=600.0
    )

    # Burst load handling
    BURST_LOAD_P99 = PerformanceThresholds(
        base=500.0, linux_ci=750.0, macos_ci=1500.0, windows_ci=1500.0
    )

    # Sustained load
    SUSTAINED_LOAD_P95 = PerformanceThresholds(
        base=10.0, linux_ci=15.0, macos_ci=30.0, windows_ci=30.0
    )


def assert_performance_threshold(
    actual_value: float, threshold: PerformanceThresholds, metric_name: str, unit: str = "ms"
) -> None:
    """Assert that a performance metric meets its threshold.

    Args:
        actual_value: The measured value
        threshold: The threshold configuration
        metric_name: Name of the metric for error messages
        unit: Unit of measurement (default: "ms")

    Raises:
        AssertionError: If the threshold is exceeded
    """
    limit = threshold.get_threshold()
    assert actual_value < limit, format_threshold_message(metric_name, actual_value, limit, unit)
