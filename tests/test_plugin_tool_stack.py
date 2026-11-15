"""Plugin tools get the same decorator stack as core tools (#627).

Core tools stack, outermost first: ``tool_errors``, ``validate_mcp_inputs``,
``metrics.measure(name)``, ``track_mcp_operation(name)``, ``on_jedi_worker``.
Plugin tools had only ``tool_errors(on_jedi_worker(...))``: arguments were never
validated, and calls appeared in neither the metrics nor dogfooding tracking.
``register_plugin_tools`` now wraps them with :func:`_wrap_like_core_tool`.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pyeye.mcp.tool_errors import WRAPPED_ATTR
from pyeye.metrics import metrics

server = importlib.import_module("pyeye.mcp.server")


class FakePlugin:
    """A plugin whose tools record their calls; one takes a validated ``file``."""

    # Real plugins carry their root (AnalyzerPlugin.project_path); the tool
    # wrapper re-spells result paths under it (#717).
    project_path = Path.cwd()

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def name(self) -> str:
        return "fake"

    def register_tools(self) -> dict[str, Any]:
        async def find_things(scope: str = "main") -> list[dict[str, Any]]:
            self.calls.append({"scope": scope})
            return []

        async def things_in(file: str, scope: str = "main") -> list[dict[str, Any]]:
            self.calls.append({"file": file, "scope": scope})
            return []

        return {"find_fake_things": find_things, "fake_things_in": things_in}

    def describe_scope(self, scope: str) -> tuple[list[str], list[str]]:  # noqa: ARG002
        return [], []


@pytest.fixture
def plugin_server() -> tuple[MCPServer, FakePlugin]:
    plugin = FakePlugin()
    fresh = MCPServer("test")
    server.register_plugin_tools(fresh, [plugin])  # type: ignore[list-item]
    return fresh, plugin


async def test_a_plugin_call_is_measured_under_its_tool_name(
    plugin_server: tuple[MCPServer, FakePlugin],
) -> None:
    fresh, plugin = plugin_server
    before = metrics.get_stats("find_fake_things").get("count", 0)

    await fresh.call_tool("find_fake_things", {"scope": "all"})

    assert plugin.calls == [{"scope": "all"}]
    assert metrics.get_stats("find_fake_things")["count"] == before + 1


async def test_plugin_arguments_are_validated(
    plugin_server: tuple[MCPServer, FakePlugin],
) -> None:
    fresh, plugin = plugin_server

    with pytest.raises(ToolError, match="ValidationError"):
        await fresh.call_tool("fake_things_in", {"file": "bad\x00path.py"})

    assert plugin.calls == []  # rejected before the plugin ran


async def test_valid_arguments_reach_the_plugin_normalised(
    plugin_server: tuple[MCPServer, FakePlugin],
) -> None:
    fresh, plugin = plugin_server

    await fresh.call_tool("fake_things_in", {"file": "src/mod.py"})

    assert plugin.calls == [{"file": "src/mod.py", "scope": "main"}]


def test_registration_uses_the_core_stack_in_core_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each decorator is applied, under the tool name, in ``resolve``'s order."""
    applied: list[str] = []

    def recorder(label: str) -> Any:
        def decorate(func: Any) -> Any:
            applied.append(label)
            return func

        return decorate

    monkeypatch.setattr(server, "tool_errors", recorder("tool_errors"))
    monkeypatch.setattr(server, "validate_mcp_inputs", recorder("validate_mcp_inputs"))
    monkeypatch.setattr(server, "on_jedi_worker", recorder("on_jedi_worker"))
    monkeypatch.setattr(
        server, "track_mcp_operation", lambda name: recorder(f"track_mcp_operation({name})")
    )
    monkeypatch.setattr(
        server.metrics, "measure", lambda name: recorder(f"metrics.measure({name})")
    )

    server.register_plugin_tools(MCPServer("test"), [FakePlugin()])  # type: ignore[list-item]

    # Applied innermost first, so this is the reverse of the decorator order on resolve.
    assert applied[:5] == [
        "on_jedi_worker",
        "track_mcp_operation(find_fake_things)",
        "metrics.measure(find_fake_things)",
        "validate_mcp_inputs",
        "tool_errors",
    ]


def test_tool_errors_stays_outermost(plugin_server: tuple[MCPServer, FakePlugin]) -> None:
    fresh, _ = plugin_server
    for name in ("find_fake_things", "fake_things_in"):
        assert getattr(fresh._tool_manager._tools[name].fn, WRAPPED_ATTR, False), name


def test_the_schema_is_still_the_plugin_signature(
    plugin_server: tuple[MCPServer, FakePlugin],
) -> None:
    """The extra wrappers must not hide ``scope`` / ``envelope`` from the MCP schema."""
    fresh, _ = plugin_server
    params = fresh._tool_manager._tools["fake_things_in"].parameters["properties"]
    assert set(params) == {"file", "scope", "envelope"}
