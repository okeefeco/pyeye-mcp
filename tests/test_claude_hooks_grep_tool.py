"""Direct Grep-tool use reaches ``mcp-report`` (#970).

The ``Grep`` hook in ``scripts/claude_hooks/hooks.json`` used to ``echo`` a line
into ``grep_usage.csv`` only, while ``mcp_analytics.py`` reads only
``grep_usage.jsonl``. So Claude's own Grep tool never counted towards grep usage
or the MCP adoption rate. ``track_grep_tool.py`` now writes both.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - runs the repo's own hook script
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "scripts" / "claude_hooks"
sys.path.insert(0, str(HOOKS))

from mcp_analytics import MCPAnalytics  # noqa: E402


def _run_hook(home: Path, payload: dict) -> None:
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    subprocess.run(  # nosec B603 - fixed argv, the repo's own script
        [sys.executable, str(HOOKS / "track_grep_tool.py")],
        input=json.dumps(payload),
        text=True,
        env=env,
        check=True,
    )


def test_a_grep_tool_call_is_recorded_where_the_report_reads(tmp_path: Path) -> None:
    payload = {
        "tool_name": "Grep",
        "session_id": "s1",
        "tool_input": {"pattern": "def resolve", "path": "src/"},
    }
    _run_hook(tmp_path, payload)

    monitoring = tmp_path / ".claude" / "mcp_monitoring"
    assert not (monitoring / "hook_errors.log").exists()
    record = json.loads((monitoring / "grep_usage.jsonl").read_text(encoding="utf-8"))
    assert record["tool"] == "grep_tool"
    assert record["context"] == "grep_tool"
    assert record["session_id"] == "s1"
    assert record["pattern"] == "def resolve"
    assert (record["glob"], record["type"]) == ("", "")
    row = (monitoring / "grep_usage.csv").read_text(encoding="utf-8").strip().split(",")
    assert row[1:] == ["s1", "grep_tool", "direct"]


def test_the_report_counts_it(tmp_path: Path) -> None:
    _run_hook(tmp_path, {"tool_name": "Grep", "session_id": "s1", "tool_input": {"pattern": "x"}})
    analytics = MCPAnalytics(monitoring_dir=tmp_path / ".claude" / "mcp_monitoring")
    # No glob, type or file path: a search over the source tree, so a code search (#1130).
    assert analytics.calculate_follow_through(days=7)["code_searches"] == 1
    assert analytics.get_grep_tool_breakdown() == {"grep_tool": 1}


def test_a_bad_payload_is_logged_not_raised(tmp_path: Path) -> None:
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    result = subprocess.run(  # nosec B603 - fixed argv, the repo's own script
        [sys.executable, str(HOOKS / "track_grep_tool.py")],
        input="not json",
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0  # a hook must never fail the tool call
    log = tmp_path / ".claude" / "mcp_monitoring" / "hook_errors.log"
    assert "track_grep_tool error" in log.read_text(encoding="utf-8")


def test_hooks_json_routes_the_grep_tool_to_the_script() -> None:
    config = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entry in config["hooks"]["PreToolUse"]
        if entry.get("matcher") == "Grep"
        for hook in entry["hooks"]
    ]
    assert commands == ["python3 ~/GitHub/pyeye-mcp/scripts/claude_hooks/track_grep_tool.py"]
