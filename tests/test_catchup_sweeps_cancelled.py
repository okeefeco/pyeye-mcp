"""No ProjectManager catch-up sweep outlives its test (#1019 review).

A sweep left over from an earlier test ran the restricted-dir prune on a
background thread during a later test and raced its patched home. The autouse
fixture in ``conftest.py`` cancels them; this pins the helper it calls.
"""

from __future__ import annotations

import threading
from pathlib import Path

from pyeye.project_manager import ProjectManager
from tests.conftest import cancel_catchup_sweeps


def _sweeps() -> list[threading.Timer]:
    return [
        t
        for t in threading.enumerate()
        if isinstance(t, threading.Timer)
        and getattr(t.function, "__func__", None) is ProjectManager._catch_up
    ]


def test_a_pending_sweep_is_cancelled(tmp_path: Path) -> None:
    manager = ProjectManager(max_projects=1)
    try:
        timer = threading.Timer(60, manager._catch_up, args=(tmp_path,))
        timer.daemon = True
        timer.start()
        assert timer in _sweeps()

        cancel_catchup_sweeps(timeout=5)

        assert not timer.is_alive()
        assert timer not in _sweeps()
    finally:
        manager.cleanup_all()


def test_other_timers_are_left_alone() -> None:
    fired = threading.Event()
    other = threading.Timer(0.05, fired.set)
    other.start()

    cancel_catchup_sweeps(timeout=5)
    other.join(timeout=5)

    assert fired.is_set()
