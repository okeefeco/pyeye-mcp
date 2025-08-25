"""Tests for dogfooding automation setup."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from scripts.dogfooding_metrics import DogfoodingMetrics


class TestAutomationSetup:
    """Test automated dogfooding setup."""

    @pytest.mark.skipif(os.name == "nt", reason="Windows doesn't use Unix permissions")
    def test_install_hooks_script_exists(self):
        """Test that install hooks script exists and is executable."""
        script_path = Path("scripts/install_hooks.sh")
        assert script_path.exists()
        assert script_path.stat().st_mode & 0o111  # Executable

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_install_hooks_script_exists_windows(self):
        """Test that install hooks script exists on Windows."""
        script_path = Path("scripts/install_hooks.sh")
        assert script_path.exists()
        # On Windows, just check it's a file (executable check doesn't apply)
        assert script_path.is_file()

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
            ["python", "scripts/dogfooding_metrics.py", "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Dogfooding metrics" in result.stdout

    def test_git_hook_templates_valid(self):
        """Test that git hook templates are valid bash scripts."""
        install_script = Path("scripts/install_hooks.sh")
        content = install_script.read_text()

        # Check that hook templates have proper shebang
        assert "#!/bin/bash" in content

        # Check for key functionality
        assert "post-checkout" in content
        assert "pre-commit" in content
        assert "prepare-commit-msg" in content
        assert "dogfooding_metrics.py" in content

    def test_session_stats_saving(self):
        """Test that session stats are saved for git hooks."""
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
            ["python", "scripts/dogfooding_metrics.py", "end"], capture_output=True, text=True
        )
        # Should not crash, should show error message
        assert "No active session" in result.stdout

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
    """Test the logic that would be in git hooks."""

    def test_branch_issue_extraction(self):
        """Test extracting issue numbers from branch names."""
        test_cases = [
            ("feat/123-add-feature", "123"),
            ("fix/456-bug-fix", "456"),
            ("docs/789-update-readme", "789"),
            ("main", None),
            ("develop", None),
            ("feat-without-number", None),
        ]

        for branch, expected in test_cases:
            # Simulate the grep command from git hook
            import re

            match = re.search(r"[0-9]+", branch)
            issue = match.group() if match else None
            assert issue == expected

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

    def test_claude_md_has_automation_section(self):
        """Test that CLAUDE.md documents the automation."""
        claude_md = Path("CLAUDE.md")
        assert claude_md.exists()

        content = claude_md.read_text(encoding="utf-8")
        # Check for the new hooks-based approach (recommended)
        assert "Claude Code Hooks Integration" in content
        assert "setup_mcp_monitoring.sh" in content
        # Check for the alternative manual approach
        assert "Manual Tracking Setup" in content
        assert "setup_dogfooding.sh" in content
        assert "What Happens Automatically" in content

    def test_all_scripts_documented(self):
        """Test that all automation scripts are documented."""
        setup_doc = Path("docs/DOGFOODING_SETUP.md").read_text(encoding="utf-8")

        # Check that all scripts are mentioned
        assert "install_hooks.sh" in setup_doc
        assert "setup_aliases.sh" in setup_doc
        assert "setup_dogfooding.sh" in setup_doc
        assert "dogfooding_metrics.py" in setup_doc
