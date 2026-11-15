"""Resolution must not depend on parso's in-memory cache size (#684, #713).

parso garbage-collected ``parso.cache.parser_cache`` by file mtime, so stdlib and
typeshed modules vanished right after parsing. A Jedi inference still holding
such a module raised ``KeyError`` in ``get_parso_cache_node``, and
``asyncio.Queue`` came back unresolved (#684). #706 switched the GC off, leaving
the cache unbounded (#713). :mod:`pyeye._parso_cache` now makes eviction
harmless (recovery) and bounds the cache (an LRU by last use).

These tests pin:

- every Jedi and parso internal the policy relies on still exists and is wrapped,
  so an upgrade that moves one fails here instead of bringing #684 back;
- the recovery is exact (same definition names, same code lines);
- the LRU evicts least-recently-used entries and stamps the parse time;
- #706's 13 resolution tests pass under eviction pressure: the original
  over-the-cap filler, and a forced bound of ONE entry.

They use the real ``parser_cache`` dict: Jedi imports it by name, so a
monkeypatched module attribute would not reach it.
"""

from __future__ import annotations

import importlib
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import parso
import parso.cache
import pytest

import pyeye  # noqa: F401  (importing pyeye applies the parso cache policy)
from pyeye import _parso_cache
from pyeye._parso_cache import apply_parso_cache_policy
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve
from pyeye.resolver import Resolved, resolve_handle
from pyeye.settings import PerformanceSettings, settings

_FILLER_KEY = "pyeye-test-684-filler"
_EXTERNAL = ("asyncio.Queue", "asyncio.queues.Queue", "json.JSONDecoder")
_STDLIB_PACKAGES = {"asyncio", "json", "pathlib"}


def _expected(identifier: str) -> str:
    """The runtime definition site, so the test holds on every Python version."""
    import asyncio
    import json

    if identifier.startswith("asyncio"):
        return f"{asyncio.Queue.__module__}.Queue"
    return f"{json.JSONDecoder.__module__}.JSONDecoder"


def _evict_stdlib(cache: dict[str, dict[Any, Any]]) -> dict[tuple[str, Any], Any]:
    """Drop the asyncio/json/pathlib entries so resolving re-parses them."""
    removed: dict[tuple[str, Any], Any] = {}
    for grammar_key, items in list(cache.items()):
        for path in list(items):
            if _STDLIB_PACKAGES & {Path(part).stem for part in Path(str(path)).parts}:
                removed[(grammar_key, path)] = items.pop(path)
    return removed


def _restore(cache: dict[str, dict[Any, Any]], removed: dict[tuple[str, Any], Any]) -> None:
    for (grammar_key, path), item in removed.items():
        cache.setdefault(grammar_key, {}).setdefault(path, item)


@pytest.fixture
def parso_cache_over_cap() -> Iterator[None]:
    """#706's fixture: the cache held over its cap by entries newer than any parse.

    The filler's ``last_used`` is in the future, so the LRU evicts the real,
    just-parsed stdlib/typeshed entries first: the worst case for #684.
    """
    cache = parso.cache.parser_cache
    removed = _evict_stdlib(cache)
    fresh = time.time() + 3600
    cache[_FILLER_KEY] = {
        f"/nonexistent/pyeye-684/{i}.py": parso.cache._NodeCacheItem(None, [], change_time=fresh)
        for i in range(settings.parso_cache_max_entries)
    }
    try:
        yield
    finally:
        cache.pop(_FILLER_KEY, None)
        _restore(cache, removed)


@pytest.fixture
def parso_cache_bound_of_one() -> Iterator[None]:
    """A forced bound of ONE entry: every parse evicts every other module."""
    cache = parso.cache.parser_cache
    removed = _evict_stdlib(cache)
    apply_parso_cache_policy(1)
    try:
        yield
    finally:
        apply_parso_cache_policy(settings.parso_cache_max_entries)
        _restore(cache, removed)


@pytest.fixture(params=["parso_cache_over_cap", "parso_cache_bound_of_one"])
def eviction_pressure(request: pytest.FixtureRequest) -> None:
    request.getfixturevalue(request.param)


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(Path(__file__).parent))


class TestPinnedInternals:
    """Every internal the policy patches still exists, and is patched."""

    def test_parso_internals_exist(self) -> None:
        assert hasattr(parso.cache, "parser_cache")
        assert hasattr(parso.cache, "_set_cache_item")
        assert hasattr(parso.cache, "_CACHED_SIZE_TRIGGER")
        item = parso.cache._NodeCacheItem(None, [], change_time=1.0)
        assert hasattr(item, "last_used") and hasattr(item, "lines")

    def test_jedi_filter_binding_is_wrapped(self) -> None:
        filters = importlib.import_module(_parso_cache._FILTER_MODULE)
        assert _parso_cache._is_marked(filters.get_parso_cache_node)

    @pytest.mark.parametrize("name", _parso_cache._CODE_LINES_MODULES)
    def test_jedi_code_lines_bindings_are_wrapped(self, name: str) -> None:
        module = importlib.import_module(name)
        assert _parso_cache._is_marked(module.get_cached_code_lines), name

    def test_parso_insert_goes_through_the_lru(self) -> None:
        assert _parso_cache._is_marked(parso.cache._set_cache_item)
        assert sys.maxsize <= parso.cache._CACHED_SIZE_TRIGGER  # parso's own GC never runs

    def test_jedi_filter_still_computes_without_its_memo(self) -> None:
        """The recovery relies on ``_get_definition_names`` accepting ``None``."""
        from jedi.inference.filters import _get_definition_names

        module = parso.parse("def f():\n    pass\n\nclass C:\n    pass\n\nf = 1\n")
        used = module.get_used_names()
        item = parso.cache._NodeCacheItem(module, [])
        for key in ("f", "C"):
            assert _get_definition_names(None, used, key) == _get_definition_names(item, used, key)

    def test_apply_is_idempotent(self) -> None:
        wrapped = parso.cache._set_cache_item
        filters = importlib.import_module(_parso_cache._FILTER_MODULE)
        node = filters.get_parso_cache_node

        apply_parso_cache_policy(settings.parso_cache_max_entries)
        apply_parso_cache_policy(settings.parso_cache_max_entries)

        assert parso.cache._set_cache_item is wrapped
        assert filters.get_parso_cache_node is node
        assert not _parso_cache._is_marked(parso.cache._set_cache_item.__wrapped__)


class TestRecovery:
    def test_a_missing_entry_gives_the_filter_none(self) -> None:
        filters = importlib.import_module(_parso_cache._FILTER_MODULE)
        grammar = parso.load_grammar()
        assert filters.get_parso_cache_node(grammar, Path("/nonexistent/x.py")) is None

    def test_missing_code_lines_are_re_read_exactly(self, tmp_path: Path) -> None:
        import jedi.parser_utils

        source = "# -*- coding: utf-8 -*-\nx = 'é'\r\ny = 2\n\tz = 3"
        path = tmp_path / "m.py"
        path.write_bytes(source.encode("utf-8"))
        grammar = parso.load_grammar()

        lines = jedi.parser_utils.get_cached_code_lines(grammar, path)

        assert lines == parso.split_lines(source, keepends=True)

    def test_a_cached_entry_is_still_returned(self, tmp_path: Path) -> None:
        import jedi.parser_utils

        path = tmp_path / "m.py"
        path.write_text("a = 1\n")
        grammar = parso.load_grammar()
        grammar.parse(path=path, cache=True)

        item = jedi.parser_utils.get_parso_cache_node(grammar, path)
        assert item is parso.cache.parser_cache[grammar._hashed][path]
        assert jedi.parser_utils.get_cached_code_lines(grammar, path) is item.lines


class TestLru:
    @pytest.fixture
    def isolated(self) -> Iterator[dict[str, dict[Any, Any]]]:
        cache = parso.cache.parser_cache
        saved = {grammar: dict(items) for grammar, items in cache.items()}
        cache.clear()
        apply_parso_cache_policy(10)
        try:
            yield cache
        finally:
            cache.clear()
            cache.update(saved)
            apply_parso_cache_policy(settings.parso_cache_max_entries)

    @staticmethod
    def _insert(name: str) -> Any:
        item = parso.cache._NodeCacheItem(None, [], change_time=0.0)  # an old mtime
        parso.cache._set_cache_item("g", name, item)
        return item

    @pytest.mark.usefixtures("isolated")
    def test_stamps_the_parse_time_not_the_mtime(self) -> None:
        before = time.time()
        item = self._insert("a.py")
        assert item.last_used >= before

    def test_evicts_least_recently_used_first(self, isolated: dict[str, dict[Any, Any]]) -> None:
        items = [self._insert(f"{i}.py") for i in range(10)]
        items[0].last_used = time.time() + 60  # "0.py" was just used (a cache hit)

        self._insert("new.py")

        kept = set(isolated["g"])
        assert "0.py" in kept and "new.py" in kept
        assert "1.py" not in kept  # the least recently used went first
        assert len(kept) <= 10

    def test_never_exceeds_the_cap(self, isolated: dict[str, dict[Any, Any]]) -> None:
        for i in range(100):
            self._insert(f"{i}.py")
            assert sum(len(v) for v in isolated.values()) <= 10


class TestSetting:
    def test_default_and_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYEYE_PARSO_CACHE_MAX_ENTRIES", raising=False)
        assert PerformanceSettings().parso_cache_max_entries == 600
        monkeypatch.setenv("PYEYE_PARSO_CACHE_MAX_ENTRIES", "50")
        assert PerformanceSettings().parso_cache_max_entries == 50


@pytest.mark.usefixtures("eviction_pressure")
class TestResolutionSurvivesEviction:
    @pytest.mark.parametrize("identifier", sorted(_EXTERNAL))
    def test_resolve_handle(self, identifier: str, analyzer: JediAnalyzer) -> None:
        result = resolve_handle(identifier, analyzer)

        assert isinstance(result, Resolved), result
        assert result.handle == _expected(identifier)
        assert result.kind == "class"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identifier", sorted(_EXTERNAL))
    async def test_resolve_operation(self, identifier: str, analyzer: JediAnalyzer) -> None:
        result = await resolve(identifier, analyzer)

        assert result["found"] is True, result
        assert result["handle"] == _expected(identifier)
        assert result["kind"] == "class"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identifier", sorted(_EXTERNAL))
    async def test_inspect_operation(self, identifier: str, analyzer: JediAnalyzer) -> None:
        node = await inspect(identifier, analyzer)

        assert node["found"] is True, node
        assert node["handle"] == _expected(identifier)
        assert node["kind"] == "class"

    @pytest.mark.asyncio
    async def test_outline_external_nested_containers_stay_external(
        self, analyzer: JediAnalyzer
    ) -> None:
        # The symptom on main from a fresh checkout: a nested container of an
        # external class came back ``survey_leaf`` instead of ``external``.
        tree = await outline("pathlib.Path", analyzer)

        assert tree["found"] is True, tree
        assert tree["node"]["scope"] == "external"
        containers = [c for c in tree["children"] if c["node"]["kind"] in ("class", "module")]
        for container in containers:
            assert container["truncation_reason"] == "external", container
            assert "children" not in container
