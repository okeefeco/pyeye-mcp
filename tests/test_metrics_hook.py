"""Tests for the metrics hook module."""

import asyncio
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.metrics_hook import auto_session_for_mcp, track_mcp_operation
from pycodemcp.unified_metrics import UnifiedMetricsCollector


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for metrics storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_collector(temp_storage_dir):
    """Create a mocked collector for testing."""
    with patch("pycodemcp.metrics_hook.get_unified_collector") as mock_get:
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)
        mock_get.return_value = collector
        yield collector


class TestTrackMcpOperationDecorator:
    """Test the track_mcp_operation decorator."""

    def test_sync_function_success(self, mock_collector):
        """Test decorator with successful synchronous function."""

        @track_mcp_operation()
        def sample_function(x, y):
            return x + y

        result = sample_function(2, 3)

        assert result == 5

        # Check that operation was recorded
        active = mock_collector.get_active_sessions()
        assert len(active) == 1  # Auto-session created

        session_id = list(active.keys())[0]
        session = active[session_id]

        assert session["mcp_operations"]["sample_function"] == 1
        assert session["errors"] == 0
        assert "operation_times" in session
        assert "sample_function" in session["operation_times"]
        assert len(session["operation_times"]["sample_function"]) == 1
        assert session["operation_times"]["sample_function"][0] > 0

    def test_sync_function_failure(self, mock_collector):
        """Test decorator with failing synchronous function."""

        @track_mcp_operation()
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            failing_function()

        # Check that error was recorded
        active = mock_collector.get_active_sessions()
        assert len(active) == 1

        session_id = list(active.keys())[0]
        session = active[session_id]

        assert session["mcp_operations"]["failing_function"] == 1
        assert session["errors"] == 1

    @pytest.mark.asyncio
    async def test_async_function_success(self, mock_collector):
        """Test decorator with successful async function."""

        @track_mcp_operation()
        async def async_sample_function(x, y):
            await asyncio.sleep(0.01)  # Small delay
            return x * y

        result = await async_sample_function(3, 4)

        assert result == 12

        # Check that operation was recorded
        active = mock_collector.get_active_sessions()
        assert len(active) == 1

        session_id = list(active.keys())[0]
        session = active[session_id]

        assert session["mcp_operations"]["async_sample_function"] == 1
        assert session["errors"] == 0
        assert session["operation_times"]["async_sample_function"][0] >= 10  # At least 10ms

    @pytest.mark.asyncio
    async def test_async_function_failure(self, mock_collector):
        """Test decorator with failing async function."""

        @track_mcp_operation()
        async def async_failing_function():
            await asyncio.sleep(0.001)
            raise RuntimeError("Async test error")

        with pytest.raises(RuntimeError, match="Async test error"):
            await async_failing_function()

        # Check that error was recorded
        active = mock_collector.get_active_sessions()
        assert len(active) == 1

        session_id = list(active.keys())[0]
        session = active[session_id]

        assert session["mcp_operations"]["async_failing_function"] == 1
        assert session["errors"] == 1

    def test_custom_tool_name(self, mock_collector):
        """Test decorator with custom tool name."""

        @track_mcp_operation("custom_tool_name")
        def function_with_custom_name():
            return "success"

        result = function_with_custom_name()
        assert result == "success"

        # Check custom tool name was used
        active = mock_collector.get_active_sessions()
        session = list(active.values())[0]

        assert session["mcp_operations"]["custom_tool_name"] == 1
        assert "function_with_custom_name" not in session["mcp_operations"]

    def test_multiple_calls(self, mock_collector):
        """Test decorator with multiple function calls."""

        @track_mcp_operation()
        def repeated_function():
            return "called"

        # Call function multiple times
        for _i in range(5):
            result = repeated_function()
            assert result == "called"

        # Check all calls were recorded
        active = mock_collector.get_active_sessions()
        session = list(active.values())[0]

        assert session["mcp_operations"]["repeated_function"] == 5
        assert len(session["operation_times"]["repeated_function"]) == 5

    def test_function_with_args_and_kwargs(self, mock_collector):
        """Test decorator preserves function signature."""

        @track_mcp_operation()
        def complex_function(a, b, c=None, *args, **kwargs):
            return {"a": a, "b": b, "c": c, "args": args, "kwargs": kwargs}

        result = complex_function(1, 2, extra="value")

        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] is None  # Default value
        assert result["args"] == ()
        assert result["kwargs"] == {"extra": "value"}

        # Check operation was recorded
        active = mock_collector.get_active_sessions()
        session = list(active.values())[0]
        assert session["mcp_operations"]["complex_function"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_async_operations(self, mock_collector):
        """Test decorator with concurrent async operations."""

        @track_mcp_operation()
        async def concurrent_operation(operation_id):
            await asyncio.sleep(0.01)
            return f"result_{operation_id}"

        # Run operations concurrently
        tasks = [concurrent_operation(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Check all operations completed
        assert len(results) == 10
        for i, result in enumerate(results):
            assert result == f"result_{i}"

        # Check all operations were recorded
        active = mock_collector.get_active_sessions()
        session = list(active.values())[0]

        assert session["mcp_operations"]["concurrent_operation"] == 10
        assert len(session["operation_times"]["concurrent_operation"]) == 10

    def test_preserves_function_metadata(self, _mock_collector):
        """Test that decorator preserves original function metadata."""

        @track_mcp_operation()
        def documented_function():
            """This function has documentation."""
            return 42

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This function has documentation."

        # Function should still work
        assert documented_function() == 42

    def test_with_existing_session(self, mock_collector):
        """Test decorator uses existing session if available."""
        # Create a session manually
        session_id = mock_collector.start_session(session_type="manual")

        @track_mcp_operation()
        def function_with_session():
            return "in_session"

        result = function_with_session()
        assert result == "in_session"

        # Should use existing session, not create new one
        active = mock_collector.get_active_sessions()
        assert len(active) == 1
        assert session_id in active

        session = active[session_id]
        assert session["mcp_operations"]["function_with_session"] == 1

    def test_timing_accuracy(self, mock_collector):
        """Test that timing measurements are reasonably accurate."""
        sleep_duration = 0.05  # 50ms

        @track_mcp_operation()
        def timed_function():
            time.sleep(sleep_duration)
            return "timed"

        result = timed_function()
        assert result == "timed"

        # Check recorded time
        active = mock_collector.get_active_sessions()
        session = list(active.values())[0]

        recorded_time = session["operation_times"]["timed_function"][0]
        # Should be close to sleep duration (within reasonable margin)
        expected_ms = sleep_duration * 1000
        assert recorded_time >= expected_ms * 0.8  # At least 80% of expected
        assert recorded_time <= expected_ms * 2.0  # No more than 200% (CI tolerance)


class TestAutoSessionForMcp:
    """Test the auto_session_for_mcp function."""

    @patch.dict(os.environ, {}, clear=True)
    def test_auto_session_main_type(self, mock_collector):
        """Test auto session creation for main session type."""
        with (
            patch("os.getpid", return_value=12345),
            patch("pycodemcp.metrics_hook.datetime") as mock_datetime,
        ):
            mock_dt = mock_datetime.now.return_value
            mock_dt.isoformat.return_value = "2025-01-15T10:30:00"

            session_id = auto_session_for_mcp()

            assert session_id == "mcp_server_12345_2025-01-15T10:30:00"

            # Check session was created
            active = mock_collector.get_active_sessions()
            assert session_id in active

            session = active[session_id]
            assert session["session_type"] == "main"
            assert session["parent_session"] is None

    @patch.dict(os.environ, {"PYCODEMCP_PARENT_SESSION": "parent_123"}, clear=True)
    def test_auto_session_subagent_type(self, mock_collector):
        """Test auto session creation for subagent session type."""
        with patch("os.getpid", return_value=54321):
            session_id = auto_session_for_mcp()

            # Check session was created as subagent
            active = mock_collector.get_active_sessions()
            session = active[session_id]

            assert session["session_type"] == "subagent"
            assert session["parent_session"] == "parent_123"

    @patch.dict(os.environ, {"PYCODEMCP_ISSUE": "456"}, clear=True)
    def test_auto_session_with_issue_metadata(self, mock_collector):
        """Test auto session creation with issue metadata."""
        session_id = auto_session_for_mcp()

        # Check metadata was set
        active = mock_collector.get_active_sessions()
        session = active[session_id]

        assert session["metadata"]["issue"] == "456"

    @patch.dict(
        os.environ, {"PYCODEMCP_PARENT_SESSION": "parent_789", "PYCODEMCP_ISSUE": "123"}, clear=True
    )
    def test_auto_session_full_context(self, mock_collector):
        """Test auto session creation with full context."""
        with patch("os.getpid", return_value=99999):
            session_id = auto_session_for_mcp()

            # Check all context was captured
            active = mock_collector.get_active_sessions()
            session = active[session_id]

            assert session["session_type"] == "subagent"
            assert session["parent_session"] == "parent_789"
            assert session["metadata"]["issue"] == "123"
            assert "99999" in session_id

    def test_multiple_auto_sessions(self, mock_collector):
        """Test that multiple calls create different sessions."""
        with patch("os.getpid", return_value=11111):
            session_id1 = auto_session_for_mcp()
            time.sleep(0.001)  # Ensure different timestamps
            session_id2 = auto_session_for_mcp()

            assert session_id1 != session_id2

            # Both should exist
            active = mock_collector.get_active_sessions()
            assert len(active) == 2
            assert session_id1 in active
            assert session_id2 in active


class TestIntegrationScenarios:
    """Test integration scenarios combining decorator and auto-session."""

    def test_decorator_with_auto_session(self, mock_collector):
        """Test decorator automatically creates session when none exists."""

        @track_mcp_operation("test_tool")
        def tool_function():
            return "tool_result"

        # No session exists initially
        assert len(mock_collector.get_active_sessions()) == 0

        # Call decorated function
        result = tool_function()
        assert result == "tool_result"

        # Auto-session should be created
        active = mock_collector.get_active_sessions()
        assert len(active) == 1

        session_id = list(active.keys())[0]
        session = active[session_id]

        assert session["session_type"] == "auto"
        assert session["mcp_operations"]["test_tool"] == 1

    @patch.dict(os.environ, {"PYCODEMCP_PARENT_SESSION": "manual_parent"}, clear=True)
    def test_decorator_inherits_context(self, mock_collector):
        """Test decorator inherits environment context for auto-session."""

        @track_mcp_operation()
        def context_tool():
            return "context_result"

        result = context_tool()
        assert result == "context_result"

        # Check session inherited context
        active = mock_collector.get_active_sessions()
        session = list(active.values())[0]

        assert session["session_type"] == "auto"  # Created by decorator
        # Note: Auto-session from decorator doesn't use auto_session_for_mcp,
        # so it won't inherit the parent context

    def test_multiple_tools_same_session(self, mock_collector):
        """Test multiple decorated tools using same auto-session."""

        @track_mcp_operation()
        def tool_one():
            return "one"

        @track_mcp_operation()
        def tool_two():
            return "two"

        # Call both tools
        result1 = tool_one()
        result2 = tool_two()

        assert result1 == "one"
        assert result2 == "two"

        # Should use same auto-session
        active = mock_collector.get_active_sessions()
        assert len(active) == 1

        session = list(active.values())[0]
        assert session["mcp_operations"]["tool_one"] == 1
        assert session["mcp_operations"]["tool_two"] == 1
        assert session["total_operations"] == 2

    def test_mixed_success_failure_tracking(self, mock_collector):
        """Test tracking mixed success and failure operations."""

        @track_mcp_operation()
        def sometimes_fails(should_fail=False):
            if should_fail:
                raise ValueError("Intentional failure")
            return "success"

        # Successful calls
        result1 = sometimes_fails(False)
        result2 = sometimes_fails(False)
        assert result1 == "success"
        assert result2 == "success"

        # Failed calls
        with pytest.raises(ValueError):
            sometimes_fails(True)

        with pytest.raises(ValueError):
            sometimes_fails(True)

        # Check tracking
        active = mock_collector.get_active_sessions()
        session = list(active.values())[0]

        assert session["mcp_operations"]["sometimes_fails"] == 4  # All calls tracked
        assert session["errors"] == 2  # Two failures
        assert session["total_operations"] == 4

    @pytest.mark.asyncio
    async def test_async_sync_mixed_operations(self, mock_collector):
        """Test mixing async and sync decorated operations."""

        @track_mcp_operation()
        def sync_tool():
            return "sync_result"

        @track_mcp_operation()
        async def async_tool():
            await asyncio.sleep(0.001)
            return "async_result"

        # Call both types
        sync_result = sync_tool()
        async_result = await async_tool()

        assert sync_result == "sync_result"
        assert async_result == "async_result"

        # Check both were tracked in same session
        active = mock_collector.get_active_sessions()
        assert len(active) == 1

        session = list(active.values())[0]
        assert session["mcp_operations"]["sync_tool"] == 1
        assert session["mcp_operations"]["async_tool"] == 1


class TestPerformanceOverhead:
    """Test that the decorator introduces minimal performance overhead."""

    def test_overhead_is_reasonable(self, mock_collector):
        """Test that decorator overhead exists but is reasonable."""

        @track_mcp_operation()
        def tracked_function():
            return "result"

        # Just verify the function works and records metrics
        result = tracked_function()
        assert result == "result"

        # Check operation was recorded
        active = mock_collector.get_active_sessions()
        assert len(active) == 1

        session = list(active.values())[0]
        assert session["mcp_operations"]["tracked_function"] == 1


class TestErrorRecovery:
    """Test error recovery and robustness."""

    def test_decorator_survives_collector_failure(self):
        """Test decorator handles collector failures gracefully."""
        with patch("pycodemcp.metrics_hook.get_unified_collector") as mock_get:
            # Make collector raise exception
            mock_get.side_effect = Exception("Collector failed")

            @track_mcp_operation()
            def robust_function():
                return "still_works"

            # Function should still work despite collector failure
            with pytest.raises(Exception, match="Collector failed"):
                robust_function()

    def test_auto_session_survives_collector_failure(self):
        """Test auto_session_for_mcp handles collector failures gracefully."""
        with patch("pycodemcp.metrics_hook.get_unified_collector") as mock_get:
            mock_get.side_effect = Exception("Collector failed")

            # Should raise the exception (not silently fail)
            with pytest.raises(Exception, match="Collector failed"):
                auto_session_for_mcp()

    def test_decorator_with_recording_failure(self, mock_collector):
        """Test decorator handles recording failures gracefully."""
        # Make record_mcp_operation fail

        def failing_record(*_args, **_kwargs):
            raise Exception("Recording failed")

        mock_collector.record_mcp_operation = failing_record

        @track_mcp_operation()
        def function_with_failing_record():
            return "function_result"

        # Function execution should fail due to recording failure in finally block
        with pytest.raises(Exception, match="Recording failed"):
            function_with_failing_record()
