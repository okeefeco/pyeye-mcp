"""Default caps on expand's stubs and resolve's ambiguous candidates (#435 slice B).

The user's decision on #435:
- caps ON by default: ``expand`` returns at most 200 stubs (``max_stubs``) and an
  ambiguous ``resolve`` at most 50 candidates (``max_candidates``); ``None`` lifts
  either cap;
- leave out, never false: when nothing is cut there is no ``truncated`` /
  ``truncation_reasons`` / ``total``; when a cap cuts, all three are present.

``trace`` is not capped this way: it walks ``expand_resolved`` with no cap and
has its own node budget.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.exceptions import ValidationError
from pyeye.mcp.operations.completeness import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_STUBS,
    cap_items,
)
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.resolve import resolve
from pyeye.mcp.operations.trace import trace
from tests.conformance.response_linter import lint_response

server = importlib.import_module("pyeye.mcp.server")

_WIDE = 250  # members in the wide module: more than the default cap
_DUPES = 3  # modules each defining `helper`


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "cappkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "wide.py").write_text(
        "".join(f"def f{i:03d}() -> int:\n    return {i}\n\n\n" for i in range(_WIDE)),
        encoding="utf-8",
    )
    (pkg / "small.py").write_text("def one() -> int:\n    return 1\n", encoding="utf-8")
    for i in range(_DUPES):
        (pkg / f"dup{i}.py").write_text("def helper() -> int:\n    return 0\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def analyzer(project: Path) -> JediAnalyzer:
    return JediAnalyzer(project.as_posix())


def _assert_cut(result: dict, key: str, reason: str, kept: int, total: int) -> None:
    assert len(result[key]) == kept
    assert result["truncated"] is True
    assert result["truncation_reasons"] == [reason]
    assert result["total"] == total


def _assert_not_cut(result: dict) -> None:
    for field in ("truncated", "truncation_reasons", "total"):
        assert field not in result, f"{field} must be left out when nothing was cut"


class TestDefaults:
    def test_documented_defaults(self) -> None:
        assert DEFAULT_MAX_STUBS == 200
        assert DEFAULT_MAX_CANDIDATES == 50

    @pytest.mark.asyncio
    async def test_expand_returns_at_most_200_by_default(self, analyzer: JediAnalyzer) -> None:
        result = await expand("cappkg.wide", "members", analyzer)
        _assert_cut(result, "stubs", "max_stubs", DEFAULT_MAX_STUBS, _WIDE)
        lint_response(result, "expand")

    @pytest.mark.asyncio
    async def test_none_lifts_the_cap(self, analyzer: JediAnalyzer) -> None:
        result = await expand("cappkg.wide", "members", analyzer, max_stubs=None)
        assert len(result["stubs"]) == _WIDE
        _assert_not_cut(result)
        lint_response(result, "expand")

    @pytest.mark.asyncio
    async def test_small_edge_is_not_cut(self, analyzer: JediAnalyzer) -> None:
        result = await expand("cappkg.small", "members", analyzer)
        assert [s["handle"] for s in result["stubs"]] == ["cappkg.small.one"]
        _assert_not_cut(result)


class TestExpandCap:
    @pytest.mark.asyncio
    async def test_cut_keeps_the_first_stubs_in_order(self, analyzer: JediAnalyzer) -> None:
        full = await expand("cappkg.wide", "members", analyzer, max_stubs=None)
        cut = await expand("cappkg.wide", "members", analyzer, max_stubs=5)
        _assert_cut(cut, "stubs", "max_stubs", 5, _WIDE)
        assert cut["stubs"] == full["stubs"][:5]
        assert cut["ceiling"] == full["ceiling"]  # the other fields are unchanged
        lint_response(cut, "expand")

    @pytest.mark.asyncio
    async def test_cap_equal_to_size_is_not_a_cut(self, analyzer: JediAnalyzer) -> None:
        _assert_not_cut(await expand("cappkg.wide", "members", analyzer, max_stubs=_WIDE))

    @pytest.mark.asyncio
    async def test_trace_is_not_capped_by_expand(self, analyzer: JediAnalyzer) -> None:
        graph = await trace("cappkg.wide", ["members"], analyzer, max_depth=1, max_nodes=1000)
        assert len(graph["nodes"]) == _WIDE + 1
        assert graph["truncated"] is False  # trace's own (pre-#435) always-present flag


class TestResolveCap:
    @pytest.mark.asyncio
    async def test_ambiguous_under_the_default_is_not_cut(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("helper", analyzer)
        assert result.get("ambiguous") is True
        assert len(result["candidates"]) == _DUPES
        _assert_not_cut(result)
        lint_response(result, "resolve")

    @pytest.mark.asyncio
    async def test_cut_keeps_the_first_candidates_in_sorted_order(
        self, analyzer: JediAnalyzer
    ) -> None:
        full = await resolve("helper", analyzer, max_candidates=None)
        cut = await resolve("helper", analyzer, max_candidates=2)
        _assert_cut(cut, "candidates", "max_candidates", 2, _DUPES)
        assert cut["candidates"] == full["candidates"][:2]
        lint_response(cut, "resolve")


class TestInvalidCaps:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [0, -1, True, 2.5, "10"])
    async def test_bad_caps_are_caller_errors(self, analyzer: JediAnalyzer, bad: object) -> None:
        with pytest.raises(ValidationError, match="max_stubs"):
            await expand("cappkg.wide", "members", analyzer, max_stubs=bad)  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="max_candidates"):
            await resolve("helper", analyzer, max_candidates=bad)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_bad_cap_reaches_the_client_as_a_tool_error(self, project: Path) -> None:
        with pytest.raises(ToolError, match="ValidationError.*max_stubs"):
            await server.expand("cappkg.wide", "members", project.as_posix(), max_stubs=0)


class TestHelper:
    def test_cap_items_is_all_or_nothing(self) -> None:
        assert cap_items([1, 2], 5, "max_stubs", "max_stubs") == ([1, 2], {})
        assert cap_items([1, 2, 3], None, "max_stubs", "max_stubs") == ([1, 2, 3], {})
        kept, fields = cap_items([1, 2, 3], 2, "max_stubs", "max_stubs")
        assert kept == [1, 2]
        assert fields == {"truncated": True, "truncation_reasons": ["max_stubs"], "total": 3}
