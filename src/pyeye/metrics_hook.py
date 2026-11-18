"""Per-tool-call hook: connection diagnostics and error tracking for MCP operations.

Every core MCP tool is wrapped by :func:`track_mcp_operation`. It logs the call
to the connection diagnostics, notes a client cancellation there, and records
the call's success or error in the error tracker. The
``get_connection_diagnostics`` admin tool and the shutdown summary read both.

It used to also write each call to a persistent "unified metrics" store under
``~/.pyeye/metrics/``. Nothing shipped read that store, and the write cost every
call a locked rewrite of a file, so it was removed (#943).
"""

import asyncio
import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _log_call(tool_name: str) -> None:
    """Log the call to the connection diagnostics."""
    try:
        from pyeye.mcp.connection_diagnostics import log_tool_call

        log_tool_call(tool_name)
    except ImportError:
        pass  # Connection diagnostics not available


def _track_outcome(tool_name: str, error: Exception | None) -> None:
    """Record the call's error, or its success, in the error tracker."""
    try:
        from pyeye.mcp.error_tracker import get_error_tracker

        tracker = get_error_tracker()
        if error:
            tracker.record_error(tool_name, error)
        else:
            tracker.record_success(tool_name)
    except ImportError:
        pass  # Error tracker not available


def track_mcp_operation(tool_name: str | None = None) -> Callable[[F], F]:
    """Decorator feeding connection diagnostics and error tracking for an MCP tool.

    Args:
        tool_name: Optional tool name (defaults to function name)

    Returns:
        Decorated function
    """

    def decorator(func: F) -> F:
        actual_tool_name = tool_name or func.__name__

        if inspect.iscoroutinefunction(func):  # not asyncio.*: deprecated in 3.14 (#763)

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                error: Exception | None = None
                _log_call(actual_tool_name)
                try:
                    return await func(*args, **kwargs)
                except asyncio.CancelledError:
                    # Log cancellation to diagnostics
                    try:
                        from pyeye.mcp.connection_diagnostics import get_diagnostics

                        get_diagnostics().log_event("request_cancelled", actual_tool_name)
                        logger.info(f"Tool '{actual_tool_name}' was cancelled by client")
                    except ImportError:
                        pass
                    raise
                except Exception as e:
                    error = e
                    raise
                finally:
                    _track_outcome(actual_tool_name, error)

            return async_wrapper  # type: ignore

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            error: Exception | None = None
            _log_call(actual_tool_name)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error = e
                raise
            finally:
                _track_outcome(actual_tool_name, error)

        return sync_wrapper  # type: ignore

    return decorator
