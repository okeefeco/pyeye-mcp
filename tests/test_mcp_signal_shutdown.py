"""The stdio server exits on SIGTERM, SIGINT and SIGHUP, and when its client goes away (#1124).

Root cause, from a reproduction:

- SIGTERM and SIGHUP had handlers that only logged, so the signal never ended
  the process.
- SIGINT made asyncio cancel the main task, but the MCP SDK's ``stdio_server``
  reads stdin with ``anyio.wrap_file``: a worker thread blocked in
  ``readline`` that cancellation waits for. The server lived on until a line or
  EOF arrived.

A signal now runs the shutdown cleanup (the Jedi worker, the file watchers)
and exits 0, within a deadline even if a cleanup step hangs. Stdin EOF already
ended the server; it's pinned here with live watchers and a Jedi worker.

Every server in these tests is this test's own subprocess. Nothing signals a
server another session is using.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess  # nosec B404 - launches this interpreter only
import sys
import threading
import time
from pathlib import Path
from typing import IO, Any

import pytest

from pyeye.cache import CodebaseWatcher
from pyeye.mcp import (
    __main__ as mcp_main,
    connection_diagnostics,
)
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

#: From the shutdown request to the process's exit, in milliseconds.
EXIT_THRESHOLD = PerformanceThresholds(base=5000, linux_ci=10000, macos_ci=15000, windows_ci=15000)

_POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX signals: Windows delivers CTRL_BREAK only to a console process group, "
    "and a stdio MCP server isn't started in one",
)


class _Server:
    """``python -m pyeye.mcp`` in *project*, initialised, with one tool call made."""

    def __init__(self, project: Path) -> None:
        self.proc = (
            subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments  # nosec B603
                [sys.executable, "-m", "pyeye.mcp"],
                cwd=project,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        )
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            }
        )
        assert b'"id":1' in self._readline()
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        # A tool call starts the project's file watchers and the Jedi worker.
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "resolve",
                    "arguments": {"identifier": "mod.VALUE", "project_path": project.as_posix()},
                },
            }
        )
        assert b'"id":2' in self._readline()

    def _stdin(self) -> IO[bytes]:
        assert self.proc.stdin is not None
        return self.proc.stdin

    def _send(self, message: dict[str, Any]) -> None:
        self._stdin().write((json.dumps(message) + "\n").encode())
        self._stdin().flush()

    def _readline(self) -> bytes:
        assert self.proc.stdout is not None
        return self.proc.stdout.readline()

    def exit_after(self, act: Any) -> tuple[int, float]:
        """Run *act*, then wait for the exit: ``(returncode, elapsed ms)``."""
        start = time.perf_counter()
        act()
        try:
            code = self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            pytest.fail("the server was still running 60 s after the shutdown request")
        return code, (time.perf_counter() - start) * 1000

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream is not None and not stream.closed:
                stream.close()


@pytest.fixture
def server(tmp_path: Path) -> Any:
    (tmp_path / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    running = _Server(tmp_path)
    try:
        yield running
    finally:
        running.close()


@_POSIX_ONLY
@pytest.mark.parametrize("signame", ["SIGTERM", "SIGINT", "SIGHUP"])
def test_a_signal_exits_the_server(server: _Server, signame: str) -> None:
    code, elapsed_ms = server.exit_after(lambda: server.proc.send_signal(getattr(signal, signame)))

    assert code == 0
    assert_performance_threshold(elapsed_ms, EXIT_THRESHOLD, f"exit after {signame}")


def test_stdin_eof_exits_the_server(server: _Server) -> None:
    """The client went away: its end of the server's stdin closed."""
    code, elapsed_ms = server.exit_after(server._stdin().close)

    assert code == 0
    assert_performance_threshold(elapsed_ms, EXIT_THRESHOLD, "exit after stdin EOF")


@pytest.mark.real_watcher
def test_the_watcher_threads_are_daemons(tmp_path: Path) -> None:
    """A watcher left running can't keep the interpreter alive at exit.

    On every OS, Windows included: watchdog 7.1.1 made its Windows reader thread
    a daemon (gorakhargosh/watchdog#1470), which 7.0-7.1.0 didn't (#1146).
    """
    before = set(threading.enumerate())
    watcher = CodebaseWatcher(tmp_path.as_posix())
    watcher.start()
    try:
        started = set(threading.enumerate()) - before
        assert started, "the watcher started no threads"
        assert all(t.daemon for t in started), [(t.name, t.daemon) for t in started]
    finally:
        watcher.stop()


class TestServingEndsWithCleanup:
    """Cleanup runs when serving ends, before the interpreter joins its threads."""

    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        log: list[str] = []
        monkeypatch.setattr(mcp_main, "cleanup", lambda: log.append("cleanup"))
        monkeypatch.setattr(
            connection_diagnostics, "log_connection_end", lambda reason: log.append(reason)
        )
        return log

    def test_after_stdin_eof(self, calls: list[str]) -> None:
        mcp_main.serve_then_clean_up(lambda: calls.append("served"))

        assert calls == ["served", "cleanup"]

    def test_after_a_crash(self, calls: list[str]) -> None:
        def crash() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            mcp_main.serve_then_clean_up(crash)

        assert calls == ["crash: RuntimeError", "cleanup"]

    def test_after_a_keyboard_interrupt(self, calls: list[str]) -> None:
        def interrupt() -> None:
            raise KeyboardInterrupt

        mcp_main.serve_then_clean_up(interrupt)

        assert calls == ["keyboard_interrupt", "cleanup"]


class TestTheShutdown:
    """The in-process parts: the handlers and the bounded shutdown (no real exit)."""

    @pytest.fixture(autouse=True)
    def _restore_handlers(self) -> Any:
        names = [n for n in ("SIGTERM", "SIGINT", "SIGHUP", "SIGPIPE") if hasattr(signal, n)]
        saved = {n: signal.getsignal(getattr(signal, n)) for n in names}
        yield
        for n, handler in saved.items():
            signal.signal(getattr(signal, n), handler)

    @pytest.mark.parametrize("signame", ["SIGTERM", "SIGINT", "SIGHUP"])
    def test_each_shutdown_signal_calls_on_terminate(self, signame: str) -> None:
        if not hasattr(signal, signame):
            pytest.skip(f"{signame} isn't defined on this platform")
        received: list[int] = []
        connection_diagnostics.setup_signal_handlers(on_terminate=received.append)

        handler = signal.getsignal(getattr(signal, signame))
        assert callable(handler)
        handler(getattr(signal, signame), None)

        assert received == [getattr(signal, signame)]

    def test_terminate_cleans_up_then_exits_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(mcp_main, "cleanup", lambda: calls.append("cleanup"))
        monkeypatch.setattr(mcp_main.os, "_exit", lambda code: calls.append(f"exit {code}"))

        mcp_main._terminate(signal.SIGTERM)

        assert calls == ["cleanup", "exit 0"]

    def test_a_hung_cleanup_still_exits_by_the_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exited = threading.Event()
        release = threading.Event()
        monkeypatch.setattr(mcp_main, "SHUTDOWN_DEADLINE_SECONDS", 0.2)
        monkeypatch.setattr(mcp_main, "cleanup", lambda: release.wait(10))
        monkeypatch.setattr(mcp_main.os, "_exit", lambda _code: exited.set())

        worker = threading.Thread(target=mcp_main._terminate, args=(signal.SIGTERM,), daemon=True)
        worker.start()
        try:
            assert exited.wait(5), "the deadline didn't force the exit"
        finally:
            release.set()
            worker.join(5)

    def test_shutdown_runs_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        started: list[int] = []
        ran = threading.Event()

        def fake_terminate(signum: int) -> None:
            started.append(signum)
            ran.set()

        monkeypatch.setattr(mcp_main, "_shutdown_started", threading.Event())
        monkeypatch.setattr(mcp_main, "_terminate", fake_terminate)

        mcp_main.request_shutdown(signal.SIGTERM)
        mcp_main.request_shutdown(signal.SIGINT)

        assert ran.wait(5)
        assert started == [signal.SIGTERM]
