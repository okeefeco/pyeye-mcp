"""``warm_median_ms``: one number per timing test that a loaded machine can't move (#1017).

A single wall-clock sample fails a local base whenever another suite runs on
the same box. The helper times *calls* awaits per run, takes each run's median
(a few stalled calls can't move it), then the minimum over *repeats* runs (a run
slowed throughout can't either). It was the benchmarks' private
``_warm_median_ms`` (#773); the plugin timing tests share it now.
"""

from __future__ import annotations

import pytest

from tests.utils import performance


class _Clock:
    """A fake ``perf_counter`` whose call *k* takes ``durations_ms[k]``."""

    def __init__(self, durations_ms: list[float]) -> None:
        self._durations = iter(durations_ms)
        self._now = 0.0
        self._started = False

    def __call__(self) -> float:
        if self._started:  # the end of a call: advance by its duration
            self._now += next(self._durations) / 1000
        self._started = not self._started
        return self._now


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_a_stalled_call_and_a_slow_run_dont_move_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # run 1: one 900 ms stall among 10s; run 2: everything slowed to 50
    clock = _Clock([10, 900, 10, 50, 50, 50])
    monkeypatch.setattr(performance.time, "perf_counter", clock)

    assert await performance.warm_median_ms(_noop, calls=3, repeats=2) == pytest.approx(10)


@pytest.mark.asyncio
async def test_it_awaits_every_call() -> None:
    seen = []

    async def call() -> None:
        seen.append(1)

    await performance.warm_median_ms(call, calls=4, repeats=3)
    assert len(seen) == 12


def test_the_benchmarks_use_the_shared_helper() -> None:
    from tests.performance.benchmarks import test_performance_regression as bench

    assert not hasattr(bench, "_warm_median_ms")
