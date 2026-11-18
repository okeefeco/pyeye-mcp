"""Tests for dogfooding metrics tracking."""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.dogfooding_metrics import DogfoodingMetrics


class TestDogfoodingMetrics:
    """Test metrics tracking functionality."""

    @pytest.fixture
    def temp_metrics_dir(self):
        """Create temporary directory for metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def metrics(self, temp_metrics_dir):
        """Create metrics instance with temp directory."""
        return DogfoodingMetrics(data_dir=temp_metrics_dir)

    def test_start_session(self, metrics):
        """Test starting a new session."""
        session = metrics.start_session(issue_number=123)

        assert session["issue"] == 123
        assert "start_time" in session
        # The CLI can't read the server's MCP metrics, so it stores none (#915)
        assert "baseline_metrics" not in session
        assert session["grep_count"] == 0
        assert session["mcp_queries"] == []

    def test_end_session(self, metrics):
        """Test ending a session."""
        # Start a session
        metrics.start_session(issue_number=123)

        # Add some data
        metrics.log_mcp_query("find_symbol", 150.5)
        metrics.log_grep_usage()
        metrics.log_time_saved(5, "Found references quickly")

        # End session
        result = metrics.end_session()

        assert "end_time" in result
        assert "stats" in result
        assert result["stats"]["mcp_queries_count"] == 1
        assert result["stats"]["grep_count"] == 1
        assert result["stats"]["time_saved_minutes"] == 5

    def test_mcp_query_logging(self, metrics):
        """Test logging MCP tool usage."""
        metrics.start_session()

        metrics.log_mcp_query("find_symbol", 120.5, success=True)
        metrics.log_mcp_query("analyze_dependencies", 250.0, success=False)

        session = metrics._load_session()
        assert len(session["mcp_queries"]) == 2
        assert session["mcp_queries"][0]["tool"] == "find_symbol"
        assert session["mcp_queries"][0]["success"] is True
        assert session["mcp_queries"][1]["success"] is False

    def test_bug_prevention_logging(self, metrics):
        """Test logging prevented bugs."""
        metrics.start_session()

        metrics.log_bug_prevented("Found missing reference in test file")
        metrics.log_bug_prevented("Discovered circular dependency")

        session = metrics._load_session()
        assert len(session["bugs_prevented"]) == 2
        assert session["bugs_prevented"][0]["description"] == "Found missing reference in test file"

    def test_generate_report(self, metrics):
        """Test report generation."""
        # Create multiple sessions
        for i in range(3):
            metrics.start_session(issue_number=100 + i)
            metrics.log_mcp_query("find_symbol", 100)
            metrics.log_mcp_query("get_type_info", 150)
            metrics.log_grep_usage()
            metrics.log_time_saved(10, f"Session {i}")
            metrics.end_session()

        # Generate report
        report = metrics.generate_report(days=7)

        assert report["sessions_count"] == 3
        assert report["mcp_adoption"]["total_mcp_queries"] == 6
        assert report["mcp_adoption"]["total_grep_usage"] == 3
        assert report["mcp_adoption"]["mcp_ratio"] == 6 / 9  # 66.7%
        assert report["impact"]["time_saved_minutes"] == 30

        # Check most used tools
        tool_usage = report["mcp_adoption"]["most_used_tools"]
        assert tool_usage[0][0] == "find_symbol"
        assert tool_usage[0][1] == 3

    def test_mcp_ratio_calculation(self, metrics):
        """Test MCP adoption ratio calculation."""
        metrics.start_session()

        # 3 MCP queries, 1 grep
        metrics.log_mcp_query("find_symbol", 100)
        metrics.log_mcp_query("find_references", 150)
        metrics.log_mcp_query("analyze_dependencies", 200)
        metrics.log_grep_usage()

        session = metrics.end_session()
        assert session["stats"]["mcp_ratio"] == 0.75  # 3/4

    def test_empty_session_handling(self, metrics):
        """Test handling of empty session."""
        metrics.start_session()
        session = metrics.end_session()

        assert session["stats"]["mcp_ratio"] == 0.0
        assert session["stats"]["mcp_queries_count"] == 0
        assert session["stats"]["grep_count"] == 0

    def test_no_active_session(self, metrics):
        """Test ending session when none exists."""
        result = metrics.end_session()
        assert "error" in result
        assert result["error"] == "No active session"

    def test_session_persistence(self, metrics):
        """Test that sessions persist to history."""
        # Create and end a session
        metrics.start_session(issue_number=99)
        metrics.log_time_saved(15, "Test saving")
        metrics.end_session()

        # Check history file exists
        history_file = metrics.history_file
        assert history_file.exists()

        # Load history
        with history_file.open() as f:
            history = [json.loads(line) for line in f]

        assert len(history) == 1
        assert history[0]["issue"] == 99
        assert history[0]["stats"]["time_saved_minutes"] == 15


class TestNoInProcessMcpRead:
    """The CLI counts MCP use from the queries it logs, nothing else (#915).

    It used to read the in-process ``pyeye.metrics`` collector at start and end,
    which is always empty outside the MCP server's process, and fall back to a
    tool removed in #271.
    """

    def test_end_counts_the_logged_queries_and_stores_no_server_metrics(self, tmp_path):
        metrics = DogfoodingMetrics(data_dir=tmp_path)
        metrics.start_session(issue_number=915)
        for tool in ("resolve", "inspect", "expand"):
            metrics.log_mcp_query(tool, 10.0)
        metrics.log_grep_usage()
        session = metrics.end_session()
        assert "final_metrics" not in session
        assert "baseline_metrics" not in session
        assert session["stats"]["mcp_queries_count"] == 3
        assert session["stats"]["mcp_ratio"] == 3 / 4

    def test_a_pre_915_session_still_ends(self, tmp_path):
        """A session saved by an older CLI, with baseline_metrics, ends normally."""
        metrics = DogfoodingMetrics(data_dir=tmp_path)
        session = metrics.start_session(issue_number=1)
        session["baseline_metrics"] = {"total_mcp_calls": 7}
        metrics._save_session(session)
        metrics.log_mcp_query("resolve", 1.0)
        assert metrics.end_session()["stats"]["mcp_queries_count"] == 1

    def test_the_dead_read_is_gone(self):
        import importlib.util

        assert not hasattr(DogfoodingMetrics, "_get_mcp_metrics")
        assert importlib.util.find_spec("scripts.dogfooding_integration") is None
        script = Path(__file__).resolve().parents[1] / "scripts" / "dogfooding_metrics.py"
        source = script.read_text(encoding="utf-8")
        assert "get_performance_metrics" not in source
