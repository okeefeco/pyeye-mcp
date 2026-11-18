"""The imports edge memoises its external re-resolutions per analyzer (#925).

``trace(..., ["imports"])`` into the stdlib re-resolved the same external
targets again and again, each through a fresh synthetic Jedi script. The
answers now live in the analyzer's ``scoped_cache``: only external
``Resolved`` results, LRU-bounded by ``PYEYE_RESOLVE_CACHE_MAX_ENTRIES``,
cleared by the watcher and guarded by the #817 epoch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pyeye import (
    resolver,
    settings as settings_mod,
)
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.project_manager import ProjectManager
from pyeye.resolver import EXTERNAL_RESOLVE_SCOPE, NotFound, Resolved, resolve_external_item
from pyeye.scope_utils import ScopedCache
from pyeye.settings import PerformanceSettings


class TestBoundedScope:
    def test_max_entries_evicts_the_least_recently_used(self) -> None:
        cache = ScopedCache()
        for key in ("a", "b", "c"):
            cache.set(key, key.upper(), "s", max_entries=3)
        assert cache.get_recent("a", "s") == "A"  # a is now the most recent
        cache.set("d", "D", "s", max_entries=3)

        assert cache.get("b", "s") is None
        assert [cache.get(k, "s") for k in ("a", "c", "d")] == ["A", "C", "D"]
        assert list(cache.timestamps["s"]) == list(cache.caches["s"])

    def test_re_setting_a_key_refreshes_it(self) -> None:
        cache = ScopedCache()
        cache.set("a", 1, "s", max_entries=2)
        cache.set("b", 2, "s", max_entries=2)
        cache.set("a", 3, "s", max_entries=2)
        cache.set("c", 4, "s", max_entries=2)

        assert cache.get("b", "s") is None
        assert (cache.get("a", "s"), cache.get("c", "s")) == (3, 4)

    def test_other_scopes_are_not_bounded(self) -> None:
        cache = ScopedCache()
        for i in range(5):
            cache.set(f"k{i}", i, "main")
        cache.set("x", 0, "s", max_entries=1)

        assert len(cache.caches["main"]) == 5

    def test_get_recent_misses_like_get(self) -> None:
        cache = ScopedCache()
        assert cache.get_recent("nope", "s") is None
        cache.set("a", 1, "s")
        cache.invalidate_all()
        assert cache.get_recent("a", "s") is None
        assert "a" not in cache.caches["s"]


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text("import logging\nfrom os import path\n", encoding="utf-8")
    return root


class _Counter:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        real = resolver.resolve_item

        def counted(path: str, analyzer: JediAnalyzer) -> Resolved | NotFound:
            self.calls.append(path)
            return real(path, analyzer)

        monkeypatch.setattr(resolver, "resolve_item", counted)


class TestResolveExternalItem:
    def test_an_external_answer_is_resolved_once(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        analyzer = JediAnalyzer(str(project))
        counter = _Counter(monkeypatch)

        first = resolve_external_item("logging.Handler", analyzer)
        second = resolve_external_item("logging.Handler", analyzer)

        assert isinstance(first, Resolved) and first.scope == "external"
        assert second is first
        assert counter.calls == ["logging.Handler"]

    def test_misses_and_project_answers_are_not_cached(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        analyzer = JediAnalyzer(str(project))
        counter = _Counter(monkeypatch)

        for _ in range(2):
            assert isinstance(resolve_external_item("logging.nope_925", analyzer), NotFound)
            hit = resolve_external_item("app", analyzer)
            assert isinstance(hit, Resolved) and hit.scope == "project"

        assert counter.calls == ["logging.nope_925", "app"] * 2
        assert not analyzer.scoped_cache.caches.get(EXTERNAL_RESOLVE_SCOPE)

    def test_invalidation_drops_the_answer(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        analyzer = JediAnalyzer(str(project))
        counter = _Counter(monkeypatch)

        resolve_external_item("logging.Handler", analyzer)
        analyzer.scoped_cache.invalidate_all()
        resolve_external_item("logging.Handler", analyzer)

        assert counter.calls == ["logging.Handler"] * 2

    def test_a_project_module_shadowing_the_stdlib_is_seen_after_the_event(
        self, project: Path
    ) -> None:
        """The one project edit that changes an external answer: a shadowing module."""
        manager = ProjectManager()
        try:
            analyzer = manager.get_analyzer(str(project))
            before = resolve_external_item("logging.Handler", analyzer)
            assert isinstance(before, Resolved) and before.scope == "external"

            shadow = project / "logging.py"
            shadow.write_text("class Handler:\n    pass\n", encoding="utf-8")
            watched = next(r for r, users in manager._watch_users.items() if users)
            manager._on_files_changed(watched, [shadow.as_posix()])

            after = resolve_external_item("logging.Handler", analyzer)
            fresh = resolver.resolve_item("logging.Handler", analyzer)
            assert isinstance(after, Resolved) and isinstance(fresh, Resolved)
            assert (after.handle, after.scope) == (fresh.handle, fresh.scope)
            assert after.scope == "project"
        finally:
            manager.cleanup_all()

    def test_an_answer_computed_across_an_invalidation_is_not_stored(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The #817 race: the watcher clears the cache while a resolution runs."""
        analyzer = JediAnalyzer(str(project))
        real = resolver.resolve_item

        def racing(path: str, a: JediAnalyzer) -> Resolved | NotFound:
            result = real(path, a)
            a.scoped_cache.invalidate_all()
            return result

        monkeypatch.setattr(resolver, "resolve_item", racing)
        assert isinstance(resolve_external_item("logging.Handler", analyzer), Resolved)
        assert not analyzer.scoped_cache.caches.get(EXTERNAL_RESOLVE_SCOPE)

    def test_the_cap_comes_from_settings(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings_mod.settings, "resolve_cache_max_entries", 1)
        analyzer = JediAnalyzer(str(project))

        resolve_external_item("logging.Handler", analyzer)
        resolve_external_item("os.path", analyzer)

        assert list(analyzer.scoped_cache.caches[EXTERNAL_RESOLVE_SCOPE]) == ["os.path"]

    def test_an_analyzer_without_a_scoped_cache_resolves_directly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentinel = NotFound(reason="unresolved", detail="x")
        monkeypatch.setattr(resolver, "resolve_item", lambda *_: sentinel)

        assert resolve_external_item("logging.Handler", MagicMock()) is sentinel

    def test_a_watcher_event_clears_it(self, project: Path) -> None:
        """The file watcher's batch handler clears the analyzer's answers (#617)."""
        manager = ProjectManager()
        try:
            analyzer = manager.get_analyzer(str(project))
            resolve_external_item("logging.Handler", analyzer)
            assert analyzer.scoped_cache.caches[EXTERNAL_RESOLVE_SCOPE]

            watched = next(r for r, users in manager._watch_users.items() if users)
            manager._on_files_changed(watched, [(project / "app.py").as_posix()])

            assert not analyzer.scoped_cache.caches[EXTERNAL_RESOLVE_SCOPE]
        finally:
            manager.cleanup_all()


class TestImportsEdge:
    async def test_a_repeated_expand_reuses_the_answers(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        analyzer = JediAnalyzer(str(project))
        counter = _Counter(monkeypatch)

        first = await expand("app", "imports", analyzer)
        cold = len(counter.calls)
        second = await expand("app", "imports", analyzer)

        assert cold > 0
        assert len(counter.calls) == cold  # every external target was a hit
        assert first == second
        assert {s["handle"] for s in first["stubs"]} >= {"logging", "os.path"}


def test_the_setting_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYEYE_RESOLVE_CACHE_MAX_ENTRIES", raising=False)
    assert PerformanceSettings().resolve_cache_max_entries == 1000
    monkeypatch.setenv("PYEYE_RESOLVE_CACHE_MAX_ENTRIES", "25")
    assert PerformanceSettings().resolve_cache_max_entries == 25
