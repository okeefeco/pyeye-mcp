"""Error tracking and diagnostics for MCP tool calls.

Tracks errors, exceptions, and patterns to help debug connection issues.
"""

import logging
import traceback
from collections import defaultdict
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ErrorTracker:
    """Track and analyze errors in MCP tool calls."""

    def __init__(self) -> None:
        """Initialize error tracker."""
        self.error_counts: dict[str, int] = defaultdict(int)
        self.error_history: list[dict[str, Any]] = []
        self.last_error_time: datetime | None = None
        self.consecutive_errors = 0

    def record_error(
        self,
        tool_name: str,
        error: Exception,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record an error that occurred during tool execution.

        Args:
            tool_name: Name of the tool that raised the error
            error: The exception that was raised
            context: Optional context about the error
        """
        error_type = type(error).__name__
        self.error_counts[error_type] += 1
        self.last_error_time = datetime.now()
        self.consecutive_errors += 1

        # Build error record
        error_record = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "error_type": error_type,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
            "context": context or {},
        }

        self.error_history.append(error_record)

        # Log the error
        logger.error(
            f"[ERROR_TRACKER] Tool '{tool_name}' raised {error_type}: {error}",
            exc_info=True,
        )

        # Warn if consecutive errors are building up
        if self.consecutive_errors >= 3:
            logger.warning(
                f"[ERROR_TRACKER] {self.consecutive_errors} consecutive errors detected - "
                "connection may be unstable"
            )

        # Keep history bounded (last 100 errors)
        if len(self.error_history) > 100:
            self.error_history = self.error_history[-100:]

    def record_success(self, _tool_name: str) -> None:
        """Record a successful tool execution.

        Args:
            _tool_name: Name of the tool that succeeded (unused, reserved for future use)
        """
        # Reset consecutive error counter on success
        self.consecutive_errors = 0

    def get_error_summary(self) -> dict[str, Any]:
        """Get summary of errors.

        Returns:
            Dictionary with error statistics
        """
        return {
            "total_errors": sum(self.error_counts.values()),
            "error_counts_by_type": dict(self.error_counts),
            "consecutive_errors": self.consecutive_errors,
            "last_error_time": self.last_error_time.isoformat() if self.last_error_time else None,
            "recent_errors": self.error_history[-10:],  # Last 10 errors
        }

    def check_error_pattern(self) -> str | None:
        """Check for error patterns that might indicate connection issues.

        Returns:
            Warning message if pattern detected, None otherwise
        """
        if self.consecutive_errors >= 5:
            return f"High consecutive error count ({self.consecutive_errors}) - connection may be failing"

        # Check for rapid errors (more than 10 in last 60 seconds)
        if len(self.error_history) >= 10:
            recent = self.error_history[-10:]
            first_time = datetime.fromisoformat(recent[0]["timestamp"])
            last_time = datetime.fromisoformat(recent[-1]["timestamp"])
            duration = (last_time - first_time).total_seconds()

            if duration < 60:
                return f"Rapid error rate detected: 10 errors in {duration:.1f} seconds"

        return None


# Global error tracker instance
_error_tracker: ErrorTracker | None = None


def get_error_tracker() -> ErrorTracker:
    """Get or create the global error tracker instance."""
    global _error_tracker
    if _error_tracker is None:
        _error_tracker = ErrorTracker()
    return _error_tracker
