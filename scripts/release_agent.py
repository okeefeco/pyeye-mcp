#!/usr/bin/env python3
"""CLI interface for the Release Automation Agent.

This script provides a command-line interface that can be called by Claude Code
to execute release automation tasks using natural language commands.
"""

import argparse
import json
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from pycodemcp.agents.release_automation import create_release_automation_agent  # noqa: E402


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Release Automation Agent - Natural language release management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/release_agent.py "Prepare release v0.2.0"
  python scripts/release_agent.py "Cut a patch release"
  python scripts/release_agent.py "Create minor release"
  python scripts/release_agent.py "Prepare major release"

The agent will:
1. Validate prerequisites (clean git, tests pass, version consistency)
2. Update version in all required files
3. Create release branch with conventional commit
4. Push branch and create pull request
5. Provide next steps for completion
        """,
    )

    parser.add_argument("command", help="Natural language release command", nargs="?", default="")

    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )

    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    parser.add_argument("--examples", action="store_true", help="Show example commands and exit")

    args = parser.parse_args()

    if args.examples:
        print_examples()
        return

    if not args.command.strip():
        print("Error: Release command is required", file=sys.stderr)
        print("\nTry:", file=sys.stderr)
        print('  python scripts/release_agent.py "Prepare release v0.2.0"', file=sys.stderr)
        print("  python scripts/release_agent.py --examples", file=sys.stderr)
        sys.exit(1)

    try:
        # Create and execute the agent
        agent = create_release_automation_agent(args.project_root)
        result = agent.handle_request(args.command)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_human_readable_result(result)

        # Exit with appropriate code
        sys.exit(0 if result["success"] else 1)

    except KeyboardInterrupt:
        print("\n❌ Release automation cancelled by user")
        sys.exit(130)
    except Exception as e:
        error_result = {
            "success": False,
            "command": args.command,
            "error": str(e),
            "error_type": type(e).__name__,
        }

        if args.json:
            print(json.dumps(error_result, indent=2))
        else:
            print(f"❌ Error: {e}", file=sys.stderr)

        sys.exit(1)


def print_examples() -> None:
    """Print example commands."""
    examples = [
        ("Prepare release v0.2.0", "Create release branch for specific version"),
        ("Cut a patch release", "Increment patch version and create release"),
        ("Create minor release", "Increment minor version and create release"),
        ("Prepare major release", "Increment major version and create release"),
        ("Cut release 1.0.0", "Alternative syntax for specific version"),
    ]

    print("Release Automation Agent - Example Commands:")
    print("=" * 50)
    print()

    for command, description in examples:
        print(f'  "{command}"')
        print(f"    → {description}")
        print()

    print("The agent will automatically:")
    print("  • Validate prerequisites (git status, tests, version consistency)")
    print("  • Update version in all required files")
    print("  • Create release branch with conventional commit")
    print("  • Push branch and create pull request")
    print("  • Provide next steps for completion")


def print_human_readable_result(result: dict) -> None:
    """Print result in human-readable format."""
    if result["success"]:
        print("🎉 Release automation completed successfully!")
        print()

        if "result" in result and result["result"]:
            r = result["result"]
            print(f"📦 Target version: {r['target_version']}")
            print(f"🌿 Branch: {r['branch']['name']}")

            if "pull_request" in r and "url" in r["pull_request"]:
                print(f"📋 Pull request: {r['pull_request']['url']}")

            if "files_updated" in r:
                print(f"📝 Files updated: {', '.join(r['files_updated'])}")

        print()

        if "next_steps" in result:
            for step in result["next_steps"]:
                print(step)

    else:
        print(f"❌ Release automation failed: {result.get('error', 'Unknown error')}")
        if result.get("error_type"):
            print(f"   Error type: {result['error_type']}")


if __name__ == "__main__":
    main()
