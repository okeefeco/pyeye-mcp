"""Tests for MCP workflow resources.

This test module verifies that workflow resources are properly exposed
and contain valid content for guiding AI agents in multi-step tasks.
"""

from pathlib import Path


class TestWorkflowResources:
    """Test that workflow resources exist and are properly structured."""

    def test_workflows_directory_exists(self):
        """Verify the workflows directory exists."""
        workflows_dir = Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows"
        assert workflows_dir.exists(), "Workflows directory should exist"
        assert workflows_dir.is_dir(), "Workflows should be a directory"

    def test_all_workflow_files_exist(self):
        """Verify all expected workflow files exist."""
        workflows_dir = Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows"

        expected_workflows = [
            "find_references.md",
            "refactoring.md",
            "code_understanding.md",
            "dependency_analysis.md",
        ]

        for workflow_file in expected_workflows:
            workflow_path = workflows_dir / workflow_file
            assert workflow_path.exists(), f"Workflow {workflow_file} should exist"
            assert workflow_path.is_file(), f"Workflow {workflow_file} should be a file"

    def test_workflow_files_are_markdown(self):
        """Verify all workflow files are markdown format."""
        workflows_dir = Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows"

        for workflow_file in workflows_dir.glob("*.md"):
            assert workflow_file.suffix == ".md", f"{workflow_file} should be markdown"

    def test_workflow_content_not_empty(self):
        """Verify workflow files contain content."""
        workflows_dir = Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows"

        for workflow_file in workflows_dir.glob("*.md"):
            content = workflow_file.read_text(encoding="utf-8")
            assert len(content) > 100, f"{workflow_file.name} should have substantial content"
            assert content.strip(), f"{workflow_file.name} should not be empty"

    def test_find_references_workflow_structure(self):
        """Verify find_references workflow has expected structure."""
        workflow_file = (
            Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows" / "find_references.md"
        )
        content = workflow_file.read_text(encoding="utf-8")

        # Check for key sections
        assert "# Find All References Workflow" in content
        assert "## Goal" in content
        assert "## When to Use" in content
        assert "## Steps" in content
        assert "get_type_info" in content
        assert "find_references" in content
        assert "Grep" in content

    def test_refactoring_workflow_structure(self):
        """Verify refactoring workflow has expected structure."""
        workflow_file = (
            Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows" / "refactoring.md"
        )
        content = workflow_file.read_text(encoding="utf-8")

        # Check for key sections
        assert "# Safe Refactoring Workflow" in content
        assert "## Goal" in content
        assert "## Steps" in content
        assert "find_subclasses" in content
        assert "find_references" in content
        assert "analyze_dependencies" in content

    def test_code_understanding_workflow_structure(self):
        """Verify code_understanding workflow has expected structure."""
        workflow_file = (
            Path(__file__).parent.parent
            / "src"
            / "pycodemcp"
            / "workflows"
            / "code_understanding.md"
        )
        content = workflow_file.read_text(encoding="utf-8")

        # Check for key sections
        assert "# Code Understanding Workflow" in content
        assert "## Goal" in content
        assert "## Steps" in content
        assert "find_symbol" in content
        assert "get_type_info" in content
        assert "get_call_hierarchy" in content

    def test_dependency_analysis_workflow_structure(self):
        """Verify dependency_analysis workflow has expected structure."""
        workflow_file = (
            Path(__file__).parent.parent
            / "src"
            / "pycodemcp"
            / "workflows"
            / "dependency_analysis.md"
        )
        content = workflow_file.read_text(encoding="utf-8")

        # Check for key sections
        assert "# Dependency Analysis Workflow" in content
        assert "## Goal" in content
        assert "## Steps" in content
        assert "analyze_dependencies" in content
        assert "list_modules" in content


class TestWorkflowResourceHandlers:
    """Test that resource handlers are properly defined in server.py."""

    def test_load_workflow_function_exists(self):
        """Verify load_workflow helper function exists."""
        server_file = Path(__file__).parent.parent / "src" / "pycodemcp" / "server.py"
        content = server_file.read_text(encoding="utf-8")

        assert "def load_workflow" in content, "load_workflow function should exist"
        assert "workflow_name: str" in content, "load_workflow should take workflow_name parameter"

    def test_resource_decorators_exist(self):
        """Verify all workflow resource decorators are defined."""
        server_file = Path(__file__).parent.parent / "src" / "pycodemcp" / "server.py"
        content = server_file.read_text(encoding="utf-8")

        expected_resources = [
            '@mcp.resource("workflows://find-references")',
            '@mcp.resource("workflows://refactoring")',
            '@mcp.resource("workflows://code-understanding")',
            '@mcp.resource("workflows://dependency-analysis")',
        ]

        for resource_decorator in expected_resources:
            assert (
                resource_decorator in content
            ), f"Resource decorator {resource_decorator} should exist"

    def test_resource_handler_functions_exist(self):
        """Verify resource handler functions are defined."""
        server_file = Path(__file__).parent.parent / "src" / "pycodemcp" / "server.py"
        content = server_file.read_text(encoding="utf-8")

        expected_functions = [
            "def get_find_references_workflow()",
            "def get_refactoring_workflow()",
            "def get_code_understanding_workflow()",
            "def get_dependency_analysis_workflow()",
        ]

        for function in expected_functions:
            assert function in content, f"Function {function} should exist"


class TestWorkflowDocumentation:
    """Test that workflow resources are documented in README."""

    def test_readme_has_workflow_resources_section(self):
        """Verify README has Workflow Resources section."""
        readme_file = Path(__file__).parent.parent / "README.md"
        content = readme_file.read_text(encoding="utf-8")

        assert "## Workflow Resources" in content, "README should have Workflow Resources section"

    def test_readme_documents_all_workflows(self):
        """Verify README documents all available workflows."""
        readme_file = Path(__file__).parent.parent / "README.md"
        content = readme_file.read_text(encoding="utf-8")

        # Check for workflow mentions
        assert "find-references" in content, "README should mention find-references workflow"
        assert "refactoring" in content, "README should mention refactoring workflow"
        assert "code-understanding" in content, "README should mention code-understanding workflow"
        assert (
            "dependency-analysis" in content
        ), "README should mention dependency-analysis workflow"

    def test_readme_documents_usage_pattern(self):
        """Verify README documents how to use workflow resources."""
        readme_file = Path(__file__).parent.parent / "README.md"
        content = readme_file.read_text(encoding="utf-8")

        # Check for usage documentation
        assert "Discovering Workflows" in content, "README should explain how to discover workflows"
        assert "Using Workflows" in content, "README should explain how to use workflows"
        assert "workflows://" in content, "README should document the workflow URI scheme"


class TestWorkflowIntegration:
    """Test workflow integration aspects."""

    def test_workflows_reference_correct_tools(self):
        """Verify workflows reference tools that actually exist in server.py."""
        server_file = Path(__file__).parent.parent / "src" / "pycodemcp" / "server.py"
        server_content = server_file.read_text(encoding="utf-8")

        workflows_dir = Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows"

        # Tools that should exist
        expected_tools = [
            "find_symbol",
            "get_type_info",
            "find_references",
            "find_subclasses",
            "analyze_dependencies",
            "list_modules",
            "get_call_hierarchy",
        ]

        # Verify all expected tools exist in server.py
        for tool in expected_tools:
            assert f"def {tool}" in server_content, f"Tool {tool} should exist in server.py"

        # Verify workflows reference these tools
        for workflow_file in workflows_dir.glob("*.md"):
            workflow_content = workflow_file.read_text(encoding="utf-8")
            # At least some tools should be mentioned in each workflow
            tool_mentions = sum(1 for tool in expected_tools if tool in workflow_content)
            assert tool_mentions > 0, f"{workflow_file.name} should reference at least one MCP tool"

    def test_workflows_have_consistent_structure(self):
        """Verify all workflows follow consistent structure."""
        workflows_dir = Path(__file__).parent.parent / "src" / "pycodemcp" / "workflows"

        required_sections = [
            "# ",  # Title (H1)
            "## Goal",
            "## When to Use",
            "## Steps",
        ]

        for workflow_file in workflows_dir.glob("*.md"):
            content = workflow_file.read_text(encoding="utf-8")

            for section in required_sections:
                assert section in content, f"{workflow_file.name} should have '{section}' section"
