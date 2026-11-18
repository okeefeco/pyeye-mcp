"""The MCP monitoring hooks count pyeye's tools in both install forms (#965).

``claude mcp add`` names them ``mcp__pyeye__<tool>``; the Claude Code plugin
names them ``mcp__plugin_pyeye_pyeye__<tool>``. The hooks matched only the
first, so a plugin install recorded no MCP calls and the adoption rate
under-reported.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - runs the repo's own hook scripts
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "scripts" / "claude_hooks"
sys.path.insert(0, str(HOOKS))

from pyeye_tool_names import HOOK_MATCHER, PYEYE_TOOL_PREFIXES, short_name  # noqa: E402

FORMS = ("mcp__pyeye__resolve", "mcp__plugin_pyeye_pyeye__resolve")


@pytest.mark.parametrize("name", FORMS)
def test_both_forms_shorten_to_the_tool(name: str) -> None:
    assert short_name(name) == "resolve"


@pytest.mark.parametrize("name", ["Bash", "mcp__other__resolve", "mcp__pyeyex__resolve"])
def test_other_tools_are_left_alone(name: str) -> None:
    assert short_name(name) == name


def test_the_matcher_covers_both_forms_and_nothing_else() -> None:
    pattern = re.compile(HOOK_MATCHER)

    for name in FORMS:
        assert pattern.fullmatch(name), name
    for name in ("Bash", "Grep", "mcp__other__resolve", "mcp__plugin_other_other__x"):
        assert not pattern.fullmatch(name), name
    assert all(prefix.endswith("__") for prefix in PYEYE_TOOL_PREFIXES)


def test_hooks_json_uses_the_matcher_for_every_pyeye_hook() -> None:
    config = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    tracked = {
        (event, entry["matcher"])
        for event, entries in config["hooks"].items()
        for entry in entries
        if any("track_mcp" in hook["command"] for hook in entry["hooks"])
    }

    assert tracked == {("PreToolUse", HOOK_MATCHER), ("PostToolUse", HOOK_MATCHER)}


@pytest.mark.parametrize(
    ("script", "csv_name"),
    [("track_mcp_call.py", "mcp_calls.csv"), ("track_mcp_success.py", "mcp_success.csv")],
)
@pytest.mark.parametrize("name", FORMS)
def test_a_script_records_either_form_under_the_tools_name(
    tmp_path: Path, script: str, csv_name: str, name: str
) -> None:
    payload = {"tool_name": name, "session_id": "s1", "tool_input": {}, "tool_response": {}}
    # Path.home() reads HOME on POSIX and USERPROFILE on Windows.
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}

    subprocess.run(  # nosec B603 - fixed argv, the repo's own script
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        text=True,
        env=env,
        check=True,
    )

    monitoring = tmp_path / ".claude" / "mcp_monitoring"
    assert not (monitoring / "hook_errors.log").exists()
    row = (monitoring / csv_name).read_text(encoding="utf-8").strip().split(",")
    assert row[1:3] == ["s1", "resolve"]
    record = json.loads((monitoring / csv_name.replace(".csv", ".jsonl")).read_text())
    assert record["tool"] == "resolve" and record["full_tool_name"] == name
