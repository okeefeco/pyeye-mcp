"""Tell MCP clients when ``configure_packages`` adds tools (#770).

#659 lets ``configure_packages`` activate a framework plugin and register its
tools at runtime. A client that caches ``tools/list`` wouldn't show them until
it re-listed, so:

- :func:`run_stdio` serves stdio with ``tools.listChanged: true`` advertised.
  The SDK's ``MCPServer.run_stdio_async`` (mcp 2.3.0) passes no notification
  options, so handshake-era clients would see ``false``, and sending the
  notification would then be off-spec. 2026-07-28+ clients derive the flag from
  ``subscriptions/listen`` being served, which it is by default.
- :func:`announces_new_tools` wraps the tool: after a call that activated a
  plugin, it sends one change event on the channel the negotiated protocol
  uses (:func:`channel_for`).

The SDK seam: ``run_stdio`` reaches the server's ``_lowlevel_server`` (the
SDK's own ``run_stdio_async`` does the same). If an upgrade removes it,
``run_stdio`` warns and falls back to the SDK's path: tools are then still
added, only not announced.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.mcpserver import Context, MCPServer
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

logger = logging.getLogger(__name__)

#: Marks :func:`announces_new_tools`' wrapper, so a test can find it in the chain.
NOTIFIER_ATTR = "_pyeye_announces_new_tools"

Channel = Literal["subscription", "notification"]


def channel_for(protocol_version: str | None) -> Channel:
    """How a tools-changed event reaches a client on *protocol_version*.

    2026-07-28+ delivers change events only on ``subscriptions/listen``
    streams (``subscription``). Every earlier version, and an unknown one,
    takes the ``notifications/tools/list_changed`` notification
    (``notification``). Never both: the notification is off-spec on a modern
    connection.
    """
    return "subscription" if protocol_version in MODERN_PROTOCOL_VERSIONS else "notification"


async def notify_tools_changed(ctx: Context) -> None:
    """Send one tools-changed event on *ctx*'s channel; a failure is logged, never raised."""
    channel = channel_for(ctx.protocol_version)
    try:
        if channel == "subscription":
            await ctx.notify_tools_changed()
        else:
            await ctx.session.send_tool_list_changed()
    except Exception as error:  # the tools are registered either way
        logger.warning(f"Could not announce new tools ({channel}): {error}")


def announces_new_tools(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Announce new tools after *func* returns a result with a non-empty ``activated_plugins``.

    Place it OUTERMOST, above ``tool_errors``: the injected ``Context`` is
    used here, on the server's loop, and is taken out before the call goes
    down the chain, so validation and the Jedi worker never see it. The SDK
    finds it by its annotation and hides it from the input schema. A call
    that raises propagates unchanged and announces nothing.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, ctx: Context | None = None, **kwargs: Any) -> Any:
        result = await func(*args, **kwargs)
        if ctx is not None and isinstance(result, dict) and result.get("activated_plugins"):
            await notify_tools_changed(ctx)
        return result

    signature = inspect.signature(func)
    context = inspect.Parameter(
        "ctx", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context
    )
    wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[*signature.parameters.values(), context]
    )
    wrapper.__annotations__ = {**getattr(func, "__annotations__", {}), "ctx": Context}
    setattr(wrapper, NOTIFIER_ATTR, True)
    return wrapper


def initialization_options(server: MCPServer) -> Any:
    """*server*'s handshake options, with ``tools.listChanged`` advertised."""
    return server._lowlevel_server.create_initialization_options(
        NotificationOptions(tools_changed=True)
    )


async def run_stdio(server: MCPServer) -> None:
    """Serve *server* over stdio, as ``run_stdio_async`` does, advertising ``listChanged``.

    Falls back to the SDK's own ``run_stdio_async``, with a warning, when the
    low-level server isn't there, so an SDK upgrade degrades to not announcing
    new tools rather than failing to start.
    """
    lowlevel = getattr(server, "_lowlevel_server", None)
    if lowlevel is None or not hasattr(lowlevel, "create_initialization_options"):
        logger.warning(
            "The MCP SDK's low-level server is not reachable: serving without "
            "tools.listChanged, so clients aren't told when configure_packages adds tools"
        )
        await server.run_stdio_async()
        return
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await lowlevel.run(read_stream, write_stream, initialization_options(server))
