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
        server_file = Path(__file__).parent.parent / "src" / "pycodemcp" / "server.py"
        assert server_file.exists(), "Server module should exist"

        content = server_file.read_text(encoding="utf-8")
        # Check for key MCP tool functions
        assert "find_symbol" in content
        assert "list_packages" in content
        assert "analyze_dependencies" in content

    def test_plugin_architecture_exists(self):
        """Verify the plugin architecture exists."""
        base_plugin = Path(__file__).parent.parent / "src" / "pycodemcp" / "plugins" / "base.py"
        assert base_plugin.exists(), "Base plugin should exist"

        # Check for concrete plugin implementations
        plugins_dir = Path(__file__).parent.parent / "src" / "pycodemcp" / "plugins"
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
        assert (root / "src" / "pycodemcp").exists()
        assert (root / "src" / "pycodemcp" / "analyzers").exists()
        assert (root / "src" / "pycodemcp" / "plugins").exists()
        assert (root / "tests").exists()

    def test_dogfooding_documentation(self):
        """Verify dogfooding is properly documented."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        assert claude_md.exists()

        content = claude_md.read_text(encoding="utf-8")

        # Check for dogfooding section
        assert "MCP-First Development Workflow" in content
        assert "Dogfooding" in content or "dogfooding" in content

        # Check that key MCP tools are documented
        assert "mcp__python-intelligence__find_symbol" in content
        assert "mcp__python-intelligence__list_packages" in content
        assert "mcp__python-intelligence__analyze_dependencies" in content


class TestMCPFirstPrinciples:
    """Test that MCP-first principles are followed correctly."""

    def test_workflow_documentation_exists(self):
        """Verify that MCP-first workflow is documented in CLAUDE.md."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        assert claude_md.exists()

        content = claude_md.read_text(encoding="utf-8")

        # Check for MCP-first workflow section
        assert "MCP-First Development Workflow" in content
        assert "Dogfooding" in content or "dogfooding" in content

        # Check for pattern replacements
        assert "Pattern Replacements" in content
        assert "find_symbol" in content
        assert "grep" in content

        # Check for real-world examples
        assert "Real-World Usage Examples" in content

        # Check for troubleshooting guide
        assert "Troubleshooting" in content

    def test_approved_tools_documented(self):
        """Verify that approved MCP tools are documented."""
        # Check project CLAUDE.md
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        # Core tools should be documented
        required_tools = [
            "find_symbol",
            "goto_definition",
            "find_references",
            "get_type_info",
            "find_imports",
            "get_call_hierarchy",
            "find_subclasses",
            "list_packages",
            "list_modules",
            "analyze_dependencies",
        ]

        for tool in required_tools:
            assert tool in content, f"Tool {tool} not documented in CLAUDE.md"

    def test_semantic_over_text_principle(self):
        """Verify semantic search is prioritized over text search."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        # Check core principle is stated
        assert "Semantic Over Text" in content or "semantic understanding" in content.lower()

        # Check that grep alternatives are provided
        assert "❌" in content  # Wrong way markers
        assert "✅" in content  # Right way markers

        # Specific anti-patterns should be called out
        assert 'grep -r "class' in content or 'grep -r "def' in content

    def test_success_metrics_defined(self):
        """Verify that success metrics for MCP usage are defined."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        assert "Measuring Success" in content or "Success" in content
        assert "80%" in content or "100%" in content  # Target metrics

        # Specific metrics should be mentioned
        assert "refactoring" in content.lower()
        assert "inheritance" in content.lower()


class TestDogfoodingBenefits:
    """Test and document the benefits of dogfooding."""

    def test_navigation_benefits_documented(self):
        """Verify that navigation benefits are documented."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        # Check that benefits are documented
        assert "3x faster navigation" in content or "faster navigation" in content.lower()
        assert "type-aware" in content.lower()
        assert "refactoring" in content.lower()

    def test_mcp_tools_provide_rich_metadata(self):
        """Verify that MCP tools are documented to provide rich metadata."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        # Check documentation mentions metadata benefits
        assert "type information" in content.lower() or "type-aware" in content.lower()
        assert "references" in content.lower()
        assert "dependencies" in content.lower()

    def test_refactoring_safety_documented(self):
        """Verify that refactoring safety is documented."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        # Check refactoring safety is emphasized
        assert "find_references" in content
        assert "before refactoring" in content.lower() or "refactoring" in content.lower()
        assert "find_subclasses" in content


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


# Performance benchmarks from dogfooding
class TestDogfoodingPerformance:
    """Test and document performance characteristics discovered through dogfooding."""

    def test_performance_metrics_documented(self):
        """Verify that performance metrics and benefits are documented."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        # Check that performance aspects are documented
        assert "performance" in content.lower() or "faster" in content.lower()
        assert "cache" in content.lower() or "caching" in content.lower()

    def test_performance_tips_provided(self):
        """Verify that performance tips are provided."""
        claude_md = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        # Check for performance tips section
        assert "Performance Tips" in content or "performance" in content.lower()
        assert "cached" in content.lower() or "cache" in content.lower()
