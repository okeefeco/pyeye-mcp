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

import re
from pathlib import Path

import pytest

from pyeye.mcp.server import mcp

# The complete primitive interface plus configuration.
EXPECTED_TOOLS = {
    "configure_packages",
    "resolve",
    "resolve_at",
    "inspect",
    "outline",
    "expand",
    "trace",
}

# Opt-in admin tools, registered only when PYEYE_ENABLE_PERFORMANCE_METRICS is set.
# They are excluded from the equality assertion rather than assumed absent — an
# earlier version of this test asserted bare equality and failed whenever the env
# var was set, contradicting its own comment.
ADMIN_TOOLS = {"get_performance_metrics", "get_connection_diagnostics"}

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
        """Holds whether or not the opt-in admin tools are enabled."""
        assert await _registered_tool_names() - ADMIN_TOOLS == EXPECTED_TOOLS

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

    @pytest.mark.parametrize(
        "module",
        ["pyeye.mcp.lookup", "pyeye.mcp.lookup_builders", "pyeye.agents"],
    )
    def test_module_is_gone(self, module: str) -> None:
        import importlib.util

        assert importlib.util.find_spec(module) is None, f"{module} should have been removed"


class TestNoPackagedCodeInvokesRemovedTools:
    """No shipped module may name a removed tool as an MCP tool to call.

    The surface tests above pin what the *server registers*. They said nothing
    about packaged code that hands an agent a plan naming `mcp__pyeye__<tool>`
    — which is how `src/pyeye/agents/` survived two removal passes still
    instructing consumers to call `mcp__pyeye__find_references` and four other
    tools that no longer exist. A consumer following such a plan gets
    tool-not-found at runtime.

    Deliberately matches the fully-qualified `mcp__pyeye__` form only, so prose
    that *names* a removed tool to explain that it is gone (the honest-limits
    notes in this repo) does not trip it. Only an invocable reference does.
    """

    SRC_ROOT = Path(__file__).parent.parent / "src" / "pyeye"

    def test_no_module_references_a_removed_tool_by_mcp_name(self) -> None:
        pattern = re.compile(r"mcp__pyeye__(" + "|".join(sorted(REMOVED_TOOLS)) + r")\b")

        offenders: list[str] = []
        for path in sorted(self.SRC_ROOT.rglob("*.py")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = pattern.search(line)
                if match:
                    rel = path.relative_to(self.SRC_ROOT.parent.parent).as_posix()
                    offenders.append(f"{rel}:{lineno} -> {match.group(0)}")

        assert not offenders, (
            "Packaged code names removed MCP tools; a consumer following these would "
            "get tool-not-found:\n  " + "\n  ".join(offenders)
        )
