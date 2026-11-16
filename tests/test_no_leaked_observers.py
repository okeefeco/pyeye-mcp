"""The session-end guard sees a real observer that a test leaves running (#807)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.project_manager import ProjectManager
from tests.utils.watchers import live_observers


@pytest.mark.real_watcher
def test_a_running_real_observer_is_reported_until_it_is_stopped(tmp_path: Path) -> None:
    before = set(live_observers())
    (tmp_path / "m.py").write_text("X = 1\n")
    manager = ProjectManager()
    try:
        manager.get_analyzer(tmp_path.as_posix())
        started = set(live_observers()) - before
        assert started, "a real_watcher test's ProjectManager should start a real observer"
    finally:
        manager.cleanup_all()
    assert not (set(live_observers()) & started), "cleanup_all() left an observer running"


def test_the_inert_observer_is_not_a_live_observer(tmp_path: Path) -> None:
    before = set(live_observers())
    (tmp_path / "m.py").write_text("X = 1\n")
    manager = ProjectManager()
    try:
        manager.get_analyzer(tmp_path.as_posix())
        assert set(live_observers()) == before
    finally:
        manager.cleanup_all()
