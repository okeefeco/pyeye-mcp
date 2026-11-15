"""A source file the server's Python can't parse is never reported as measured-empty (#703).

Before #703 the per-file resolvers wrapped ``get_ast`` in ``except Exception:
return []``, so a module using newer syntax than the server's interpreter (a
3.14 t-string on a 3.12 server) outlined as ``children: []``, expanded as
``stubs: []`` and counted ``edge_counts.members: 0``: "couldn't parse" read as
"has none". Now a parse failure on the source's own file is:

- ``expand`` / ``trace``: the unsupported branch, ``reason: "unparseable"``;
- ``outline``: ``truncated: true``, ``truncation_reason: "unparseable"``,
  ``children`` absent;
- ``inspect``: the count (and a class's ``superclasses`` field) omitted.

The fixture is invalid on EVERY interpreter (``def broken(:``), so these tests
run on every CI leg. Only parse failures map to ``unparseable``; other failures
keep their existing handling (#704).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations import edges
from pyeye.mcp.operations.edges import UnparseableSource, parse_own_source
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.trace import trace
from tests.conformance.response_linter import lint_response

_BROKEN = (
    "import os\n\n\n"
    "class Base:\n"
    "    pass\n\n\n"
    "class Child(Base):\n"
    "    def method(self) -> int:\n"
    "        return 1\n\n\n"
    "def broken(:\n"
    "    pass\n\n\n"
    "def after() -> int:\n"
    "    return 3\n"
)
_OK = "import os\n\n\ndef fine() -> int:\n    return 1\n"
_BROKEN_LINE = 13  # the `def broken(:` line


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "upkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "broken.py").write_text(_BROKEN, encoding="utf-8")
    (pkg / "ok.py").write_text(_OK, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix())


def _assert_unparseable_branch(result: dict[str, Any], edge: str) -> None:
    assert result["found"] is True
    assert result["edge"] == edge
    assert result["unsupported"] is True
    assert result["reason"] == "unparseable"
    assert "stubs" not in result, "unparseable must never be a measured stubs: []"
    detail = result["detail"]
    assert "broken.py" in detail
    assert f"line {_BROKEN_LINE}" in detail
    assert f"{sys.version_info.major}.{sys.version_info.minor}" in detail
    assert result["report_issues"]
    lint_response(result, "expand")


class TestExpand:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("edge", ["members", "imports"])
    async def test_module_edges_are_unparseable(self, analyzer: JediAnalyzer, edge: str) -> None:
        _assert_unparseable_branch(await expand("upkg.broken", edge, analyzer), edge)

    @pytest.mark.asyncio
    async def test_superclasses_of_a_class_in_the_file_are_unparseable(
        self, analyzer: JediAnalyzer
    ) -> None:
        _assert_unparseable_branch(
            await expand("upkg.broken.Child", "superclasses", analyzer), "superclasses"
        )

    @pytest.mark.asyncio
    async def test_parseable_sibling_is_unaffected(self, analyzer: JediAnalyzer) -> None:
        result = await expand("upkg.ok", "members", analyzer)
        assert [s["handle"] for s in result["stubs"]] == ["upkg.ok.fine"]
        assert [s["handle"] for s in (await expand("upkg.ok", "imports", analyzer))["stubs"]] == [
            "os"
        ]


class TestInspect:
    @pytest.mark.asyncio
    async def test_module_member_count_is_omitted_not_zero(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("upkg.broken", analyzer)
        assert node["found"] is True
        assert "members" not in node["edge_counts"]
        # Not linted: the linter's B.3 rule assumes every measurement succeeded,
        # so it can't tell an honest omission (here, or a timeout) from a gap.

    @pytest.mark.asyncio
    async def test_class_superclasses_are_omitted_not_empty(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("upkg.broken.Child", analyzer)
        assert node["found"] is True
        assert "superclasses" not in node, "unknown bases must be omitted, never []"
        assert "superclasses" not in node["edge_counts"]
        # Not linted: see test_module_member_count_is_omitted_not_zero.

    @pytest.mark.asyncio
    async def test_parseable_sibling_still_counts(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("upkg.ok", analyzer)
        assert node["edge_counts"]["members"] == 1


class TestOutline:
    @pytest.mark.asyncio
    async def test_unparseable_root_is_truncated_not_empty(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("upkg.broken", analyzer)
        assert tree["found"] is True
        assert "children" not in tree, "unparseable must never be a measured children: []"
        assert tree["truncated"] is True
        assert tree["truncation_reason"] == "unparseable"
        assert "member_count" not in tree
        lint_response(tree, "outline")

    @pytest.mark.asyncio
    async def test_survey_marks_only_the_unparseable_module(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("upkg", analyzer)
        by_handle = {c["node"]["handle"]: c for c in tree["children"]}
        broken, ok = by_handle["upkg.broken"], by_handle["upkg.ok"]
        assert broken["truncation_reason"] == "unparseable"
        assert "children" not in broken
        assert ok["truncation_reason"] == "survey_leaf"
        lint_response(tree, "outline")


class TestTrace:
    @pytest.mark.asyncio
    async def test_unparseable_hop_is_an_unsupported_edge(self, analyzer: JediAnalyzer) -> None:
        graph = await trace("upkg.broken", ["members"], analyzer)
        reasons = {(u["edge"], u["reason"]) for u in graph["unsupported_edges"]}
        assert ("members", "unparseable") in reasons
        assert graph["report_issues"]
        lint_response(graph, "trace")


class TestOnlyParseErrorsAreMapped:
    def test_syntax_error_becomes_unparseable(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.py"
        bad.write_text("def f(:\n    pass\n", encoding="utf-8")
        with pytest.raises(UnparseableSource) as info:
            parse_own_source(bad)
        assert info.value.lineno == 1
        assert isinstance(info.value.__cause__, SyntaxError)

    def test_other_failures_propagate_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Narrowed to parse errors (#703); everything else is left for #704."""

        def boom(_path: Any) -> Any:
            raise PermissionError("denied")

        monkeypatch.setattr(file_artifact_cache, "get_ast", boom)
        with pytest.raises(PermissionError):
            parse_own_source("whatever.py")

    @pytest.mark.asyncio
    async def test_a_non_parse_failure_propagates(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Jedi failure is internal: it propagates (#704), never ``unparseable``."""

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("jedi broke")

        monkeypatch.setattr(edges.file_artifact_cache, "get_script", boom)
        with pytest.raises(RuntimeError, match="jedi broke"):
            await expand("upkg.ok", "members", analyzer)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("edge", ["members", "imports"])
    async def test_a_non_parse_ast_failure_propagates(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch, edge: str
    ) -> None:
        """Only ``SyntaxError`` maps to unparseable; any other read failure is
        internal and propagates (#704). A namespace package's directory never
        reaches the read: ``edges._own_source`` answers it first."""

        def denied(_path: Any) -> Any:
            raise IsADirectoryError("is a directory")

        monkeypatch.setattr(edges.file_artifact_cache, "get_ast", denied)
        with pytest.raises(IsADirectoryError):
            await expand("upkg.ok", edge, analyzer)


@pytest.mark.skipif(sys.version_info >= (3, 14), reason="these modules parse on 3.14 (#543)")
class TestNewerSyntaxOnAnOlderServer:
    """The #703 report: 3.14-only syntax analysed by an older server."""

    _MODULES = {
        "tstr": 'def render(name):\n    return t"hello {name}"\n\n\ndef after() -> int:\n    return 3\n',
        "exc": (
            "def guard() -> int:\n    try:\n        return 1\n"
            "    except ValueError, TypeError:\n        return 0\n"
        ),
    }

    @pytest.fixture
    def newer(self, tmp_path: Path) -> JediAnalyzer:
        pkg = tmp_path / "p314"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        for name, source in self._MODULES.items():
            (pkg / f"{name}.py").write_text(source, encoding="utf-8")
        return JediAnalyzer(tmp_path.as_posix())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("module", ["tstr", "exc"])
    async def test_outline_reports_unparseable_not_empty(
        self, newer: JediAnalyzer, module: str
    ) -> None:
        tree = await outline(f"p314.{module}", newer)
        assert tree["truncation_reason"] == "unparseable"
        assert "children" not in tree
        result = await expand(f"p314.{module}", "members", newer)
        assert result["reason"] == "unparseable"
