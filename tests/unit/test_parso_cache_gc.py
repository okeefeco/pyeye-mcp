"""Resolution must not depend on parso's in-memory cache size (#684).

parso garbage-collects ``parso.cache.parser_cache`` once it holds
``_CACHED_SIZE_TRIGGER`` (600) files, dropping every entry whose ``last_used``
is more than 10 minutes old. ``last_used`` starts at the FILE's mtime, so a
stdlib or typeshed file is dropped at the next insert after its own. A Jedi
inference still holding that module then raises ``KeyError`` in
``jedi.parser_utils.get_parso_cache_node``, and ``asyncio.Queue`` came back
unresolved. A fresh checkout keeps 600+ recent-mtime project files in the cache,
so on a real project this fired in normal use.

pyeye disables that GC once, in :mod:`pyeye._parso_cache`. These tests use the
real ``parser_cache`` dict: Jedi imports it by name, so a monkeypatched module
attribute would not reach it.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path

import parso.cache
import pytest

import pyeye  # noqa: F401  (importing pyeye applies the parso cache policy)
from pyeye._parso_cache import disable_parso_cache_gc
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve
from pyeye.resolver import Resolved, resolve_handle

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


@pytest.fixture
def parso_cache_over_gc_trigger() -> Iterator[None]:
    """Hold parso's cache over its GC trigger, with the stdlib files evicted.

    The filler is FRESH, like a just-checked-out project, so parso's GC never
    drops it and every insert runs a GC pass. The ``asyncio``/``json`` files are
    removed so resolving re-parses them: real stdlib/typeshed files with OLD
    mtimes, which the GC drops at the next insert after their own. Everything is
    restored afterwards.
    """
    cache = parso.cache.parser_cache
    removed: dict[tuple[str, object], object] = {}
    for grammar_key, items in list(cache.items()):
        for path in list(items):
            if _STDLIB_PACKAGES & {Path(part).stem for part in Path(str(path)).parts}:
                removed[(grammar_key, path)] = items.pop(path)
    fresh = time.time() + 3600
    cache[_FILLER_KEY] = {
        f"/nonexistent/pyeye-684/{i}.py": parso.cache._NodeCacheItem(None, [], change_time=fresh)
        for i in range(600)  # parso's default _CACHED_SIZE_TRIGGER
    }
    try:
        yield
    finally:
        cache.pop(_FILLER_KEY, None)
        for (grammar_key, path), item in removed.items():
            cache.setdefault(grammar_key, {}).setdefault(path, item)


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(Path(__file__).parent))


class TestParsoCachePolicy:
    def test_parso_still_has_the_pinned_private(self) -> None:
        # The fix sets a parso private. If an upgrade renames it, fail here
        # instead of silently bringing #684 back.
        assert hasattr(parso.cache, "_CACHED_SIZE_TRIGGER")
        assert hasattr(parso.cache, "parser_cache")

    def test_importing_pyeye_disables_parso_cache_gc(self) -> None:
        assert sys.maxsize <= parso.cache._CACHED_SIZE_TRIGGER

    def test_disable_is_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(parso.cache, "_CACHED_SIZE_TRIGGER", 600)
        disable_parso_cache_gc()
        disable_parso_cache_gc()
        assert sys.maxsize == parso.cache._CACHED_SIZE_TRIGGER


@pytest.mark.usefixtures("parso_cache_over_gc_trigger")
class TestResolutionSurvivesAFullParsoCache:
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
