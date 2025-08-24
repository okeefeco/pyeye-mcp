"""Tests for the unified metrics CLI tool."""

# Import the CLI module by file path to avoid naming conflicts
import importlib.util
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.unified_metrics import UnifiedMetricsCollector

cli_path = Path(__file__).parent.parent / "scripts" / "unified_metrics.py"
spec = importlib.util.spec_from_file_location("unified_metrics_cli", cli_path)
cli_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli_module)

# Extract the functions we need
command_cleanup = cli_module.command_cleanup
command_dashboard = cli_module.command_dashboard
command_report = cli_module.command_report
command_status = cli_module.command_status
format_duration = cli_module.format_duration
format_percentage = cli_module.format_percentage
main = cli_module.main
print_separator = cli_module.print_separator


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for metrics storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_collector(temp_storage_dir):
    """Create a collector with sample data."""
    collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

    # Create some sample sessions
    main_session = collector.start_session(session_type="main")
    collector.record_mcp_operation("find_symbol", main_session)
    collector.record_mcp_operation("find_symbol", main_session)
    collector.record_mcp_operation("goto_definition", main_session)
    collector.record_grep_operation(main_session)
    collector.update_cache_stats(hits=10, misses=2, session_id=main_session)

    # Create subagent session
    sub_session = collector.start_session(session_type="subagent", parent_session=main_session)
    collector.record_mcp_operation("find_references", sub_session)
    collector.record_grep_operation(sub_session)

    # End one session to create completed data
    collector.end_session(sub_session)

    return collector


@pytest.fixture
def mock_collector_patch(sample_collector):
    """Patch get_unified_collector to return sample collector."""
    # Patch the get_unified_collector function that the CLI module imported
    with patch.object(cli_module, "get_unified_collector", return_value=sample_collector):
        yield sample_collector


class TestUtilityFunctions:
    """Test utility formatting functions."""

    def test_format_duration_seconds(self):
        """Test duration formatting for seconds."""
        assert format_duration(0.5) == "30s"
        assert format_duration(0.1) == "6s"

    def test_format_duration_minutes(self):
        """Test duration formatting for minutes."""
        assert format_duration(1.5) == "1.5m"
        assert format_duration(30.0) == "30.0m"
        assert format_duration(59.9) == "59.9m"

    def test_format_duration_hours(self):
        """Test duration formatting for hours."""
        assert format_duration(60.0) == "1.0h"
        assert format_duration(90.0) == "1.5h"
        assert format_duration(120.5) == "2.0h"

    def test_format_percentage_colors(self):
        """Test percentage formatting with colors."""
        # High percentage (green)
        high_result = format_percentage(0.85)
        assert "85.0%" in high_result
        assert "\033[92m" in high_result  # Green color
        assert "\033[0m" in high_result  # Reset color

        # Medium percentage (yellow)
        med_result = format_percentage(0.65)
        assert "65.0%" in med_result
        assert "\033[93m" in med_result  # Yellow color

        # Low percentage (red)
        low_result = format_percentage(0.25)
        assert "25.0%" in low_result
        assert "\033[91m" in low_result  # Red color

    def test_format_percentage_edge_cases(self):
        """Test percentage formatting edge cases."""
        assert "0.0%" in format_percentage(0.0)
        assert "100.0%" in format_percentage(1.0)
        assert "50.0%" in format_percentage(0.5)

    def test_print_separator(self, capsys):
        """Test separator printing."""
        print_separator("Test Title")
        captured = capsys.readouterr()

        assert "=" * 60 in captured.out
        assert "Test Title" in captured.out

        # Test without title
        print_separator()
        captured = capsys.readouterr()
        assert "-" * 60 in captured.out


class TestStatusCommand:
    """Test the status command."""

    def test_status_with_active_sessions(self, _mock_collector_patch, capsys):
        """Test status command with active sessions."""
        # Mock argparse namespace
        args = type("Args", (), {})()

        command_status(args)
        captured = capsys.readouterr()

        # Check for expected output elements
        assert "UNIFIED METRICS STATUS" in captured.out
        assert "Active Sessions" in captured.out
        assert "main" in captured.out
        assert "MCP" in captured.out
        assert "grep" in captured.out
        assert "Today's Activity" in captured.out

    def test_status_with_session_tree(self, _mock_collector_patch, capsys):
        """Test status displays parent-child relationships."""
        args = type("Args", (), {})()

        command_status(args)
        captured = capsys.readouterr()

        # Should show parent-child structure
        assert "main" in captured.out
        # Note: subagent was ended in fixture, so won't appear as active

    def test_status_no_active_sessions(self, temp_storage_dir, capsys):
        """Test status with no active sessions."""
        empty_collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        with patch.object(cli_module, "get_unified_collector", return_value=empty_collector):
            args = type("Args", (), {})()
            command_status(args)

            captured = capsys.readouterr()
            assert "No active sessions" in captured.out


class TestReportCommand:
    """Test the report command."""

    def test_report_basic(self, _mock_collector_patch, capsys):
        """Test basic report command."""
        args = type("Args", (), {"days": 7, "verbose": False})()

        command_report(args)
        captured = capsys.readouterr()

        # Check for expected sections
        assert "METRICS REPORT" in captured.out
        assert "Last 7 days" in captured.out
        assert "Summary:" in captured.out
        assert "All-Time Stats:" in captured.out
        assert "Most Used MCP Tools:" in captured.out
        assert "Session Types:" in captured.out

    def test_report_verbose(self, _mock_collector_patch, capsys):
        """Test verbose report command."""
        args = type("Args", (), {"days": 7, "verbose": True})()

        command_report(args)
        captured = capsys.readouterr()

        # Should include additional details
        assert "Recent Sessions Detail" in captured.out
        assert "Duration:" in captured.out

    def test_report_custom_days(self, _mock_collector_patch, capsys):
        """Test report with custom number of days."""
        args = type("Args", (), {"days": 30, "verbose": False})()

        command_report(args)
        captured = capsys.readouterr()

        assert "Last 30 days" in captured.out

    def test_report_with_tool_usage(self, _mock_collector_patch, capsys):
        """Test report shows tool usage statistics."""
        args = type("Args", (), {"days": 7, "verbose": False})()

        command_report(args)
        captured = capsys.readouterr()

        # Should show tools that were used in sample data
        assert "find_symbol" in captured.out or "goto_definition" in captured.out


class TestDashboardCommand:
    """Test the dashboard command."""

    def test_dashboard_pretty_format(self, _mock_collector_patch, capsys):
        """Test dashboard command with pretty format."""
        args = type("Args", (), {"format": "pretty"})()

        command_dashboard(args)
        captured = capsys.readouterr()

        # Check for expected dashboard sections
        assert "DASHBOARD DATA" in captured.out
        assert "Overview:" in captured.out
        assert "Active Sessions:" in captured.out
        assert "Total Sessions:" in captured.out
        assert "MCP Adoption:" in captured.out

    def test_dashboard_json_format(self, _mock_collector_patch, capsys):
        """Test dashboard command with JSON format."""
        args = type("Args", (), {"format": "json"})()

        command_dashboard(args)
        captured = capsys.readouterr()

        # Should output valid JSON
        try:
            data = json.loads(captured.out)
            assert "timestamp" in data
            assert "overview" in data
            assert "charts" in data
            assert "live_activity" in data
        except json.JSONDecodeError:
            pytest.fail("Dashboard JSON output is not valid JSON")

    def test_dashboard_with_activity_data(self, _mock_collector_patch, capsys):
        """Test dashboard shows activity data."""
        args = type("Args", (), {"format": "pretty"})()

        command_dashboard(args)
        captured = capsys.readouterr()

        # Should show some activity metrics
        assert "Top Tools:" in captured.out
        assert "Daily Trend" in captured.out

    def test_dashboard_live_activity(self, _mock_collector_patch, capsys):
        """Test dashboard shows live activity."""
        args = type("Args", (), {"format": "pretty"})()

        command_dashboard(args)
        captured = capsys.readouterr()

        # Should show live activity if there are active sessions
        if "Live Activity:" in captured.out:
            # If live activity is shown, should have session info
            assert "main" in captured.out


class TestCleanupCommand:
    """Test the cleanup command."""

    def test_cleanup_command(self, _mock_collector_patch, capsys):
        """Test cleanup command (currently just shows what would be done)."""
        args = type("Args", (), {"days": 30})()

        command_cleanup(args)
        captured = capsys.readouterr()

        # Currently just shows what would be cleaned
        assert "Would clean up data older than" in captured.out
        assert "Cleanup functionality not yet implemented" in captured.out

    def test_cleanup_custom_days(self, _mock_collector_patch, capsys):
        """Test cleanup with custom retention days."""
        args = type("Args", (), {"days": 90})()

        command_cleanup(args)
        captured = capsys.readouterr()

        # Should reference the custom days
        cutoff_date = datetime.now() - timedelta(days=90)
        assert cutoff_date.strftime("%Y-%m-%d") in captured.out


class TestMainFunction:
    """Test the main entry point function."""

    def test_main_no_args(self, _capsys):
        """Test main function with no arguments shows help."""
        with (
            patch("sys.argv", ["unified_metrics.py"]),
            patch("argparse.ArgumentParser.print_help") as mock_help,
        ):
            main()
            mock_help.assert_called_once()

    def test_main_status_command(self, _mock_collector_patch):
        """Test main function with status command."""
        with (
            patch("sys.argv", ["unified_metrics.py", "status"]),
            patch.object(cli_module, "command_status") as mock_status,
        ):
            main()
            mock_status.assert_called_once()

    def test_main_report_command(self, _mock_collector_patch):
        """Test main function with report command."""
        with (
            patch("sys.argv", ["unified_metrics.py", "report", "--days", "14"]),
            patch.object(cli_module, "command_report") as mock_report,
        ):
            main()
            mock_report.assert_called_once()

    def test_main_dashboard_command(self, _mock_collector_patch):
        """Test main function with dashboard command."""
        with (
            patch("sys.argv", ["unified_metrics.py", "dashboard", "--format", "json"]),
            patch.object(cli_module, "command_dashboard") as mock_dashboard,
        ):
            main()
            mock_dashboard.assert_called_once()

    def test_main_cleanup_command(self, _mock_collector_patch):
        """Test main function with cleanup command."""
        with (
            patch("sys.argv", ["unified_metrics.py", "cleanup", "--days", "60"]),
            patch.object(cli_module, "command_cleanup") as mock_cleanup,
        ):
            main()
            mock_cleanup.assert_called_once()

    def test_main_exception_handling(self, capsys):
        """Test main function handles exceptions gracefully."""
        with (
            patch("sys.argv", ["unified_metrics.py", "status"]),
            patch.object(cli_module, "command_status", side_effect=Exception("Test error")),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "❌ Error: Test error" in captured.err


class TestArgumentParsing:
    """Test argument parsing functionality."""

    def test_status_subcommand(self):
        """Test status subcommand parsing."""
        with (
            patch("sys.argv", ["unified_metrics.py", "status"]),
            patch.object(cli_module, "command_status") as mock_cmd,
        ):
            main()

            # Check that args were passed correctly
            args = mock_cmd.call_args[0][0]
            assert args.command == "status"

    def test_report_subcommand_defaults(self):
        """Test report subcommand with default arguments."""
        with (
            patch("sys.argv", ["unified_metrics.py", "report"]),
            patch.object(cli_module, "command_report") as mock_cmd,
        ):
            main()

            args = mock_cmd.call_args[0][0]
            assert args.command == "report"
            assert args.days == 7  # Default
            assert not args.verbose  # Default

    def test_report_subcommand_custom_args(self):
        """Test report subcommand with custom arguments."""
        with (
            patch("sys.argv", ["unified_metrics.py", "report", "--days", "14", "--verbose"]),
            patch.object(cli_module, "command_report") as mock_cmd,
        ):
            main()

            args = mock_cmd.call_args[0][0]
            assert args.command == "report"
            assert args.days == 14
            assert args.verbose

    def test_dashboard_subcommand_args(self):
        """Test dashboard subcommand argument parsing."""
        with (
            patch("sys.argv", ["unified_metrics.py", "dashboard", "--format", "json"]),
            patch.object(cli_module, "command_dashboard") as mock_cmd,
        ):
            main()

            args = mock_cmd.call_args[0][0]
            assert args.command == "dashboard"
            assert args.format == "json"

    def test_cleanup_subcommand_args(self):
        """Test cleanup subcommand argument parsing."""
        with (
            patch("sys.argv", ["unified_metrics.py", "cleanup", "--days", "45"]),
            patch.object(cli_module, "command_cleanup") as mock_cmd,
        ):
            main()

            args = mock_cmd.call_args[0][0]
            assert args.command == "cleanup"
            assert args.days == 45


class TestIntegrationScenarios:
    """Test integration scenarios with real data flow."""

    def test_full_workflow_simulation(self, temp_storage_dir, capsys):
        """Test complete workflow from session creation to reporting."""
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        # Simulate a complete development session
        session_id = collector.start_session(
            session_type="main", metadata={"issue": 123, "task": "implement_feature"}
        )

        # Simulate various operations
        for _ in range(5):
            collector.record_mcp_operation("find_symbol", session_id)
        for _ in range(3):
            collector.record_mcp_operation("goto_definition", session_id)
        for _ in range(2):
            collector.record_grep_operation(session_id)

        collector.update_cache_stats(hits=20, misses=5, session_id=session_id)
        collector.end_session(session_id)

        # Test reporting on this data
        with patch.object(cli_module, "get_unified_collector", return_value=collector):
            # Test status (no active sessions)
            args = type("Args", (), {})()
            command_status(args)
            status_output = capsys.readouterr().out
            assert "No active sessions" in status_output

            # Test report
            args = type("Args", (), {"days": 7, "verbose": True})()
            command_report(args)
            report_output = capsys.readouterr().out

            # Should show the completed session
            assert "find_symbol" in report_output
            assert "goto_definition" in report_output
            assert "All-Time Stats:" in report_output

    def test_multiple_session_types(self, temp_storage_dir, capsys):
        """Test reporting with multiple session types."""
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        # Create different types of sessions
        main_session = collector.start_session(session_type="main")
        collector.record_mcp_operation("find_symbol", main_session)
        collector.end_session(main_session)

        subagent_session = collector.start_session(session_type="subagent")
        collector.record_mcp_operation("goto_definition", subagent_session)
        collector.end_session(subagent_session)

        task_session = collector.start_session(session_type="task")
        collector.record_grep_operation(task_session)
        collector.end_session(task_session)

        # Test report shows session types
        with patch.object(cli_module, "get_unified_collector", return_value=collector):
            args = type("Args", (), {"days": 7, "verbose": False})()
            command_report(args)
            output = capsys.readouterr().out

            assert "Session Types:" in output
            assert "main:" in output
            assert "subagent:" in output
            assert "task:" in output

    def test_adoption_rate_calculation(self, temp_storage_dir, capsys):
        """Test MCP adoption rate calculation and display."""
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        # Create session with known MCP/grep ratio
        session_id = collector.start_session(session_type="main")

        # 8 MCP operations, 2 grep operations = 80% adoption
        for _ in range(8):
            collector.record_mcp_operation("find_symbol", session_id)
        for _ in range(2):
            collector.record_grep_operation(session_id)

        collector.end_session(session_id)

        # Test that adoption rate is displayed correctly
        with patch.object(cli_module, "get_unified_collector", return_value=collector):
            args = type("Args", (), {"days": 7, "verbose": False})()
            command_report(args)
            output = capsys.readouterr().out

            # Should show 80% adoption rate (formatted with color)
            assert "80.0%" in output

    def test_empty_data_handling(self, temp_storage_dir, capsys):
        """Test CLI handles empty data gracefully."""
        empty_collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        with patch.object(cli_module, "get_unified_collector", return_value=empty_collector):
            # Test all commands with empty data
            args = type("Args", (), {})()
            command_status(args)
            status_output = capsys.readouterr().out
            assert "No active sessions" in status_output

            args = type("Args", (), {"days": 7, "verbose": False})()
            command_report(args)
            report_output = capsys.readouterr().out
            assert "Summary:" in report_output  # Should still show structure

            args = type("Args", (), {"format": "pretty"})()
            command_dashboard(args)
            dashboard_output = capsys.readouterr().out
            assert "Overview:" in dashboard_output  # Should still show structure


class TestErrorHandling:
    """Test error handling in CLI commands."""

    def test_collector_exception_handling(self, _capsys):
        """Test handling of collector exceptions."""
        with patch.object(
            cli_module, "get_unified_collector", side_effect=Exception("Collector failed")
        ):
            args = type("Args", (), {})()

            # Should propagate the exception (handled by main)
            with pytest.raises(Exception, match="Collector failed"):
                command_status(args)

    def test_missing_data_files(self, temp_storage_dir, _capsys):
        """Test handling of missing data files."""
        # Create collector but remove data files
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)
        collector.active_sessions_file.unlink()

        with patch.object(cli_module, "get_unified_collector", return_value=collector):
            args = type("Args", (), {})()

            # Should handle missing files gracefully
            with pytest.raises(FileNotFoundError):
                command_status(args)

    def test_corrupted_json_handling(self, temp_storage_dir, _capsys):
        """Test handling of corrupted JSON files."""
        collector = UnifiedMetricsCollector(storage_dir=temp_storage_dir)

        # Corrupt the JSON file
        collector.active_sessions_file.write_text("invalid json content")

        with patch.object(cli_module, "get_unified_collector", return_value=collector):
            args = type("Args", (), {})()

            # Should handle corrupted JSON
            with pytest.raises(json.JSONDecodeError):
                command_status(args)
