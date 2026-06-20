"""End-to-end acceptance for the ``submodules`` containment stack (#423, Task 10).

Proves the three-tier stack the single edge registration unlocks works together
on a real multi-level package, using ONLY handles (no ``ls``/grep):

- the cold-start drill chain ``resolve → outline → expand → inspect``;
- ``trace(follow=["submodules"])`` stays bounded with an honest ``truncated`` flag;
- the count/enumeration invariant
  ``inspect(pkg).edge_counts["submodules"] == len(expand(pkg, "submodules").stubs)``
  holds end-to-end.

Fixture: the real ``tests/fixtures/containment/regular/mypkg`` tree
(``mypkg`` → {``alpha``, ``beta``, ``sub``} ; ``sub`` → {``gamma``}).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve
from pyeye.mcp.operations.trace import trace

_REGULAR = Path(__file__).parent / "fixtures" / "containment" / "regular"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_REGULAR))


class TestColdStartWorkflow:
    @pytest.mark.asyncio
    async def test_resolve_outline_expand_inspect_chain(self, analyzer: JediAnalyzer) -> None:
        # 1. resolve the package root by bare name.
        root = await resolve("mypkg", analyzer)
        assert root.get("found") is True
        assert root.get("handle") == "mypkg"

        # 2. outline the package → depth-1 submodule survey.
        tree = await outline("mypkg", analyzer)
        top = {c["node"]["handle"] for c in tree["children"]}
        assert top == {"mypkg.alpha", "mypkg.beta", "mypkg.sub"}

        # 3. expand the subpackage one hop → its children.
        sub = await expand("mypkg.sub", "submodules", analyzer)
        assert {s["handle"] for s in sub["stubs"]} == {"mypkg.sub.gamma"}

        # 4. inspect a leaf module reached purely via handles.
        node = await inspect("mypkg.sub.gamma", analyzer)
        assert node["handle"] == "mypkg.sub.gamma"
        assert node["kind"] == "module"


class TestBoundedTrace:
    @pytest.mark.asyncio
    async def test_trace_respects_max_nodes(self, analyzer: JediAnalyzer) -> None:
        # A tight node budget must cut the tree and report it honestly — never an
        # unbounded dump.
        result = await trace("mypkg", follow=["submodules"], analyzer=analyzer, max_nodes=2)
        assert len(result["nodes"]) <= 2
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_trace_full_tree_within_budget(self, analyzer: JediAnalyzer) -> None:
        # With ample budget the whole containment tree is reachable from the root.
        result = await trace(
            "mypkg", follow=["submodules"], analyzer=analyzer, max_depth=3, max_nodes=50
        )
        nodes = set(result["nodes"])
        assert {"mypkg.alpha", "mypkg.beta", "mypkg.sub", "mypkg.sub.gamma"} <= nodes


class TestCountEnumerationInvariant:
    @pytest.mark.asyncio
    async def test_count_equals_expand_stubs(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("mypkg", analyzer)
        expanded = await expand("mypkg", "submodules", analyzer)
        assert node["edge_counts"]["submodules"] == len(expanded["stubs"])

    @pytest.mark.asyncio
    async def test_count_equals_expand_stubs_for_subpackage(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("mypkg.sub", analyzer)
        expanded = await expand("mypkg.sub", "submodules", analyzer)
        assert node["edge_counts"]["submodules"] == len(expanded["stubs"])
