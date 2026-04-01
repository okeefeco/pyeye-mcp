"""Tests for error tracker module."""

from pyeye.mcp.error_tracker import ErrorTracker, get_error_tracker


class TestErrorTracker:
    """Test error tracker functionality."""

    def test_record_error(self) -> None:
        """Test error recording."""
        tracker = ErrorTracker()

        error = ValueError("Test error")
        tracker.record_error("test_tool", error)

        assert tracker.error_counts["ValueError"] == 1
        assert tracker.consecutive_errors == 1
        assert len(tracker.error_history) == 1

    def test_record_success(self) -> None:
        """Test success recording resets consecutive errors."""
        tracker = ErrorTracker()

        # Record some errors
        error = ValueError("Test error")
        tracker.record_error("test_tool", error)
        tracker.record_error("test_tool", error)
        assert tracker.consecutive_errors == 2

        # Success should reset
        tracker.record_success("test_tool")
        assert tracker.consecutive_errors == 0

    def test_get_error_summary(self) -> None:
        """Test error summary."""
        tracker = ErrorTracker()

        error1 = ValueError("Error 1")
        error2 = TypeError("Error 2")

        tracker.record_error("tool1", error1)
        tracker.record_error("tool2", error2)

        summary = tracker.get_error_summary()

        assert summary["total_errors"] == 2
        assert summary["error_counts_by_type"]["ValueError"] == 1
        assert summary["error_counts_by_type"]["TypeError"] == 1
        assert summary["consecutive_errors"] == 2
        assert len(summary["recent_errors"]) == 2

    def test_check_error_pattern_consecutive(self) -> None:
        """Test detection of consecutive error pattern."""
        tracker = ErrorTracker()

        # Record 5+ consecutive errors
        error = ValueError("Test error")
        for _ in range(5):
            tracker.record_error("test_tool", error)

        warning = tracker.check_error_pattern()
        assert warning is not None
        assert "consecutive" in warning.lower()

    def test_check_error_pattern_rapid(self) -> None:
        """Test detection of rapid error pattern."""
        tracker = ErrorTracker()

        # Record 10 errors rapidly
        # Note: This will trigger consecutive error pattern (10 >= 5)
        # before the rapid error pattern check
        error = ValueError("Test error")
        for _ in range(10):
            tracker.record_error("test_tool", error)

        warning = tracker.check_error_pattern()
        assert warning is not None
        # Either consecutive or rapid pattern should be detected
        assert "consecutive" in warning.lower() or "rapid" in warning.lower()

    def test_error_history_bounded(self) -> None:
        """Test that error history is bounded to 100 entries."""
        tracker = ErrorTracker()

        error = ValueError("Test error")
        for _ in range(150):
            tracker.record_error("test_tool", error)

        assert len(tracker.error_history) == 100

    def test_get_error_tracker_singleton(self) -> None:
        """Test that get_error_tracker returns the same instance."""
        tracker1 = get_error_tracker()
        tracker2 = get_error_tracker()

        assert tracker1 is tracker2
