#!/usr/bin/env python3
"""CLI interface for the Release Automation Agent.

This script provides a command-line interface that can be called by Claude Code
to execute release automation tasks using natural language commands.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    # Force UTF-8 encoding for stdout/stderr on Windows
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    # Set console code page to UTF-8
    os.system("chcp 65001 > nul 2>&1")

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


def safe_print(text: str, file: Any = None) -> None:
    """Print text with fallback for Unicode encoding issues."""
    try:
        print(text, file=file)
    except UnicodeEncodeError:
        # Fallback to ASCII representation
        ascii_replacements = {
            "→": "->",
            "•": "*",
            "🎉": "[SUCCESS]",
            "✅": "[OK]",
            "❌": "[ERROR]",
            "⚠️": "[WARNING]",
            "📋": "[INFO]",
            "🚀": "[DEPLOY]",
            "🌿": "[BRANCH]",
            "📝": "[EDIT]",
            "🤖": "[BOT]",
        }
        for unicode_char, ascii_char in ascii_replacements.items():
            text = text.replace(unicode_char, ascii_char)
        print(text, file=file)


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
        safe_print("\n❌ Release automation cancelled by user")
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
            safe_print(f"❌ Error: {e}", file=sys.stderr)

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

    safe_print("Release Automation Agent - Example Commands:")
    safe_print("=" * 50)
    safe_print("")

    for command, description in examples:
        safe_print(f'  "{command}"')
        safe_print(f"    → {description}")
        safe_print("")

    safe_print("The agent will automatically:")
    safe_print("  • Validate prerequisites (git status, tests, version consistency)")
    safe_print("  • Update version in all required files")
    safe_print("  • Create release branch with conventional commit")
    safe_print("  • Push branch and create pull request")
    safe_print("  • Provide next steps for completion")


def print_human_readable_result(result: dict) -> None:
    """Print result in human-readable format."""
    if result["success"]:
        safe_print("🎉 Release automation completed successfully!")
        safe_print("")

        if "result" in result and result["result"]:
            r = result["result"]
            safe_print(f"📦 Target version: {r['target_version']}")
            safe_print(f"🌿 Branch: {r['branch']['name']}")

            if "pull_request" in r and "url" in r["pull_request"]:
                safe_print(f"📋 Pull request: {r['pull_request']['url']}")

            if "files_updated" in r:
                safe_print(f"📝 Files updated: {', '.join(r['files_updated'])}")

        safe_print("")

        if "next_steps" in result:
            for step in result["next_steps"]:
                safe_print(step)

    else:
        safe_print(f"❌ Release automation failed: {result.get('error', 'Unknown error')}")
        if result.get("error_type"):
            safe_print(f"   Error type: {result['error_type']}")


if __name__ == "__main__":
    main()
