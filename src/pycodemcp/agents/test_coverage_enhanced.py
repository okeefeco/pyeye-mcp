"""Enhanced test coverage agent with full MCP integration instructions.

This module provides the complete implementation of the test coverage enhancement agent
that runs as a Claude Code sub-agent using MCP tools for ALL analysis.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..exceptions import ValidationError


@dataclass
class MCPInstruction:
    """Instruction for Claude to execute an MCP tool."""

    tool: str
    params: dict[str, Any]
    purpose: str
    expected_output: str


@dataclass
class TestGap:
    """Represents a gap in test coverage."""

    symbol_name: str
    symbol_type: str  # function, class, method
    file_path: str
    line: int
    column: int
    has_tests: bool
    test_files: list[str] = field(default_factory=list)
    usage_count: int = 0
    complexity: str = "medium"  # low, medium, high


@dataclass
class TestPattern:
    """Represents a discovered test pattern."""

    pattern_type: str  # naming, assertion, fixture, mock
    value: str
    frequency: int
    examples: list[str] = field(default_factory=list)


@dataclass
class GeneratedTest:
    """Represents a generated test."""

    test_name: str
    test_code: str
    target_symbol: str
    test_file: str
    test_type: str  # unit, integration, edge_case, regression
    uses_mocks: bool = False
    uses_fixtures: bool = False


class EnhancedTestCoverageAgent:
    """Enhanced agent with complete MCP integration for test generation.

    This agent is designed to be executed by Claude using the Task tool,
    providing clear instructions for MCP tool usage at each step.
    """

    def __init__(self, project_root: Path | None = None):
        """Initialize the enhanced test coverage agent."""
        self.project_root = project_root or Path.cwd()
        self._validate_project()
        self.mcp_instructions: list[MCPInstruction] = []
        self.test_gaps: list[TestGap] = []
        self.test_patterns: list[TestPattern] = []
        self.generated_tests: list[GeneratedTest] = []

    def _validate_project(self) -> None:
        """Validate project structure."""
        if (
            not (self.project_root / "pyproject.toml").exists()
            and not (self.project_root / "setup.py").exists()
        ):
            raise ValidationError(f"No Python project found at {self.project_root}")

    def analyze_and_generate(self, request: str) -> dict[str, Any]:
        """Main entry point for test coverage analysis and generation.

        This method orchestrates the entire workflow, providing clear
        instructions for Claude to execute MCP tools at each step.
        """
        # Parse the request
        parsed = self._parse_request(request)

        # Phase 1: Discovery - Find what needs testing
        discovery_instructions = self._create_discovery_instructions(parsed)

        # Phase 2: Analysis - Understand existing patterns
        analysis_instructions = self._create_analysis_instructions()

        # Phase 3: Generation - Create tests using semantic understanding
        generation_instructions = self._create_generation_instructions(parsed)

        # Phase 4: Validation - Ensure tests are correct
        validation_instructions = self._create_validation_instructions()

        # Compile all instructions for Claude
        all_instructions = {
            "discovery": discovery_instructions,
            "analysis": analysis_instructions,
            "generation": generation_instructions,
            "validation": validation_instructions,
        }

        # Create execution plan
        execution_plan = self._create_execution_plan(all_instructions)

        # Return structured response for Claude Task tool
        return {
            "success": True,
            "request": request,
            "parsed": parsed,
            "execution_plan": execution_plan,
            "mcp_instructions": self._format_mcp_instructions(),
            "expected_results": self._describe_expected_results(parsed),
        }

    def _parse_request(self, request: str) -> dict[str, Any]:
        """Parse natural language request into structured format."""
        request_lower = request.lower()

        # Extract target module/file
        module = None
        # Try multiple patterns to extract module name
        patterns = [
            r"for\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s+module\s+to",  # "for cache module to"
            r"(?:module|file)\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)",
            r"for\s+(?:the\s+)?([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s+module",
        ]

        for pattern in patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                module = match.group(1)
                break

        # Extract target coverage
        coverage_match = re.search(r"(\d+)%", request)
        target_coverage = int(coverage_match.group(1)) if coverage_match else 90

        # Determine focus area
        focus = "comprehensive"
        if "async" in request_lower:
            focus = "async"
        elif "edge" in request_lower:
            focus = "edge_cases"
        elif "regression" in request_lower:
            focus = "regression"
        elif "performance" in request_lower:
            focus = "performance"

        return {
            "module": module,
            "target_coverage": target_coverage,
            "focus": focus,
            "original_request": request,
        }

    def _create_discovery_instructions(self, parsed: dict[str, Any]) -> list[MCPInstruction]:
        """Create MCP instructions for discovering what needs testing."""
        instructions = []

        # 1. Get module structure
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__list_modules",
                params={"project_path": str(self.project_root)},
                purpose="Discover all modules and their structure",
                expected_output="List of modules with exports, classes, functions, and metrics",
            )
        )

        # 2. Find all testable symbols
        if parsed["module"]:
            instructions.append(
                MCPInstruction(
                    tool="mcp__python-intelligence__get_module_info",
                    params={"module_path": parsed["module"]},
                    purpose=f"Get detailed info about {parsed['module']}",
                    expected_output="Module exports, classes, functions, and dependencies",
                )
            )

        # 3. Find existing tests
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_symbol",
                params={"name": "test_", "fuzzy": True},
                purpose="Find all existing test functions",
                expected_output="List of test functions with locations",
            )
        )

        # 4. Check test coverage for specific symbols
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_subclasses",
                params={"base_class": "TestCase"},
                purpose="Find all test classes following unittest pattern",
                expected_output="Test class hierarchy",
            )
        )

        self.mcp_instructions.extend(instructions)
        return instructions

    def _create_analysis_instructions(self) -> list[MCPInstruction]:
        """Create MCP instructions for analyzing test patterns."""
        instructions = []

        # 1. Detect test framework
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_imports",
                params={"module_name": "pytest"},
                purpose="Check if project uses pytest",
                expected_output="Import locations for pytest",
            )
        )

        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_imports",
                params={"module_name": "unittest"},
                purpose="Check if project uses unittest",
                expected_output="Import locations for unittest",
            )
        )

        # 2. Find fixture patterns
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_symbol",
                params={"name": "fixture"},
                purpose="Find pytest fixtures",
                expected_output="Fixture definitions and usage",
            )
        )

        # 3. Find mock patterns
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_imports",
                params={"module_name": "mock"},
                purpose="Find mock usage patterns",
                expected_output="Mock import and usage locations",
            )
        )

        # 4. Find performance test patterns
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_symbol",
                params={"name": "PerformanceThresholds"},
                purpose="Find performance testing patterns",
                expected_output="Performance test framework usage",
            )
        )

        self.mcp_instructions.extend(instructions)
        return instructions

    def _create_generation_instructions(self, parsed: dict[str, Any]) -> list[MCPInstruction]:
        """Create MCP instructions for generating tests."""
        instructions = []

        # For each untested function/class, we need to:

        # 1. Get type information
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__get_type_info",
                params={"file": "<target_file>", "line": "<function_line>", "column": 0},
                purpose="Get function signature and docstring",
                expected_output="Parameter types, return type, and documentation",
            )
        )

        # 2. Find usage patterns
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_references",
                params={"file": "<target_file>", "line": "<function_line>", "column": 0},
                purpose="Find how function is used in codebase",
                expected_output="All usage locations to understand patterns",
            )
        )

        # 3. Understand dependencies for mocking
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__get_call_hierarchy",
                params={"function_name": "<function_name>"},
                purpose="Understand what function calls and what calls it",
                expected_output="Call hierarchy for mock requirements",
            )
        )

        # 4. Check for framework-specific needs
        if parsed["focus"] == "async":
            instructions.append(
                MCPInstruction(
                    tool="mcp__python-intelligence__find_symbol",
                    params={"name": "async def", "fuzzy": True},
                    purpose="Find async functions needing special test handling",
                    expected_output="Async function locations",
                )
            )

        # 5. For Pydantic models
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_models",
                params={},
                purpose="Find Pydantic models needing validation tests",
                expected_output="All Pydantic model definitions",
            )
        )

        # 6. For Flask routes
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__find_routes",
                params={},
                purpose="Find Flask routes needing endpoint tests",
                expected_output="All Flask route definitions",
            )
        )

        self.mcp_instructions.extend(instructions)
        return instructions

    def _create_validation_instructions(self) -> list[MCPInstruction]:
        """Create MCP instructions for validating generated tests."""
        instructions = []

        # 1. Verify imports exist
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__analyze_dependencies",
                params={"module_path": "<test_module>"},
                purpose="Verify all imports in generated tests are valid",
                expected_output="Import validation results",
            )
        )

        # 2. Check for circular dependencies
        instructions.append(
            MCPInstruction(
                tool="mcp__python-intelligence__analyze_dependencies",
                params={"module_path": "<module>"},
                purpose="Ensure no circular dependencies introduced",
                expected_output="Dependency analysis with circular check",
            )
        )

        self.mcp_instructions.extend(instructions)
        return instructions

    def _create_execution_plan(
        self, instructions: dict[str, list[MCPInstruction]]
    ) -> dict[str, Any]:
        """Create a detailed execution plan for Claude."""
        plan: dict[str, Any] = {
            "overview": "Systematic test coverage enhancement using MCP semantic understanding",
            "phases": [],
        }

        # Phase 1: Discovery
        plan["phases"].append(
            {
                "name": "Discovery",
                "description": "Find untested code using semantic analysis",
                "steps": [
                    "Use list_modules to understand project structure",
                    "Use find_symbol to locate all functions and classes",
                    "Use find_references to check which symbols have tests",
                    "Identify coverage gaps semantically (not with coverage.py)",
                ],
                "mcp_tools": [inst.tool for inst in instructions.get("discovery", [])],
                "output": "List of untested symbols with metadata",
            }
        )

        # Phase 2: Analysis
        plan["phases"].append(
            {
                "name": "Pattern Analysis",
                "description": "Learn existing test patterns",
                "steps": [
                    "Detect test framework (pytest/unittest) via imports",
                    "Find naming conventions in existing tests",
                    "Identify fixture and mock patterns",
                    "Learn assertion styles and test structure",
                ],
                "mcp_tools": [inst.tool for inst in instructions.get("analysis", [])],
                "output": "Test pattern library for generation",
            }
        )

        # Phase 3: Generation
        plan["phases"].append(
            {
                "name": "Test Generation",
                "description": "Generate tests using semantic understanding",
                "steps": [
                    "For each untested symbol, get type information",
                    "Find usage patterns to understand expected behavior",
                    "Identify dependencies that need mocking",
                    "Generate test following discovered patterns",
                    "Handle framework-specific needs (Pydantic, Flask, etc.)",
                ],
                "mcp_tools": [inst.tool for inst in instructions.get("generation", [])],
                "output": "Generated test code following conventions",
            }
        )

        # Phase 4: Validation
        plan["phases"].append(
            {
                "name": "Validation",
                "description": "Ensure generated tests are valid",
                "steps": [
                    "Verify all imports are available",
                    "Check naming follows conventions",
                    "Ensure no circular dependencies",
                    "Validate test will likely pass",
                ],
                "mcp_tools": [inst.tool for inst in instructions.get("validation", [])],
                "output": "Validated, ready-to-run tests",
            }
        )

        return plan

    def _format_mcp_instructions(self) -> list[dict[str, Any]]:
        """Format MCP instructions for Claude execution."""
        formatted = []
        for inst in self.mcp_instructions:
            formatted.append(
                {
                    "tool": inst.tool,
                    "params": inst.params,
                    "purpose": inst.purpose,
                    "expected": inst.expected_output,
                }
            )
        return formatted

    def _describe_expected_results(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Describe expected results from the agent."""
        return {
            "coverage_improvement": f"Increase coverage to {parsed['target_coverage']}%",
            "test_types": self._get_test_types_for_focus(parsed["focus"]),
            "deliverables": [
                "List of coverage gaps with priorities",
                "Generated test code following project patterns",
                "Test file paths for new tests",
                "Validation report confirming tests will pass",
            ],
            "mcp_usage_metrics": {
                "expected_tool_calls": len(self.mcp_instructions),
                "semantic_accuracy_target": ">90%",
                "no_grep_or_ast": True,
            },
        }

    def _get_test_types_for_focus(self, focus: str) -> list[str]:
        """Get test types based on focus area."""
        base_types = ["unit", "integration"]

        focus_types = {
            "comprehensive": ["unit", "integration", "edge_cases"],
            "async": ["async_unit", "async_integration", "concurrency"],
            "edge_cases": ["boundary", "error_handling", "validation"],
            "regression": ["regression", "bug_prevention"],
            "performance": ["performance", "load", "stress"],
        }

        return focus_types.get(focus, base_types)


def create_enhanced_test_coverage_agent(
    project_root: Path | None = None,
) -> EnhancedTestCoverageAgent:
    """Factory function for creating enhanced test coverage agent."""
    return EnhancedTestCoverageAgent(project_root)
