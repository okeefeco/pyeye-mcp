"""Connection lifecycle diagnostics for MCP stdio transport.

This module provides tools to debug connection drops and disconnects between
the MCP server and Claude Code client.
"""

import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ConnectionDiagnostics:
    """Track and log MCP connection lifecycle events."""

    def __init__(self) -> None:
        """Initialize connection diagnostics."""
        self.start_time = datetime.now()
        self.connection_events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stdin_alive = True
        self._stdout_alive = True
        self._last_activity = time.time()

    def log_event(self, event_type: str, details: str | None = None) -> None:
        """Log a connection event with timestamp.

        Args:
            event_type: Type of event (startup, shutdown, error, activity)
            details: Optional additional details
        """
        with self._lock:
            event = {
                "timestamp": datetime.now().isoformat(),
                "event": event_type,
                "details": details,
                "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            }
            self.connection_events.append(event)

            # Log to logger as well
            if details:
                logger.info(f"[CONNECTION] {event_type}: {details}")
            else:
                logger.info(f"[CONNECTION] {event_type}")

    def mark_activity(self) -> None:
        """Mark that connection activity occurred."""
        self._last_activity = time.time()

    def get_idle_seconds(self) -> float:
        """Get seconds since last activity."""
        return time.time() - self._last_activity

    def get_summary(self) -> dict[str, Any]:
        """Get connection diagnostics summary."""
        uptime = (datetime.now() - self.start_time).total_seconds()
        return {
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": uptime,
            "idle_seconds": self.get_idle_seconds(),
            "stdin_alive": self._stdin_alive,
            "stdout_alive": self._stdout_alive,
            "total_events": len(self.connection_events),
            "recent_events": self.connection_events[-10:],  # Last 10 events
        }


# Global diagnostics instance
_diagnostics: ConnectionDiagnostics | None = None


def get_diagnostics() -> ConnectionDiagnostics:
    """Get or create the global diagnostics instance."""
    global _diagnostics
    if _diagnostics is None:
        _diagnostics = ConnectionDiagnostics()
    return _diagnostics


def setup_signal_handlers(on_terminate: Callable[[int], None]) -> None:
    """Log the shutdown signals and the client's disconnect, and act on them (#1124).

    SIGTERM, SIGINT and SIGHUP (SIGBREAK on Windows) each ask the server to
    stop: the handler logs the signal and calls *on_terminate* with its number,
    which shuts the server down. A handler that only logged (before #1124) kept
    the process alive: a handled signal never terminates it. SIGINT can't be
    left to asyncio either, because the MCP SDK reads stdin in a thread that
    cancellation waits for, so the server would live until the client next wrote.

    SIGPIPE (POSIX) is logged only: a write to a closed pipe then raises instead
    of killing the process, and stdin's EOF ends the server.
    """
    diagnostics = get_diagnostics()

    def handle_shutdown(signum: int, _: Any) -> None:
        name = signal.Signals(signum).name
        diagnostics.log_event("signal_received", f"{name} (signal {signum})")
        logger.warning("Received %s - shutting down", name)
        on_terminate(signum)

    def handle_sigpipe(signum: int, _: Any) -> None:
        """Handle SIGPIPE - broken pipe (client disconnected)."""
        diagnostics.log_event("signal_received", f"SIGPIPE (signal {signum})")
        logger.error("Received SIGPIPE - stdio pipe broken, client disconnected unexpectedly")
        summary = diagnostics.get_summary()
        logger.error(f"Connection summary at disconnect: {summary}")

    # SIGTERM and SIGINT exist on every platform; SIGHUP and SIGPIPE are POSIX
    # only, and SIGBREAK (CTRL_BREAK) is Windows only.
    registered = []
    for name in ("SIGTERM", "SIGINT", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), handle_shutdown)
            registered.append(name)

    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, handle_sigpipe)
        registered.append("SIGPIPE")

    diagnostics.log_event("startup", f"Signal handlers registered ({', '.join(registered)})")

    logger.info("Connection diagnostics signal handlers installed")


def start_heartbeat_monitor(interval_seconds: int = 30) -> None:
    """Start a background thread that logs periodic heartbeats.

    This helps identify when the connection goes silent.

    Args:
        interval_seconds: Seconds between heartbeat logs
    """
    diagnostics = get_diagnostics()

    def heartbeat() -> None:
        """Log periodic heartbeat."""
        while True:
            time.sleep(interval_seconds)
            idle = diagnostics.get_idle_seconds()
            diagnostics.log_event("heartbeat", f"idle_for={idle:.1f}s")

            # Warn if idle for more than 5 minutes
            if idle > 300:
                logger.warning(f"Connection idle for {idle:.1f} seconds")

    thread = threading.Thread(target=heartbeat, daemon=True, name="connection-heartbeat")
    thread.start()
    diagnostics.log_event("startup", f"Heartbeat monitor started (interval={interval_seconds}s)")
    logger.info(f"Started connection heartbeat monitor (interval={interval_seconds}s)")


def log_connection_start() -> None:
    """Log that the MCP connection has started."""
    diagnostics = get_diagnostics()
    diagnostics.log_event("startup", "MCP server connection established")
    logger.info("=" * 60)
    logger.info("MCP CONNECTION STARTED")
    logger.info(f"Start time: {diagnostics.start_time.isoformat()}")
    logger.info(f"Python: {sys.version.split()[0]}")
    logger.info(f"PID: {os.getpid()}")
    logger.info("=" * 60)


def log_connection_end(reason: str = "normal_shutdown") -> None:
    """Log that the MCP connection has ended.

    Args:
        reason: Reason for connection end
    """
    diagnostics = get_diagnostics()
    diagnostics.log_event("shutdown", reason)

    summary = diagnostics.get_summary()
    logger.info("=" * 60)
    logger.info("MCP CONNECTION ENDED")
    logger.info(f"Reason: {reason}")
    logger.info(f"Uptime: {summary['uptime_seconds']:.1f} seconds")
    logger.info(f"Total events: {summary['total_events']}")
    logger.info(f"Final idle time: {summary['idle_seconds']:.1f} seconds")
    logger.info("=" * 60)


def log_tool_call(tool_name: str) -> None:
    """Log that a tool was called (activity marker).

    Args:
        tool_name: Name of the tool that was called
    """
    diagnostics = get_diagnostics()
    diagnostics.mark_activity()
    diagnostics.log_event("tool_call", tool_name)
