"""One error channel for MCP calls that can't run (#626 slice C).

pyeye answers in two channels, by design:

* **A lookup that ran** is a response: found, not-found (``found: false``, the
  #626 shape) or unsupported. A miss never raises.
* **A call that couldn't run** is an MCP tool error (``is_error``). That covers
  a bad argument, a ``project_path`` that doesn't exist, an unusable config, or
  an unreadable file.

The caller-side failures surface as pyeye ``MCPError`` subclasses. Left alone,
the MCP SDK treats any exception a tool raises as a crash: it logs it with a
traceback and sends the client only ``"Error executing tool <name>"``, so an
agent that passed ``line=0`` gets no hint what was wrong, and the log can't
tell a typo from a pyeye bug. :func:`tool_errors` turns exactly those caller
errors into the SDK's :class:`ToolError`, which the SDK reports to the client
with its message and logs as an expected failure. Every other exception (a
genuine bug) passes through unchanged and stays a loud, logged crash.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from ..exceptions import (
    ConfigurationError,
    FileAccessError,
    MCPError,
    ProjectNotFoundError,
    ValidationError,
)

#: pyeye errors that mean "the call couldn't run as asked", not "pyeye broke".
CALLER_ERRORS: tuple[type[MCPError], ...] = (
    ValidationError,
    ProjectNotFoundError,
    ConfigurationError,
    FileAccessError,
)

#: Marker attribute set on every wrapped tool, checked by the wiring test.
WRAPPED_ATTR = "__pyeye_tool_errors__"


def tool_error_message(error: MCPError) -> str:
    """The client-facing text: the error type, then its message and details.

    ``MCPError.__str__`` already appends the details (``parameter=…``,
    ``value=…``), so the agent sees which argument to fix.
    """
    return f"{type(error).__name__}: {error}"


def tool_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Report *func*'s caller errors as MCP tool errors, with their message.

    Apply it **outermost**, directly under ``@mcp.tool()``, so argument
    validation (``@validate_mcp_inputs``) is inside it. Works for sync and
    async tools and keeps the wrapped signature, so the tool's schema is
    unchanged.
    """
    wrapper: Callable[..., Any]
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except CALLER_ERRORS as error:
                raise ToolError(tool_error_message(error)) from error

        wrapper = async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except CALLER_ERRORS as error:
                raise ToolError(tool_error_message(error)) from error

        wrapper = sync_wrapper

    setattr(wrapper, WRAPPED_ATTR, True)
    return wrapper
