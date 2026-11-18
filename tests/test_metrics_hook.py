"""``track_mcp_operation`` feeds connection diagnostics and the error tracker (#943).

It used to also write every call to the unified metrics store. That write is gone;
what the ``get_connection_diagnostics`` admin tool and the shutdown summary read
is pinned here.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from pyeye import metrics_hook
from pyeye.mcp import connection_diagnostics, error_tracker


class _Tracker:
    def __init__(self, log: list[Any]) -> None:
        self._log = log

    def record_error(self, tool: str, error: Exception) -> None:
        self._log.append(("error", tool, type(error).__name__))

    def record_success(self, tool: str) -> None:
        self._log.append(("success", tool))


class _Diagnostics:
    def __init__(self, log: list[Any]) -> None:
        self._log = log

    def log_event(self, event: str, tool: str) -> None:
        self._log.append(("event", event, tool))


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    monkeypatch.setattr(
        connection_diagnostics, "log_tool_call", lambda t: calls.append(("call", t))
    )
    monkeypatch.setattr(connection_diagnostics, "get_diagnostics", lambda: _Diagnostics(calls))
    monkeypatch.setattr(error_tracker, "get_error_tracker", lambda: _Tracker(calls))
    return calls


def test_an_async_success_is_logged_and_tracked(log: list[Any]) -> None:
    @metrics_hook.track_mcp_operation("inspect")
    async def tool() -> str:
        return "ok"

    assert asyncio.run(tool()) == "ok"
    assert log == [("call", "inspect"), ("success", "inspect")]


def test_an_async_error_is_tracked_and_raised(log: list[Any]) -> None:
    @metrics_hook.track_mcp_operation("expand")
    async def tool() -> None:
        raise ValueError("bad")

    with pytest.raises(ValueError):
        asyncio.run(tool())
    assert log == [("call", "expand"), ("error", "expand", "ValueError")]


def test_a_cancellation_is_logged_and_reraised(log: list[Any]) -> None:
    @metrics_hook.track_mcp_operation("trace")
    async def tool() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tool())
    assert ("event", "request_cancelled", "trace") in log
    assert log[-1] == ("success", "trace")  # a cancellation is not a tool error


def test_a_sync_tool_is_logged_and_tracked(log: list[Any]) -> None:
    @metrics_hook.track_mcp_operation()
    def resolve() -> int:
        return 1

    @metrics_hook.track_mcp_operation("outline")
    def broken() -> None:
        raise KeyError("x")

    assert resolve() == 1
    with pytest.raises(KeyError):
        broken()
    assert log == [
        ("call", "resolve"),
        ("success", "resolve"),
        ("call", "outline"),
        ("error", "outline", "KeyError"),
    ]


def test_without_the_diagnostics_modules_the_tool_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ImportError of either module is swallowed; the call's result is untouched."""
    monkeypatch.setitem(sys.modules, "pyeye.mcp.connection_diagnostics", None)
    monkeypatch.setitem(sys.modules, "pyeye.mcp.error_tracker", None)

    @metrics_hook.track_mcp_operation("inspect")
    async def tool() -> str:
        return "ok"

    @metrics_hook.track_mcp_operation("trace")
    async def cancelled() -> None:
        raise asyncio.CancelledError

    assert asyncio.run(tool()) == "ok"
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancelled())
