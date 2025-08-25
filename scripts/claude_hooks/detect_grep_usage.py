#!/usr/bin/env python3
"""Detect grep/find/rg usage in Bash commands from Claude Code hooks."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Patterns that indicate manual search instead of MCP tools
GREP_PATTERNS = [
    r"\bgrep\b",
    r"\brg\b",
    r"\bfind\b.*-name",
    r"\bfind\b.*-type",
    r"\bag\b",  # The Silver Searcher
    r"\back\b",  # ack
    r"xargs.*grep",
    r"git.*grep",
]


def ensure_monitoring_dir() -> Path:
    """Ensure monitoring directory exists."""
    monitoring_dir = Path.home() / ".claude" / "mcp_monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    return monitoring_dir


def is_grep_usage(command: str) -> bool:
    """Check if command contains grep-like patterns."""
    if not command:
        return False

    command_lower = command.lower()
    return any(re.search(pattern, command_lower) for pattern in GREP_PATTERNS)


def main() -> None:
    """Detect and log grep usage in Bash commands."""
    try:
        # Read hook payload from stdin
        payload = json.load(sys.stdin)

        # Extract command from tool input
        tool_input = payload.get("tool_input", {})
        command = tool_input.get("command", "")

        if is_grep_usage(command):
            monitoring_dir = ensure_monitoring_dir()
            session_id = payload.get("session_id", "unknown")

            # Determine which tool was used
            grep_tool = "unknown"
            if "grep" in command:
                grep_tool = "grep"
            elif "rg" in command:
                grep_tool = "ripgrep"
            elif "find" in command:
                grep_tool = "find"
            elif "ag" in command:
                grep_tool = "ag"
            elif "ack" in command:
                grep_tool = "ack"

            # Log to CSV
            csv_file = monitoring_dir / "grep_usage.csv"
            with csv_file.open("a") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
                f.write(f"{timestamp},{session_id},{grep_tool},bash_command\n")

            # Log detailed JSON
            json_file = monitoring_dir / "grep_usage.jsonl"
            with json_file.open("a") as f:
                json.dump(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "session_id": session_id,
                        "tool": grep_tool,
                        "command": command,
                        "description": tool_input.get("description", ""),
                        "context": "bash_command",
                    },
                    f,
                )
                f.write("\n")

    except Exception as e:
        # Log errors but don't fail the hook
        error_file = Path.home() / ".claude" / "mcp_monitoring" / "hook_errors.log"
        error_file.parent.mkdir(parents=True, exist_ok=True)
        with error_file.open("a") as f:
            f.write(f"{datetime.now().isoformat()} - detect_grep_usage error: {e}\n")


if __name__ == "__main__":
    main()
