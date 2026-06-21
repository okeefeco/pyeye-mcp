"""Tests for ``outline`` package-survey mode (#423, Task 7).

When the ROOT handle is a package, ``outline`` switches to *survey mode*: it
walks the ``submodules`` containment edge (not ``members``), defaults to depth-1,
and treats plain modules as leaves (their members are NOT walked).  A subpackage
with children at the depth frontier is truncated (``max_depth``), preserving the
§4.2 absence contracts.

``outline`` of a *module* or *class* root is unchanged (survey mode off) — the
regression suite for that lives in ``tests/unit`` / ``tests/integration``; here we
only assert the new package-handle contract, plus one explicit guard that a
module root still walks members.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.outline import outline

_REGULAR = Path(__file__).parent / "fixtures" / "containment" / "regular"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_REGULAR))


def _child(tree: dict, handle: str) -> dict:
    return next(c for c in tree["children"] if c["node"]["handle"] == handle)


class TestOutlinePackageSurvey:
    @pytest.mark.asyncio
    async def test_depth1_default_lists_submodules(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("mypkg", analyzer)
        handles = {c["node"]["handle"] for c in tree["children"]}
        assert handles == {"mypkg.alpha", "mypkg.beta", "mypkg.sub"}

    @pytest.mark.asyncio
    async def test_subpackage_truncated_at_depth1(self, analyzer: JediAnalyzer) -> None:
        # mypkg.sub is a package WITH children → at the depth-1 frontier it is
        # truncated (max_depth), with NO children key (absence contract).
        tree = await outline("mypkg", analyzer)
        sub = _child(tree, "mypkg.sub")
        assert sub.get("truncated") is True
        assert sub["truncation_reason"] == "max_depth"
        assert "children" not in sub

    @pytest.mark.asyncio
    async def test_plain_module_children_are_leaves(self, analyzer: JediAnalyzer) -> None:
        # alpha/beta are plain modules: in survey mode their members are NOT
        # walked — they are leaves with children == [] and no truncated key.
        tree = await outline("mypkg", analyzer)
        for h in ("mypkg.alpha", "mypkg.beta"):
            node = _child(tree, h)
            assert node["children"] == []
            assert "truncated" not in node

    @pytest.mark.asyncio
    async def test_depth2_expands_subpackage(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("mypkg", analyzer, max_depth=2)
        sub = _child(tree, "mypkg.sub")
        gamma = {c["node"]["handle"] for c in sub["children"]}
        assert gamma == {"mypkg.sub.gamma"}

    @pytest.mark.asyncio
    async def test_reexports_not_listed(self, analyzer: JediAnalyzer) -> None:
        # mypkg/__init__.py re-exports `A` and defines `__all__`; survey mode is
        # submodules-only, so neither appears among the children.
        tree = await outline("mypkg", analyzer)
        handles = {c["node"]["handle"] for c in tree["children"]}
        assert "mypkg.A" not in handles
        assert "mypkg.__all__" not in handles


class TestOutlineModuleRootUnchanged:
    @pytest.mark.asyncio
    async def test_module_root_walks_members_not_submodules(self, analyzer: JediAnalyzer) -> None:
        # A MODULE root (alpha.py, not a package) stays in members mode: it walks
        # the class A defined in it, proving survey mode did not hijack modules.
        tree = await outline("mypkg.alpha", analyzer)
        handles = {c["node"]["handle"] for c in tree["children"]}
        assert "mypkg.alpha.A" in handles
