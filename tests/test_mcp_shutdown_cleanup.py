"""Regression tests for the MCP server's atexit cleanup (#791).

``server.get_unified_collector`` imported the nonexistent
``pyeye.mcp.unified_metrics``; ``cleanup()`` called it first with no guard, so
on every shutdown the Jedi worker and the file watchers were never torn down.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyeye.unified_metrics as unified_metrics
from pyeye.mcp import (
    __main__ as mcp_main,
    connection_diagnostics,
    jedi_worker,
    server,
)


class _FakeCollector:
    def __init__(self, calls: list[str], fail: bool = False) -> None:
        self._calls = calls
        self._fail = fail

    def end_session(self) -> dict[str, Any]:
        self._calls.append("end_session")
        if self._fail:
            raise RuntimeError("metrics broke")
        return {}


class _FakeManager:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def cleanup_all(self) -> None:
        self._calls.append("cleanup_all")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch every teardown target with a recorder; return the call log."""
    log: list[str] = []
    monkeypatch.setattr(
        unified_metrics, "get_unified_collector", lambda *_a, **_k: _FakeCollector(log)
    )
    monkeypatch.setattr(jedi_worker, "shutdown", lambda: log.append("jedi_shutdown"))
    monkeypatch.setattr(server, "get_project_manager", lambda: _FakeManager(log))
    monkeypatch.setattr(
        connection_diagnostics,
        "log_connection_end",
        lambda reason="normal_shutdown": log.append(f"connection_end:{reason}"),
    )
    return log


@pytest.mark.usefixtures("calls")
def test_server_get_unified_collector_resolves_real_module() -> None:
    """The server helper delegates to pyeye.unified_metrics (it raised ModuleNotFoundError)."""
    collector = server.get_unified_collector()
    assert isinstance(collector, _FakeCollector)


def test_cleanup_runs_every_teardown_step(calls: list[str]) -> None:
    """cleanup() ends the metrics session, stops the Jedi worker and cleans up projects."""
    mcp_main.cleanup()

    assert calls == [
        "end_session",
        "jedi_shutdown",
        "cleanup_all",
        "connection_end:normal_shutdown",
    ]


def test_cleanup_step_failure_does_not_skip_later_steps(
    calls: list[str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failing step is logged and the Jedi worker and watcher teardown still run."""
    monkeypatch.setattr(
        unified_metrics,
        "get_unified_collector",
        lambda *_a, **_k: _FakeCollector(calls, fail=True),
    )

    with caplog.at_level("ERROR", logger=mcp_main.__name__):
        mcp_main.cleanup()

    assert calls == [
        "end_session",
        "jedi_shutdown",
        "cleanup_all",
        "connection_end:normal_shutdown",
    ]
    assert "Shutdown cleanup step failed: metrics session" in caplog.text
