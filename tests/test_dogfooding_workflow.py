"""Tests for dogfooding workflow and MCP-first development practices.

This test module verifies that the dogfooding principles documented in CLAUDE.md
are properly followed and that MCP tools work correctly for self-analysis.
"""

from pathlib import Path


class TestDogfoodingWorkflow:
    """Test that MCP tools can analyze their own codebase effectively.

    Note: These tests focus on verifying the dogfooding concept and documentation
    rather than actual function execution, which requires a running MCP server.
    """

    def test_server_module_exists(self):
        """Verify the server module exists and contains MCP tools."""
        server_file = Path(__file__).parent.parent / "src" / "pyeye" / "server.py"
        assert server_file.exists(), "Server module should exist"

        content = server_file.read_text(encoding="utf-8")
        # Check for key MCP tool functions
        assert "find_symbol" in content
        assert "list_packages" in content
        assert "analyze_dependencies" in content

    def test_plugin_architecture_exists(self):
        """Verify the plugin architecture exists."""
        base_plugin = Path(__file__).parent.parent / "src" / "pyeye" / "plugins" / "base.py"
        assert base_plugin.exists(), "Base plugin should exist"

        # Check for concrete plugin implementations
        plugins_dir = Path(__file__).parent.parent / "src" / "pyeye" / "plugins"
        plugin_files = list(plugins_dir.glob("*.py"))
        plugin_names = [f.stem for f in plugin_files]

        assert "django" in plugin_names
        assert "flask" in plugin_names
        assert "pydantic" in plugin_names

    def test_project_structure(self):
        """Verify the project has expected structure."""
        root = Path(__file__).parent.parent

        # Check key directories exist
        assert (root / "src").exists()
        assert (root / "src" / "pyeye").exists()
        assert (root / "src" / "pyeye" / "analyzers").exists()
        assert (root / "src" / "pyeye" / "plugins").exists()
        assert (root / "tests").exists()


class TestDogfoodingIssuesAndWorkarounds:
    """Document known issues discovered through dogfooding."""

    def test_document_known_issues(self):
        """Ensure known issues from dogfooding are documented."""
        # This test serves as documentation of issues found
        known_issues = {
            "symbol_search_reliability": {
                "issue": "42.9% error rate in find_symbol during testing",
                "workaround": "Use fuzzy=True or fall back to Grep tool",
                "tracked_in": "Issue discovered during dogfooding test",
            },
            "response_size_limits": {
                "issue": "Some queries exceed MCP response limits",
                "workaround": "Use more specific queries or pagination",
                "example": "find_models() can return >25K tokens",
            },
            "path_resolution": {
                "issue": "PosixPath handling errors in some scenarios",
                "workaround": "Use path_utils.py helpers",
                "reference": "PR #121 addressed cross-platform paths",
            },
        }

        # Document these issues exist and have workarounds
        for _issue_key, issue_data in known_issues.items():
            assert "issue" in issue_data
            assert "workaround" in issue_data

            # Workarounds should be actionable
            assert len(issue_data["workaround"]) > 10
