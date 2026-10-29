"""Conformance: plugin tools are registered under the names their plugins declare.

Each plugin declares its tool names as the keys of ``register_tools()``. Until
#555 the server registered ``mcp.tool()(tool_func)``, which names a tool after
``tool_func.__name__`` and throws the key away. The method names collide across
plugins (Django, Pydantic and Flask all have ``find_models`` / ``find_views`` /
``find_templates``-style methods), so with several frameworks detected the
later plugin's tools were dropped with only a log warning, and the documented
``find_django_*`` / ``find_flask_*`` names never existed.

Registration is exercised on a fresh ``MCPServer``: the module-level ``mcp``
must not be mutated here, because ``test_mcp_surface_conformance`` pins its
exact tool set.
"""

import inspect
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer

from pyeye.mcp.server import mcp, register_plugin_tools
from pyeye.plugins.base import AnalyzerPlugin
from pyeye.plugins.django import DjangoPlugin
from pyeye.plugins.flask import FlaskPlugin
from pyeye.plugins.pydantic import PydanticPlugin

# The client-visible plugin tool surface. A change here is a rename for every
# MCP client, so it must be deliberate (and listed in the CHANGELOG).
EXPECTED_PLUGIN_TOOLS = {
    PydanticPlugin: {
        "find_pydantic_models",
        "get_model_schema",
        "find_validators",
        "find_field_validators",
        "find_model_config",
        "trace_model_inheritance",
        "find_computed_fields",
    },
    DjangoPlugin: {
        "find_django_models",
        "find_django_views",
        "find_django_urls",
        "find_django_templates",
        "find_django_migrations",
    },
    FlaskPlugin: {
        "find_flask_routes",
        "find_flask_blueprints",
        "find_flask_views",
        "find_flask_templates",
        "find_flask_extensions",
        "find_flask_config",
        "find_error_handlers",
        "find_cli_commands",
    },
}


@pytest.fixture
def all_plugins(tmp_path: Path) -> list[AnalyzerPlugin]:
    """One instance of every plugin, in the order ``initialize_plugins`` loads them."""
    return [cls(tmp_path.as_posix()) for cls in (PydanticPlugin, DjangoPlugin, FlaskPlugin)]


async def _tool_names(server: MCPServer) -> set[str]:
    return {tool.name for tool in await server.list_tools()}


class TestPluginToolNames:
    @pytest.mark.parametrize("plugin_class", list(EXPECTED_PLUGIN_TOOLS))
    def test_declared_names_match_the_pinned_surface(
        self, plugin_class: type[AnalyzerPlugin], tmp_path: Path
    ) -> None:
        declared = set(plugin_class(tmp_path.as_posix()).register_tools())  # type: ignore[abstract]

        assert declared == EXPECTED_PLUGIN_TOOLS[plugin_class]

    @pytest.mark.asyncio
    async def test_all_plugins_together_register_every_declared_name(
        self, all_plugins: list[AnalyzerPlugin]
    ) -> None:
        """The #555 regression: no tool may be lost when several plugins are active."""
        server = MCPServer("plugin-names")

        register_plugin_tools(server, all_plugins)

        expected = set().union(*EXPECTED_PLUGIN_TOOLS.values())
        assert await _tool_names(server) == expected
        assert len(expected) == sum(len(names) for names in EXPECTED_PLUGIN_TOOLS.values())

    @pytest.mark.asyncio
    async def test_each_name_dispatches_to_its_own_plugin(
        self, all_plugins: list[AnalyzerPlugin]
    ) -> None:
        """find_django_models must be Django's method, not Pydantic's find_models."""
        server = MCPServer("plugin-names")
        register_plugin_tools(server, all_plugins)
        # The SDK and inspect.getdoc indent docstrings differently; compare words.
        descriptions = {
            tool.name: " ".join((tool.description or "").split())
            for tool in await server.list_tools()
        }

        for plugin in all_plugins:
            for name, func in plugin.register_tools().items():
                assert descriptions[name] == " ".join((inspect.getdoc(func) or "").split()), name

    def test_duplicate_name_raises_instead_of_dropping_a_tool(self, tmp_path: Path) -> None:
        server = MCPServer("plugin-names")
        twice = [FlaskPlugin(tmp_path.as_posix()), FlaskPlugin(tmp_path.as_posix())]

        with pytest.raises(ValueError, match="find_flask_routes"):
            register_plugin_tools(server, twice)

    @pytest.mark.asyncio
    async def test_plugin_names_do_not_shadow_core_tools(self) -> None:
        """Reads the module-level server without registering anything on it."""
        core = await _tool_names(mcp)
        plugin_names = set().union(*EXPECTED_PLUGIN_TOOLS.values())

        assert not core & plugin_names
