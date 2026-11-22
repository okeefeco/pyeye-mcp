#!/usr/bin/env python3
"""Analytics dashboard for MCP monitoring data collected by Claude Code hooks."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

#: A code search counts as followed up when the same session calls pyeye within
#: this long after it: grep found the text, pyeye proved the facts (#1130).
FOLLOW_UP_WINDOW = timedelta(minutes=10)

#: A Bash search command aimed at Python source.
_PYTHON_COMMAND = re.compile(r"\.py\b|--include[= ]['\"]?\*\.py|(?:-t|--type)[= ]?py\b")


def is_code_search(record: dict) -> bool:
    """Whether a recorded search was aimed at Python source (#1130).

    Grep is the right tool for finding where a concept lives in the code, so it
    isn't a failure in itself; searching logs, docs or process lists has nothing
    to do with pyeye at all. Only code searches are measured.

    - The Grep tool: a ``py`` type, a glob naming ``.py``, or a path that is a
      ``.py`` file or a directory (no glob or type: the whole tree's source).
    - A Bash command: one naming ``.py`` files, ``--include=*.py`` or ``-t py``.
    """
    if record.get("tool") == "grep_tool":
        file_type = record.get("type") or ""
        glob = record.get("glob") or ""
        if file_type or glob:
            return file_type == "py" or ".py" in glob
        path = record.get("path") or ""
        return not Path(path).suffix or path.endswith(".py")
    return bool(_PYTHON_COMMAND.search(record.get("command") or ""))


class MCPAnalytics:
    """Analyze MCP usage patterns from Claude Code hook data."""

    def __init__(self, monitoring_dir: Path | None = None):
        """Initialize analytics with monitoring directory."""
        self.monitoring_dir = monitoring_dir or (Path.home() / ".claude" / "mcp_monitoring")

    def load_mcp_calls(self) -> list[dict]:
        """Load MCP call data from JSON lines file."""
        calls = []
        json_file = self.monitoring_dir / "mcp_calls.jsonl"
        if json_file.exists():
            with json_file.open() as f:
                for line in f:
                    try:
                        calls.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return calls

    def load_grep_usage(self) -> list[dict]:
        """Load grep usage data from JSON lines file."""
        usage = []
        json_file = self.monitoring_dir / "grep_usage.jsonl"
        if json_file.exists():
            with json_file.open() as f:
                for line in f:
                    try:
                        usage.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return usage

    def load_sessions(self) -> list[dict]:
        """Load session data."""
        sessions = []
        session_file = self.monitoring_dir / "sessions.jsonl"
        if session_file.exists():
            with session_file.open() as f:
                for line in f:
                    try:
                        sessions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return sessions

    def calculate_follow_through(self, days: int = 7) -> dict:
        """How many code searches were followed by a pyeye call (#1130).

        Grep to find, pyeye to prove: a code search (:func:`is_code_search`) is
        followed up when its session calls pyeye within :data:`FOLLOW_UP_WINDOW`
        after it. The rate is the followed-up share of code searches. Other
        searches are counted apart and don't affect it.
        """
        cutoff = datetime.now() - timedelta(days=days)
        mcp_calls = [
            c for c in self.load_mcp_calls() if datetime.fromisoformat(c["timestamp"]) > cutoff
        ]
        searches = [
            g for g in self.load_grep_usage() if datetime.fromisoformat(g["timestamp"]) > cutoff
        ]
        code = [g for g in searches if is_code_search(g)]

        calls_by_session: dict[str, list[datetime]] = defaultdict(list)
        for call in mcp_calls:
            calls_by_session[call.get("session_id", "unknown")].append(
                datetime.fromisoformat(call["timestamp"])
            )

        def followed_up(search: dict) -> bool:
            at = datetime.fromisoformat(search["timestamp"])
            calls = calls_by_session.get(search.get("session_id", "unknown"), [])
            return any(at <= t <= at + FOLLOW_UP_WINDOW for t in calls)

        followed = sum(1 for g in code if followed_up(g))
        rate = (followed / len(code) * 100) if code else 0.0
        return {
            "mcp_calls": len(mcp_calls),
            "code_searches": len(code),
            "followed_by_pyeye": followed,
            "follow_through_rate": round(rate, 1),
            "other_searches": len(searches) - len(code),
            "period_days": days,
        }

    def get_top_mcp_tools(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get most frequently used MCP tools."""
        mcp_calls = self.load_mcp_calls()
        tool_counts = Counter(call["tool"] for call in mcp_calls)
        return tool_counts.most_common(limit)

    def get_session_stats(self) -> dict:
        """Get session statistics."""
        sessions = self.load_sessions()
        session_groups = defaultdict(list)

        for session in sessions:
            session_groups[session["session_id"]].append(session)

        total_sessions = len(session_groups)
        complete_sessions = sum(
            1 for events in session_groups.values() if any(e["action"] == "end" for e in events)
        )

        return {
            "total_sessions": total_sessions,
            "complete_sessions": complete_sessions,
            "active_sessions": total_sessions - complete_sessions,
        }

    def get_grep_tool_breakdown(self) -> dict[str, int]:
        """Get breakdown of grep tool usage."""
        grep_usage = self.load_grep_usage()
        tool_counts = Counter(g["tool"] for g in grep_usage)
        return dict(tool_counts)

    def generate_report(self, days: int = 7) -> str:
        """Generate comprehensive analytics report."""
        follow = self.calculate_follow_through(days)
        top_tools = self.get_top_mcp_tools()
        session_stats = self.get_session_stats()
        grep_breakdown = self.get_grep_tool_breakdown()

        report = []
        report.append("=" * 60)
        report.append("MCP MONITORING ANALYTICS REPORT")
        report.append(f"Period: Last {days} days")
        report.append("=" * 60)
        report.append("")

        # Find with grep, prove with pyeye (#1130)
        minutes = int(FOLLOW_UP_WINDOW.total_seconds() // 60)
        report.append("📊 FIND, THEN PROVE")
        report.append("-" * 40)
        report.append(f"pyeye calls: {follow['mcp_calls']}")
        report.append(f"Code searches (grep over Python): {follow['code_searches']}")
        report.append(
            f"  followed by pyeye within {minutes} min: {follow['followed_by_pyeye']}"
            f" ({follow['follow_through_rate']}%)"
        )
        report.append(
            f"Other searches (logs, docs, processes; not counted): {follow['other_searches']}"
        )
        report.append("")

        # Session statistics
        report.append("📅 SESSION STATISTICS")
        report.append("-" * 40)
        report.append(f"Total Sessions: {session_stats['total_sessions']}")
        report.append(f"Complete Sessions: {session_stats['complete_sessions']}")
        report.append(f"Active Sessions: {session_stats['active_sessions']}")
        report.append("")

        # Top MCP tools
        if top_tools:
            report.append("🔧 TOP MCP TOOLS USED")
            report.append("-" * 40)
            for tool, count in top_tools[:5]:
                report.append(f"  {tool}: {count} calls")
            report.append("")

        # Grep tool breakdown
        if grep_breakdown:
            report.append("🔍 GREP TOOL BREAKDOWN")
            report.append("-" * 40)
            for tool, count in grep_breakdown.items():
                report.append(f"  {tool}: {count} uses")
            report.append("")

        # Recommendations
        report.append("💡 RECOMMENDATIONS")
        report.append("-" * 40)
        if not follow["code_searches"]:
            report.append("No code searches in this period.")
        elif follow["follow_through_rate"] < 50:
            report.append("⚠️  Most code searches weren't followed by pyeye:")
            report.append("  • Turn grep hits into handles with resolve_at, then inspect / expand")
            report.append("  • Never answer callers/references with grep: use the LSP")
        else:
            report.append("🎉 Grep hits are being proved with pyeye.")
            report.append("  • Keep checking callers/references with the LSP, not grep")

        return "\n".join(report)

    def export_metrics(self, output_file: Path | None = None) -> None:
        """Export metrics to JSON file."""
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "follow_through_7d": self.calculate_follow_through(7),
            "follow_through_30d": self.calculate_follow_through(30),
            "top_tools": self.get_top_mcp_tools(),
            "session_stats": self.get_session_stats(),
            "grep_breakdown": self.get_grep_tool_breakdown(),
        }

        output_file = output_file or (self.monitoring_dir / "metrics_export.json")
        with output_file.open("w") as f:
            json.dump(metrics, f, indent=2, default=str)
        print(f"Metrics exported to: {output_file}")


def main() -> None:
    """Main entry point for analytics dashboard."""
    parser = argparse.ArgumentParser(description="MCP Monitoring Analytics Dashboard")
    parser.add_argument("--days", type=int, default=7, help="Number of days to analyze")
    parser.add_argument("--export", action="store_true", help="Export metrics to JSON")
    parser.add_argument("--output", type=Path, help="Output file for export")

    args = parser.parse_args()

    analytics = MCPAnalytics()

    # Generate and print report
    report = analytics.generate_report(args.days)
    print(report)

    # Export if requested
    if args.export:
        analytics.export_metrics(args.output)


if __name__ == "__main__":
    main()
