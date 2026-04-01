"""Tests for connection diagnostics module."""

import signal
import time

from pyeye.mcp.connection_diagnostics import (
    ConnectionDiagnostics,
    get_diagnostics,
    setup_signal_handlers,
)


class TestConnectionDiagnostics:
    """Test connection diagnostics functionality."""

    def test_log_event(self) -> None:
        """Test logging connection events."""
        diag = ConnectionDiagnostics()

        diag.log_event("startup", "Test startup")
        assert len(diag.connection_events) == 1
        assert diag.connection_events[0]["event"] == "startup"
        assert diag.connection_events[0]["details"] == "Test startup"

    def test_mark_activity(self) -> None:
        """Test activity marking."""
        diag = ConnectionDiagnostics()

        initial_time = diag._last_activity
        time.sleep(0.1)

        diag.mark_activity()
        assert diag._last_activity > initial_time

    def test_get_idle_seconds(self) -> None:
        """Test idle time calculation."""
        diag = ConnectionDiagnostics()

        time.sleep(0.1)
        idle = diag.get_idle_seconds()
        assert idle >= 0.1

    def test_get_summary(self) -> None:
        """Test diagnostic summary."""
        diag = ConnectionDiagnostics()

        diag.log_event("startup", "Test")
        diag.log_event("tool_call", "find_symbol")

        summary = diag.get_summary()

        assert "start_time" in summary
        assert "uptime_seconds" in summary
        assert "idle_seconds" in summary
        assert summary["total_events"] == 2
        assert len(summary["recent_events"]) == 2

    def test_get_diagnostics_singleton(self) -> None:
        """Test that get_diagnostics returns the same instance."""
        diag1 = get_diagnostics()
        diag2 = get_diagnostics()

        assert diag1 is diag2

    def test_signal_handlers_registered(self) -> None:
        """Test that signal handlers can be registered."""
        # This just verifies no errors are raised
        # We can't easily test actual signal handling in unit tests
        setup_signal_handlers()

        # Verify handlers are registered
        assert signal.getsignal(signal.SIGTERM) != signal.SIG_DFL
        assert signal.getsignal(signal.SIGHUP) != signal.SIG_DFL

        # SIGPIPE only on Unix
        if hasattr(signal, "SIGPIPE"):
            assert signal.getsignal(signal.SIGPIPE) != signal.SIG_DFL
