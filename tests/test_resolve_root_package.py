"""Root-package and shadow rules for bare names in ``resolve`` (#423, #623).

``resolve("<pkg>")`` for a bare top-level package name yields the SINGLE root
handle, not an ambiguous set, even when a deeper symbol shares the name: an
exact top-level module wins (#623 slice 4, extending #423's promotion).  A real
**shadow** (two top-level packages with one import name across roots) stays
ambiguous, because picking one would hide the collision (#423).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve
from pyeye.resolver import Ambiguous, resolve_name

_ROOT = Path(__file__).parent / "fixtures" / "root_package"
_SHADOW = Path(__file__).parent / "fixtures" / "root_package_shadow"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_ROOT))


@pytest.fixture
def shadow_analyzer() -> JediAnalyzer:
    analyzer = JediAnalyzer(str(_SHADOW))
    analyzer.source_roots = [_SHADOW / "a", _SHADOW / "b"]
    return analyzer


class TestRootPackage:
    @pytest.mark.asyncio
    async def test_bare_package_resolves_to_single_root(self, analyzer: JediAnalyzer) -> None:
        # The fixture has a top-level `mypkg` package AND a deeper symbol named
        # `mypkg` (mypkg.inner.mypkg); resolve must pick the root, not ambiguate.
        result = await resolve("mypkg", analyzer)
        assert result.get("found") is True
        assert result.get("ambiguous") is not True
        assert result.get("handle") == "mypkg"
        assert result.get("kind") == "module"

    @pytest.mark.asyncio
    async def test_deeper_symbol_still_reachable_by_dotted_handle(
        self, analyzer: JediAnalyzer
    ) -> None:
        result = await resolve("mypkg.inner.mypkg", analyzer)
        assert result.get("found") is True
        assert result.get("handle") == "mypkg.inner.mypkg"

    @pytest.mark.asyncio
    async def test_dotted_handle_unchanged(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("mypkg.inner", analyzer)
        assert result.get("found") is True
        assert result.get("handle") == "mypkg.inner"


class TestShadow:
    @pytest.mark.asyncio
    async def test_same_name_shadow_across_roots_stays_ambiguous(
        self, shadow_analyzer: JediAnalyzer
    ) -> None:
        # Two genuinely different top-level packages sharing an import name across
        # two roots: same handle, DIFFERENT files.  Promoting either would hide
        # the collision, so stay ambiguous (#423 review #7).
        result = await resolve("mypkg", shadow_analyzer)
        assert result.get("found") is True
        assert result.get("ambiguous") is True
        files = sorted(Path(c["location"]["file"]).parent.parent.name for c in result["candidates"])
        assert files == ["a", "b"]
        assert {c["handle"] for c in result["candidates"]} == {"mypkg"}

    @pytest.mark.asyncio
    async def test_shadow_beats_exact_module(self, shadow_analyzer: JediAnalyzer) -> None:
        result = await resolve_name("mypkg", shadow_analyzer)
        assert isinstance(result, Ambiguous)
        assert len(result.candidates) == 2
