#!/usr/bin/env python3
"""Analytics dashboard for MCP monitoring data collected by Claude Code hooks."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


class MCPAnalytics:
    """Analyze MCP usage patterns from Claude Code hook data."""

    def __init__(self, monitoring_dir: Path = None):
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

    def calculate_adoption_rate(self, days: int = 7) -> dict:
        """Calculate MCP adoption rate over specified days."""
        cutoff = datetime.now() - timedelta(days=days)

        mcp_calls = [
            c for c in self.load_mcp_calls() if datetime.fromisoformat(c["timestamp"]) > cutoff
        ]
        grep_usage = [
            g for g in self.load_grep_usage() if datetime.fromisoformat(g["timestamp"]) > cutoff
        ]

        total_searches = len(mcp_calls) + len(grep_usage)
        adoption_rate = (len(mcp_calls) / total_searches * 100) if total_searches > 0 else 0

        return {
            "mcp_calls": len(mcp_calls),
            "grep_usage": len(grep_usage),
            "total_searches": total_searches,
            "adoption_rate": round(adoption_rate, 1),
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
        adoption = self.calculate_adoption_rate(days)
        top_tools = self.get_top_mcp_tools()
        session_stats = self.get_session_stats()
        grep_breakdown = self.get_grep_tool_breakdown()

        report = []
        report.append("=" * 60)
        report.append("MCP MONITORING ANALYTICS REPORT")
        report.append(f"Period: Last {days} days")
        report.append("=" * 60)
        report.append("")

        # Adoption metrics
        report.append("📊 ADOPTION METRICS")
        report.append("-" * 40)
        report.append(f"MCP Tool Calls: {adoption['mcp_calls']}")
        report.append(f"Grep/Find Usage: {adoption['grep_usage']}")
        report.append(f"Total Searches: {adoption['total_searches']}")
        report.append(f"🎯 MCP Adoption Rate: {adoption['adoption_rate']}%")
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
        if adoption["adoption_rate"] < 50:
            report.append("⚠️  MCP adoption below 50% - consider:")
            report.append("  • Review why grep is still being used")
            report.append("  • Check if MCP tools cover all use cases")
            report.append("  • Ensure MCP tools are discoverable")
        elif adoption["adoption_rate"] < 80:
            report.append("📈 Good progress! To reach 80% adoption:")
            report.append("  • Identify remaining grep use cases")
            report.append("  • Add missing MCP functionality")
        else:
            report.append("🎉 Excellent MCP adoption rate!")
            report.append("  • Continue monitoring for edge cases")
            report.append("  • Share learnings with team")

        return "\n".join(report)

    def export_metrics(self, output_file: Path = None) -> None:
        """Export metrics to JSON file."""
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "adoption_7d": self.calculate_adoption_rate(7),
            "adoption_30d": self.calculate_adoption_rate(30),
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
