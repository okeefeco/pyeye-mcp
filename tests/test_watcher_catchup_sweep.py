"""A change made while a watcher is starting up is still picked up (#738).

watchdog's ``Observer.start()`` returns before the emitter listens (macOS FSEvents,
Windows ``ReadDirectoryChangesW``), so a change in that window is never delivered.
``ProjectManager`` follows every watcher start with catch-up sweeps that re-stat the
root's ``.py`` files and invalidate what changed since the watcher started.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import pyeye.project_manager as project_manager_module
from pyeye.mcp.operations.resolve import resolve
from pyeye.project_manager import ProjectManager
from tests.test_watcher_invalidation import FakeWatcher, _project
from tests.utils.performance import PerformanceThresholds

#: How long a sweep (or a real observer) may take to make a change visible.
DELIVERY = PerformanceThresholds(
    base=5000.0, linux_ci=10000.0, macos_ci=20000.0, windows_ci=20000.0
)


@pytest.fixture
def fast_sweeps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_manager_module, "CATCHUP_SWEEP_OFFSETS", (0.05, 0.3))
    monkeypatch.setattr(project_manager_module.settings.settings, "watcher_debounce", 0.0)


@pytest.fixture
def silent_watchers(monkeypatch: pytest.MonkeyPatch) -> list[FakeWatcher]:
    """Watchers that start but never deliver an event: the start-up window, forever."""
    FakeWatcher.instances = []
    monkeypatch.setattr(project_manager_module, "CodebaseWatcher", FakeWatcher)
    return FakeWatcher.instances


@pytest.fixture
def manager() -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=10)
    yield m
    m.cleanup_all()


@pytest.fixture
def written(manager: ProjectManager, monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Hold every sweep until the test has made its change; set it after the write (#906).

    A sweep catches a change made between the watcher's start and the sweep.
    Under load the test's own set-up (``get_analyzer``, a cold first
    ``resolve``) can outlast both fast sweeps, so the write lands after the last
    one: a silent watcher then never delivers it, and no wait budget helps.
    Holding the sweeps puts the write inside the window by construction.
    """
    done = threading.Event()
    real = manager._catch_up

    def gated(root: Path) -> None:
        done.wait(timeout=DELIVERY.get_threshold() / 1000)
        real(root)

    # Each sweep's Timer looks ``_catch_up`` up when it is scheduled, in get_analyzer.
    monkeypatch.setattr(manager, "_catch_up", gated)
    return done


def _spy(
    manager: ProjectManager, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[list[str]], threading.Event]:
    calls: list[list[str]] = []
    fired = threading.Event()
    real = manager._on_files_changed

    def spy(root: Path, paths: list[str]) -> None:
        calls.append(paths)
        fired.set()
        real(root, paths)

    monkeypatch.setattr(manager, "_on_files_changed", spy)
    return calls, fired


async def _until_found(name: str, analyzer: Any) -> bool:
    deadline = time.monotonic() + DELIVERY.get_threshold() / 1000
    while time.monotonic() < deadline:
        if (await resolve(name, analyzer))["found"]:
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.usefixtures("fast_sweeps", "silent_watchers")
class TestCatchUpSweep:
    @pytest.mark.asyncio
    # 0.5 s outlasts both fast sweeps: a slow start-up, as on a loaded CI runner (#906).
    @pytest.mark.parametrize("start_up", [0.0, 0.5], ids=["fast", "slow-start-up"])
    async def test_a_change_during_start_up_is_picked_up(
        self, tmp_path: Path, manager: ProjectManager, written: threading.Event, start_up: float
    ) -> None:
        proj = _project(tmp_path / "proj")
        analyzer = manager.get_analyzer(proj.as_posix())
        # A slow set-up builds the index only after both sweeps would have run.
        await asyncio.sleep(start_up)
        assert (await resolve("Gamma", analyzer))["found"] is False

        (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")
        written.set()

        assert await _until_found("Gamma", analyzer), "the catch-up sweep never invalidated"

    @pytest.mark.asyncio
    async def test_a_stub_only_module_written_during_start_up_is_picked_up(
        self, tmp_path: Path, manager: ProjectManager, written: threading.Event
    ) -> None:
        """The sweep reads stubs too: a stub-only module is analysed from its ``.pyi`` (#933)."""
        proj = _project(tmp_path / "proj")
        old = time.time() - 3600  # only the stub can look changed to the sweep
        for py in proj.rglob("*.py"):
            os.utime(py, (old, old))
        analyzer = manager.get_analyzer(proj.as_posix())
        assert (await resolve("Delta", analyzer))["found"] is False

        (proj / "pkg" / "declared.pyi").write_text("class Delta: ...\n")
        written.set()

        assert await _until_found("Delta", analyzer), "the catch-up sweep never saw the stub"

    @pytest.mark.asyncio
    async def test_without_the_sweep_the_window_is_real(
        self,
        tmp_path: Path,
        manager: ProjectManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Control: with no sweeps, a silent watcher leaves the change undelivered."""
        monkeypatch.setattr(project_manager_module, "CATCHUP_SWEEP_OFFSETS", ())
        proj = _project(tmp_path / "proj")
        analyzer = manager.get_analyzer(proj.as_posix())
        assert (await resolve("Gamma", analyzer))["found"] is False

        (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")
        await asyncio.sleep(0.5)

        assert (await resolve("Gamma", analyzer))["found"] is False

    @pytest.mark.asyncio
    async def test_unchanged_files_trigger_nothing(
        self,
        tmp_path: Path,
        manager: ProjectManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        proj = _project(tmp_path / "proj")
        old = time.time() - 3600
        for py in proj.rglob("*.py"):
            os.utime(py, (old, old))
        calls, fired = _spy(manager, monkeypatch)

        manager.get_analyzer(proj.as_posix())
        # Both sweeps (0.05 s and 0.3 s) have run well within this bound.
        fired.wait(timeout=1.5)

        assert calls == []

    @pytest.mark.asyncio
    async def test_excluded_dirs_are_not_swept(
        self,
        tmp_path: Path,
        manager: ProjectManager,
        monkeypatch: pytest.MonkeyPatch,
        written: threading.Event,
    ) -> None:
        proj = _project(tmp_path / "proj")
        old = time.time() - 3600
        for py in proj.rglob("*.py"):
            os.utime(py, (old, old))
        calls, fired = _spy(manager, monkeypatch)

        manager.get_analyzer(proj.as_posix())
        venv = proj / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "site.py").write_text("X = 1\n")
        (proj / "pkg" / "new.py").write_text("Y = 2\n")
        written.set()

        assert fired.wait(timeout=DELIVERY.get_threshold() / 1000)
        swept = {Path(p).name for batch in calls for p in batch}
        assert "new.py" in swept and "site.py" not in swept

    def test_cleanup_cancels_pending_sweeps(
        self,
        tmp_path: Path,
        manager: ProjectManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(project_manager_module, "CATCHUP_SWEEP_OFFSETS", (0.4, 0.6))
        proj = _project(tmp_path / "proj")
        calls, fired = _spy(manager, monkeypatch)

        manager.get_analyzer(proj.as_posix())
        (proj / "pkg" / "late.py").write_text("Z = 3\n")
        manager.cleanup_all()

        assert manager._catchup_timers == {}
        assert not fired.wait(timeout=1.0)
        assert calls == []


class TestRealObserverStartUp:
    @pytest.mark.real_watcher
    @pytest.mark.asyncio
    async def test_a_file_written_immediately_after_start_is_delivered(
        self, tmp_path: Path
    ) -> None:
        """The #715 race without #736's probe handshake: the sweep closes it on every OS."""
        m = ProjectManager(max_projects=10)
        try:
            proj = _project(tmp_path / "proj")
            analyzer = m.get_analyzer(proj.as_posix())
            (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")

            assert await _until_found("Gamma", analyzer), "the created file was never picked up"
        finally:
            m.cleanup_all()
