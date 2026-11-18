"""Regression tests for the MCP server's atexit cleanup (#791).

``cleanup()`` once called a broken metrics step first, with no guard, so on
every shutdown the Jedi worker and the file watchers were never torn down. Each
step now runs independently. The metrics step itself is gone with the unified
metrics store (#943): the server no longer writes ``~/.pyeye/metrics``.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - launches this interpreter only
import sys
from pathlib import Path

import pytest

from pyeye.mcp import (
    __main__ as mcp_main,
    connection_diagnostics,
    jedi_worker,
    server,
)


class _FakeManager:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def cleanup_all(self) -> None:
        self._calls.append("cleanup_all")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch every teardown target with a recorder; return the call log."""
    log: list[str] = []
    monkeypatch.setattr(jedi_worker, "shutdown", lambda: log.append("jedi_shutdown"))
    monkeypatch.setattr(server, "get_project_manager", lambda: _FakeManager(log))
    monkeypatch.setattr(
        connection_diagnostics,
        "log_connection_end",
        lambda reason="normal_shutdown": log.append(f"connection_end:{reason}"),
    )
    return log


def test_cleanup_runs_every_teardown_step(calls: list[str]) -> None:
    """cleanup() stops the Jedi worker, cleans up projects and logs the end."""
    mcp_main.cleanup()

    assert calls == ["jedi_shutdown", "cleanup_all", "connection_end:normal_shutdown"]


def test_cleanup_step_failure_does_not_skip_later_steps(
    calls: list[str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failing step is logged and the watcher teardown and end log still run."""

    failed: list[bool] = []

    def broken() -> None:
        calls.append("jedi_shutdown")
        if not failed:  # only cleanup()'s call; a later teardown call must succeed
            failed.append(True)
            raise RuntimeError("worker broke")

    monkeypatch.setattr(jedi_worker, "shutdown", broken)

    with caplog.at_level("ERROR", logger=mcp_main.__name__):
        mcp_main.cleanup()

    assert calls == ["jedi_shutdown", "cleanup_all", "connection_end:normal_shutdown"]
    assert "Shutdown cleanup step failed: Jedi worker" in caplog.text


def test_the_server_no_longer_wires_the_metrics_store() -> None:
    """#943: no server hook, no start-up or shutdown step (the module is a stub)."""
    assert not hasattr(server, "get_unified_collector")
    assert not hasattr(server, "ensure_unified_session")
    assert not hasattr(mcp_main, "_end_metrics_session")


def test_a_server_run_writes_no_metrics_store(tmp_path: Path) -> None:
    """Start and stop a real ``python -m pyeye.mcp``: nothing under ``~/.pyeye/metrics``."""
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    proc = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments  # nosec B603
        [sys.executable, "-m", "pyeye.mcp"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        check=False,
        env=env,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert not (home / ".pyeye" / "metrics").exists()
