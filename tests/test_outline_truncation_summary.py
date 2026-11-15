"""outline's result-level summary and budget counts (#435).

- The root carries ``truncation_reasons``: the sorted set of every node's
  ``truncation_reason``, absent when nothing was cut (named like trace's).
- A ``max_depth`` cut is a budget truncation, so, like ``max_nodes``, it counts
  what it withheld, named for the edge walked, and the count equals ``inspect``'s.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from tests.conformance.response_linter import lint_response

_FIXTURES = Path(__file__).parent / "fixtures"
_NESTED = _FIXTURES / "nested_class_inspect"
_SURVEY = _FIXTURES / "containment" / "survey"


def _nodes(tree: dict[str, Any]):
    yield tree
    for child in tree.get("children", []):
        yield from _nodes(child)


@pytest.fixture
def nested() -> JediAnalyzer:
    return JediAnalyzer(str(_NESTED))


@pytest.fixture
def survey() -> JediAnalyzer:
    return JediAnalyzer(str(_SURVEY))


class TestSummary:
    @pytest.mark.asyncio
    async def test_fully_walked_tree_has_no_summary(self, nested: JediAnalyzer) -> None:
        tree = await outline("pkg.mod", nested, max_depth=None)
        assert not any(n.get("truncated") for n in _nodes(tree))
        assert "truncation_reasons" not in tree

    @pytest.mark.asyncio
    async def test_depth_cut_is_summarised(self, nested: JediAnalyzer) -> None:
        tree = await outline("pkg.mod", nested)  # max_depth=1: Outer is cut
        assert tree["truncation_reasons"] == ["max_depth"]
        lint_response(tree, "outline")

    @pytest.mark.asyncio
    async def test_root_max_nodes_cut_is_summarised(self, nested: JediAnalyzer) -> None:
        tree = await outline("pkg.mod", nested, max_nodes=1)
        assert tree["truncation_reason"] == "max_nodes"
        assert tree["truncation_reasons"] == ["max_nodes"]
        lint_response(tree, "outline")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("max_nodes", [200, 4])
    async def test_survey_summary_is_the_union_of_node_reasons(
        self, survey: JediAnalyzer, max_nodes: int
    ) -> None:
        tree = await outline("svpkg", survey, max_nodes=max_nodes)
        expected = sorted({n["truncation_reason"] for n in _nodes(tree) if n.get("truncated")})
        assert expected, "the survey fixture always has survey_leaf nodes"
        assert tree["truncation_reasons"] == expected
        lint_response(tree, "outline")


class TestBudgetCounts:
    @pytest.mark.asyncio
    async def test_member_mode_depth_cut_counts_members(self, nested: JediAnalyzer) -> None:
        tree = await outline("pkg.mod", nested)
        outer = next(c for c in tree["children"] if c["node"]["handle"] == "pkg.mod.Outer")
        assert outer["truncation_reason"] == "max_depth"
        edge_counts = (await inspect("pkg.mod.Outer", nested))["edge_counts"]
        assert outer["member_count"] == edge_counts["members"]
        assert "submodule_count" not in outer
