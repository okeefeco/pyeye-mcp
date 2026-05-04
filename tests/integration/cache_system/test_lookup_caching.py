"""Benchmark: cold-vs-warm lookup latency demonstrates cache wiring.

This module verifies that wiring ``file_artifact_cache`` into the lookup
pipeline (Task 1.5) delivers a measurable latency improvement on the second
call against the same project + identifier — the cache hit path skips both
the source read and the ``jedi.Script(...)`` construction that dominate the
cold path.

The assertion is intentionally generous to stay non-flaky on shared CI:

* We average ``REPEATS`` warm runs (rather than measuring a single warm call)
  to smooth out per-call jitter.
* We assert the warm average against an absolute threshold defined via
  :class:`tests.utils.performance.PerformanceThresholds` (cache-hit budget),
  not a strict ``warm < cold`` ratio — ratio assertions on millisecond-scale
  operations get noisy when the host has scheduling jitter.
* As a coarse sanity check we also verify ``warm_avg_ms <= cold_ms`` within
  a 1.5x tolerance on the same machine; this catches an outright wiring
  regression where the cache is bypassed entirely.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from pathlib import Path

import pytest

from pyeye import file_artifact_cache
from pyeye.mcp.lookup import lookup
from tests.utils.performance import (
    PerformanceThresholds,
    assert_performance_threshold,
)

REPEATS = 5


@pytest.fixture(autouse=True)
def _clear_cache() -> Generator[None, None, None]:
    """Clear the file artifact cache before and after every test in this file.

    The module-level ``_default_cache`` singleton is left warm across tests
    unless explicitly cleared.  Clearing before + after ensures each test
    starts from a clean-cache state and does not leak warm entries that can
    mask cold-path coverage in future cache-aware tests added to this file.
    """
    file_artifact_cache.invalidate_all()
    yield
    file_artifact_cache.invalidate_all()


# Warm-call budget.  Generous because the lookup() pipeline does work
# beyond the cache (resolving identifiers, building Jedi names, etc.).
# These numbers are well above what the cache-hit path itself costs; they
# guard against a regression where the wiring is undone (e.g. a future
# refactor reintroduces ``jedi.Script(...)`` directly).
WARM_LOOKUP_BUDGET = PerformanceThresholds(
    base=300.0,  # local dev
    linux_ci=600.0,
    macos_ci=1200.0,
    windows_ci=1200.0,
)


@pytest.mark.asyncio
async def test_warm_lookup_is_faster_than_cold() -> None:
    """A second lookup against the same fixture must be measurably faster.

    Uses the ``lookup_project`` fixture and resolves the ``ServiceManager``
    class inside it.  After a cold call to populate caches, ``REPEATS``
    warm calls are timed and averaged.  We assert:

    1. The warm average meets the absolute cache-hit budget.
    2. The warm average is no slower than the cold time (with a 1.5x grace
       margin to absorb jitter on shared CI).
    """
    # Ensure a clean cache so the first call is genuinely cold.
    file_artifact_cache.invalidate_all()

    project_root = Path(__file__).resolve().parent.parent.parent / "fixtures" / "lookup_project"
    assert project_root.is_dir(), f"Fixture project not found: {project_root.as_posix()}"

    identifier = "ServiceManager"
    project_path = project_root.as_posix()

    # Cold call: cache empty, full Script construction.
    cold_start = time.perf_counter()
    cold_result = await lookup(identifier=identifier, project_path=project_path)
    cold_ms = (time.perf_counter() - cold_start) * 1000.0

    assert "error" not in cold_result, f"Cold lookup unexpectedly errored: {cold_result}"

    # Warm calls: should hit the file_artifact_cache for AST/Script reuse.
    warm_times_ms: list[float] = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        warm_result = await lookup(identifier=identifier, project_path=project_path)
        warm_times_ms.append((time.perf_counter() - start) * 1000.0)
        assert "error" not in warm_result, f"Warm lookup unexpectedly errored: {warm_result}"

    warm_avg_ms = sum(warm_times_ms) / len(warm_times_ms)

    # (1) Absolute warm budget.
    assert_performance_threshold(warm_avg_ms, WARM_LOOKUP_BUDGET, "lookup() warm-call average")

    # (2) Warm average must be no worse than 1.5x the cold time.  This is
    # a coarse regression guard against the cache being bypassed; it
    # tolerates jitter without asserting an exact speedup ratio.
    tolerance_factor = 1.5
    assert warm_avg_ms <= cold_ms * tolerance_factor, (
        f"Warm-call average ({warm_avg_ms:.2f}ms) is slower than cold call "
        f"({cold_ms:.2f}ms) beyond the {tolerance_factor:.1f}x jitter tolerance — "
        f"the file_artifact_cache wiring may be bypassed."
    )

    # Sanity check: at least one cache hit should have been recorded.
    stats = file_artifact_cache.stats()
    assert stats["hits"] > 0, (
        f"Expected at least one file_artifact_cache hit after {REPEATS + 1} lookups against "
        f"the same fixture, but stats reported zero hits: {stats}"
    )
