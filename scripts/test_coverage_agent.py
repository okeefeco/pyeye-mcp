#!/usr/bin/env python3
"""CLI interface for the Test Coverage Enhancement Agent.

This script is designed to be called by Claude Code's Task tool to execute
test coverage analysis and generation in a separate context, using MCP tools
for ALL semantic analysis.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    os.system("chcp 65001 > nul 2>&1")

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from pyeye.agents.test_coverage import create_test_coverage_agent  # noqa: E402


def main() -> None:
    """Main CLI entry point for Claude Code Task tool integration."""
    parser = argparse.ArgumentParser(
        description="Test Coverage Enhancement Agent - Semantic test generation using MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This agent is designed to be invoked by Claude Code's Task tool for running
in a separate context. It uses PyEye tools exclusively
for ALL code analysis - no AST parsing or grep.

Examples for Claude Task tool:
  "Improve test coverage for cache module"
  "Add missing test cases for async_utils.py"
  "Bring test coverage up to 90% for validation module"
  "Generate regression tests for the import bug"

The agent will:
1. Analyze coverage gaps using MCP semantic understanding
2. Learn existing test patterns via MCP tools
3. Generate tests based on semantic understanding
4. Return concise results to main Claude session
        """,
    )

    parser.add_argument(
        "command", help="Natural language test coverage command", nargs="?", default=""
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )

    parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format for Claude processing"
    )

    parser.add_argument(
        "--verbose", action="store_true", help="Include detailed MCP tool usage metrics"
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Analyze but don't generate actual test files"
    )

    args = parser.parse_args()

    if not args.command.strip():
        print("Error: Test coverage command is required", file=sys.stderr)
        print("\nExpected usage via Claude Task tool:", file=sys.stderr)
        print('  Task(description="improve test coverage",', file=sys.stderr)
        print('       prompt="Improve test coverage for cache module",', file=sys.stderr)
        print('       subagent_type="general-purpose")', file=sys.stderr)
        sys.exit(1)

    try:
        # Create and execute the agent
        agent = create_test_coverage_agent(args.project_root)
        result = agent.handle_request(args.command)

        if args.json or is_claude_task_context():
            # Output for Claude processing
            print_json_result(result, args.verbose)
        else:
            # Human-readable output
            print_human_readable_result(result, args.verbose)

        sys.exit(0 if result["success"] else 1)

    except KeyboardInterrupt:
        print("\n[CANCELLED] Test coverage analysis interrupted")
        sys.exit(130)
    except Exception as e:
        error_result = {
            "success": False,
            "command": args.command,
            "error": str(e),
            "error_type": type(e).__name__,
        }

        if args.json or is_claude_task_context():
            print(json.dumps(error_result, indent=2))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)

        sys.exit(1)


def is_claude_task_context() -> bool:
    """Detect if running in Claude Task tool context."""
    # Claude Task tool sets specific environment variables
    return os.environ.get("CLAUDE_TASK") == "1" or os.environ.get("MCP_CONTEXT") == "1"


def print_json_result(result: dict, verbose: bool = False) -> None:
    """Print result in JSON format for Claude processing."""
    output = {
        "success": result["success"],
        "summary": generate_summary(result),
    }

    if verbose:
        output["details"] = result

    if result["success"]:
        output["mcp_adoption"] = f"{result.get('semantic_accuracy', 0):.1f}%"
        output["tools_used"] = result.get("mcp_tools_used", 0)

    print(json.dumps(output, indent=2))


def print_human_readable_result(result: dict, verbose: bool = False) -> None:
    """Print result in human-readable format."""
    if result["success"]:
        print("[SUCCESS] Test coverage analysis completed!")
        print("")

        if "result" in result:
            r = result["result"]

            # Coverage gaps
            if "coverage_gaps" in r:
                print("COVERAGE GAPS FOUND:")
                gaps = r["coverage_gaps"]
                for gap_type, items in gaps.items():
                    if items:
                        print(f"  - {gap_type}: {len(items)} items")

            # Test patterns
            if "test_patterns" in r:
                print("\nTEST PATTERNS DISCOVERED:")
                patterns = r["test_patterns"]
                if patterns.get("test_framework"):
                    print(f"  - Framework: {patterns['test_framework']}")
                if patterns.get("naming_convention"):
                    print(f"  - Naming: {patterns['naming_convention']}")

            # Generated tests
            if "generated_tests" in r:
                print(f"\nTESTS GENERATED: {len(r['generated_tests'])}")
                for test in r["generated_tests"][:3]:  # Show first 3
                    print(f"  - {test.get('test_name', 'Unknown')}")
                if len(r["generated_tests"]) > 3:
                    print(f"  ... and {len(r['generated_tests']) - 3} more")

            # Improvements
            if "improvements" in r:
                imp = r["improvements"]
                print("\nEXPECTED IMPROVEMENTS:")
                print(f"  - Functions to cover: {imp.get('functions_to_cover', 0)}")
                print(f"  - Classes to cover: {imp.get('classes_to_cover', 0)}")
                print(f"  - Coverage increase: ~{imp.get('estimated_coverage_increase', 0)}%")

        # MCP metrics
        print("\nMCP TOOL USAGE:")
        print(f"  - Tools used: {result.get('mcp_tools_used', 0)}")
        print(f"  - Semantic accuracy: {result.get('semantic_accuracy', 0):.1f}%")

        if verbose:
            print("\n[VERBOSE] Full details:")
            print(json.dumps(result, indent=2))

    else:
        print(f"[FAILED] {result.get('error', 'Unknown error')}")
        if result.get("error_type"):
            print(f"  Error type: {result['error_type']}")


def generate_summary(result: dict) -> str:
    """Generate a concise summary for Claude main session."""
    if not result["success"]:
        return f"Test coverage analysis failed: {result.get('error', 'Unknown error')}"

    r = result.get("result", {})
    improvements = r.get("improvements", {})

    summary_parts = []

    # Coverage gaps
    total_gaps = 0
    if "coverage_gaps" in r:
        for items in r["coverage_gaps"].values():
            if isinstance(items, list):
                total_gaps += len(items)
        if total_gaps > 0:
            summary_parts.append(f"Found {total_gaps} coverage gaps")

    # Generated tests
    if "generated_tests" in r:
        num_tests = len(r["generated_tests"])
        summary_parts.append(f"Generated {num_tests} tests")

    # Expected improvement
    coverage_increase = improvements.get("estimated_coverage_increase", 0)
    if coverage_increase > 0:
        summary_parts.append(f"Expected +{coverage_increase}% coverage")

    # MCP usage
    mcp_accuracy = result.get("semantic_accuracy", 0)
    summary_parts.append(f"{mcp_accuracy:.0f}% semantic analysis")

    return " | ".join(summary_parts) if summary_parts else "Analysis complete"


if __name__ == "__main__":
    main()
