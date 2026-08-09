"""The primitive pipeline is actually wired into ``file_artifact_cache``.

Replaces `test_lookup_caching.py`, deleted with `lookup()` in #505. That module
proved cache wiring by timing a cold call against an average of warm ones — a
wall-clock assertion of the kind tracked as flaky in #486. The property it
actually cared about is *"the entry point reuses cached artifacts rather than
re-reading and re-parsing"*, and that is directly observable from the cache's own
`hits` / `misses` counters, so this asserts it deterministically instead.

A wiring regression (an entry point bypassing the cache and constructing
`jedi.Script(...)` itself) shows up here as a second call that records no hits.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect as inspect_impl
from pyeye.mcp.operations.outline import outline as outline_impl
from pyeye.mcp.operations.resolve import resolve as resolve_impl

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "lookup_project"
_HANDLE = "lookup_project.models.ServiceConfig"


@pytest.fixture
def fresh_cache() -> Generator[None, None, None]:
    """Swap in a clean default cache so counters start at zero."""
    original = file_artifact_cache._default_cache
    file_artifact_cache._default_cache = file_artifact_cache.FileArtifactCache()
    try:
        yield
    finally:
        file_artifact_cache._default_cache = original


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURE))


@pytest.mark.usefixtures("fresh_cache")
class TestPrimitivePipelineUsesArtifactCache:
    @pytest.mark.asyncio
    async def test_repeated_resolve_records_cache_hits(self, analyzer: JediAnalyzer) -> None:
        """The second resolve of the same handle reuses cached artifacts."""
        await resolve_impl(_HANDLE, analyzer)
        after_cold = file_artifact_cache.stats()

        await resolve_impl(_HANDLE, analyzer)
        after_warm = file_artifact_cache.stats()

        assert after_warm["hits"] > after_cold["hits"], (
            "Second resolve() recorded no cache hit — the entry point is not reusing "
            f"file_artifact_cache. cold={after_cold}, warm={after_warm}"
        )

    @pytest.mark.asyncio
    async def test_cold_pipeline_populates_the_cache(self, analyzer: JediAnalyzer) -> None:
        """A cold run must miss (and therefore populate), not bypass silently."""
        assert file_artifact_cache.stats()["misses"] == 0

        await resolve_impl(_HANDLE, analyzer)

        assert file_artifact_cache.stats()["misses"] > 0, (
            "Cold resolve() recorded no cache miss — it never consulted "
            "file_artifact_cache at all."
        )

    @pytest.mark.asyncio
    async def test_inspect_and_outline_share_the_cached_artifacts(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Warming via one primitive benefits the others (shared, not per-operation)."""
        await resolve_impl(_HANDLE, analyzer)
        warmed = file_artifact_cache.stats()

        await inspect_impl(_HANDLE, analyzer)
        await outline_impl(_HANDLE, analyzer)
        after = file_artifact_cache.stats()

        assert after["hits"] > warmed["hits"], (
            "inspect()/outline() recorded no hits against a cache warmed by resolve() — "
            f"the operations are not sharing artifacts. warmed={warmed}, after={after}"
        )
