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
drive ``ProjectManager._on_files_changed``, so they need no sleeps. One test runs
a real watchdog observer, bounded by a ``PerformanceThresholds`` deadline.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
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
from tests.utils.performance import PerformanceThresholds

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

#: How long a real watchdog observer may take to deliver a debounced change.
WATCHER_DELIVERY = PerformanceThresholds(
    base=5000.0, linux_ci=10000.0, macos_ci=20000.0, windows_ci=20000.0
)


class TestRealObserver:
    @pytest.mark.real_watcher
    async def test_created_file_reaches_the_name_index(self, tmp_path: Path) -> None:
        m = ProjectManager(max_projects=10)
        try:
            proj = _project(tmp_path / "proj")
            analyzer = m.get_analyzer(proj.as_posix())
            assert (await resolve("Gamma", analyzer))["found"] is False
            (proj / "pkg" / "extra.py").write_text("class Gamma:\n    pass\n")

            deadline = time.monotonic() + WATCHER_DELIVERY.get_threshold() / 1000
            found = False
            while time.monotonic() < deadline:
                if (await resolve("Gamma", analyzer))["found"]:
                    found = True
                    break
                await asyncio.sleep(0.1)

            assert found, "the watcher never delivered the created file"
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
