"""Tests for dogfooding automation setup."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scripts.dogfooding_metrics import DogfoodingMetrics


class TestAutomationSetup:
    """Test automated dogfooding setup."""

    @pytest.mark.skipif(os.name == "nt", reason="Windows doesn't use Unix permissions")
    def test_setup_aliases_script_exists(self):
        """Test that setup aliases script exists and is executable."""
        script_path = Path("scripts/setup_aliases.sh")
        assert script_path.exists()
        assert script_path.stat().st_mode & 0o111  # Executable

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_setup_aliases_script_exists_windows(self):
        """Test that setup aliases script exists on Windows."""
        script_path = Path("scripts/setup_aliases.sh")
        assert script_path.exists()
        assert script_path.is_file()

    @pytest.mark.skipif(os.name == "nt", reason="Windows doesn't use Unix permissions")
    def test_setup_dogfooding_script_exists(self):
        """Test that main setup script exists and is executable."""
        script_path = Path("scripts/setup_dogfooding.sh")
        assert script_path.exists()
        assert script_path.stat().st_mode & 0o111  # Executable

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_setup_dogfooding_script_exists_windows(self):
        """Test that main setup script exists on Windows."""
        script_path = Path("scripts/setup_dogfooding.sh")
        assert script_path.exists()
        assert script_path.is_file()

    def test_dogfooding_metrics_cli_help(self):
        """Test that dogfooding metrics CLI shows help."""
        result = subprocess.run(
            # sys.executable (the venv interpreter under `uv run`), NOT bare "python"
            # which would hit a system interpreter without the project's deps (#414).
            [sys.executable, "scripts/dogfooding_metrics.py", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Dogfooding metrics" in result.stdout

    def test_session_stats_saving(self):
        """Test that the latest session's stats are saved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = DogfoodingMetrics(data_dir=Path(tmpdir))

            # Start and end a session
            metrics.start_session(issue_number=123)
            metrics.log_mcp_query("find_symbol", 100.0)
            metrics.log_time_saved(5, "Test")
            metrics.end_session()

            # Check that stats file was created
            stats_file = Path(tmpdir) / "last_session_stats.json"
            assert stats_file.exists()

            # Check content
            import json

            stats = json.loads(stats_file.read_text())
            assert stats["mcp_queries_count"] == 1
            assert stats["time_saved_minutes"] == 5

    def test_automation_scripts_handle_errors(self):
        """Test that automation scripts handle errors gracefully."""
        # Test dogfooding metrics with no session
        result = subprocess.run(
            [sys.executable, "scripts/dogfooding_metrics.py", "end"],
            capture_output=True,
            text=True,
        )
        # Should not crash - either shows "No active session" or a summary
        assert result.returncode == 0
        assert "No active session" in result.stdout or "Session Summary" in result.stdout

    def test_metrics_directory_creation(self):
        """Test metrics directory creation."""
        from scripts.dogfooding_metrics import DogfoodingMetrics

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "test_metrics"
            DogfoodingMetrics(data_dir=test_dir)

            # Directory should be created automatically
            assert test_dir.exists()
            assert test_dir.is_dir()


class TestShellIntegration:
    """Test shell integration features."""

    def test_grep_wrapper_concept(self):
        """Test the concept of grep wrapper (without actually modifying system)."""

        # This tests the logic that would be in the shell alias
        def tracked_grep(*_args):
            # Simulate tracking call
            tracking_called = True
            # Simulate actual grep call
            grep_result = "function found"
            return tracking_called, grep_result

        tracking, result = tracked_grep("function", "file.py")
        assert tracking is True
        assert "function found" in result

    def test_cd_wrapper_concept(self):
        """Test the concept of cd wrapper (without actually changing directories)."""

        def tracked_cd(_path):
            # Simulate checking for dogfooding metrics
            has_metrics = Path("scripts/dogfooding_metrics.py").exists()
            # Simulate branch extraction
            branch = "feat/123-test-feature"
            issue = "123" if "123" in branch else None
            return has_metrics, issue

        has_metrics, issue = tracked_cd(".")
        assert has_metrics is True  # We are in the project
        assert issue == "123"


class TestGitHookLogic:
    """Session-file detection used by the shell helpers."""

    def test_metrics_session_file_detection(self):
        """Test detecting active metrics sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_dir = Path(tmpdir)
            session_file = metrics_dir / "current_session.json"

            # No session file
            assert not session_file.exists()

            # Create session file
            session_file.write_text('{"id": "test"}')
            assert session_file.exists()


class TestDocumentation:
    """Test that documentation files exist and are complete."""

    def test_dogfooding_setup_docs_exist(self):
        """Test that setup documentation exists."""
        docs_file = Path("docs/DOGFOODING_SETUP.md")
        assert docs_file.exists()

        content = docs_file.read_text(encoding="utf-8")
        assert "Quick Setup" in content
        assert "Git Hooks" in content
        assert "Shell Aliases" in content


class TestSessionHandover:
    """Starting a session finalises the open one instead of discarding it (#578).

    The retired ``install_hooks.sh`` ended the session in a hand-written git
    ``pre-commit`` hook. Without it, the next ``start`` (e.g. the post-checkout
    hook on the next branch) would overwrite ``current_session.json`` and the
    open session's data would never reach ``history.jsonl``.
    """

    @staticmethod
    def _history(data_dir: Path) -> list[dict]:
        history = data_dir / "history.jsonl"
        if not history.exists():
            return []
        return [json.loads(line) for line in history.read_text().splitlines()]

    def test_start_saves_open_session_to_history(self, tmp_path):
        metrics = DogfoodingMetrics(data_dir=tmp_path)
        metrics.start_session(issue_number=1)
        metrics.log_time_saved(5, "handover test")

        metrics.start_session(issue_number=2)

        history = self._history(tmp_path)
        assert [s["issue"] for s in history] == [1]
        assert "end_time" in history[0]
        assert history[0]["time_saved_estimates"][0]["minutes"] == 5
        assert metrics._load_session()["issue"] == 2

    def test_start_without_open_session_writes_no_history(self, tmp_path):
        metrics = DogfoodingMetrics(data_dir=tmp_path)
        metrics.start_session(issue_number=1)

        assert self._history(tmp_path) == []
        assert metrics._load_session()["issue"] == 1
