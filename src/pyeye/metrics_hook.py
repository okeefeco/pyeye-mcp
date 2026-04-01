"""Hook to integrate unified metrics with MCP server operations.

This module provides automatic metrics collection for all MCP operations
by hooking into the server's execution flow.
"""

import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

try:
    from pyeye.unified_metrics import get_unified_collector

    METRICS_AVAILABLE = True
except ImportError:
    # Handle case where unified_metrics is not available
    METRICS_AVAILABLE = False

    def get_unified_collector() -> Any:  # type: ignore[misc]
        """Dummy collector when metrics not available."""

        class DummyCollector:
            def record_mcp_operation(self, **kwargs):  # type: ignore[no-untyped-def]
                _ = kwargs  # Mark as intentionally unused
                pass

            def start_session(self, **kwargs):  # type: ignore[no-untyped-def]
                _ = kwargs  # Mark as intentionally unused
                return "dummy_session"

        return DummyCollector()


F = TypeVar("F", bound=Callable[..., Any])


def track_mcp_operation(tool_name: str | None = None) -> Callable[[F], F]:
    """Decorator to automatically track MCP tool operations in unified metrics.

    Also integrates with connection diagnostics and error tracking to help
    debug connection issues.

    Args:
        tool_name: Optional tool name (defaults to function name)

    Returns:
        Decorated function that tracks metrics
    """

    def decorator(func: F) -> F:
        import asyncio

        # Determine the actual tool name
        actual_tool_name = tool_name or func.__name__

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                collector = get_unified_collector()
                start = time.perf_counter()
                success = True
                error: Exception | None = None

                # Log tool call to connection diagnostics
                try:
                    from pyeye.mcp.connection_diagnostics import log_tool_call

                    log_tool_call(actual_tool_name)
                except ImportError:
                    pass  # Connection diagnostics not available

                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    success = False
                    error = e
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    collector.record_mcp_operation(
                        tool_name=actual_tool_name, success=success, duration_ms=duration_ms
                    )

                    # Track errors and successes
                    try:
                        from pyeye.mcp.error_tracker import get_error_tracker

                        tracker = get_error_tracker()
                        if error:
                            tracker.record_error(actual_tool_name, error)
                        else:
                            tracker.record_success(actual_tool_name)
                    except ImportError:
                        pass  # Error tracker not available

            return async_wrapper  # type: ignore
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                collector = get_unified_collector()
                start = time.perf_counter()
                success = True
                error: Exception | None = None

                # Log tool call to connection diagnostics
                try:
                    from pyeye.mcp.connection_diagnostics import log_tool_call

                    log_tool_call(actual_tool_name)
                except ImportError:
                    pass  # Connection diagnostics not available

                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    success = False
                    error = e
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    collector.record_mcp_operation(
                        tool_name=actual_tool_name, success=success, duration_ms=duration_ms
                    )

                    # Track errors and successes
                    try:
                        from pyeye.mcp.error_tracker import get_error_tracker

                        tracker = get_error_tracker()
                        if error:
                            tracker.record_error(actual_tool_name, error)
                        else:
                            tracker.record_success(actual_tool_name)
                    except ImportError:
                        pass  # Error tracker not available

            return sync_wrapper  # type: ignore

    return decorator


def auto_session_for_mcp() -> str:
    """Create or get an auto-session for MCP server instance.

    Returns:
        Session ID
    """
    import os
    from datetime import datetime

    collector = get_unified_collector()

    # Use process ID and timestamp for unique session ID
    pid = os.getpid()
    session_id = f"mcp_server_{pid}_{datetime.now().isoformat()}"

    # Check if we're in a subagent context
    parent_session = os.environ.get("PYEYE_PARENT_SESSION")
    session_type = "subagent" if parent_session else "main"

    # Get issue number from environment or git branch
    metadata = {}
    if issue_num := os.environ.get("PYEYE_ISSUE"):
        metadata["issue"] = issue_num

    return collector.start_session(
        session_id=session_id,
        session_type=session_type,
        parent_session=parent_session,
        metadata=metadata,
    )
