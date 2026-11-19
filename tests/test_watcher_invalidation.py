"""File changes reach every cache of the project that changed, and only that project (#617).

Before this fix, in a default setup (no ``.pyeye.json``):

1. ``get_analyzer`` started no watcher, so nothing noticed code changes.
2. The watcher handled only ``FileModifiedEvent``: created, deleted and moved
   files were ignored. Only ``changes[0]`` of a debounced batch was passed on.
3. Nothing cleared the analyzer's ``scoped_cache``, so ``get_project_files``
   kept serving a stale file list for 300 s.
4. ``GranularCache.invalidate_file`` called ``project_graph.invalidate()`` with
   no key, clearing every project's name index. (#628 deleted GranularCache.)

Event tests drive ``CodebaseWatcher`` handlers directly and invalidation tests
drive ``ProjectManager._on_files_changed``, so they need no sleeps. Four tests
run a real watchdog observer, bounded by a wait derived from the catch-up sweep
schedule (#715): the last sweep is what guarantees delivery at start-up. Two of
them disable the sweeps to check post-live delivery, alone and in a burst
(#788; no longer xfail on macOS after 264 clean macOS legs following #819).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import warnings
from collections.abc import Iterator
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest
from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

import pyeye.project_manager as project_manager_module
from pyeye.analyzers import project_graph
from pyeye.cache import CodebaseWatcher
from pyeye.mcp.operations.resolve import resolve
from pyeye.project_manager import ProjectManager

# ---------------------------------------------------------------------------
# CodebaseWatcher: every event kind, every path in the batch
# ---------------------------------------------------------------------------


@pytest.fixture
def recorded() -> list[list[str]]:
    return []


@pytest.fixture
def watcher(tmp_path: Path, recorded: list[list[str]]) -> Iterator[CodebaseWatcher]:
    w = CodebaseWatcher(tmp_path.as_posix(), recorded.append)
    yield w
    w.stop()  # cancels the debounce timer the handlers start


def _p(root: Path, name: str) -> str:
    return (root / name).as_posix()


class TestWatcherEvents:
    def test_every_file_event_kind_reaches_the_callback(
        self, tmp_path: Path, watcher: CodebaseWatcher, recorded: list[list[str]]
    ) -> None:
        watcher.on_created(FileCreatedEvent(_p(tmp_path, "new.py")))
        watcher.on_deleted(FileDeletedEvent(_p(tmp_path, "gone.py")))
        watcher.on_moved(FileMovedEvent(_p(tmp_path, "old.py"), _p(tmp_path, "renamed.py")))
        watcher.on_modified(FileModifiedEvent(_p(tmp_path, "edited.py")))

        watcher._process_changes()

        assert recorded == [
            sorted(
                _p(tmp_path, n) for n in ("new.py", "gone.py", "old.py", "renamed.py", "edited.py")
            )
        ]

    def test_whole_batch_is_passed_on(
        self, tmp_path: Path, watcher: CodebaseWatcher, recorded: list[list[str]]
    ) -> None:
        for name in ("a.py", "b.py", "c.py"):
            watcher.on_modified(FileModifiedEvent(_p(tmp_path, name)))

        watcher._process_changes()

        assert recorded == [[_p(tmp_path, n) for n in ("a.py", "b.py", "c.py")]]

    def test_move_out_of_python_still_counts_the_source(
        self, tmp_path: Path, watcher: CodebaseWatcher, recorded: list[list[str]]
    ) -> None:
        watcher.on_moved(FileMovedEvent(_p(tmp_path, "mod.py"), _p(tmp_path, "mod.py.bak")))

        watcher._process_changes()

        assert recorded == [[_p(tmp_path, "mod.py")]]

    def test_directory_structure_events_count_but_directory_modified_does_not(
        self, tmp_path: Path, watcher: CodebaseWatcher, recorded: list[list[str]]
    ) -> None:
        # A directory created, deleted or moved adds or removes whole modules. A
        # directory "modified" event only echoes a change to a file inside it.
        watcher.on_modified(DirModifiedEvent(_p(tmp_path, "pkg")))
        watcher.on_created(DirCreatedEvent(_p(tmp_path, "newpkg")))
        watcher.on_deleted(DirDeletedEvent(_p(tmp_path, "oldpkg")))
        watcher.on_moved(DirMovedEvent(_p(tmp_path, "a"), _p(tmp_path, "b")))

        watcher._process_changes()

        assert recorded == [sorted(_p(tmp_path, n) for n in ("newpkg", "oldpkg", "a", "b"))]

    def test_non_python_and_ignored_dirs_are_skipped(
        self, tmp_path: Path, watcher: CodebaseWatcher, recorded: list[list[str]]
    ) -> None:
        watcher.on_created(FileCreatedEvent(_p(tmp_path, "notes.txt")))
        watcher.on_modified(FileModifiedEvent(_p(tmp_path, ".venv/lib/x.py")))
        watcher.on_created(DirCreatedEvent(_p(tmp_path, "__pycache__")))

        watcher._process_changes()

        assert recorded == []


# ---------------------------------------------------------------------------
# ProjectManager: one watcher per analyzer root, deduplicated
# ---------------------------------------------------------------------------


class FakeWatcher:
    """Stands in for CodebaseWatcher so wiring tests start no OS observers."""

    instances: list[FakeWatcher] = []

    def __init__(self, project_path: str, on_change_callback: Any = None) -> None:
        self.project_path = Path(project_path)
        self.on_change_callback = on_change_callback
        self.started = False
        self.stopped = False
        FakeWatcher.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def fake_watchers(monkeypatch: pytest.MonkeyPatch) -> list[FakeWatcher]:
    FakeWatcher.instances = []
    monkeypatch.setattr(project_manager_module, "CodebaseWatcher", FakeWatcher)
    return FakeWatcher.instances


@pytest.fixture
def manager() -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=10)
    yield m
    m.cleanup_all()


def _project(root: Path, config: str | None = None, files: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in (
        files or {"pkg/__init__.py": "", "pkg/mod.py": "class Alpha:\n    pass\n"}
    ).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if config is not None:
        (root / ".pyeye.json").write_text(config)
    return root


def _watched(fakes: list[FakeWatcher]) -> list[Path]:
    return sorted(w.project_path.resolve() for w in fakes if w.started and not w.stopped)


class TestEveryAnalyzerIsWatched:
    def test_no_config_project_gets_a_watcher(
        self, tmp_path: Path, manager: ProjectManager, fake_watchers: list[FakeWatcher]
    ) -> None:
        proj = _project(tmp_path / "proj")

        manager.get_analyzer(proj.as_posix())

        assert _watched(fake_watchers) == [proj.resolve()]

    def test_package_namespace_and_standalone_roots_are_watched(
        self, tmp_path: Path, manager: ProjectManager, fake_watchers: list[FakeWatcher]
    ) -> None:
        lib = _project(tmp_path / "lib")
        ns = _project(tmp_path / "nsrepo")
        scripts = tmp_path / "proj" / "scripts"
        scripts.mkdir(parents=True)
        proj = _project(
            tmp_path / "proj",
            config=json.dumps(
                {
                    "packages": [lib.as_posix()],
                    "namespaces": {"acme": [ns.as_posix()]},
                    "standalone": {"dirs": ["scripts"]},
                }
            ),
        )

        manager.get_analyzer(proj.as_posix())

        assert _watched(fake_watchers) == sorted(
            [proj.resolve(), lib.resolve(), ns.resolve(), scripts.resolve()]
        )

    def test_shared_root_gets_one_watcher_and_outlives_one_user(
        self, tmp_path: Path, manager: ProjectManager, fake_watchers: list[FakeWatcher]
    ) -> None:
        shared = _project(tmp_path / "shared")
        config = json.dumps({"packages": [shared.as_posix()]})
        a = _project(tmp_path / "a", config=config)
        b = _project(tmp_path / "b", config=config)

        manager.get_analyzer(a.as_posix())
        manager.get_analyzer(b.as_posix())

        shared_watchers = [w for w in fake_watchers if w.project_path.resolve() == shared.resolve()]
        assert len(shared_watchers) == 1
        assert _watched(fake_watchers) == sorted([a.resolve(), b.resolve(), shared.resolve()])

        manager._cleanup_project(a.resolve())
        assert _watched(fake_watchers) == sorted([b.resolve(), shared.resolve()])

        manager._cleanup_project(b.resolve())
        assert _watched(fake_watchers) == []

    def test_repeated_get_analyzer_starts_no_extra_watchers(
        self, tmp_path: Path, manager: ProjectManager, fake_watchers: list[FakeWatcher]
    ) -> None:
        proj = _project(tmp_path / "proj")

        manager.get_analyzer(proj.as_posix())
        manager.invalidate_analyzer(proj.as_posix())
        manager.get_analyzer(proj.as_posix())

        assert len(fake_watchers) == 1

    def test_cleanup_all_stops_watchers_of_analyzer_only_projects(
        self, tmp_path: Path, fake_watchers: list[FakeWatcher]
    ) -> None:
        m = ProjectManager(max_projects=10)
        m.get_analyzer(_project(tmp_path / "proj").as_posix())

        m.cleanup_all()

        assert _watched(fake_watchers) == []

    def test_the_watcher_callback_is_wired_to_on_files_changed(
        self,
        tmp_path: Path,
        manager: ProjectManager,
        fake_watchers: list[FakeWatcher],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        proj = _project(tmp_path / "proj")
        manager.get_analyzer(proj.as_posix())
        calls: list[tuple[Path, list[str]]] = []
        monkeypatch.setattr(manager, "_on_files_changed", lambda r, p: calls.append((r, p)))

        fake_watchers[0].on_change_callback([(proj / "x.py").as_posix()])

        assert calls == [(proj.resolve(), [(proj / "x.py").as_posix()])]


# ---------------------------------------------------------------------------
# ProjectManager._on_files_changed: invalidate everything, for that project only
# ---------------------------------------------------------------------------


def _assert_indexed(*roots: Path) -> None:
    """Every project in *roots* has a name index, and no other project does (#1001).

    The invalidation checks below are only meaningful when the builds happened,
    and the autouse ``_cold_project_graph`` fixture means nothing else is there.
    """
    keys = set(project_graph._name_indices)
    expected = {project_graph._normalize(root.as_posix()) for root in roots}
    assert keys == expected, f"name indices before the change: {sorted(keys)}"


class TestPerProjectInvalidation:
    @pytest.mark.usefixtures("fake_watchers")
    async def test_scoped_cache_sees_a_new_file_before_the_ttl(
        self, tmp_path: Path, manager: ProjectManager
    ) -> None:
        proj = _project(tmp_path / "proj")
        analyzer = manager.get_analyzer(proj.as_posix())
        before = await analyzer.get_project_files("*.py", "main")
        new = proj / "pkg" / "added.py"
        new.write_text("X = 1\n")
        # Guard: the file list really is cached, so the next step proves invalidation.
        assert await analyzer.get_project_files("*.py", "main") == before

        manager._on_files_changed(proj.resolve(), [new.as_posix()])

        assert new in await analyzer.get_project_files("*.py", "main")

    @pytest.mark.usefixtures("fake_watchers")
    async def test_only_the_changed_projects_name_index_is_dropped(
        self, tmp_path: Path, manager: ProjectManager
    ) -> None:
        a = _project(tmp_path / "a")
        b = _project(tmp_path / "b")
        for root in (a, b):
            await manager.get_analyzer(root.as_posix()).find_symbol("Alpha")
        _assert_indexed(a, b)
        index_b = project_graph._name_indices[project_graph._normalize(b.as_posix())]

        manager._on_files_changed(a.resolve(), [(a / "pkg" / "mod.py").as_posix()])

        keys = set(project_graph._name_indices)
        assert project_graph._normalize(a.as_posix()) not in keys
        assert project_graph._name_indices[project_graph._normalize(b.as_posix())] is index_b

    @pytest.mark.usefixtures("fake_watchers")
    async def test_a_shared_package_change_invalidates_every_user(
        self, tmp_path: Path, manager: ProjectManager
    ) -> None:
        shared = _project(tmp_path / "shared")
        config = json.dumps({"packages": [shared.as_posix()]})
        a = _project(tmp_path / "a", config=config)
        b = _project(tmp_path / "b", config=config)
        other = _project(tmp_path / "other")
        for root in (a, b, other):
            await manager.get_analyzer(root.as_posix()).find_symbol("Alpha")
        # Without this, a build that didn't happen would pass both `not in` checks (#1001).
        _assert_indexed(a, b, other)

        manager._on_files_changed(shared.resolve(), [(shared / "pkg" / "mod.py").as_posix()])

        keys = set(project_graph._name_indices)
        assert project_graph._normalize(a.as_posix()) not in keys
        assert project_graph._normalize(b.as_posix()) not in keys
        assert project_graph._normalize(other.as_posix()) in keys


class TestIssueRepro:
    async def test_new_class_in_existing_file_resolves_by_bare_name(
        self, tmp_path: Path, manager: ProjectManager, fake_watchers: list[FakeWatcher]
    ) -> None:
        """#617 repro: in a project with no config, add ``class Beta`` to an existing file."""
        proj = _project(tmp_path / "proj")
        analyzer = manager.get_analyzer(proj.as_posix())
        assert (await resolve("Alpha", analyzer))["found"] is True  # index built
        mod = proj / "pkg" / "mod.py"
        mod.write_text(mod.read_text() + "\n\nclass Beta:\n    pass\n")

        # The watcher callback, as the debounced observer would call it.
        fake_watchers[0].on_change_callback([mod.as_posix()])

        assert (await resolve("Beta", analyzer))["found"] is True


# ---------------------------------------------------------------------------
# One end-to-end run with a real observer
# ---------------------------------------------------------------------------


#: Floor for how long the real-observer tests wait for a created file (#715).
SWEEP_WAIT_FLOOR_S = 20.0

#: Seconds between file A's write and extra.py's create in the burst test (#788):
#: well inside the watcher's debounce (0.5 s by default) and FSEvents' own
#: latency window, as in the post-live test's timing before #798.
BURST_DELAY_S = 0.1


def _last_sweep_s() -> float:
    """Seconds after a watcher starts at which its LAST catch-up sweep fires (#738)."""
    debounce = project_manager_module.settings.settings.watcher_debounce
    return float(debounce + max(project_manager_module.CATCHUP_SWEEP_OFFSETS))


def _sweep_wait_s() -> float:
    """How long to wait for a created file: 3x the last sweep, 20 s floor (#715).

    Derived from the sweep schedule, so a debounce or offset change can't shrink
    the margin past the sweep that guarantees delivery.
    """
    return max(SWEEP_WAIT_FLOOR_S, 3 * _last_sweep_s())


class FSEventsDiagnostic(UserWarning):
    """A real-observer test's failure diagnostics, emitted as a warning (#788).

    pytest's warnings summary lists every warning with the test id, so a
    real-observer failure leaves its evidence in the CI log even when the
    assertion message is cut short: grep for ``FSEventsDiagnostic``. (These tests
    were darwin-xfail until #788's evidence watch, and pytest prints neither the
    assertion message nor the captured output of an XFAIL.) A dedicated class, so it can't meet the
    ``error::DeprecationWarning:pyeye`` filter or be confused with other warnings.
    """


def _diagnose(message: str) -> None:
    """Emit *message* as an :class:`FSEventsDiagnostic`, just before the assert fails."""
    warnings.warn(FSEventsDiagnostic(message), stacklevel=2)


def _batches(delivered: list[list[str]], limit: int = 8) -> str:
    """*delivered*, truncated to *limit* batches, each path shortened to its file name."""
    shown = [[PureWindowsPath(p).name for p in batch] for batch in delivered[:limit]]
    more = f" (+{len(delivered) - limit} more)" if len(delivered) > limit else ""
    return f"{shown}{more}"


async def _wait_until_observer_is_live(
    watcher: CodebaseWatcher, probe: Path, until: float, stats: dict[str, Any] | None = None
) -> bool:
    """Wait, until monotonic time *until*, for *watcher*'s observer to deliver (#715).

    ``Observer.start()`` returns before the emitter thread is live. On macOS that
    thread first snapshots the tree and only then starts the FSEvents stream,
    which reports events from that moment on, and watchdog drops a "created"
    event for a file already in the starting snapshot as historic. A file
    written in that window is never delivered. watchdog has no ready signal,
    so write a probe until one change comes through (event-driven, never a
    fixed sleep). Best-effort: returns whether it came up in time, because the
    catch-up sweep, not this handshake, is what guarantees delivery.
    If *stats* is given, it receives the probe count and handshake time (#788).
    """
    before = watcher.last_change
    begun = time.monotonic()
    n = 0
    live = True
    while watcher.last_change == before:
        if time.monotonic() >= until:
            live = False
            break
        probe.write_text(f"# probe {n}\n")
        n += 1
        await asyncio.sleep(0.2)
    if stats is not None:
        stats.update(probes=n, handshake_s=time.monotonic() - begun)
    return live


class TestRealObserver:
    @pytest.mark.real_watcher
    async def test_created_file_reaches_the_name_index(self, tmp_path: Path) -> None:
        m = ProjectManager(max_projects=10)
        try:
            proj = _project(tmp_path / "proj")
            started = time.monotonic()  # no later than the watcher's own start
            analyzer = m.get_analyzer(proj.as_posix())
            watcher = m.watchers[proj.resolve()]
            # Record every delivered batch, so a failure says whether the event was
            # dropped or delivered-but-not-visible (#715 diagnostics).
            delivered: list[list[str]] = []
            deliver = watcher.on_change_callback

            def recording(paths: list[str]) -> None:
                delivered.append(list(paths))
                deliver(paths)

            watcher.on_change_callback = recording
            # The LAST catch-up sweep (#738) is what guarantees delivery: it re-stats
            # the tree and invalidates every file changed since start-up, whether or
            # not the emitter delivered its event (macOS FSEvents can drop a create
            # made while it comes up, #715). So extra.py must be written before that
            # sweep fires: the handshake is bounded to a second before it.
            write_by = started + _last_sweep_s() - 1.0
            live = await _wait_until_observer_is_live(watcher, proj / "pkg" / "_probe.py", write_by)
            assert (await resolve("Gamma", analyzer))["found"] is False
            (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")
            written_after = time.monotonic() - started

            deadline = time.monotonic() + _sweep_wait_s()
            found = False
            while time.monotonic() < deadline:
                if (await resolve("Gamma", analyzer))["found"]:
                    found = True
                    break
                await asyncio.sleep(0.1)

            got_extra = any(p.endswith("extra.py") for batch in delivered for p in batch)
            assert found, (
                "the watcher never delivered the created file: "
                f"extra.py {'WAS' if got_extra else 'was NOT'} in a delivered batch; "
                f"watch root={watcher.project_path.as_posix()}, "
                f"analyzer root={analyzer.project_path.as_posix()}, observer live={live}, "
                f"written {written_after:.2f}s after start (last sweep at "
                f"{_last_sweep_s():.2f}s), batches={delivered}"
            )
        finally:
            m.cleanup_all()

    @pytest.mark.real_watcher
    async def test_a_create_after_the_watcher_is_live_is_delivered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The original #715 scenario: once the observer is live, the EMITTER delivers.

        The catch-up sweeps are disabled, so a drop can't be masked: only a
        delivered event can make Gamma visible. On macOS CI this was missed with
        the observer already live (#788). The likely cause was #817's race, fixed by
        #819; the darwin xfail was removed after 264 clean macOS legs.
        """
        monkeypatch.setattr(project_manager_module, "CATCHUP_SWEEP_OFFSETS", ())
        m = ProjectManager(max_projects=10)
        try:
            proj = _project(tmp_path / "proj")
            analyzer = m.get_analyzer(proj.as_posix())
            watcher = m.watchers[proj.resolve()]
            # Record every delivered batch, so a failure says whether the event was
            # dropped or delivered-but-not-visible (#756 diagnostics).
            delivered: list[list[str]] = []
            deliver = watcher.on_change_callback

            def recording(paths: list[str]) -> None:
                delivered.append(list(paths))
                deliver(paths)

            watcher.on_change_callback = recording
            hs: dict[str, Any] = {}
            live = await _wait_until_observer_is_live(
                watcher, proj / "pkg" / "_probe.py", time.monotonic() + SWEEP_WAIT_FLOOR_S, hs
            )
            handshake = f"handshake {hs['handshake_s']:.2f}s, {hs['probes']} probe(s)"
            if not live:
                _diagnose(
                    f"#788 deadline=handshake: the observer never came up; {handshake}; "
                    f"batches={_batches(delivered)}"
                )
            assert live, "the observer never came up"
            # Wait for the probe's BATCH, not just its event: the handshake returns
            # on the event, a debounce before the batch is delivered, and that batch
            # invalidates the whole project. Written in between, extra.py would be
            # seen even if its own event were dropped, so a drop couldn't fail the
            # test (#788).
            settle_by = time.monotonic() + SWEEP_WAIT_FLOOR_S
            while not delivered and time.monotonic() < settle_by:
                await asyncio.sleep(0.05)
            if not delivered:
                _diagnose(
                    f"#788 deadline=probe-batch: the probe's event was seen but its batch "
                    f"never delivered; {handshake}"
                )
            assert delivered, "the probe's batch was never delivered"
            assert (await resolve("Gamma", analyzer))["found"] is False
            (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")

            deadline = time.monotonic() + SWEEP_WAIT_FLOOR_S
            found = False
            while time.monotonic() < deadline:
                if (await resolve("Gamma", analyzer))["found"]:
                    found = True
                    break
                await asyncio.sleep(0.1)

            got_extra = any(p.endswith("extra.py") for batch in delivered for p in batch)
            if not found:
                _diagnose(
                    "#788 deadline=post-write: "
                    f"{'delivered but not visible' if got_extra else 'dropped'} "
                    f"(extra.py {'WAS' if got_extra else 'was NOT'} in a delivered batch); "
                    f"{handshake}; waited {SWEEP_WAIT_FLOOR_S:.0f}s after the write; "
                    f"batches={_batches(delivered)}"
                )
            assert found, (
                "a create after the observer was live was missed: "
                f"extra.py {'WAS' if got_extra else 'was NOT'} in a delivered batch "
                f"({'delivered but not visible' if got_extra else 'dropped'}); "
                f"watch root={watcher.project_path.as_posix()}, "
                f"analyzer root={analyzer.project_path.as_posix()}, batches={delivered}"
            )
        finally:
            m.cleanup_all()

    @pytest.mark.real_watcher
    async def test_a_create_in_a_burst_is_delivered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A create BURST_DELAY_S after another change in the same dir is delivered (#788).

        The timing the post-live test had before #798: 3 of 24 macOS legs missed
        it, against 0 of 74 once the create came only after the earlier batch.
        Delivery and visibility are asserted separately, because file A's batch
        invalidates the whole project and lands after extra.py is written: it
        would make Gamma visible even if extra.py's own event were dropped.
        """
        monkeypatch.setattr(project_manager_module, "CATCHUP_SWEEP_OFFSETS", ())
        m = ProjectManager(max_projects=10)
        try:
            proj = _project(tmp_path / "proj")
            analyzer = m.get_analyzer(proj.as_posix())
            watcher = m.watchers[proj.resolve()]
            delivered: list[list[str]] = []
            deliver = watcher.on_change_callback

            def recording(paths: list[str]) -> None:
                delivered.append(list(paths))
                deliver(paths)

            watcher.on_change_callback = recording
            hs: dict[str, Any] = {}
            live = await _wait_until_observer_is_live(
                watcher, proj / "pkg" / "_probe.py", time.monotonic() + SWEEP_WAIT_FLOOR_S, hs
            )
            handshake = f"handshake {hs['handshake_s']:.2f}s, {hs['probes']} probe(s)"
            if not live:
                _diagnose(f"#788 burst deadline=handshake: never came up; {handshake}")
            assert live, "the observer never came up"
            # Settle first: the burst must not ride on the probe's pending batch.
            settle_by = time.monotonic() + SWEEP_WAIT_FLOOR_S
            while not delivered and time.monotonic() < settle_by:
                await asyncio.sleep(0.05)
            if not delivered:
                _diagnose(f"#788 burst deadline=probe-batch: never delivered; {handshake}")
            assert delivered, "the probe's batch was never delivered"
            settled = len(delivered)
            assert (await resolve("Gamma", analyzer))["found"] is False

            # The burst: file A, then extra.py BURST_DELAY_S later, same directory.
            (proj / "pkg" / "burst_a.py").write_text("A = 1\n")
            a_at = time.monotonic()
            await asyncio.sleep(BURST_DELAY_S)
            (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")
            gap = time.monotonic() - a_at

            def in_burst(name: str) -> bool:
                return any(p.endswith(name) for batch in delivered[settled:] for p in batch)

            deadline = time.monotonic() + SWEEP_WAIT_FLOOR_S
            got_extra = found = False
            while time.monotonic() < deadline and not (got_extra and found):
                got_extra = in_burst("extra.py")
                found = bool((await resolve("Gamma", analyzer))["found"])
                await asyncio.sleep(0.1)

            if not (got_extra and found):
                if not got_extra:
                    verdict = "dropped" + (
                        " (Gamma visible anyway, via file A's batch)" if found else ""
                    )
                else:
                    verdict = "delivered but not visible"
                _diagnose(
                    f"#788 burst deadline=post-write: {verdict}; burst_a.py "
                    f"{'WAS' if in_burst('burst_a.py') else 'was NOT'} delivered; "
                    f"gap {gap:.3f}s (BURST_DELAY_S={BURST_DELAY_S}); {handshake}; "
                    f"batches={_batches(delivered)}"
                )
            assert got_extra, f"extra.py's create was never delivered: {delivered[settled:]}"
            assert found, f"extra.py was delivered but Gamma never resolved: {delivered}"
        finally:
            m.cleanup_all()

    @pytest.mark.real_watcher
    async def test_a_dropped_create_is_caught_by_the_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#715's failure mode on every OS: the emitter drops the create, a sweep delivers it.

        A real observer at the real sweep schedule, with delivery disabled, so no
        event ever reaches a batch: only the catch-up sweep can make Gamma visible.
        """
        monkeypatch.setattr(CodebaseWatcher, "_schedule", lambda _self: None)
        m = ProjectManager(max_projects=10)
        try:
            proj = _project(tmp_path / "proj")
            analyzer = m.get_analyzer(proj.as_posix())
            watcher = m.watchers[proj.resolve()]
            delivered: list[list[str]] = []
            deliver = watcher.on_change_callback

            def recording(paths: list[str]) -> None:
                delivered.append(list(paths))
                deliver(paths)

            watcher.on_change_callback = recording
            assert (await resolve("Gamma", analyzer))["found"] is False
            (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")

            deadline = time.monotonic() + _sweep_wait_s()
            found = False
            while time.monotonic() < deadline:
                if (await resolve("Gamma", analyzer))["found"]:
                    found = True
                    break
                await asyncio.sleep(0.1)

            assert found, "no catch-up sweep picked up the dropped create"
            assert delivered == [], "an event was delivered: delivery wasn't disabled"
        finally:
            m.cleanup_all()


# ---------------------------------------------------------------------------
# Thread safety: invalidation runs on the watchdog thread, next to analysis
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_scoped_cache_get_survives_concurrent_invalidate_all(self) -> None:
        """``get`` checked a key, then indexed it: a clear in between raised KeyError."""
        import threading

        from pyeye.scope_utils import ScopedCache

        cache = ScopedCache(ttl_seconds=300)
        stop = threading.Event()
        errors: list[BaseException] = []

        def clear() -> None:
            while not stop.is_set():
                cache.invalidate_all()

        def use() -> None:
            try:
                for i in range(20000):
                    cache.set(f"k{i % 7}", i, "main")
                    cache.get(f"k{i % 7}", "main")
            except BaseException as e:  # noqa: BLE001 - the failure under test
                errors.append(e)

        clearer = threading.Thread(target=clear)
        clearer.start()
        try:
            use()
        finally:
            stop.set()
            clearer.join()

        assert errors == []

    def test_index_built_across_an_invalidation_is_not_cached(self, tmp_path: Path) -> None:
        """A build that started before a change must not be stored as current."""
        f = tmp_path / "a.py"
        f.write_text("class Old:\n    pass\n")
        key = tmp_path.as_posix()
        project_graph.invalidate(key)

        generation = project_graph.generation(key)
        # The file list was read; now the watcher invalidates before the build stores.
        project_graph.invalidate(key)
        stale = project_graph.get_name_index(key, [f], {f: "a"}, generation=generation)

        assert "Old" in stale  # the caller still gets an answer
        fresh = project_graph.get_name_index(key, [f], {f: "a"})
        assert fresh is not stale  # but it wasn't cached

    def test_on_files_changed_snapshots_watch_users(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Projects registered while a batch is processed must not break the iteration."""
        m = ProjectManager(max_projects=10)
        root = tmp_path.resolve()
        m._watch_users[root] = {root}

        real_invalidate = project_graph.invalidate

        def registering_invalidate(project_key: str | None = None) -> None:
            # Simulate another thread watching the same root mid-batch.
            m._watch_users[root].add(tmp_path / f"other{len(m._watch_users[root])}")
            real_invalidate(project_key)

        monkeypatch.setattr(project_graph, "invalidate", registering_invalidate)

        m._on_files_changed(root, [(tmp_path / "x.py").as_posix()])


class TestWatcherStartFailure:
    def test_analysis_continues_when_a_watcher_cannot_start(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An exhausted inotify limit degrades freshness; it must not break the tools."""

        class FailingWatcher(FakeWatcher):
            def start(self) -> None:
                raise OSError(24, "inotify instance limit reached")

        FakeWatcher.instances = []
        monkeypatch.setattr(project_manager_module, "CodebaseWatcher", FailingWatcher)
        m = ProjectManager(max_projects=10)
        proj = _project(tmp_path / "proj")

        analyzer = m.get_analyzer(proj.as_posix())

        assert analyzer is not None
        assert m.watchers == {}
        assert any(
            "inotify instance limit reached" in r.getMessage() and r.levelname == "WARNING"
            for r in caplog.records
        )
        m.cleanup_all()


# ---------------------------------------------------------------------------
# TypeRef cache (#620/#652): cleared per project on a watched change
# ---------------------------------------------------------------------------


def _typeref_key(root: Path, n: int) -> tuple[str, str, int, int, int, int, int, str]:
    return (root.resolve().as_posix(), f"{root.as_posix()}/m.py", n, 0, 0, 0, 0, "X")


class TestTypeRefInvalidation:
    def test_watched_change_clears_only_that_projects_typerefs(self, tmp_path: Path) -> None:
        from pyeye.mcp.operations import typeref

        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        typeref.invalidate_all()
        typeref._typeref_cache[_typeref_key(a, 1)] = {"raw": "A"}
        typeref._typeref_cache[_typeref_key(b, 1)] = {"raw": "B"}
        m = ProjectManager(max_projects=10)
        m._watch_users[a.resolve()] = {a.resolve()}

        m._on_files_changed(a.resolve(), [(a / "m.py").as_posix()])

        assert list(typeref._typeref_cache) == [_typeref_key(b, 1)]
        typeref.invalidate_all()

    def test_invalidate_project_survives_concurrent_inserts(self, tmp_path: Path) -> None:
        """The watcher thread invalidates while analysis inserts: no 'mutated during iteration'."""
        import threading

        from pyeye.mcp.operations import typeref

        typeref.invalidate_all()
        # A full cache and a tiny switch interval make the unlocked iteration
        # reliably see a concurrent insert ("OrderedDict mutated during iteration").
        for n in range(3000):
            typeref._store_typeref(_typeref_key(tmp_path, -n - 1), {"raw": "x"})
        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        stop = threading.Event()
        errors: list[BaseException] = []

        def insert() -> None:
            n = 0
            try:
                while not stop.is_set():
                    typeref._store_typeref(_typeref_key(tmp_path, n), {"raw": "x"})
                    typeref._cached_typeref(_typeref_key(tmp_path, n))
                    n += 1
            except BaseException as e:  # noqa: BLE001 - the failure under test
                errors.append(e)

        inserter = threading.Thread(target=insert)
        inserter.start()
        try:
            for _ in range(300):
                try:
                    typeref.invalidate_project(tmp_path / "elsewhere")
                except BaseException as e:  # noqa: BLE001 - the failure under test
                    errors.append(e)
                    break
        finally:
            stop.set()
            inserter.join()
            sys.setswitchinterval(old_interval)
            typeref.invalidate_all()

        assert errors == []
