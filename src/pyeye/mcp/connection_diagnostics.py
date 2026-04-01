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


def setup_signal_handlers() -> None:
    """Set up signal handlers to detect connection drops.

    Handles SIGTERM, SIGPIPE, and SIGHUP to track when the client disconnects.
    """
    diagnostics = get_diagnostics()

    def handle_sigterm(signum: int, _frame: Any) -> None:
        """Handle SIGTERM - client requested shutdown."""
        diagnostics.log_event("signal_received", f"SIGTERM (signal {signum})")
        logger.warning("Received SIGTERM - client likely disconnected")
        # Allow normal cleanup to proceed
        sys.exit(0)

    def handle_sigpipe(signum: int, _frame: Any) -> None:
        """Handle SIGPIPE - broken pipe (client disconnected)."""
        diagnostics.log_event("signal_received", f"SIGPIPE (signal {signum})")
        logger.error("Received SIGPIPE - stdio pipe broken, client disconnected unexpectedly")
        # Log diagnostic summary before exit
        summary = diagnostics.get_summary()
        logger.error(f"Connection summary at disconnect: {summary}")
        sys.exit(1)

    def handle_sighup(signum: int, _frame: Any) -> None:
        """Handle SIGHUP - hangup (terminal closed)."""
        diagnostics.log_event("signal_received", f"SIGHUP (signal {signum})")
        logger.warning("Received SIGHUP - terminal hangup")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGHUP, handle_sighup)

    # SIGPIPE may not be available on all platforms (Windows doesn't have it)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, handle_sigpipe)
        diagnostics.log_event("startup", "Signal handlers registered (SIGTERM, SIGPIPE, SIGHUP)")
    else:
        diagnostics.log_event("startup", "Signal handlers registered (SIGTERM, SIGHUP)")

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
