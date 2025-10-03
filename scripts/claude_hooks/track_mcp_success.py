#!/usr/bin/env python3
"""Track successful MCP tool completions from Claude Code PostToolUse hooks."""

import json
import sys
from datetime import datetime
from pathlib import Path


def ensure_monitoring_dir() -> Path:
    """Ensure monitoring directory exists."""
    monitoring_dir = Path.home() / ".claude" / "mcp_monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    return monitoring_dir


def main() -> None:
    """Track successful MCP tool completion."""
    try:
        # Read hook payload from stdin
        payload = json.load(sys.stdin)

        monitoring_dir = ensure_monitoring_dir()

        # Extract tool information
        tool_name = payload.get("tool_name", "unknown")
        session_id = payload.get("session_id", "unknown")
        tool_response = payload.get("tool_response", {})

        # Extract the specific MCP tool
        if tool_name.startswith("mcp__pyeye__"):
            mcp_tool = tool_name.replace("mcp__pyeye__", "")
        else:
            mcp_tool = tool_name

        # Calculate response size (useful for performance tracking)
        response_size = len(json.dumps(tool_response))

        # Log to CSV
        csv_file = monitoring_dir / "mcp_success.csv"
        with csv_file.open("a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
            f.write(f"{timestamp},{session_id},{mcp_tool},success,{response_size}\n")

        # Log detailed JSON
        json_file = monitoring_dir / "mcp_success.jsonl"
        with json_file.open("a") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session_id,
                    "tool": mcp_tool,
                    "full_tool_name": tool_name,
                    "stage": "post_call",
                    "success": True,
                    "response_size": response_size,
                    "has_error": "error" in str(tool_response).lower(),
                },
                f,
            )
            f.write("\n")

    except Exception as e:
        # Log errors but don't fail the hook
        error_file = Path.home() / ".claude" / "mcp_monitoring" / "hook_errors.log"
        error_file.parent.mkdir(parents=True, exist_ok=True)
        with error_file.open("a") as f:
            f.write(f"{datetime.now().isoformat()} - track_mcp_success error: {e}\n")


if __name__ == "__main__":
    main()
