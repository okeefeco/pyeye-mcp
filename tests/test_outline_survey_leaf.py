"""Tests for #596 — ``outline`` package-survey mode must not report unwalked nodes as empty.

Survey mode (#423) walks the ``submodules`` containment edge, so a node's
*members* are never walked.  Before #596 such a node came back as
``children: []`` — which Contract 1 defines as *measured empty* — even when it had
members.  These tests pin the fixed shape:

- a survey leaf WITH members → ``truncated: true, truncation_reason: "survey_leaf"``
  and ``children`` absent (recovery: ``outline(<that module>)``);
- a survey leaf with NO members → ``children: []`` (a genuine leaf);
- a walked package whose ``__init__`` defines members → ``init_member_count: N``
  (omitted when N == 0), so the submodules-only view never hides them silently;
- a package root with no submodules → member mode (survey of nothing is useless,
  and ``survey_leaf`` pointing back at itself would be circular).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.edges import resolve_members
from pyeye.mcp.operations.inspect import _resolve_handle_to_jedi_name
from pyeye.mcp.operations.outline import outline
from tests.conformance.response_linter import lint_response

_SURVEY = Path(__file__).parent / "fixtures" / "containment" / "survey"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_SURVEY))


def _child(tree: dict, handle: str) -> dict:
    return next(c for c in tree["children"] if c["node"]["handle"] == handle)


def _assert_survey_leaf(node: dict) -> None:
    assert node.get("truncated") is True
    assert node["truncation_reason"] == "survey_leaf"
    assert "children" not in node, "a survey_leaf was not walked: children must be absent"
    assert "member_count" not in node, "survey_leaf deliberately carries no count (cost)"


def _assert_genuine_leaf(node: dict) -> None:
    assert node["children"] == []
    assert "truncated" not in node
    assert "truncation_reason" not in node


async def _member_count(handle: str, analyzer: JediAnalyzer) -> int:
    jedi_name = await _resolve_handle_to_jedi_name(handle, analyzer)
    assert jedi_name is not None
    return len(resolve_members(jedi_name, analyzer).adjacents)


class TestSurveyLeafNodes:
    @pytest.mark.asyncio
    async def test_children_are_the_submodules(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer)
        handles = {c["node"]["handle"] for c in tree["children"]}
        assert handles == {
            "svpkg.full",
            "svpkg.empty",
            "svpkg.initonly",
            "svpkg.bare",
            "svpkg.nested",
            "svpkg.both",
        }

    @pytest.mark.asyncio
    async def test_plain_module_with_members_is_survey_leaf(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer)
        _assert_survey_leaf(_child(tree, "svpkg.full"))

    @pytest.mark.asyncio
    async def test_plain_module_without_members_is_genuine_leaf(
        self, analyzer: JediAnalyzer
    ) -> None:
        tree = await outline("svpkg", analyzer)
        _assert_genuine_leaf(_child(tree, "svpkg.empty"))

    @pytest.mark.asyncio
    async def test_submoduleless_package_with_members_at_frontier(
        self, analyzer: JediAnalyzer
    ) -> None:
        # The jaraco.context shape: __init__ members, no submodules, at the
        # depth-1 frontier.  Not max_depth (deeper survey would never walk its
        # members) and not children: [] (it is not empty).
        tree = await outline("svpkg", analyzer)
        _assert_survey_leaf(_child(tree, "svpkg.initonly"))

    @pytest.mark.asyncio
    async def test_submoduleless_package_with_members_unbounded(
        self, analyzer: JediAnalyzer
    ) -> None:
        tree = await outline("svpkg", analyzer, max_depth=None)
        _assert_survey_leaf(_child(tree, "svpkg.initonly"))

    @pytest.mark.asyncio
    async def test_empty_package_is_genuine_leaf(self, analyzer: JediAnalyzer) -> None:
        for depth in (1, None):
            tree = await outline("svpkg", analyzer, max_depth=depth)
            _assert_genuine_leaf(_child(tree, "svpkg.bare"))

    @pytest.mark.asyncio
    async def test_package_with_submodules_still_max_depth(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer)
        nested = _child(tree, "svpkg.nested")
        assert nested.get("truncated") is True
        assert nested["truncation_reason"] == "max_depth"
        assert "children" not in nested

    @pytest.mark.asyncio
    async def test_nested_plain_module_is_survey_leaf(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer, max_depth=None)
        nested = _child(tree, "svpkg.nested")
        _assert_survey_leaf(_child(nested, "svpkg.nested.inner"))

    @pytest.mark.asyncio
    async def test_survey_leaf_under_exhausted_budget(self, analyzer: JediAnalyzer) -> None:
        # A plain module leaf is classified before the budget check, so a tight
        # budget never turns it back into a false children: [].
        tree = await outline("svpkg", analyzer, max_nodes=7)
        _assert_survey_leaf(_child(tree, "svpkg.full"))
        _assert_genuine_leaf(_child(tree, "svpkg.empty"))
        # Packages hit the exhausted-budget peek: a submodule-less package with
        # members is still a survey_leaf, never a max_nodes "0 members" or a [].
        _assert_survey_leaf(_child(tree, "svpkg.initonly"))
        _assert_genuine_leaf(_child(tree, "svpkg.bare"))

    @pytest.mark.asyncio
    async def test_recovery_route_lists_the_members(self, analyzer: JediAnalyzer) -> None:
        # survey_leaf's documented recovery — outline the leaf itself — works.
        tree = await outline("svpkg.full", analyzer)
        assert "svpkg.full.full_fn" in {c["node"]["handle"] for c in tree["children"]}


class TestInitMemberDisclosure:
    @pytest.mark.asyncio
    async def test_root_discloses_init_member_count(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer)
        expected = await _member_count("svpkg", analyzer)
        assert expected > 0
        assert tree["init_member_count"] == expected
        # The members themselves are still NOT listed (submodules-only view).
        assert "svpkg.init_fn" not in {c["node"]["handle"] for c in tree["children"]}

    @pytest.mark.asyncio
    async def test_walked_subpackage_discloses_init_member_count(
        self, analyzer: JediAnalyzer
    ) -> None:
        tree = await outline("svpkg", analyzer, max_depth=None)
        both = _child(tree, "svpkg.both")
        assert both["init_member_count"] == await _member_count("svpkg.both", analyzer)
        assert {c["node"]["handle"] for c in both["children"]} == {"svpkg.both.leaf"}

    @pytest.mark.asyncio
    async def test_init_member_count_absent_when_zero(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg.nested", analyzer)
        assert "init_member_count" not in tree
        walked = await outline("svpkg", analyzer, max_depth=None)
        assert "init_member_count" not in _child(walked, "svpkg.nested")

    @pytest.mark.asyncio
    async def test_init_member_count_absent_on_truncated_nodes(
        self, analyzer: JediAnalyzer
    ) -> None:
        # A node that was not walked carries no init disclosure — it was not surveyed.
        tree = await outline("svpkg", analyzer)
        assert "init_member_count" not in _child(tree, "svpkg.both")


class TestSubmodulelessPackageRoot:
    @pytest.mark.asyncio
    async def test_root_without_submodules_walks_members(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg.initonly", analyzer)
        handles = {c["node"]["handle"] for c in tree["children"]}
        assert "svpkg.initonly.initonly_fn" in handles
        assert "init_member_count" not in tree  # member mode: members are listed

    @pytest.mark.asyncio
    async def test_empty_package_root_is_genuine_leaf(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg.bare", analyzer)
        _assert_genuine_leaf(tree)


class TestConformance:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("max_depth", [1, 2, None])
    async def test_survey_responses_pass_the_linter(
        self, analyzer: JediAnalyzer, max_depth: int | None
    ) -> None:
        tree = await outline("svpkg", analyzer, max_depth=max_depth)
        lint_response(tree, "outline")  # raises on any violation
