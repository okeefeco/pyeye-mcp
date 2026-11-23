"""Structural edges carry their static-surface ceiling as data (#417).

pyeye's structural edges are complete over what is written in source, not over
what exists at runtime. #568 put that boundary in the prose; #417 puts it in the
response, so a JSON consumer that never reads a docstring still sees it:
``expand`` carries ``ceiling``, ``outline``'s root carries ``ceiling``, and
``trace`` carries ``ceilings: {edge: id}``. One table, ``edges.EDGE_CEILINGS``,
drives all three and the docs.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.edges import (
    _IMPLEMENTED_EDGES,
    CEILING_MEANINGS,
    EDGE_CEILINGS,
    EXACT_EDGES,
)
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.trace import trace
from tests.conformance import response_linter
from tests.conformance.response_linter import lint_response

server = importlib.import_module("pyeye.mcp.server")
_FIXTURES = Path(__file__).parent / "fixtures"
_SKILL = Path(__file__).parent.parent / ".claude" / "skills" / "python-explore" / "SKILL.md"


class TestTable:
    def test_every_implemented_edge_has_a_ceiling_or_is_exact(self) -> None:
        assert set(EDGE_CEILINGS) | EXACT_EDGES == set(_IMPLEMENTED_EDGES)
        assert not set(EDGE_CEILINGS) & EXACT_EDGES

    def test_every_id_has_one_meaning(self) -> None:
        assert set(EDGE_CEILINGS.values()) == set(CEILING_MEANINGS)
        assert all(m.strip() for m in CEILING_MEANINGS.values())

    def test_linter_copy_is_the_table(self) -> None:
        assert EDGE_CEILINGS == response_linter._EDGE_CEILINGS


class TestDocs:
    def test_expand_description_defines_every_id(self) -> None:
        description = " ".join(
            (server.mcp._tool_manager._tools["expand"].description or "").split()
        )
        for ceiling, meaning in CEILING_MEANINGS.items():
            assert f"{ceiling}: {meaning}" in description.replace("``", ""), ceiling

    def test_skill_binds_every_id(self) -> None:
        """The skill shows the ceilings as the generated ``ceilings.table`` block (#830).

        ``docs_facts check`` keeps the block's content equal to ``CEILING_MEANINGS``,
        so here it is enough that the block is there and lists every id.
        """
        skill = _SKILL.read_text(encoding="utf-8")
        start = skill.index("<!-- fact:begin ceilings.table -->")
        block = skill[start : skill.index("<!-- fact:end -->", start)]
        for ceiling in CEILING_MEANINGS:
            assert f"| `{ceiling}` |" in block, ceiling

    @pytest.mark.parametrize("tool, field", [("outline", "ceiling"), ("trace", "ceilings")])
    def test_outline_and_trace_descriptions_name_the_field(self, tool: str, field: str) -> None:
        description = server.mcp._tool_manager._tools[tool].description or ""
        assert f"``{field}``" in description or f'"{field}"' in description


@pytest.fixture
def nested() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURES / "nested_class_inspect"))


@pytest.fixture
def survey() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURES / "containment" / "survey"))


class TestLiveResponses:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle, edge",
        [
            ("pkg.mod", "members"),
            ("pkg.mod.Outer", "members"),
            ("pkg.mod.Outer", "superclasses"),
            ("pkg.mod.Outer", "subclasses"),
            ("pkg.mod", "imports"),
            ("pkg.mod", "imported_by"),
            ("pkg.mod.top_level_function", "callees"),
            ("pkg.mod.top_level_function", "enclosing_scope"),
        ],
    )
    async def test_expand_carries_its_edge_ceiling(
        self, nested: JediAnalyzer, handle: str, edge: str
    ) -> None:
        result = await expand(handle, edge, nested)
        assert "stubs" in result, result
        assert result.get("ceiling") == EDGE_CEILINGS.get(edge)
        lint_response(result, "expand")

    @pytest.mark.asyncio
    async def test_unsupported_branch_has_no_ceiling(self, nested: JediAnalyzer) -> None:
        result = await expand("pkg.mod.Outer", "imports", nested)  # not_applicable
        assert result["unsupported"] is True
        assert "ceiling" not in result
        lint_response(result, "expand")

    @pytest.mark.asyncio
    async def test_outline_member_walk_root_ceiling(self, nested: JediAnalyzer) -> None:
        tree = await outline("pkg.mod", nested, max_depth=None)
        assert tree["ceiling"] == "static_definitions"
        assert all("ceiling" not in c for c in tree["children"])
        lint_response(tree, "outline")

    @pytest.mark.asyncio
    async def test_outline_survey_root_ceiling(self, survey: JediAnalyzer) -> None:
        tree = await outline("svpkg", survey)
        assert tree["ceiling"] == "on_disk_modules"
        lint_response(tree, "outline")

    @pytest.mark.asyncio
    async def test_outline_of_a_non_container_has_no_ceiling(self, nested: JediAnalyzer) -> None:
        tree = await outline("pkg.mod.top_level_function", nested)
        assert tree["children"] == []
        assert "ceiling" not in tree

    @pytest.mark.asyncio
    async def test_trace_lists_each_walked_edges_ceiling(self, nested: JediAnalyzer) -> None:
        graph = await trace("pkg.mod", ["members", "imports", "enclosing_scope"], nested)
        assert graph["ceilings"] == {
            "imports": "static_imports",
            "members": "static_definitions",
        }
        lint_response(graph, "trace")

    @pytest.mark.asyncio
    async def test_trace_with_only_exact_edges_has_no_ceilings(self, nested: JediAnalyzer) -> None:
        graph = await trace("pkg.mod.top_level_function", ["enclosing_scope"], nested)
        assert "ceilings" not in graph
