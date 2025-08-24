#!/usr/bin/env python3
"""Unified metrics reporting and management tool.

This script provides comprehensive reporting across all Claude sessions,
including subagents and parallel MCP operations.
"""

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import unified_metrics module directly
unified_metrics_path = Path(__file__).parent.parent / "src" / "pycodemcp" / "unified_metrics.py"
spec = importlib.util.spec_from_file_location("unified_metrics", unified_metrics_path)
unified_metrics_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(unified_metrics_module)
get_unified_collector = unified_metrics_module.get_unified_collector


def format_duration(minutes: float) -> str:
    """Format duration in a human-readable way."""
    if minutes < 1:
        return f"{minutes * 60:.0f}s"
    elif minutes < 60:
        return f"{minutes:.1f}m"
    else:
        hours = minutes / 60
        return f"{hours:.1f}h"


def format_percentage(value: float) -> str:
    """Format percentage with color coding."""
    percentage = value * 100
    if percentage >= 80:
        color = "\033[92m"  # Green
    elif percentage >= 50:
        color = "\033[93m"  # Yellow
    else:
        color = "\033[91m"  # Red

    return f"{color}{percentage:.1f}%\033[0m"


def print_separator(title: str = "") -> None:
    """Print a section separator."""
    if title:
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print("=" * 60)
    else:
        print("-" * 60)


def command_status(_args: argparse.Namespace) -> None:
    """Show current status of all sessions."""
    collector = get_unified_collector()

    print_separator("📊 UNIFIED METRICS STATUS")

    # Active sessions
    active = collector.get_active_sessions()
    if active:
        print(f"\n🟢 Active Sessions ({len(active)}):")
        session_tree = collector.get_session_tree()

        for session_id, session in session_tree.items():
            session_type = session.get("session_type", "unknown")
            mcp_ops = sum(session.get("mcp_operations", {}).values())
            grep_ops = session.get("grep_operations", 0)
            total_ops = mcp_ops + grep_ops

            start_time = datetime.fromisoformat(session["start_time"])
            duration = (datetime.now() - start_time).total_seconds() / 60

            print(f"  📍 {session_id}")
            print(f"     Type: {session_type} | Duration: {format_duration(duration)}")
            print(f"     Operations: {mcp_ops} MCP, {grep_ops} grep (total: {total_ops})")

            # Show children (subagents)
            if session.get("children"):
                for child in session["children"]:
                    child_mcp = sum(child.get("mcp_operations", {}).values())
                    child_grep = child.get("grep_operations", 0)
                    print(f"       └── {child['session_id']} ({child['session_type']})")
                    print(f"           Operations: {child_mcp} MCP, {child_grep} grep")

            print()
    else:
        print("\n🔴 No active sessions")

    # Recent statistics
    stats = collector.get_aggregated_report(days=1, include_sessions=False)
    summary = stats["summary"]

    print("\n📈 Today's Activity:")
    print(f"  Sessions: {summary['total_sessions']}")
    print(f"  MCP Operations: {summary['mcp_operations']}")
    print(f"  Grep Operations: {summary['grep_operations']}")
    print(f"  MCP Adoption: {format_percentage(summary['mcp_adoption_rate'])}")


def command_report(args: argparse.Namespace) -> None:
    """Generate comprehensive metrics report."""
    collector = get_unified_collector()
    report = collector.get_aggregated_report(days=args.days, include_sessions=args.verbose)

    print_separator(f"📊 METRICS REPORT - {report['period']}")

    # Summary statistics
    summary = report["summary"]
    global_stats = report["global_stats"]

    print("\n📋 Summary:")
    print(f"  Total Sessions: {summary['total_sessions']}")
    print(f"  Active Sessions: {summary['active_sessions']}")
    print(f"  MCP Operations: {summary['mcp_operations']}")
    print(f"  Grep Operations: {summary['grep_operations']}")
    print(f"  MCP Adoption Rate: {format_percentage(summary['mcp_adoption_rate'])}")

    # Global statistics
    print("\n🌍 All-Time Stats:")
    print(f"  Total Sessions: {global_stats['total_sessions']}")
    print(f"  Total MCP Operations: {global_stats['total_mcp_operations']}")
    print(f"  Total Grep Operations: {global_stats['total_grep_operations']}")
    print(f"  Overall MCP Adoption: {format_percentage(global_stats['mcp_adoption_rate'])}")

    # Top tools
    if global_stats["top_tools"]:
        print("\n🔧 Most Used MCP Tools:")
        for i, (tool, count) in enumerate(global_stats["top_tools"][:5], 1):
            print(f"  {i}. {tool}: {count} uses")

    # Session types
    if global_stats["session_types"]:
        print("\n🎭 Session Types:")
        for session_type, count in global_stats["session_types"].items():
            print(f"  {session_type}: {count} sessions")

    # Activity patterns
    if global_stats["hourly_activity"]:
        print("\n⏰ Hourly Activity (last 7 days):")
        hours = sorted(global_stats["hourly_activity"].items())
        for hour, count in hours[-10:]:  # Show last 10 active hours
            if count > 0:
                print(f"  {hour}:00 - {count} sessions")

    # Active sessions detail
    if report["active_sessions"]:
        print_separator("Active Sessions Detail")
        for session_id, session in report["active_sessions"].items():
            print(f"\n🔄 {session_id}")
            print(f"   Type: {session.get('session_type', 'unknown')}")
            print(f"   Started: {session['start_time']}")

            mcp_ops = session.get("mcp_operations", {})
            if mcp_ops:
                print("   MCP Tools Used:")
                for tool, count in sorted(mcp_ops.items(), key=lambda x: x[1], reverse=True):
                    print(f"     {tool}: {count}")

            if session.get("children"):
                print(f"   Subagents: {len(session['children'])}")

    # Verbose session details
    if args.verbose and "recent_sessions" in report:
        print_separator("Recent Sessions Detail")
        for session in report["recent_sessions"][-10:]:  # Last 10 sessions
            stats = session.get("statistics", {})
            print(f"\n📄 {session['session_id']}")
            print(f"   Duration: {format_duration(stats.get('duration_minutes', 0))}")
            print(f"   MCP Adoption: {format_percentage(stats.get('mcp_adoption_rate', 0))}")
            print(
                f"   Operations: {stats.get('mcp_operations_count', 0)} MCP, {stats.get('grep_operations_count', 0)} grep"
            )


def command_dashboard(args: argparse.Namespace) -> None:
    """Export data for dashboard visualization."""
    collector = get_unified_collector()
    data = collector.export_for_dashboard()

    if args.format == "json":
        print(json.dumps(data, indent=2, default=str))
    else:
        # Pretty print for terminal
        print_separator("🎛️  DASHBOARD DATA")

        overview = data["overview"]
        print("\n📊 Overview:")
        print(f"  Active Sessions: {overview['active_sessions']}")
        print(f"  Total Sessions: {overview['total_sessions']}")
        print(f"  MCP Adoption: {overview['mcp_adoption']}")
        print(f"  Total Operations: {overview['total_operations']}")

        charts = data["charts"]

        print("\n🔧 Top Tools:")
        for tool, count in list(charts["tool_usage"].items())[:5]:
            print(f"  {tool}: {count}")

        print("\n📈 Daily Trend (last 7 days):")
        daily = sorted(charts["daily_trend"].items())[-7:]
        for date, count in daily:
            print(f"  {date}: {count} sessions")

        if data["live_activity"]:
            print("\n🔴 Live Activity:")
            for activity in data["live_activity"]:
                duration = format_duration(activity["duration"])
                print(
                    f"  {activity['session']} ({activity['type']}) - {duration} - {activity['operations']} ops"
                )


def command_cleanup(args: argparse.Namespace) -> None:
    """Clean up old metrics data."""
    get_unified_collector()

    # For now, just show what would be cleaned
    cutoff_date = datetime.now() - timedelta(days=args.days)
    print(f"Would clean up data older than {cutoff_date.isoformat()}")
    print("(Cleanup functionality not yet implemented)")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified metrics reporting for Python Code Intelligence MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status command
    subparsers.add_parser("status", help="Show current session status")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate comprehensive report")
    report_parser.add_argument(
        "--days", type=int, default=7, help="Number of days to include (default: 7)"
    )
    report_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Include detailed session information"
    )

    # Dashboard command
    dashboard_parser = subparsers.add_parser("dashboard", help="Export dashboard data")
    dashboard_parser.add_argument(
        "--format", choices=["json", "pretty"], default="pretty", help="Output format"
    )

    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up old metrics data")
    cleanup_parser.add_argument(
        "--days", type=int, default=30, help="Keep data newer than N days (default: 30)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "status":
            command_status(args)
        elif args.command == "report":
            command_report(args)
        elif args.command == "dashboard":
            command_dashboard(args)
        elif args.command == "cleanup":
            command_cleanup(args)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
