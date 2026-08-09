"""Conformance: the live MCP tool surface is exactly the primitive interface.

#505 removed the last three legacy tools (``find_references``,
``get_call_hierarchy``, ``analyze_dependencies``) because they returned
confidently wrong answers — an always-empty ``callees``, a src-layout
misclassification that also disabled cycle detection, and an "ALL usages" claim
with no absence-vs-zero signal.  Nothing about the removal is self-enforcing, so
this test pins the surface: a re-registration has to fail here before it can
reach a client.

The registered set is read from the FastMCP server itself, not from a hand-kept
list, so it cannot drift from what actually ships.
"""

import pytest

from pyeye.mcp.server import mcp

# The complete primitive interface plus configuration.  Admin tools
# (get_performance_metrics / get_connection_diagnostics) register only when
# PYEYE_ENABLE_PERFORMANCE_METRICS is set, so they are not asserted here.
EXPECTED_TOOLS = {
    "configure_packages",
    "resolve",
    "resolve_at",
    "inspect",
    "outline",
    "expand",
    "trace",
}

# Removed in v2.0.  Reverse-reference questions are deferred to the Pyright
# backend (#333); these must never come back as tools.
REMOVED_TOOLS = {
    # Removed in the first v2.0 phase
    "find_symbol",
    "goto_definition",
    "get_type_info",
    "find_imports",
    "find_subclasses",
    "list_packages",
    "list_modules",
    "get_module_info",
    "list_project_structure",
    # Removed by #505
    "find_references",
    "get_call_hierarchy",
    "analyze_dependencies",
    # Superseded entry point, removed alongside #505
    "lookup",
}


async def _registered_tool_names() -> set[str]:
    return {tool.name for tool in await mcp.list_tools()}


class TestMcpSurface:
    @pytest.mark.asyncio
    async def test_registered_tools_are_exactly_the_primitive_interface(self) -> None:
        assert await _registered_tool_names() == EXPECTED_TOOLS

    @pytest.mark.asyncio
    async def test_no_removed_tool_is_registered(self) -> None:
        resurrected = REMOVED_TOOLS & await _registered_tool_names()

        assert not resurrected, (
            f"Removed tools are registered again: {sorted(resurrected)}. "
            "These were removed because they returned wrong answers (#505) or "
            "were superseded by the primitives — do not re-register them."
        )


class TestRemovedAnalyzerMethods:
    """The backing methods are gone too, not merely unregistered."""

    @pytest.mark.parametrize(
        "method_name",
        ["find_references", "get_call_hierarchy", "analyze_dependencies", "get_module_info"],
    )
    def test_analyzer_method_removed(self, method_name: str) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer

        assert not hasattr(JediAnalyzer, method_name), (
            f"JediAnalyzer.{method_name} still exists. It was removed in #505 because "
            "it produced confidently wrong results; leaving it in place invites "
            "re-exposure through a future tool or helper."
        )

    def test_find_importers_survives(self) -> None:
        """find_importers backs the live imported_by edge and must NOT be removed."""
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer

        assert hasattr(JediAnalyzer, "find_importers")


class TestLookupSubsystemRemoved:
    """The orphaned lookup entry point was removed alongside the legacy tools."""

    @pytest.mark.parametrize("module", ["pyeye.mcp.lookup", "pyeye.mcp.lookup_builders"])
    def test_module_is_gone(self, module: str) -> None:
        import importlib.util

        assert importlib.util.find_spec(module) is None, f"{module} should have been removed"
