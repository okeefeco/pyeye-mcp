"""Regression tests for #697: a symbol defined in a package ``__init__`` is not a package.

``outline`` chose package survey mode (#423/#596) from the ``module_path`` alone.
A class or function defined in ``pkg/__init__.py`` shares that path, so when the
package had submodules, ``outline(<class>)`` returned the package's submodules
(as fake handles like ``pkg.Widget.sub``, ``truncated: "survey_leaf"``) in place
of the class's members. Python 3.14 exposed it through ``pathlib.Path``, which moved
into ``pathlib/__init__.py``; these tests use a project fixture so they fail on
every Python version without the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.outline import outline
from tests.conformance.response_linter import lint_response

_FIXTURE = Path(__file__).parent / "fixtures" / "containment" / "class_in_init"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURE))


def _child_handles(tree: dict) -> list[str]:
    return [c["node"]["handle"] for c in tree.get("children", [])]


def _assert_no_survey(tree: dict) -> None:
    """No node in *tree* carries a survey-mode marker."""
    stack = [tree]
    while stack:
        node = stack.pop()
        assert node.get("truncation_reason") != "survey_leaf", node["node"]["handle"]
        assert "submodule_count" not in node, node["node"]["handle"]
        stack.extend(node.get("children", []))


class TestClassInPackageInit:
    @pytest.mark.asyncio
    async def test_class_outline_lists_its_members_not_submodules(
        self, analyzer: JediAnalyzer
    ) -> None:
        tree = await outline("cipkg.Widget", analyzer)
        assert tree["found"] is True
        assert tree["node"]["kind"] == "class"
        assert _child_handles(tree) == [
            "cipkg.Widget.size",
            "cipkg.Widget.grow",
            "cipkg.Widget.Part",
        ]
        _assert_no_survey(tree)
        # member_count is a survey-package disclosure; a walked class has none.
        assert "member_count" not in tree
        lint_response(tree, "outline")

    @pytest.mark.asyncio
    async def test_class_outline_matches_members_edge(self, analyzer: JediAnalyzer) -> None:
        """outline walks ``members``, so its children equal ``expand(members)``."""
        tree = await outline("cipkg.Widget", analyzer)
        edge = await expand("cipkg.Widget", "members", analyzer)
        assert _child_handles(tree) == [s["handle"] for s in edge["stubs"]]

    @pytest.mark.asyncio
    async def test_function_in_init_is_a_leaf(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("cipkg.helper", analyzer)
        assert tree["node"]["kind"] == "function"
        assert tree["children"] == []
        assert "truncated" not in tree
        assert "member_count" not in tree
        lint_response(tree, "outline")

    @pytest.mark.asyncio
    async def test_nested_class_in_init_is_not_surveyed(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("cipkg.Widget", analyzer, max_depth=None)
        _assert_no_survey(tree)
        part = next(c for c in tree["children"] if c["node"]["handle"] == "cipkg.Widget.Part")
        assert part["children"] == []

    @pytest.mark.asyncio
    async def test_package_itself_is_still_surveyed(self, analyzer: JediAnalyzer) -> None:
        """The fix narrows survey mode to modules; the package root still surveys."""
        tree = await outline("cipkg", analyzer)
        assert _child_handles(tree) == ["cipkg.sub"]
        # Widget + helper are disclosed as the package __init__'s own members.
        assert tree["member_count"] == 2
