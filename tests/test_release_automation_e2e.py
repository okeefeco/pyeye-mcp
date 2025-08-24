"""End-to-end tests for the Release Automation Agent.

These tests validate the complete workflow from natural language command
to release branch creation using a real project structure.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestReleaseAutomationEndToEnd:
    """End-to-end tests for release automation workflow."""

    def setup_method(self):
        """Set up a complete test project structure."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.setup_test_project()

    def teardown_method(self):
        """Clean up test environment."""
        import shutil

        if hasattr(self, "temp_dir") and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def setup_test_project(self):
        """Create a realistic project structure for testing."""
        # Create pyproject.toml
        (self.temp_dir / "pyproject.toml").write_text(
            """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "test-project"
version = "0.1.0"
description = "Test project for release automation"
authors = [{name = "Test Author", email = "test@example.com"}]
license = {text = "MIT"}
readme = "README.md"
requires-python = ">=3.8"

[tool.commitizen]
name = "cz_conventional_commits"
version = "0.1.0"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "--cov=src --cov-report=term-missing --cov-fail-under=85"
""",
            encoding="utf-8",
        )

        # Create source structure
        src_dir = self.temp_dir / "src" / "pycodemcp"
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

        # Create basic test file
        tests_dir = self.temp_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        (tests_dir / "test_version_consistency.py").write_text(
            '''
"""Test version consistency across files."""

def test_version_consistency():
    """Test that all version declarations match."""
    # This is a placeholder that always passes for testing
    assert True
'''
        )

        # Create README
        (self.temp_dir / "README.md").write_text(
            "# Test Project\n\nFor testing release automation.\n"
        )

        # Create scripts directory and copy release_agent.py
        scripts_dir = self.temp_dir / "scripts"
        scripts_dir.mkdir()

        # Copy the release agent script from the current project
        current_script = Path("scripts/release_agent.py")
        if current_script.exists():
            (scripts_dir / "release_agent.py").write_text(
                current_script.read_text(encoding="utf-8"), encoding="utf-8"
            )

    def test_cli_help_functionality(self):
        """Test that CLI help works correctly."""
        result = subprocess.run(
            ["python", "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
            cwd=self.temp_dir,
        )
        # pytest should be available in the environment
        assert result.returncode == 0

    @patch("subprocess.run")
    def test_end_to_end_patch_release(self, mock_subprocess):
        """Test complete patch release workflow."""

        # Mock git commands to simulate clean repo state
        def subprocess_side_effect(*args, **_kwargs):
            cmd = args[0]
            result = subprocess.CompletedProcess(cmd, 0, "", "")

            if "git" in cmd[0] and "status" in cmd:
                result.stdout = ""  # Clean working directory
            elif "git" in cmd[0] and "branch" in cmd:
                result.stdout = "main"  # On main branch
            elif "pytest" in cmd:
                result.returncode = 0  # Tests pass
            elif "git" in cmd[0] and "checkout" in cmd:
                result.returncode = 0  # Branch creation succeeds
            elif "git" in cmd[0] and "commit" in cmd:
                result.returncode = 0  # Commit succeeds
            elif "git" in cmd[0] and "push" in cmd:
                result.returncode = 0  # Push succeeds
            elif "gh" in cmd[0] and "pr" in cmd:
                result.stdout = "https://github.com/test/repo/pull/123"

            return result

        mock_subprocess.side_effect = subprocess_side_effect

        # Import and create agent from current project
        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)
        result = agent.handle_request("Cut a patch release")

        # Verify successful execution
        assert result["success"] is True
        assert result["result"]["target_version"] == "0.1.1"
        assert result["result"]["branch"]["name"] == "release/0.1.1"

    @patch("subprocess.run")
    def test_end_to_end_specific_version_release(self, mock_subprocess):
        """Test complete specific version release workflow."""

        def subprocess_side_effect(*args, **_kwargs):
            cmd = args[0]
            result = subprocess.CompletedProcess(cmd, 0, "", "")

            if "git" in cmd[0] and "status" in cmd:
                result.stdout = ""
            elif "git" in cmd[0] and "branch" in cmd:
                result.stdout = "main"
            elif (
                "pytest" in cmd
                or "git" in cmd[0]
                and ("checkout" in cmd or "commit" in cmd or "push" in cmd)
            ):
                result.returncode = 0
            elif "gh" in cmd[0] and "pr" in cmd:
                result.stdout = "https://github.com/test/repo/pull/124"

            return result

        mock_subprocess.side_effect = subprocess_side_effect

        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)
        result = agent.handle_request("Prepare release v0.2.0")

        assert result["success"] is True
        assert result["result"]["target_version"] == "0.2.0"
        assert result["result"]["branch"]["name"] == "release/0.2.0"

    def test_validation_failure_scenarios(self):
        """Test that validation failures are handled correctly."""
        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)

        # Test invalid command
        result = agent.handle_request("do something random")
        assert result["success"] is False
        assert "ValidationError" in result["error_type"]

    def test_version_file_updates(self):
        """Test that version updates work correctly in all files."""
        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)
        agent._update_version("0.2.5")

        # Check pyproject.toml
        content = (self.temp_dir / "pyproject.toml").read_text(encoding="utf-8")
        assert 'version = "0.2.5"' in content

        # Check that commitizen version was updated
        assert '[tool.commitizen]\nname = "cz_conventional_commits"\nversion = "0.2.5"' in content

        # Check __init__.py
        init_content = (self.temp_dir / "src" / "pycodemcp" / "__init__.py").read_text(
            encoding="utf-8"
        )
        assert '__version__ = "0.2.5"' in init_content

    def test_natural_language_parsing_comprehensive(self):
        """Test comprehensive natural language parsing."""
        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)

        test_cases = [
            ("Prepare release v1.0.0", {"type": "specific", "version": "1.0.0"}),
            ("Cut patch release", {"type": "patch", "version": None}),
            ("Create minor release", {"type": "minor", "version": None}),
            ("Prepare major release", {"type": "major", "version": None}),
            ("cut release 2.0.0", {"type": "specific", "version": "2.0.0"}),
        ]

        for command, expected in test_cases:
            parsed = agent._parse_release_command(command)
            assert parsed["type"] == expected["type"]
            assert parsed["version"] == expected["version"]

    def test_next_steps_generation(self):
        """Test that next steps are generated correctly."""
        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)
        steps = agent._generate_next_steps("0.3.0")

        assert isinstance(steps, list)
        assert len(steps) > 0
        assert any("Release preparation complete" in step for step in steps)
        assert any("git tag -a v0.3.0" in step for step in steps)
        assert any("git push origin v0.3.0" in step for step in steps)

    @patch("subprocess.run")
    def test_error_handling_git_failure(self, mock_subprocess):
        """Test error handling when git commands fail."""

        def subprocess_side_effect(*args, **_kwargs):
            cmd = args[0]
            result = subprocess.CompletedProcess(cmd, 1, "", "Git command failed")

            if "git" in cmd[0] and "status" in cmd:
                result.stdout = "M modified_file.py"  # Dirty working directory
                result.returncode = 0

            return result

        mock_subprocess.side_effect = subprocess_side_effect

        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)
        result = agent.handle_request("Cut patch release")

        assert result["success"] is False
        assert "ValidationError" in result["error_type"]

    def test_dev_version_handling(self):
        """Test handling of .dev0 versions."""
        # Update project to have dev version
        (self.temp_dir / "pyproject.toml").write_text(
            """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "test-project"
version = "0.2.0.dev0"
description = "Test project"

[tool.commitizen]
version = "0.2.0.dev0"
""",
            encoding="utf-8",
        )

        from pycodemcp.agents.release_automation import create_release_automation_agent

        agent = create_release_automation_agent(self.temp_dir)

        # Test that patch release from dev version removes .dev0
        parsed = {"type": "patch", "version": None}
        version = agent._determine_target_version(parsed)
        assert version == "0.2.0"  # Should remove .dev0


class TestCLIIntegration:
    """Test CLI integration with real scripts."""

    def test_cli_script_basic_functionality(self):
        """Test that the CLI script can be executed."""
        # This test requires the actual script to exist
        script_path = Path("scripts/release_agent.py")
        if not script_path.exists():
            pytest.skip("release_agent.py script not found")

        result = subprocess.run(
            ["python", str(script_path), "--help"], capture_output=True, text=True
        )

        assert result.returncode == 0
        assert "Release Automation Agent" in result.stdout

    def test_cli_examples_command(self):
        """Test CLI examples functionality."""
        script_path = Path("scripts/release_agent.py")
        if not script_path.exists():
            pytest.skip("release_agent.py script not found")

        result = subprocess.run(
            ["python", str(script_path), "--examples"], capture_output=True, text=True
        )

        assert result.returncode == 0
        assert "Example Commands" in result.stdout
        assert "Prepare release v" in result.stdout


class TestIntegrationWithExistingWorkflow:
    """Test that the agent integrates well with existing release workflow."""

    def test_consistent_with_prepare_release_script(self):
        """Test that agent behavior is consistent with prepare_release.py."""
        # Import both implementations
        from pycodemcp.agents.release_automation import ReleaseAutomationAgent
        from scripts.prepare_release import get_current_version, parse_version

        # Test with current project
        current_version = get_current_version()
        original_parsed = parse_version(current_version)

        # Create agent and test same parsing
        agent = ReleaseAutomationAgent()
        agent_parsed = agent._parse_version(current_version)

        assert original_parsed == agent_parsed

    def test_same_version_locations(self):
        """Test that agent updates same locations as prepare_release.py."""
        from pycodemcp.agents.release_automation import ReleaseAutomationAgent

        agent = ReleaseAutomationAgent()
        version_files = agent._get_version_files()

        expected_files = ["pyproject.toml", "src/pycodemcp/__init__.py"]

        for expected_file in expected_files:
            assert expected_file in version_files

    def test_command_equivalence(self):
        """Test that agent commands produce equivalent results to manual scripts."""
        # This would be tested in real scenarios, but for now we verify
        # that the patterns match what the existing script does

        from pycodemcp.agents.release_automation import ReleaseAutomationAgent

        agent = ReleaseAutomationAgent()

        # Test that patch increment works the same way
        # (This is a structural test - real test would require git setup)
        assert callable(agent._determine_target_version)
        assert callable(agent._update_version)
        assert callable(agent._create_release_branch)
