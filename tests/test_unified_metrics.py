"""Comprehensive tests for the unified metrics system."""

import json
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.unified_metrics import SessionMetrics, UnifiedMetricsCollector, get_unified_collector


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for metrics storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def metrics_collector(temp_storage_dir):
    """Create a UnifiedMetricsCollector with temporary storage."""
    return UnifiedMetricsCollector(storage_dir=temp_storage_dir)


class TestSessionMetrics:
    """Test SessionMetrics dataclass."""

    def test_default_values(self):
        """Test SessionMetrics with default values."""
        session = SessionMetrics(session_id="test_session", session_type="main")

        assert session.session_id == "test_session"
        assert session.session_type == "main"
        assert session.parent_session is None
        assert session.end_time is None
        assert session.mcp_operations == {}
        assert session.grep_operations == 0
        assert session.total_operations == 0
        assert session.errors == 0
        assert session.cache_hits == 0
        assert session.cache_misses == 0
        assert session.memory_peak_mb == 0.0
        assert session.metadata == {}
        assert datetime.fromisoformat(session.start_time)  # Should parse correctly

    def test_with_custom_values(self):
        """Test SessionMetrics with custom values."""
        custom_time = "2025-01-15T10:30:00"
        metadata = {"issue": 123, "task": "fix_bug"}

        session = SessionMetrics(
            session_id="custom_session",
            session_type="subagent",
            parent_session="parent_123",
            start_time=custom_time,
            metadata=metadata,
        )

        assert session.session_id == "custom_session"
        assert session.session_type == "subagent"
        assert session.parent_session == "parent_123"
        assert session.start_time == custom_time
        assert session.metadata == metadata


class TestUnifiedMetricsCollectorInitialization:
    """Test UnifiedMetricsCollector initialization."""

    def test_default_storage_dir(self):
        """Test initialization with default storage directory."""
        collector = UnifiedMetricsCollector()
        expected_dir = Path.home() / ".pycodemcp" / "unified_metrics"

        assert collector.storage_dir == expected_dir
        assert collector.active_sessions_file == expected_dir / "active_sessions.json"
        assert collector.completed_sessions_file == expected_dir / "completed_sessions.jsonl"
        assert collector.aggregated_stats_file == expected_dir / "aggregated_stats.json"

    def test_custom_storage_dir(self, temp_storage_dir):
        """Test initialization with custom storage directory."""
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        assert collector.storage_dir == temp_storage_dir
        assert collector.active_sessions_file == temp_storage_dir / "active_sessions.json"
        assert collector.completed_sessions_file == temp_storage_dir / "completed_sessions.jsonl"
        assert collector.aggregated_stats_file == temp_storage_dir / "aggregated_stats.json"

    def test_creates_storage_directory(self, temp_storage_dir):
        """Test that storage directory is created."""
        storage_subdir = temp_storage_dir / "metrics"
        UnifiedMetricsCollector(storage_dir=storage_subdir)

        assert storage_subdir.exists()
        assert storage_subdir.is_dir()

    def test_initializes_files(self, temp_storage_dir):
        """Test that required files are initialized."""
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        # Check files exist
        assert collector.active_sessions_file.exists()
        assert collector.completed_sessions_file.exists()
        assert collector.aggregated_stats_file.exists()

        # Check initial content
        active_data = collector._read_json(collector.active_sessions_file)
        assert active_data == {}

        # JSONL file should be empty initially
        assert collector.completed_sessions_file.read_text().strip() == ""

        # Check aggregated stats structure
        stats_data = collector._read_json(collector.aggregated_stats_file)
        assert "last_updated" in stats_data
        assert stats_data["total_sessions"] == 0
        assert stats_data["total_mcp_operations"] == 0
        assert stats_data["total_grep_operations"] == 0
        assert stats_data["mcp_adoption_rate"] == 0.0


class TestFileOperations:
    """Test file locking and JSON operations."""

    def test_read_write_json(self, metrics_collector):
        """Test JSON read/write operations."""
        test_data = {"test": "data", "number": 42, "array": [1, 2, 3]}

        metrics_collector._write_json(metrics_collector.active_sessions_file, test_data)
        read_data = metrics_collector._read_json(metrics_collector.active_sessions_file)

        assert read_data == test_data

    def test_append_jsonl(self, metrics_collector):
        """Test JSONL append operations."""
        test_entries = [
            {"session": "test1", "data": "first"},
            {"session": "test2", "data": "second"},
            {"session": "test3", "data": "third"},
        ]

        # Append multiple entries
        for entry in test_entries:
            metrics_collector._append_jsonl(metrics_collector.completed_sessions_file, entry)

        # Read back and verify
        content = metrics_collector.completed_sessions_file.read_text()
        lines = [line.strip() for line in content.split("\n") if line.strip()]

        assert len(lines) == 3
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed == test_entries[i]

    def test_concurrent_file_access(self, metrics_collector):
        """Test that file locking prevents data corruption."""
        results = []
        errors = []

        def write_data(thread_id):
            try:
                for i in range(10):
                    data = {"thread": thread_id, "iteration": i, "timestamp": time.time()}
                    metrics_collector._write_json(metrics_collector.active_sessions_file, data)
                    time.sleep(0.001)  # Small delay to increase contention
                results.append(f"thread_{thread_id}_success")
            except Exception as e:
                errors.append(f"thread_{thread_id}_error: {e}")

        # Start multiple threads writing concurrently
        threads = []
        for i in range(5):
            thread = threading.Thread(target=write_data, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        assert len(errors) == 0, f"Concurrent access errors: {errors}"
        assert len(results) == 5


class TestSessionManagement:
    """Test session lifecycle management."""

    def test_start_session_basic(self, metrics_collector):
        """Test starting a basic session."""
        session_id = metrics_collector.start_session(session_id="test_session", session_type="main")

        assert session_id == "test_session"

        # Check session stored in active sessions
        active = metrics_collector.get_active_sessions()
        assert "test_session" in active

        session = active["test_session"]
        assert session["session_id"] == "test_session"
        assert session["session_type"] == "main"
        assert session["parent_session"] is None
        assert session["end_time"] is None
        assert datetime.fromisoformat(session["start_time"])

    def test_start_session_auto_id(self, metrics_collector):
        """Test starting session with auto-generated ID."""
        session_id = metrics_collector.start_session(session_type="subagent")

        assert session_id.startswith("subagent_")
        assert datetime.fromisoformat(session_id.split("_", 1)[1])  # Should parse datetime

    def test_start_session_with_parent(self, metrics_collector):
        """Test starting session with parent relationship."""
        parent_id = metrics_collector.start_session(session_type="main")
        child_id = metrics_collector.start_session(
            session_type="subagent", parent_session=parent_id, metadata={"task": "analyze_code"}
        )

        active = metrics_collector.get_active_sessions()

        # Check parent session
        assert parent_id in active
        assert active[parent_id]["parent_session"] is None

        # Check child session
        assert child_id in active
        assert active[child_id]["parent_session"] == parent_id
        assert active[child_id]["metadata"]["task"] == "analyze_code"

    def test_thread_local_session(self, metrics_collector):
        """Test thread-local session tracking."""
        session_id = metrics_collector.start_session(session_type="main")

        # Check thread-local storage
        assert metrics_collector._local.session_id == session_id

        def check_different_thread():
            # Different thread should not have session_id set
            assert not hasattr(metrics_collector._local, "session_id")

        thread = threading.Thread(target=check_different_thread)
        thread.start()
        thread.join()

    def test_end_session(self, metrics_collector):
        """Test ending a session."""
        # Start session and record some operations
        session_id = metrics_collector.start_session(session_type="main")
        metrics_collector.record_mcp_operation("find_symbol", session_id)
        metrics_collector.record_mcp_operation("goto_definition", session_id)
        metrics_collector.record_grep_operation(session_id)

        # End session
        metrics_collector.end_session(session_id)

        # Check session removed from active
        active = metrics_collector.get_active_sessions()
        assert session_id not in active

        # Check session moved to completed
        with open(metrics_collector.completed_sessions_file) as f:
            completed_line = f.read().strip()
            completed_session = json.loads(completed_line)

        assert completed_session["session_id"] == session_id
        assert completed_session["end_time"] is not None
        assert "statistics" in completed_session

        # Check calculated statistics
        stats = completed_session["statistics"]
        assert stats["mcp_operations_count"] == 2
        assert stats["grep_operations_count"] == 1
        assert stats["mcp_adoption_rate"] == 2 / 3  # 2 MCP out of 3 total
        assert stats["duration_minutes"] > 0

    def test_end_nonexistent_session(self, metrics_collector):
        """Test ending a session that doesn't exist."""
        result = metrics_collector.end_session("nonexistent")
        assert result == {}

    def test_end_session_thread_local_cleanup(self, metrics_collector):
        """Test that thread-local session is cleaned up."""
        session_id = metrics_collector.start_session(session_type="main")
        assert metrics_collector._local.session_id == session_id

        metrics_collector.end_session(session_id)
        assert not hasattr(metrics_collector._local, "session_id")


class TestOperationRecording:
    """Test recording of different operation types."""

    def test_record_mcp_operation_basic(self, metrics_collector):
        """Test recording basic MCP operations."""
        session_id = metrics_collector.start_session(session_type="main")

        # Record various operations
        metrics_collector.record_mcp_operation("find_symbol", session_id)
        metrics_collector.record_mcp_operation("find_symbol", session_id)  # Duplicate
        metrics_collector.record_mcp_operation("goto_definition", session_id)

        active = metrics_collector.get_active_sessions()
        session = active[session_id]

        assert session["mcp_operations"]["find_symbol"] == 2
        assert session["mcp_operations"]["goto_definition"] == 1
        assert session["total_operations"] == 3

    def test_record_mcp_operation_with_duration(self, metrics_collector):
        """Test recording MCP operations with duration."""
        session_id = metrics_collector.start_session(session_type="main")

        metrics_collector.record_mcp_operation("find_symbol", session_id, duration_ms=150.5)
        metrics_collector.record_mcp_operation("find_symbol", session_id, duration_ms=75.2)

        active = metrics_collector.get_active_sessions()
        session = active[session_id]

        assert "operation_times" in session
        assert "find_symbol" in session["operation_times"]
        assert session["operation_times"]["find_symbol"] == [150.5, 75.2]

    def test_record_mcp_operation_failures(self, metrics_collector):
        """Test recording failed MCP operations."""
        session_id = metrics_collector.start_session(session_type="main")

        # Record successful and failed operations
        metrics_collector.record_mcp_operation("find_symbol", session_id, success=True)
        metrics_collector.record_mcp_operation("goto_definition", session_id, success=False)
        metrics_collector.record_mcp_operation("find_references", session_id, success=False)

        active = metrics_collector.get_active_sessions()
        session = active[session_id]

        assert session["errors"] == 2
        assert session["total_operations"] == 3

    def test_record_mcp_operation_auto_session(self, metrics_collector):
        """Test that MCP operations create auto-session if needed."""
        # No active session
        assert not hasattr(metrics_collector._local, "session_id")

        metrics_collector.record_mcp_operation("find_symbol")

        # Should create auto session
        active = metrics_collector.get_active_sessions()
        assert len(active) == 1

        session_id = list(active.keys())[0]
        assert session_id.startswith("auto_")
        assert active[session_id]["session_type"] == "auto"

    def test_record_grep_operation(self, metrics_collector):
        """Test recording grep operations."""
        session_id = metrics_collector.start_session(session_type="main")

        # Record multiple grep operations
        metrics_collector.record_grep_operation(session_id)
        metrics_collector.record_grep_operation(session_id)
        metrics_collector.record_grep_operation(session_id)

        active = metrics_collector.get_active_sessions()
        session = active[session_id]

        assert session["grep_operations"] == 3
        assert session["total_operations"] == 3

    def test_record_grep_operation_no_session(self, metrics_collector):
        """Test grep operation with no session does nothing."""
        # No session created
        metrics_collector.record_grep_operation()

        active = metrics_collector.get_active_sessions()
        assert len(active) == 0

    def test_update_cache_stats(self, metrics_collector):
        """Test updating cache statistics."""
        session_id = metrics_collector.start_session(session_type="main")

        # Update cache stats multiple times
        metrics_collector.update_cache_stats(hits=5, misses=2, session_id=session_id)
        metrics_collector.update_cache_stats(hits=3, misses=1, session_id=session_id)

        active = metrics_collector.get_active_sessions()
        session = active[session_id]

        assert session["cache_hits"] == 8
        assert session["cache_misses"] == 3

    def test_mixed_operations(self, metrics_collector):
        """Test recording mixed operation types."""
        session_id = metrics_collector.start_session(session_type="main")

        # Record mixed operations
        metrics_collector.record_mcp_operation("find_symbol", session_id)
        metrics_collector.record_grep_operation(session_id)
        metrics_collector.record_mcp_operation("goto_definition", session_id, success=False)
        metrics_collector.update_cache_stats(hits=10, misses=2, session_id=session_id)

        active = metrics_collector.get_active_sessions()
        session = active[session_id]

        assert sum(session["mcp_operations"].values()) == 2
        assert session["grep_operations"] == 1
        assert session["total_operations"] == 3
        assert session["errors"] == 1
        assert session["cache_hits"] == 10
        assert session["cache_misses"] == 2


class TestSessionTree:
    """Test hierarchical session view."""

    def test_get_session_tree_single_session(self, metrics_collector):
        """Test session tree with single root session."""
        session_id = metrics_collector.start_session(session_type="main")

        tree = metrics_collector.get_session_tree()

        assert len(tree) == 1
        assert session_id in tree
        assert tree[session_id]["children"] == []
        assert tree[session_id]["session_id"] == session_id

    def test_get_session_tree_with_children(self, metrics_collector):
        """Test session tree with parent-child relationships."""
        parent_id = metrics_collector.start_session(session_type="main")
        child1_id = metrics_collector.start_session(
            session_type="subagent", parent_session=parent_id
        )
        child2_id = metrics_collector.start_session(session_type="task", parent_session=parent_id)

        tree = metrics_collector.get_session_tree()

        # Should have only parent at root level
        assert len(tree) == 1
        assert parent_id in tree

        # Parent should have two children
        parent = tree[parent_id]
        assert len(parent["children"]) == 2

        child_ids = [child["session_id"] for child in parent["children"]]
        assert child1_id in child_ids
        assert child2_id in child_ids

    def test_get_session_tree_orphaned_children(self, metrics_collector):
        """Test session tree with orphaned children (parent not found)."""
        # Create child with non-existent parent
        metrics_collector.start_session(
            session_type="subagent", parent_session="nonexistent_parent"
        )

        tree = metrics_collector.get_session_tree()

        # Should have no root sessions (child is orphaned)
        assert len(tree) == 0

    def test_get_session_tree_multiple_roots(self, metrics_collector):
        """Test session tree with multiple root sessions."""
        root1_id = metrics_collector.start_session(session_type="main")
        root2_id = metrics_collector.start_session(session_type="main")
        child_id = metrics_collector.start_session(session_type="subagent", parent_session=root1_id)

        tree = metrics_collector.get_session_tree()

        # Should have two root sessions
        assert len(tree) == 2
        assert root1_id in tree
        assert root2_id in tree

        # First root should have child, second should not
        assert len(tree[root1_id]["children"]) == 1
        assert len(tree[root2_id]["children"]) == 0
        assert tree[root1_id]["children"][0]["session_id"] == child_id


class TestAggregatedStatistics:
    """Test aggregated statistics and reporting."""

    def test_empty_aggregated_stats(self, metrics_collector):
        """Test initial empty aggregated statistics."""
        stats = metrics_collector._read_json(metrics_collector.aggregated_stats_file)

        assert stats["total_sessions"] == 0
        assert stats["total_mcp_operations"] == 0
        assert stats["total_grep_operations"] == 0
        assert stats["mcp_adoption_rate"] == 0.0
        assert stats["tool_usage"] == {}
        assert stats["top_tools"] == []
        assert stats["error_rate"] == 0.0
        assert stats["cache_hit_rate"] == 0.0

    def test_update_aggregated_stats(self, metrics_collector):
        """Test updating aggregated statistics with completed session."""
        # Create and end a session
        session_id = metrics_collector.start_session(session_type="main")
        metrics_collector.record_mcp_operation("find_symbol", session_id)
        metrics_collector.record_mcp_operation("find_symbol", session_id)
        metrics_collector.record_mcp_operation("goto_definition", session_id)
        metrics_collector.record_grep_operation(session_id)

        metrics_collector.end_session(session_id)

        # Check updated aggregated stats
        stats = metrics_collector._read_json(metrics_collector.aggregated_stats_file)

        assert stats["total_sessions"] == 1
        assert stats["total_mcp_operations"] == 3
        assert stats["total_grep_operations"] == 1
        assert stats["mcp_adoption_rate"] == 0.75  # 3/4

        assert stats["tool_usage"]["find_symbol"] == 2
        assert stats["tool_usage"]["goto_definition"] == 1

        assert stats["session_types"]["main"] == 1

        # Top tools should be sorted by usage
        assert len(stats["top_tools"]) == 2
        assert stats["top_tools"][0] == ["find_symbol", 2]
        assert stats["top_tools"][1] == ["goto_definition", 1]

    def test_aggregated_stats_multiple_sessions(self, metrics_collector):
        """Test aggregated statistics across multiple sessions."""
        # Session 1
        session1_id = metrics_collector.start_session(session_type="main")
        metrics_collector.record_mcp_operation("find_symbol", session1_id)
        metrics_collector.record_grep_operation(session1_id)
        metrics_collector.end_session(session1_id)

        # Session 2
        session2_id = metrics_collector.start_session(session_type="subagent")
        metrics_collector.record_mcp_operation("find_symbol", session2_id)
        metrics_collector.record_mcp_operation("goto_definition", session2_id)
        metrics_collector.end_session(session2_id)

        # Check aggregated stats
        stats = metrics_collector._read_json(metrics_collector.aggregated_stats_file)

        assert stats["total_sessions"] == 2
        assert stats["total_mcp_operations"] == 3
        assert stats["total_grep_operations"] == 1
        assert stats["mcp_adoption_rate"] == 0.75  # 3/4

        assert stats["tool_usage"]["find_symbol"] == 2
        assert stats["tool_usage"]["goto_definition"] == 1

        assert stats["session_types"]["main"] == 1
        assert stats["session_types"]["subagent"] == 1

    def test_activity_patterns(self, metrics_collector):
        """Test that activity patterns are recorded correctly."""
        # Mock current time for consistent testing
        with patch("pycodemcp.unified_metrics.datetime") as mock_datetime:
            mock_time = datetime(2025, 1, 15, 14, 30, 0)  # 2:30 PM
            mock_datetime.now.return_value = mock_time
            mock_datetime.fromisoformat = datetime.fromisoformat  # Keep original

            session_id = metrics_collector.start_session(session_type="main")
            metrics_collector.record_mcp_operation("find_symbol", session_id)

            # End session (this triggers stats update)
            metrics_collector.end_session(session_id)

            # Check activity patterns
            stats = metrics_collector._read_json(metrics_collector.aggregated_stats_file)

            assert stats["hourly_activity"]["14"] == 1  # 14:00 hour
            assert stats["daily_activity"]["2025-01-15"] == 1


class TestReporting:
    """Test reporting functionality."""

    def test_get_aggregated_report_basic(self, metrics_collector):
        """Test basic aggregated report."""
        # Create some test data
        session_id = metrics_collector.start_session(session_type="main")
        metrics_collector.record_mcp_operation("find_symbol", session_id)
        metrics_collector.record_grep_operation(session_id)
        metrics_collector.end_session(session_id)

        report = metrics_collector.get_aggregated_report(days=7)

        assert report["period"] == "Last 7 days"
        assert "generated_at" in report
        assert "summary" in report
        assert "global_stats" in report
        assert "active_sessions" in report

        # Check summary for recent activity
        summary = report["summary"]
        assert summary["total_sessions"] >= 0
        assert summary["active_sessions"] >= 0

    def test_get_aggregated_report_with_sessions(self, metrics_collector):
        """Test aggregated report including session details."""
        # Create and end a session
        session_id = metrics_collector.start_session(session_type="main")
        metrics_collector.record_mcp_operation("find_symbol", session_id)
        metrics_collector.end_session(session_id)

        report = metrics_collector.get_aggregated_report(days=7, include_sessions=True)

        assert "recent_sessions" in report
        assert len(report["recent_sessions"]) > 0

        session = report["recent_sessions"][0]
        assert session["session_id"] == session_id
        assert "statistics" in session

    def test_export_for_dashboard(self, metrics_collector):
        """Test dashboard export format."""
        # Create active and completed sessions
        active_id = metrics_collector.start_session(session_type="main")
        metrics_collector.record_mcp_operation("find_symbol", active_id)

        completed_id = metrics_collector.start_session(session_type="subagent")
        metrics_collector.record_mcp_operation("goto_definition", completed_id)
        metrics_collector.end_session(completed_id)

        dashboard_data = metrics_collector.export_for_dashboard()

        assert "timestamp" in dashboard_data
        assert "overview" in dashboard_data
        assert "charts" in dashboard_data
        assert "live_activity" in dashboard_data

        # Check overview
        overview = dashboard_data["overview"]
        assert overview["active_sessions"] >= 1
        assert overview["total_sessions"] >= 1

        # Check charts
        charts = dashboard_data["charts"]
        assert "tool_usage" in charts
        assert "hourly_activity" in charts
        assert "daily_trend" in charts
        assert "session_types" in charts

        # Check live activity
        live_activity = dashboard_data["live_activity"]
        assert len(live_activity) >= 1
        assert live_activity[0]["session"] == active_id


class TestConcurrency:
    """Test concurrent access scenarios."""

    def test_concurrent_session_creation(self, metrics_collector):
        """Test concurrent session creation."""
        results = []
        errors = []

        def create_session(thread_id):
            try:
                session_id = metrics_collector.start_session(session_type=f"thread_{thread_id}")
                results.append(session_id)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = []
        for i in range(10):
            thread = threading.Thread(target=create_session, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert len(errors) == 0, f"Concurrent session creation errors: {errors}"
        assert len(results) == 10
        assert len(set(results)) == 10  # All session IDs should be unique

    def test_concurrent_operation_recording(self, metrics_collector):
        """Test concurrent operation recording."""
        session_id = metrics_collector.start_session(session_type="main")
        results = []
        errors = []

        def record_operations(thread_id):
            try:
                for _i in range(10):
                    metrics_collector.record_mcp_operation(f"tool_{thread_id}", session_id)
                results.append(f"thread_{thread_id}_success")
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = []
        for i in range(5):
            thread = threading.Thread(target=record_operations, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert len(errors) == 0, f"Concurrent operation recording errors: {errors}"
        assert len(results) == 5

        # Check final state
        active = metrics_collector.get_active_sessions()
        session = active[session_id]

        # Each thread recorded 10 operations of its tool
        for i in range(5):
            assert session["mcp_operations"][f"tool_{i}"] == 10


class TestGlobalCollectorFunction:
    """Test global collector function."""

    def test_get_unified_collector_singleton(self):
        """Test that global collector is singleton."""
        collector1 = get_unified_collector()
        collector2 = get_unified_collector()

        assert collector1 is collector2

    def test_get_unified_collector_defaults(self):
        """Test global collector uses default settings."""
        collector = get_unified_collector()

        expected_dir = Path.home() / ".pycodemcp" / "unified_metrics"
        assert collector.storage_dir == expected_dir


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_invalid_session_operations(self, metrics_collector):
        """Test operations on invalid sessions."""
        # Operations on non-existent session should not crash
        metrics_collector.record_grep_operation("nonexistent")
        metrics_collector.update_cache_stats(1, 1, "nonexistent")

        # Should not create any active sessions
        active = metrics_collector.get_active_sessions()
        assert len(active) == 0

    def test_malformed_datetime_handling(self, metrics_collector):
        """Test handling of sessions with malformed timestamps."""
        session_id = metrics_collector.start_session(session_type="main")

        # Manually corrupt the start time
        active = metrics_collector.get_active_sessions()
        active[session_id]["start_time"] = "invalid_datetime"
        metrics_collector._write_json(metrics_collector.active_sessions_file, active)

        # Ending session should handle the error gracefully
        with pytest.raises((ValueError, TypeError)):
            metrics_collector.end_session(session_id)

    @patch("builtins.open")
    def test_file_permission_errors(self, mock_open, temp_storage_dir):
        """Test handling of file permission errors."""
        mock_open.side_effect = PermissionError("Permission denied")

        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        # Should handle permission errors gracefully
        with pytest.raises(PermissionError):
            collector._read_json(collector.active_sessions_file)

    def test_corrupted_json_handling(self, metrics_collector):
        """Test handling of corrupted JSON files."""
        # Write invalid JSON
        metrics_collector.active_sessions_file.write_text("invalid json content")

        # Should raise JSONDecodeError
        with pytest.raises(json.JSONDecodeError):
            metrics_collector._read_json(metrics_collector.active_sessions_file)


class TestPerformance:
    """Test performance characteristics."""

    def test_operation_recording_performance(self, metrics_collector):
        """Test that operation recording is fast enough."""
        from tests.utils.performance import CommonThresholds, assert_performance_threshold

        session_id = metrics_collector.start_session(session_type="main")

        # Time recording operations
        start = time.perf_counter()

        for i in range(100):
            metrics_collector.record_mcp_operation(f"tool_{i % 5}", session_id)

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Each operation should be very fast
        avg_per_operation = elapsed_ms / 100
        assert_performance_threshold(
            avg_per_operation, CommonThresholds.METRICS_OVERHEAD, "Metrics operation recording"
        )

    def test_session_end_performance(self, metrics_collector):
        """Test that session ending is reasonably fast."""
        from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

        session_id = metrics_collector.start_session(session_type="main")

        # Record many operations
        for i in range(1000):
            metrics_collector.record_mcp_operation(f"tool_{i % 10}", session_id)
            if i % 10 == 0:
                metrics_collector.record_grep_operation(session_id)

        # Time session ending
        start = time.perf_counter()
        metrics_collector.end_session(session_id)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Session ending should be reasonably fast even with many operations
        threshold = PerformanceThresholds(
            base=50.0,  # 50ms for local
            linux_ci=100.0,  # 100ms for Linux CI
            macos_ci=200.0,  # 200ms for macOS CI
            windows_ci=200.0,  # 200ms for Windows CI
        )

        assert_performance_threshold(elapsed_ms, threshold, "Session end with 1000 operations")
