"""``configure_packages`` tells clients when it adds tools (#770).

#659 lets ``configure_packages`` activate a framework plugin and register its
tools at runtime; ``activated_plugins`` names them. A client that caches
``tools/list`` wouldn't show them until it re-listed. Now:

- the server advertises ``tools.listChanged: true`` on the handshake
  (``pyeye.mcp.list_changed.initialization_options``, used by ``run_stdio``);
- a call that activates a plugin sends exactly one change event, on the
  channel the negotiated protocol uses: ``notifications/tools/list_changed``
  for handshake-era clients, a ``subscriptions/listen`` event for 2026-07-28+;
- a call that activates nothing, or fails, sends none;
- ``configure_packages``' input schema is unchanged (the injected ``Context`` is
  hidden), and a client that ignores the event still calls the tools by name.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import types
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

from pyeye.mcp import list_changed
from pyeye.mcp.jedi_worker import WRAPPED_ATTR

server = importlib.import_module("pyeye.mcp.server")

_FLASK_APP = "from flask import Flask\n\napp = Flask(__name__)\n\n\n@app.route('/hi')\ndef hi():\n    return 'hi'\n"


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> MCPServer:
    """A fresh server carrying ``configure_packages``, with an empty plugin list."""
    fresh = MCPServer("test-list-changed")
    fresh.add_tool(server.configure_packages)
    monkeypatch.setattr(server, "mcp", fresh)  # activated plugins register here
    saved = list(server._plugins)
    server._plugins.clear()
    yield fresh
    server._plugins.clear()
    server._plugins.extend(saved)


@pytest.fixture
def startup_and_lib(tmp_path: Path) -> tuple[Path, Path]:
    """A startup project with no Flask, and a separate package that uses it (as #659's tests)."""
    root = tmp_path / "projects" / "app"
    root.mkdir(parents=True)
    (root / "main.py").write_text("X = 1\n", encoding="utf-8")
    lib = tmp_path / "vendor" / "libs" / "weblib"
    lib.mkdir(parents=True)
    (lib / "app.py").write_text(_FLASK_APP, encoding="utf-8")
    server.initialize_plugins(root.as_posix())
    return root, lib


def _args(root: Path, lib: Path) -> dict[str, Any]:
    return {"packages": [lib.as_posix()], "save": False, "project_path": root.as_posix()}


class _Recorder:
    """A client message handler that records every tools/list_changed notification."""

    def __init__(self) -> None:
        self.changed = 0

    async def __call__(self, message: Any) -> None:
        if isinstance(message, types.ToolListChangedNotification):
            self.changed += 1


class TestTheChannelFollowsTheProtocol:
    @pytest.mark.parametrize("version", MODERN_PROTOCOL_VERSIONS)
    def test_modern_versions_publish_on_the_subscription_bus(self, version: str) -> None:
        assert list_changed.channel_for(version) == "subscription"

    @pytest.mark.parametrize("version", [*HANDSHAKE_PROTOCOL_VERSIONS, None, "1999-01-01"])
    def test_everything_else_sends_the_handshake_notification(self, version: str | None) -> None:
        assert list_changed.channel_for(version) == "notification"


class TestTheCapabilityIsAdvertised:
    def test_the_initialization_options_say_list_changed(self, isolated: MCPServer) -> None:
        options = list_changed.initialization_options(isolated)

        assert options.capabilities.tools is not None
        assert options.capabilities.tools.list_changed is True

    @pytest.mark.asyncio
    async def test_a_handshake_client_sees_it(self, isolated: MCPServer) -> None:
        """Over real JSON-RPC streams, with the options ``run_stdio`` uses."""
        from mcp.client.session import ClientSession
        from mcp.shared.memory import create_client_server_memory_streams

        async with (
            create_client_server_memory_streams() as (client_streams, server_streams),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(
                isolated._lowlevel_server.run,
                *server_streams,
                list_changed.initialization_options(isolated),
            )
            async with ClientSession(*client_streams) as session:
                result = await session.initialize()
            tg.cancel_scope.cancel()

        assert result.capabilities.tools is not None
        assert result.capabilities.tools.list_changed is True

    def test_the_sdk_attribute_run_stdio_relies_on_exists(self, isolated: MCPServer) -> None:
        assert hasattr(isolated, "_lowlevel_server")


class TestRunStdioFallsBack:
    @pytest.mark.asyncio
    async def test_without_the_attribute_it_runs_the_sdks_own_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An SDK upgrade that drops the attribute degrades to today's behaviour, never a crash."""

        class Upgraded:
            ran = False

            async def run_stdio_async(self) -> None:
                Upgraded.ran = True

        with caplog.at_level("WARNING"):
            await list_changed.run_stdio(Upgraded())  # type: ignore[arg-type]

        assert Upgraded.ran
        assert "listChanged" in caplog.text


class TestAHandshakeClientIsNotified:
    @pytest.mark.asyncio
    async def test_an_activation_sends_exactly_one(
        self, isolated: MCPServer, startup_and_lib: tuple[Path, Path]
    ) -> None:
        recorder = _Recorder()
        async with Client(isolated, mode="legacy", message_handler=recorder) as client:
            result = await client.call_tool("configure_packages", _args(*startup_and_lib))
            await anyio.sleep(0.05)  # let a notification sent after the result arrive

        assert result.structured_content is not None
        assert result.structured_content["activated_plugins"] == ["Flask"]
        assert recorder.changed == 1

    @pytest.mark.asyncio
    async def test_nothing_activated_sends_none(
        self, isolated: MCPServer, startup_and_lib: tuple[Path, Path]
    ) -> None:
        recorder = _Recorder()
        async with Client(isolated, mode="legacy", message_handler=recorder) as client:
            await client.call_tool("configure_packages", _args(*startup_and_lib))
            await client.call_tool("configure_packages", _args(*startup_and_lib))  # again
            await anyio.sleep(0.05)

        assert recorder.changed == 1  # the first call only

    @pytest.mark.asyncio
    async def test_a_failing_call_sends_none(self, isolated: MCPServer) -> None:
        """A refused project path raises inside the chain: the error propagates, nothing is sent."""
        recorder = _Recorder()
        async with Client(isolated, mode="legacy", message_handler=recorder) as client:
            result = await client.call_tool(
                "configure_packages", {"packages": ["x"], "project_path": "/etc"}
            )
            await anyio.sleep(0.05)

        assert result.is_error is True
        assert recorder.changed == 0

    @pytest.mark.asyncio
    async def test_a_client_that_ignores_it_still_calls_the_tools(
        self, isolated: MCPServer, startup_and_lib: tuple[Path, Path]
    ) -> None:
        async with Client(isolated, mode="legacy") as client:
            await client.call_tool("configure_packages", _args(*startup_and_lib))
            routes = await client.call_tool("find_flask_routes", {})

        assert routes.is_error is False


class TestAModernClientIsNotified:
    @pytest.mark.asyncio
    async def test_an_activation_reaches_a_listen_stream(
        self, isolated: MCPServer, startup_and_lib: tuple[Path, Path]
    ) -> None:
        events: list[Any] = []
        async with (
            Client(isolated, mode=MODERN_PROTOCOL_VERSIONS[-1]) as client,
            client.listen(tools_list_changed=True) as subscription,
        ):
            await client.call_tool("configure_packages", _args(*startup_and_lib))
            with anyio.move_on_after(2):
                async for event in subscription:
                    events.append(event)
                    break

        assert len(events) == 1
        assert type(events[0]).__name__ == "ToolsListChanged"


class TestTheToolsShape:
    def test_the_input_schema_has_no_context(self) -> None:
        tool = server.mcp._tool_manager._tools["configure_packages"]

        assert set(tool.parameters["properties"]) == {
            "packages",
            "namespaces",
            "standalone_dirs",
            "save",
            "project_path",
        }
        assert tool.context_kwarg is not None  # the SDK injects one, hidden from clients

    def test_the_notifier_sits_above_the_worker_hop(self) -> None:
        """The ``Context`` is used on the server's loop and never crosses to the Jedi worker."""
        fn: Any = server.configure_packages
        chain = []
        while fn is not None:
            chain.append(fn)
            fn = getattr(fn, "__wrapped__", None)

        # functools.wraps copies __dict__, so a marker shows on every wrapper ABOVE the one
        # that set it: each is found as the deepest wrapper carrying its marker.
        notifier = max(
            i for i, f in enumerate(chain) if getattr(f, list_changed.NOTIFIER_ATTR, False)
        )
        worker = max(i for i, f in enumerate(chain) if getattr(f, WRAPPED_ATTR, False))
        assert notifier < worker
