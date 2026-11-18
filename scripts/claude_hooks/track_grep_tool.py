#!/usr/bin/env python3
"""Record Claude Code's own Grep tool use, where ``mcp_analytics.py`` reads it (#970).

The ``Grep`` hook used to append a CSV line only, and the report reads only
``grep_usage.jsonl``, so the Grep tool never counted towards grep usage or the
MCP adoption rate. This writes the same JSONL record shape as
``detect_grep_usage.py`` (tool ``grep_tool``), plus the CSV line.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def ensure_monitoring_dir() -> Path:
    """Ensure the monitoring directory exists."""
    monitoring_dir = Path.home() / ".claude" / "mcp_monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    return monitoring_dir


def main() -> None:
    """Log one Grep tool call."""
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input", {}) or {}
        session_id = payload.get("session_id", "unknown")
        monitoring_dir = ensure_monitoring_dir()

        with (monitoring_dir / "grep_usage.csv").open("a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
            f.write(f"{timestamp},{session_id},grep_tool,direct\n")

        with (monitoring_dir / "grep_usage.jsonl").open("a") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session_id,
                    "tool": "grep_tool",
                    "pattern": tool_input.get("pattern", ""),
                    "path": tool_input.get("path", ""),
                    "context": "grep_tool",
                },
                f,
            )
            f.write("\n")

    except Exception as e:
        # Log errors but never fail the hook (or the tool call it observes)
        error_file = Path.home() / ".claude" / "mcp_monitoring" / "hook_errors.log"
        error_file.parent.mkdir(parents=True, exist_ok=True)
        with error_file.open("a") as f:
            f.write(f"{datetime.now().isoformat()} - track_grep_tool error: {e}\n")


if __name__ == "__main__":
    main()
