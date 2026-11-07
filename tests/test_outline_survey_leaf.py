"""Tests for #596 — ``outline`` package-survey mode must not report unwalked nodes as empty.

Survey mode (#423) walks the ``submodules`` containment edge, so a node's
*members* are never walked.  Before #596 such a node came back as
``children: []`` — which Contract 1 defines as *measured empty* — even when it had
members.  These tests pin the fixed shape:

- a survey leaf WITH members → ``truncated: true, truncation_reason: "survey_leaf"``
  and ``children`` absent (recovery: ``outline(<that module>)``);
- a survey leaf with NO members → ``children: []`` (a genuine leaf);
- a walked package whose ``__init__`` defines members → ``member_count: N``
  (omitted when N == 0), so the submodules-only view never hides them silently;
- every ``<edge>_count`` names its edge (#599): a survey-mode ``max_nodes``
  truncation withholds SUBMODULES, so it carries ``submodule_count`` — and any
  ``X_count`` equals ``inspect(h).edge_counts[X]``, on every node, in every mode;
- a package root with no submodules → member mode (survey of nothing is useless,
  and ``survey_leaf`` pointing back at itself would be circular).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
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


async def _edge_counts(handle: str, analyzer: JediAnalyzer) -> dict[str, int]:
    node = await inspect(handle, analyzer)
    assert node["found"] is True
    return node["edge_counts"]


# ``<edge>_count`` key in an outline node → the ``inspect().edge_counts`` key it mirrors.
_COUNT_KEYS: dict[str, str] = {"member_count": "members", "submodule_count": "submodules"}


def _nodes(tree: dict):
    yield tree
    for child in tree.get("children", []):
        yield from _nodes(child)


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


class TestUnlistedMemberDisclosure:
    @pytest.mark.asyncio
    async def test_root_discloses_member_count(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer)
        expected = (await _edge_counts("svpkg", analyzer))["members"]
        assert expected > 0
        assert tree["member_count"] == expected
        # The members themselves are still NOT listed (submodules-only view).
        assert "svpkg.init_fn" not in {c["node"]["handle"] for c in tree["children"]}

    @pytest.mark.asyncio
    async def test_walked_subpackage_discloses_member_count(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer, max_depth=None)
        both = _child(tree, "svpkg.both")
        assert both["member_count"] == (await _edge_counts("svpkg.both", analyzer))["members"]
        assert {c["node"]["handle"] for c in both["children"]} == {"svpkg.both.leaf"}

    @pytest.mark.asyncio
    async def test_member_count_absent_when_zero(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg.nested", analyzer)
        assert "member_count" not in tree
        walked = await outline("svpkg", analyzer, max_depth=None)
        assert "member_count" not in _child(walked, "svpkg.nested")

    @pytest.mark.asyncio
    async def test_no_count_on_depth_truncated_nodes(self, analyzer: JediAnalyzer) -> None:
        # A max_depth cut node was not surveyed: it carries no count of any edge.
        tree = await outline("svpkg", analyzer)
        both = _child(tree, "svpkg.both")
        assert both["truncation_reason"] == "max_depth"
        assert not set(_COUNT_KEYS) & set(both)


class TestSurveyMaxNodesCount:
    """#599 — a survey-mode max_nodes cut withholds submodules and says so."""

    @pytest.mark.asyncio
    async def test_root_cut_carries_submodule_count(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg", analyzer, max_nodes=1)
        counts = await _edge_counts("svpkg", analyzer)
        assert counts["members"] != counts["submodules"], "fixture must tell them apart"
        assert tree["truncated"] is True
        assert tree["truncation_reason"] == "max_nodes"
        assert tree["submodule_count"] == counts["submodules"]
        assert "member_count" not in tree
        assert "children" not in tree

    @pytest.mark.asyncio
    async def test_budget_full_subpackage_cut_carries_submodule_count(
        self, analyzer: JediAnalyzer
    ) -> None:
        # Root + its 6 submodules fill a budget of 7, so the walk reaches svpkg.both
        # with no room left: the budget-full peek path.
        tree = await outline("svpkg", analyzer, max_nodes=7, max_depth=None)
        both = _child(tree, "svpkg.both")
        assert both["truncation_reason"] == "max_nodes"
        assert both["submodule_count"] == (await _edge_counts("svpkg.both", analyzer))["submodules"]
        assert "member_count" not in both

    @pytest.mark.asyncio
    async def test_member_mode_cut_still_carries_member_count(self, analyzer: JediAnalyzer) -> None:
        # Member mode is unchanged: a module root cut by max_nodes withholds members.
        tree = await outline("svpkg.initonly", analyzer, max_nodes=1)
        assert tree["truncation_reason"] == "max_nodes"
        assert tree["member_count"] == (await _edge_counts("svpkg.initonly", analyzer))["members"]
        assert "submodule_count" not in tree


class TestCountInvariant:
    """Every ``X_count`` on every node equals ``inspect(h).edge_counts[X]`` (#599).

    The linter is pure (no analyzer), so it can check only the SHAPE of counts;
    this is the value check, swept over modes, depths and budgets.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle", ["svpkg", "svpkg.both", "svpkg.nested", "svpkg.initonly", "svpkg.full"]
    )
    @pytest.mark.parametrize("max_depth", [1, None])
    @pytest.mark.parametrize("max_nodes", [1, 2, 4, 7, 9, 200])
    async def test_every_count_matches_inspect(
        self,
        analyzer: JediAnalyzer,
        handle: str,
        max_depth: int | None,
        max_nodes: int,
    ) -> None:
        tree = await outline(handle, analyzer, max_depth=max_depth, max_nodes=max_nodes)
        for node in _nodes(tree):
            for key, edge in _COUNT_KEYS.items():
                if key in node:
                    h = node["node"]["handle"]
                    expected = (await _edge_counts(h, analyzer))[edge]
                    assert node[key] == expected, f"{h}.{key}={node[key]} != {edge}={expected}"


class TestSubmodulelessPackageRoot:
    @pytest.mark.asyncio
    async def test_root_without_submodules_walks_members(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg.initonly", analyzer)
        handles = {c["node"]["handle"] for c in tree["children"]}
        assert "svpkg.initonly.initonly_fn" in handles
        assert "member_count" not in tree  # member mode: members ARE the children

    @pytest.mark.asyncio
    async def test_empty_package_root_is_genuine_leaf(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("svpkg.bare", analyzer)
        _assert_genuine_leaf(tree)


class TestConformance:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("max_depth", [1, 2, None])
    @pytest.mark.parametrize("max_nodes", [1, 7, 9, 200])
    async def test_survey_responses_pass_the_linter(
        self, analyzer: JediAnalyzer, max_depth: int | None, max_nodes: int
    ) -> None:
        tree = await outline("svpkg", analyzer, max_depth=max_depth, max_nodes=max_nodes)
        lint_response(tree, "outline")  # raises on any violation
