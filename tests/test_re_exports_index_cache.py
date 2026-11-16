"""The re-export binding index is built once per package, not once per handle (#803).

#797 (#795) made one scan parse each package file once. But the scan runs for
each new handle, and #393's cache is keyed by handle, so every new handle still
re-indexed the whole package: on django, 907 files per ``inspect`` (about 885
artifact-cache misses at the default cap), 13–15 s per cold project handle.
The index is now cached per (project, layout, package root), next to #393's
scan cache and cleared by the same ``invalidate_re_exports``.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from pyeye import canonicalization, file_artifact_cache
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import (
    _collect_re_exports_impl,
    invalidate_re_exports,
    re_export_scan,
)
from pyeye.handle import Handle
from pyeye.mcp.operations.inspect import inspect
from pyeye.path_utils import path_to_key


def _project(tmp_path: Path, files: dict[str, str]) -> JediAnalyzer:
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


_PKG = {
    "pkg/__init__.py": "from ._core import X, Y\n",
    "pkg/_core.py": "class X:\n    pass\n\n\nclass Y:\n    pass\n\n\nclass Z:\n    pass\n",
    "pkg/api.py": "from ._core import X, Y, Z\n",
    "other/__init__.py": "from ._impl import W\n",
    "other/_impl.py": "class W:\n    pass\n",
}


class _Counter:
    """Wrap a callable and record each call's first argument."""

    def __init__(self, real) -> None:  # type: ignore[no-untyped-def]
        self.real = real
        self.calls: list[str] = []

    def __call__(self, first, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(Path(first).as_posix())
        return self.real(first, *args, **kwargs)


@pytest.mark.asyncio
async def test_the_second_handle_in_a_package_parses_nothing(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, _PKG)
    counter = _Counter(file_artifact_cache.get_ast)

    with patch.object(file_artifact_cache, "get_ast", counter):
        first = await re_export_scan(Handle("pkg._core.X"), analyzer)
        after_first = len(counter.calls)
        second = await re_export_scan(Handle("pkg._core.Y"), analyzer)
        third = await re_export_scan(Handle("pkg._core.Z"), analyzer)

    assert after_first == len(list((tmp_path / "pkg").rglob("*.py")))  # one build
    assert len(counter.calls) == after_first  # Y and Z: zero get_ast calls
    assert first.paths == ("pkg.X", "pkg.api.X")
    assert second.paths == ("pkg.Y", "pkg.api.Y")
    assert third.paths == ("pkg.api.Z",)


@pytest.mark.asyncio
async def test_each_package_is_indexed_once(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, _PKG)
    builds = _Counter(canonicalization._build_binding_index)

    with patch.object(canonicalization, "_build_binding_index", builds):
        for handle in ("pkg._core.X", "pkg._core.Y", "other._impl.W", "pkg._core.Z"):
            await re_export_scan(Handle(handle), analyzer)

    assert sorted(builds.calls) == sorted(
        [(tmp_path / "pkg").as_posix(), (tmp_path / "other").as_posix()]
    )


@pytest.mark.asyncio
async def test_concurrent_first_calls_build_once(tmp_path: Path) -> None:
    """On one loop, first calls for several handles share one build."""
    analyzer = _project(tmp_path, _PKG)
    builds = _Counter(canonicalization._build_binding_index)

    with patch.object(canonicalization, "_build_binding_index", builds):
        scans = await asyncio.gather(
            *(re_export_scan(Handle(f"pkg._core.{n}"), analyzer) for n in "XYZ")
        )

    assert len(builds.calls) == 1
    assert [s.paths for s in scans] == [
        ("pkg.X", "pkg.api.X"),
        ("pkg.Y", "pkg.api.Y"),
        ("pkg.api.Z",),
    ]


def test_threads_racing_on_a_cold_package_build_once(tmp_path: Path) -> None:
    """Two threads (the worker and, say, a test client) still share one build."""
    analyzer = _project(tmp_path, _PKG)
    real = canonicalization._build_binding_index
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def slow_build(root, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(root).as_posix())
        entered.set()
        release.wait(5)
        return real(root, *args, **kwargs)

    results: dict[str, tuple[str, ...]] = {}

    def run(name: str) -> None:
        results[name] = asyncio.run(re_export_scan(Handle(f"pkg._core.{name}"), analyzer)).paths

    with patch.object(canonicalization, "_build_binding_index", slow_build):
        a = threading.Thread(target=run, args=("X",))
        a.start()
        assert entered.wait(5)
        b = threading.Thread(target=run, args=("Y",))
        b.start()
        release.set()
        a.join(10)
        b.join(10)

    assert len(calls) == 1
    assert results == {"X": ("pkg.X", "pkg.api.X"), "Y": ("pkg.Y", "pkg.api.Y")}


@pytest.mark.asyncio
async def test_unparseable_files_come_from_the_cached_index_too(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, {**_PKG, "pkg/broken.py": "def (:\n"})
    broken = path_to_key(tmp_path / "pkg" / "broken.py")

    first = await re_export_scan(Handle("pkg._core.X"), analyzer)
    second = await re_export_scan(Handle("pkg._core.Y"), analyzer)

    assert first.unparseable_files == second.unparseable_files == (broken,)
    assert second.paths == ("pkg.Y", "pkg.api.Y")


@pytest.mark.asyncio
async def test_without_a_list_a_cached_parse_failure_still_raises(tmp_path: Path) -> None:
    """The strict mode (#704) is unchanged when the index comes from the cache."""
    analyzer = _project(tmp_path, {**_PKG, "pkg/broken.py": "def (:\n"})
    await re_export_scan(Handle("pkg._core.X"), analyzer)  # builds and caches the index

    with pytest.raises(SyntaxError):
        await _collect_re_exports_impl(Handle("pkg._core.Y"), analyzer)


@pytest.mark.asyncio
async def test_an_added_binding_shows_after_the_watcher_runs(tmp_path: Path) -> None:
    from pyeye.project_manager import ProjectManager

    _project(tmp_path, _PKG)
    manager = ProjectManager()
    try:
        analyzer = manager.get_analyzer(str(tmp_path))
        assert (await inspect("pkg._core.X", analyzer))["re_exports"] == ["pkg.X", "pkg.api.X"]
        await inspect("pkg._core.Y", analyzer)  # the index is warm for the package

        facade = tmp_path / "pkg" / "facade.py"
        facade.write_text("from ._core import Y\n", encoding="utf-8")
        manager._on_files_changed(tmp_path.resolve(), [str(facade)])

        assert (await inspect("pkg._core.Y", analyzer))["re_exports"] == [
            "pkg.Y",
            "pkg.api.Y",
            "pkg.facade.Y",
        ]
    finally:
        manager.cleanup_all()


@pytest.mark.asyncio
async def test_a_removed_binding_goes_after_the_watcher_runs(tmp_path: Path) -> None:
    from pyeye.project_manager import ProjectManager

    _project(tmp_path, _PKG)
    manager = ProjectManager()
    try:
        analyzer = manager.get_analyzer(str(tmp_path))
        assert (await inspect("pkg._core.X", analyzer))["re_exports"] == ["pkg.X", "pkg.api.X"]

        api = tmp_path / "pkg" / "api.py"
        api.write_text("from ._core import Y, Z\n", encoding="utf-8")
        manager._on_files_changed(tmp_path.resolve(), [str(api)])

        assert (await inspect("pkg._core.X", analyzer))["re_exports"] == ["pkg.X"]
    finally:
        manager.cleanup_all()


@pytest.mark.asyncio
async def test_configure_packages_drops_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyeye.project_manager as project_manager_module
    from pyeye.mcp import server
    from pyeye.project_manager import ProjectManager

    # Isolate the server's global manager and plugins (as test_layout_keyed_caches does).
    manager = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", manager)
    monkeypatch.setattr(server, "_plugins", [])
    request_cleanup = manager.cleanup_all

    analyzer = _project(tmp_path, _PKG)
    await re_export_scan(Handle("pkg._core.X"), analyzer)
    assert canonicalization._binding_index_cache

    await server.configure_packages(packages=[], project_path=str(tmp_path))

    project = path_to_key(tmp_path)
    assert not [k for k in canonicalization._binding_index_cache if k[0] == project]
    request_cleanup()


@pytest.mark.asyncio
async def test_invalidation_is_per_project(tmp_path: Path) -> None:
    one = _project(tmp_path / "one", _PKG)
    two = _project(tmp_path / "two", _PKG)
    await re_export_scan(Handle("pkg._core.X"), one)
    await re_export_scan(Handle("pkg._core.X"), two)

    invalidate_re_exports(tmp_path / "one")

    roots = {k[0] for k in canonicalization._binding_index_cache}
    assert roots == {path_to_key(tmp_path / "two")}
    invalidate_re_exports()
    assert not canonicalization._binding_index_cache


@pytest.mark.asyncio
async def test_an_index_built_across_an_invalidation_is_not_stored(tmp_path: Path) -> None:
    """A watcher batch landing mid-build must not leave the pre-edit index cached."""
    analyzer = _project(tmp_path, _PKG)
    real = canonicalization._build_binding_index

    def build_then_invalidate(root, *args, **kwargs):  # type: ignore[no-untyped-def]
        index = real(root, *args, **kwargs)
        invalidate_re_exports(tmp_path)  # the watcher, during the build
        return index

    with patch.object(canonicalization, "_build_binding_index", build_then_invalidate):
        scan = await re_export_scan(Handle("pkg._core.X"), analyzer)

    assert scan.paths == ("pkg.X", "pkg.api.X")  # this call still answers
    assert not canonicalization._binding_index_cache  # but nothing stale is kept


@pytest.mark.asyncio
async def test_the_index_cache_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(canonicalization, "_BINDING_INDEX_CACHE_MAX", 1)
    analyzer = _project(tmp_path, _PKG)

    await re_export_scan(Handle("pkg._core.X"), analyzer)
    await re_export_scan(Handle("other._impl.W"), analyzer)

    assert [k[2] for k in canonicalization._binding_index_cache] == [
        path_to_key(tmp_path / "other")
    ]
