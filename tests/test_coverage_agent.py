"""Tests for the test coverage enhancement agent."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.agents.test_coverage import TestCoverageAgent, create_test_coverage_agent
from pycodemcp.agents.test_coverage_enhanced import (
    EnhancedTestCoverageAgent,
    GeneratedTest,
    MCPInstruction,
    TestGap,
    TestPattern,
    create_enhanced_test_coverage_agent,
)
from pycodemcp.exceptions import ValidationError


class TestBasicTestCoverageAgent:
    """Test the basic test coverage agent functionality."""

    def test_agent_creation(self, tmp_path):
        """Test agent can be created with valid project."""
        # Create a mock project
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = create_test_coverage_agent(tmp_path)
        assert agent is not None
        assert agent.project_root == tmp_path

    def test_agent_creation_invalid_project(self, tmp_path):
        """Test agent creation fails without valid project."""
        with pytest.raises(ValidationError) as exc_info:
            create_test_coverage_agent(tmp_path)
        assert "No pyproject.toml or setup.py found" in str(exc_info.value)

    def test_parse_coverage_command_basic(self, tmp_path):
        """Test parsing of basic coverage commands."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = TestCoverageAgent(tmp_path)

        # Test module extraction
        parsed = agent._parse_coverage_command("Improve test coverage for module cache")
        assert parsed["module"] == "cache"
        assert parsed["target_coverage"] == 90  # default
        assert parsed["test_type"] == "comprehensive"

    def test_parse_coverage_command_with_percentage(self, tmp_path):
        """Test parsing commands with coverage percentage."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = TestCoverageAgent(tmp_path)

        parsed = agent._parse_coverage_command("Bring coverage to 95% for validation module")
        assert parsed["target_coverage"] == 95
        assert parsed["module"] == "validation"

    def test_parse_coverage_command_test_types(self, tmp_path):
        """Test parsing different test type requests."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = TestCoverageAgent(tmp_path)

        # Regression tests
        parsed = agent._parse_coverage_command("Generate regression tests for bug fix")
        assert parsed["test_type"] == "regression"

        # Edge case tests
        parsed = agent._parse_coverage_command("Add edge case tests for parser")
        assert parsed["test_type"] == "edge_cases"

        # Integration tests
        parsed = agent._parse_coverage_command("Create integration tests")
        assert parsed["test_type"] == "integration"

        # Unit tests
        parsed = agent._parse_coverage_command("Add unit tests for helpers")
        assert parsed["test_type"] == "unit"

    def test_handle_request_success(self, tmp_path):
        """Test successful request handling."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = TestCoverageAgent(tmp_path)

        result = agent.handle_request("Improve test coverage for cache module")

        assert result["success"] is True
        assert "parsed" in result
        assert "result" in result
        assert "mcp_tools_used" in result
        assert result["mcp_tools_used"] > 0  # Should track MCP usage

    def test_handle_request_error(self, tmp_path):
        """Test error handling in request."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = TestCoverageAgent(tmp_path)

        # Mock a method to raise an error
        with patch.object(agent, "_execute_test_workflow", side_effect=RuntimeError("Test error")):
            result = agent.handle_request("Test command")

        assert result["success"] is False
        assert result["error"] == "Test error"
        assert result["error_type"] == "RuntimeError"

    def test_mcp_tools_tracking(self, tmp_path):
        """Test that MCP tool usage is tracked."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = TestCoverageAgent(tmp_path)

        # Simulate MCP tool usage
        agent._analyze_coverage_gaps_mcp(None)
        agent._recognize_test_patterns_mcp()

        assert len(agent.mcp_tools_used) > 0
        assert "list_modules" in agent.mcp_tools_used
        assert "find_symbol" in agent.mcp_tools_used

    def test_semantic_accuracy_calculation(self, tmp_path):
        """Test semantic accuracy metric calculation."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = TestCoverageAgent(tmp_path)

        # No tools used
        assert agent._calculate_semantic_accuracy() == 0.0

        # Add some semantic tools
        agent.mcp_tools_used = ["get_type_info", "find_references", "list_modules"]
        accuracy = agent._calculate_semantic_accuracy()
        assert accuracy > 50  # Most tools are semantic

        # Add non-semantic tools
        agent.mcp_tools_used = ["list_modules", "find_imports"]
        accuracy = agent._calculate_semantic_accuracy()
        assert accuracy < 50  # Fewer semantic tools


class TestEnhancedTestCoverageAgent:
    """Test the enhanced test coverage agent with full MCP integration."""

    def test_enhanced_agent_creation(self, tmp_path):
        """Test enhanced agent creation."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = create_enhanced_test_coverage_agent(tmp_path)
        assert agent is not None
        assert isinstance(agent, EnhancedTestCoverageAgent)

    def test_parse_request_comprehensive(self, tmp_path):
        """Test comprehensive request parsing."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = EnhancedTestCoverageAgent(tmp_path)

        # Test with module name
        parsed = agent._parse_request("Improve coverage for pycodemcp.cache module")
        assert parsed["module"] == "pycodemcp.cache"
        assert parsed["target_coverage"] == 90
        assert parsed["focus"] == "comprehensive"

        # Test with async focus
        parsed = agent._parse_request("Add tests for async functions")
        assert parsed["focus"] == "async"

        # Test with performance focus
        parsed = agent._parse_request("Create performance tests")
        assert parsed["focus"] == "performance"

    def test_mcp_instruction_creation(self, tmp_path):
        """Test MCP instruction generation."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = EnhancedTestCoverageAgent(tmp_path)

        parsed = {"module": "test_module", "target_coverage": 90, "focus": "comprehensive"}

        # Create discovery instructions
        instructions = agent._create_discovery_instructions(parsed)

        assert len(instructions) > 0
        assert all(isinstance(inst, MCPInstruction) for inst in instructions)

        # Check instruction details
        first_inst = instructions[0]
        assert first_inst.tool == "mcp__python-intelligence__list_modules"
        assert first_inst.purpose is not None
        assert len(first_inst.purpose) > 0

    def test_execution_plan_creation(self, tmp_path):
        """Test execution plan generation."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = EnhancedTestCoverageAgent(tmp_path)

        instructions = {
            "discovery": agent._create_discovery_instructions({"module": None}),
            "analysis": agent._create_analysis_instructions(),
            "generation": agent._create_generation_instructions({"focus": "comprehensive"}),
            "validation": agent._create_validation_instructions(),
        }

        plan = agent._create_execution_plan(instructions)

        assert "overview" in plan
        assert "phases" in plan
        assert len(plan["phases"]) == 4

        # Check phase structure
        for phase in plan["phases"]:
            assert "name" in phase
            assert "description" in phase
            assert "steps" in phase
            assert "mcp_tools" in phase
            assert "output" in phase

    def test_analyze_and_generate_workflow(self, tmp_path):
        """Test the complete analysis and generation workflow."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = EnhancedTestCoverageAgent(tmp_path)

        result = agent.analyze_and_generate("Improve test coverage for cache module to 95%")

        assert result["success"] is True
        assert "execution_plan" in result
        assert "mcp_instructions" in result
        assert "expected_results" in result

        # Check parsed request
        assert result["parsed"]["module"] == "cache"
        assert result["parsed"]["target_coverage"] == 95

    def test_test_types_for_focus(self, tmp_path):
        """Test that correct test types are selected based on focus."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = EnhancedTestCoverageAgent(tmp_path)

        # Comprehensive focus
        types = agent._get_test_types_for_focus("comprehensive")
        assert "unit" in types
        assert "integration" in types
        assert "edge_cases" in types

        # Async focus
        types = agent._get_test_types_for_focus("async")
        assert "async_unit" in types
        assert "concurrency" in types

        # Performance focus
        types = agent._get_test_types_for_focus("performance")
        assert "performance" in types
        assert "load" in types

    def test_expected_results_description(self, tmp_path):
        """Test expected results generation."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        agent = EnhancedTestCoverageAgent(tmp_path)

        parsed = {"target_coverage": 85, "focus": "edge_cases"}
        expected = agent._describe_expected_results(parsed)

        assert "coverage_improvement" in expected
        assert "85%" in expected["coverage_improvement"]
        assert "test_types" in expected
        assert "boundary" in expected["test_types"]  # edge_cases focus
        assert "deliverables" in expected
        assert "mcp_usage_metrics" in expected
        assert expected["mcp_usage_metrics"]["no_grep_or_ast"] is True


class TestCLIScript:
    """Test the CLI script interface."""

    def test_cli_script_exists(self):
        """Test that CLI script exists."""
        script_path = Path(__file__).parent.parent / "scripts" / "test_coverage_agent.py"
        assert script_path.exists()

    def test_cli_help(self):
        """Test CLI help output."""
        script_path = Path(__file__).parent.parent / "scripts" / "test_coverage_agent.py"

        result = subprocess.run(
            ["python", str(script_path), "--help"], capture_output=True, text=True
        )

        assert result.returncode == 0
        assert "Test Coverage Enhancement Agent" in result.stdout
        assert "Natural language test coverage command" in result.stdout

    @patch("pycodemcp.agents.test_coverage.TestCoverageAgent.handle_request")
    def test_cli_execution(self, mock_handle, tmp_path):
        """Test CLI execution with mock agent."""
        # Setup mock response
        mock_handle.return_value = {
            "success": True,
            "command": "test",
            "result": {},
            "mcp_tools_used": 10,
            "semantic_accuracy": 95.0,
        }

        script_path = Path(__file__).parent.parent / "scripts" / "test_coverage_agent.py"

        # Create project structure
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "test"')

        result = subprocess.run(
            [
                "python",
                str(script_path),
                "Improve test coverage",
                "--project-root",
                str(tmp_path),
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        # Check JSON output can be parsed
        if result.returncode == 0 and result.stdout:
            try:
                json.loads(result.stdout)
            except json.JSONDecodeError:
                pytest.fail("CLI output is not valid JSON")


class TestDataClasses:
    """Test the data classes used in the enhanced agent."""

    def test_mcp_instruction(self):
        """Test MCPInstruction dataclass."""
        inst = MCPInstruction(
            tool="mcp__python-intelligence__find_symbol",
            params={"name": "test"},
            purpose="Find test functions",
            expected_output="List of test functions",
        )

        assert inst.tool == "mcp__python-intelligence__find_symbol"
        assert inst.params["name"] == "test"
        assert "Find" in inst.purpose

    def test_test_gap(self):
        """Test TestGap dataclass."""
        gap = TestGap(
            symbol_name="process_data",
            symbol_type="function",
            file_path="src/utils.py",
            line=42,
            column=0,
            has_tests=False,
        )

        assert gap.symbol_name == "process_data"
        assert gap.symbol_type == "function"
        assert gap.has_tests is False
        assert gap.test_files == []  # Default
        assert gap.complexity == "medium"  # Default

    def test_test_pattern(self):
        """Test TestPattern dataclass."""
        pattern = TestPattern(
            pattern_type="naming",
            value="test_{function}_{scenario}",
            frequency=25,
            examples=["test_parse_valid_input", "test_parse_empty_string"],
        )

        assert pattern.pattern_type == "naming"
        assert "{function}" in pattern.value
        assert pattern.frequency == 25
        assert len(pattern.examples) == 2

    def test_generated_test(self):
        """Test GeneratedTest dataclass."""
        test = GeneratedTest(
            test_name="test_cache_miss",
            test_code="def test_cache_miss():\n    assert True",
            target_symbol="cache_get",
            test_file="tests/test_cache.py",
            test_type="edge_case",
            uses_mocks=True,
        )

        assert test.test_name == "test_cache_miss"
        assert "assert True" in test.test_code
        assert test.uses_mocks is True
        assert test.uses_fixtures is False  # Default
