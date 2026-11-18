#!/usr/bin/env python3
"""Track pyeye MCP tool calls from Claude Code PreToolUse hooks."""

import json
import sys
from datetime import datetime
from pathlib import Path

from pyeye_tool_names import short_name  # a sibling module: hooks run the script by path


def ensure_monitoring_dir() -> Path:
    """Ensure monitoring directory exists."""
    monitoring_dir = Path.home() / ".claude" / "mcp_monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    return monitoring_dir


def main() -> None:
    """Track MCP tool call."""
    try:
        # Read hook payload from stdin
        payload = json.load(sys.stdin)

        monitoring_dir = ensure_monitoring_dir()

        # Extract tool information
        tool_name = payload.get("tool_name", "unknown")
        session_id = payload.get("session_id", "unknown")

        # Extract the specific MCP tool being called
        mcp_tool = short_name(tool_name)  # either install form (#965)

        # Log to CSV for easy analysis
        csv_file = monitoring_dir / "mcp_calls.csv"
        with csv_file.open("a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
            f.write(f"{timestamp},{session_id},{mcp_tool},pre_call\n")

        # Also log detailed JSON for advanced analysis
        json_file = monitoring_dir / "mcp_calls.jsonl"
        with json_file.open("a") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session_id,
                    "tool": mcp_tool,
                    "full_tool_name": tool_name,
                    "stage": "pre_call",
                    "tool_input": payload.get("tool_input", {}),
                },
                f,
            )
            f.write("\n")

    except Exception as e:
        # Log errors but don't fail the hook
        error_file = Path.home() / ".claude" / "mcp_monitoring" / "hook_errors.log"
        error_file.parent.mkdir(parents=True, exist_ok=True)
        with error_file.open("a") as f:
            f.write(f"{datetime.now().isoformat()} - track_mcp_call error: {e}\n")


if __name__ == "__main__":
    main()
