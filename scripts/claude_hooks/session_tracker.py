#!/usr/bin/env python3
"""Track Claude Code sessions for MCP monitoring."""

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
    """Track session start/end events."""
    try:
        # Get action from command line
        action = sys.argv[1] if len(sys.argv) > 1 else "unknown"

        # Read hook payload from stdin
        payload = json.load(sys.stdin)

        monitoring_dir = ensure_monitoring_dir()
        session_id = payload.get("session_id", "unknown")

        # Log session events
        session_file = monitoring_dir / "sessions.jsonl"
        with session_file.open("a") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session_id,
                    "action": action,
                    "cwd": payload.get("cwd", "unknown"),
                    "transcript_path": payload.get("transcript_path", ""),
                },
                f,
            )
            f.write("\n")

        # Create/update active session file for easy lookup
        if action == "start":
            active_file = monitoring_dir / "active_session.json"
            with active_file.open("w") as f:
                json.dump(
                    {
                        "session_id": session_id,
                        "start_time": datetime.now().isoformat(),
                        "cwd": payload.get("cwd", "unknown"),
                    },
                    f,
                    indent=2,
                )
        elif action == "end":
            active_file = monitoring_dir / "active_session.json"
            if active_file.exists():
                active_file.unlink()

    except Exception as e:
        # Log errors but don't fail the hook
        error_file = Path.home() / ".claude" / "mcp_monitoring" / "hook_errors.log"
        error_file.parent.mkdir(parents=True, exist_ok=True)
        with error_file.open("a") as f:
            f.write(f"{datetime.now().isoformat()} - session_tracker error: {e}\n")


if __name__ == "__main__":
    main()
