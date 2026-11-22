"""``mcp-report`` measures find-then-prove, not grep avoidance (#1130).

The report used to count every grep or ``find`` (a ``ps | grep``, a search of
Markdown) against pyeye: adoption was pyeye calls over all searches. The
python-explore skill now says grep is for discovery and pyeye proves the hits,
so the report measures what that guidance asks for: code searches followed by
a pyeye call in the same session. Other searches are counted apart.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "claude_hooks"))

from mcp_analytics import FOLLOW_UP_WINDOW, MCPAnalytics, is_code_search  # noqa: E402


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"tool": "grep_tool", "pattern": "x"}, True),
        ({"tool": "grep_tool", "pattern": "x", "path": "src/pkg"}, True),
        ({"tool": "grep_tool", "pattern": "x", "path": "src/pkg/mod.py"}, True),
        ({"tool": "grep_tool", "pattern": "x", "type": "py"}, True),
        ({"tool": "grep_tool", "pattern": "x", "glob": "**/*.py"}, True),
        ({"tool": "grep_tool", "pattern": "x", "glob": "*.md"}, False),
        ({"tool": "grep_tool", "pattern": "x", "type": "md"}, False),
        ({"tool": "grep_tool", "pattern": "x", "path": "CHANGELOG.md"}, False),
        ({"tool": "grep", "command": "grep -rn hashlib --include=*.py src"}, True),
        ({"tool": "ripgrep", "command": "rg -t py sha256"}, True),
        ({"tool": "grep", "command": "grep -n def src/pkg/mod.py"}, True),
        ({"tool": "grep", "command": "ps aux | grep pytest"}, False),
        ({"tool": "grep", "command": "git log --oneline | grep fix"}, False),
        ({"tool": "find", "command": "find docs -name '*.md'"}, False),
    ],
)
def test_what_counts_as_a_code_search(record: dict, expected: bool) -> None:
    assert is_code_search(record) is expected


def _write(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


@pytest.fixture
def analytics(tmp_path: Path) -> MCPAnalytics:
    now = datetime.now()

    def at(minutes: int) -> str:
        return (now - timedelta(hours=1) + timedelta(minutes=minutes)).isoformat()

    late = int(FOLLOW_UP_WINDOW.total_seconds() // 60) + 5
    _write(
        tmp_path / "grep_usage.jsonl",
        [
            # s1: found, then proved two minutes later
            {"timestamp": at(0), "session_id": "s1", "tool": "grep_tool", "pattern": "sha256"},
            # s1: a pyeye call came, but only after the window
            {"timestamp": at(30), "session_id": "s1", "tool": "grep_tool", "type": "py"},
            # s2: a code search, and pyeye only in ANOTHER session
            {"timestamp": at(0), "session_id": "s2", "tool": "grep", "command": "rg -t py x"},
            # not code searches
            {"timestamp": at(1), "session_id": "s1", "tool": "grep", "command": "ps aux | grep x"},
            {"timestamp": at(1), "session_id": "s2", "tool": "grep_tool", "glob": "*.md"},
        ],
    )
    _write(
        tmp_path / "mcp_calls.jsonl",
        [
            {"timestamp": at(2), "session_id": "s1", "tool": "resolve_at"},
            {"timestamp": at(30 + late), "session_id": "s1", "tool": "inspect"},
            {"timestamp": at(1), "session_id": "s3", "tool": "inspect"},
        ],
    )
    return MCPAnalytics(monitoring_dir=tmp_path)


def test_follow_through_counts_only_code_searches_and_same_session_calls(
    analytics: MCPAnalytics,
) -> None:
    assert analytics.calculate_follow_through(days=7) == {
        "mcp_calls": 3,
        "code_searches": 3,
        "followed_by_pyeye": 1,
        "follow_through_rate": 33.3,
        "other_searches": 2,
        "period_days": 7,
    }


def test_the_report_states_find_then_prove(analytics: MCPAnalytics) -> None:
    report = analytics.generate_report(days=7)

    assert "FIND, THEN PROVE" in report
    assert "Code searches (grep over Python): 3" in report
    assert "followed by pyeye within 10 min: 1 (33.3%)" in report
    assert "not counted): 2" in report
    assert "resolve_at" in report  # the advice is to prove hits, not to stop grepping
    assert "Adoption" not in report


def test_no_code_searches_is_said_plainly(tmp_path: Path) -> None:
    report = MCPAnalytics(monitoring_dir=tmp_path).generate_report(days=7)

    assert "No code searches in this period." in report
