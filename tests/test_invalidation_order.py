"""A lookup during a watcher invalidation never caches a stale index (#817).

``ProjectManager._on_files_changed`` used to bump ``project_graph``'s generation
first and clear the analyzer's file listings (``scoped_cache``) last. A lookup
in between took the NEW generation, read the STALE listing and cached an index
without the new file, so #617's generation guard passed. The new class stayed
invisible until some other file changed (seen on Windows CI by #816's burst
test). Now everything a build reads is dropped before any generation moves, and
``ScopedCache.set`` won't store a listing that raced its own invalidation.

Every interleaving here is forced with events, never timing.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers import (
    jedi_analyzer as jedi_analyzer_module,
    project_graph,
)
from pyeye.mcp.operations import typeref
from pyeye.mcp.operations.resolve import resolve
from pyeye.project_manager import ProjectManager
from pyeye.scope_utils import ScopedCache

GAMMA = "class Gamma:\n    pass\n"


def _project(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "core.py").write_text("class Alpha:\n    pass\n")
    return root


@pytest.fixture
def manager() -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=10)
    yield m
    m.cleanup_all()


class TestScopedCacheEpoch:
    def test_a_value_computed_before_an_invalidation_is_not_stored(self) -> None:
        cache = ScopedCache()
        epoch = cache.epoch()
        cache.invalidate_all()
        assert cache.set("files:*.py", ["stale.py"], "all", epoch=epoch) is False
        assert cache.get("files:*.py", "all") is None

    def test_a_value_computed_in_the_current_epoch_is_stored(self) -> None:
        cache = ScopedCache()
        cache.invalidate_all()
        epoch = cache.epoch()
        assert cache.set("files:*.py", ["fresh.py"], "all", epoch=epoch) is True
        assert cache.get("files:*.py", "all") == ["fresh.py"]

    def test_without_an_epoch_set_always_stores(self) -> None:
        cache = ScopedCache()
        cache.invalidate_all()
        assert cache.set("k", 1, "main") is True
        assert cache.get("k", "main") == 1


class TestListingRacedByInvalidation:
    @pytest.mark.asyncio
    async def test_a_listing_raced_by_its_own_projects_invalidation_is_not_cached(
        self, tmp_path: Path, manager: ProjectManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj = _project(tmp_path / "proj")
        analyzer = manager.get_analyzer(proj.as_posix())
        real = jedi_analyzer_module.parallel_search

        async def raced(pattern: str, paths: list[Path]) -> list[Path]:
            files = await real(pattern, paths)
            # The watcher lands mid-listing, for this very project.
            manager._on_files_changed(proj.resolve(), [(proj / "pkg" / "core.py").as_posix()])
            return list(files)

        monkeypatch.setattr(jedi_analyzer_module, "parallel_search", raced)
        files = await analyzer.get_project_files(pattern="*.py", scope="all")

        assert files, "the raced listing is still returned to its caller"
        assert analyzer.scoped_cache.get("files:*.py", "all") is None

    @pytest.mark.asyncio
    async def test_another_projects_invalidation_mid_listing_still_stores(
        self, tmp_path: Path, manager: ProjectManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj = _project(tmp_path / "proj")
        other = _project(tmp_path / "other")
        analyzer = manager.get_analyzer(proj.as_posix())
        manager.get_analyzer(other.as_posix())
        real = jedi_analyzer_module.parallel_search

        async def raced(pattern: str, paths: list[Path]) -> list[Path]:
            files = await real(pattern, paths)
            # Steady watcher traffic on ANOTHER project must not discard this
            # listing (the #803/#805 global-counter failure mode).
            manager._on_files_changed(other.resolve(), [(other / "pkg" / "core.py").as_posix()])
            return list(files)

        monkeypatch.setattr(jedi_analyzer_module, "parallel_search", raced)
        files = await analyzer.get_project_files(pattern="*.py", scope="all")

        assert analyzer.scoped_cache.get("files:*.py", "all") == files


class TestInvalidationOrder:
    def test_file_listings_are_gone_before_the_generation_moves(
        self, tmp_path: Path, manager: ProjectManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj = _project(tmp_path / "proj")
        analyzer = manager.get_analyzer(proj.as_posix())
        analyzer.scoped_cache.set("files:*.py", ["stale.py"], "all")
        seen: list[Any] = []
        real = project_graph.invalidate

        def recording(project_key: str | None = None) -> None:
            seen.append(analyzer.scoped_cache.get("files:*.py", "all"))
            real(project_key)

        monkeypatch.setattr(project_graph, "invalidate", recording)
        manager._on_files_changed(proj.resolve(), [(proj / "pkg" / "core.py").as_posix()])

        assert seen == [None], "the generation moved while a stale listing was still cached"

    @pytest.mark.asyncio
    async def test_a_lookup_inside_the_invalidation_window_does_not_hide_a_new_class(
        self, tmp_path: Path, manager: ProjectManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The #817 repro: stall the invalidation after the generation bump, look up."""
        proj = _project(tmp_path / "proj")
        analyzer = manager.get_analyzer(proj.as_posix())
        assert (await resolve("Gamma", analyzer))["found"] is False  # caches a listing
        (proj / "pkg" / "extra.py").write_text(GAMMA)

        in_window = threading.Event()
        release = threading.Event()
        real = typeref.invalidate_project

        def stalled(project: Path) -> None:  # after project_graph.invalidate
            in_window.set()
            assert release.wait(10), "the test never released the invalidation"
            real(project)

        monkeypatch.setattr(typeref, "invalidate_project", stalled)
        batch = threading.Thread(
            target=manager._on_files_changed,
            args=(proj.resolve(), [(proj / "pkg" / "extra.py").as_posix()]),
        )
        batch.start()
        try:
            assert in_window.wait(10), "the invalidation never reached the window"
            # A lookup in the window builds and caches the index under the new
            # generation, so it must read a fresh listing.
            assert (await resolve("Gamma", analyzer))["found"] is True
        finally:
            release.set()
            batch.join(10)
        assert not batch.is_alive()
        assert (await resolve("Gamma", analyzer))["found"] is True
