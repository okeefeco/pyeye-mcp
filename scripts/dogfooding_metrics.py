#!/usr/bin/env python3
"""Dogfooding metrics tracking for Python Code Intelligence MCP.

This script helps track how we use our own MCP tools during development,
measuring adoption, performance, and identifying patterns.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add src to path to import constants (must be before other local imports)
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

import click  # noqa: E402

from pyeye.constants import METRICS_DIR  # noqa: E402


class DogfoodingMetrics:
    """Track and report MCP usage during development."""

    def __init__(self, data_dir: Path | None = None):
        """Initialize metrics tracker."""
        self.data_dir = data_dir or Path.home() / METRICS_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.data_dir / "current_session.json"
        self.history_file = self.data_dir / "history.jsonl"

    def start_session(self, issue_number: int | None = None) -> dict[str, Any]:
        """Start a new development session."""
        # Get current MCP metrics via the MCP tool
        # For now, we'll simulate this - in production, call the actual MCP
        session = {
            "id": datetime.now().isoformat(),
            "issue": issue_number,
            "start_time": datetime.now().isoformat(),
            "baseline_metrics": self._get_mcp_metrics(),
            "grep_count": 0,
            "mcp_queries": [],
            "time_saved_estimates": [],
            "bugs_prevented": [],
        }

        self._save_session(session)
        return session

    def end_session(self) -> dict[str, Any]:
        """End current session and calculate stats."""
        if not self.session_file.exists():
            return {"error": "No active session"}

        session = self._load_session()
        session["end_time"] = datetime.now().isoformat()
        session["final_metrics"] = self._get_mcp_metrics()

        # Calculate deltas
        session["stats"] = self._calculate_stats(session)

        # Append to history
        with self.history_file.open("a") as f:
            f.write(json.dumps(session) + "\n")

        # Save stats for commit message hook
        stats_file = self.data_dir / "last_session_stats.json"
        with stats_file.open("w") as f:
            json.dump(session["stats"], f, indent=2)

        # Clear current session
        self.session_file.unlink()

        return session

    def log_mcp_query(self, tool: str, duration_ms: float, success: bool = True) -> None:
        """Log an MCP tool usage."""
        session = self._load_session()
        session["mcp_queries"].append(
            {
                "tool": tool,
                "duration_ms": duration_ms,
                "success": success,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self._save_session(session)

    def log_grep_usage(self) -> None:
        """Log a grep/manual search usage."""
        session = self._load_session()
        session["grep_count"] += 1
        self._save_session(session)

    def log_bug_prevented(self, description: str) -> None:
        """Log a bug that was prevented by using MCP."""
        session = self._load_session()
        session["bugs_prevented"].append(
            {"description": description, "timestamp": datetime.now().isoformat()}
        )
        self._save_session(session)

    def log_time_saved(self, minutes: int, reason: str) -> None:
        """Log estimated time saved."""
        session = self._load_session()
        session["time_saved_estimates"].append(
            {"minutes": minutes, "reason": reason, "timestamp": datetime.now().isoformat()}
        )
        self._save_session(session)

    def sync_mcp_metrics(self) -> dict[str, Any]:
        """Sync current MCP metrics to the active session."""
        if not self.session_file.exists():
            return {"error": "No active session"}

        try:
            # Try to get fresh MCP metrics
            current_metrics = self._get_mcp_metrics()

            session = self._load_session()
            session["current_metrics"] = current_metrics
            session["last_sync"] = datetime.now().isoformat()

            # Update MCP query count if we have it
            if "total_mcp_calls" in current_metrics:
                baseline_total = session.get("baseline_metrics", {}).get("total_mcp_calls", 0)
                current_total = current_metrics.get("total_mcp_calls", 0)
                session["mcp_queries_count"] = max(current_total - baseline_total, 0)

            self._save_session(session)

            return {
                "synced": True,
                "mcp_calls": session.get("mcp_queries_count", 0),
                "session_id": session.get("id"),
            }

        except Exception as e:
            return {"error": f"Failed to sync MCP metrics: {e}"}

    def generate_report(self, days: int = 7) -> dict[str, Any]:
        """Generate a report for the last N days."""
        if not self.history_file.exists():
            return {"error": "No history available"}

        sessions = []
        with self.history_file.open() as f:
            for line in f:
                sessions.append(json.loads(line))

        # Filter to last N days
        cutoff = datetime.now().timestamp() - (days * 86400)
        recent_sessions = [
            s for s in sessions if datetime.fromisoformat(s["start_time"]).timestamp() > cutoff
        ]

        # Calculate aggregates
        total_mcp_queries = sum(len(s.get("mcp_queries", [])) for s in recent_sessions)
        total_grep_count = sum(s.get("grep_count", 0) for s in recent_sessions)
        total_bugs_prevented = sum(len(s.get("bugs_prevented", [])) for s in recent_sessions)
        total_time_saved = sum(
            sum(t["minutes"] for t in s.get("time_saved_estimates", [])) for s in recent_sessions
        )

        # Find most used tools
        tool_usage: dict[str, int] = {}
        for session in recent_sessions:
            for query in session.get("mcp_queries", []):
                tool = query["tool"]
                tool_usage[tool] = tool_usage.get(tool, 0) + 1

        return {
            "period_days": days,
            "sessions_count": len(recent_sessions),
            "mcp_adoption": {
                "total_mcp_queries": total_mcp_queries,
                "total_grep_usage": total_grep_count,
                "mcp_ratio": total_mcp_queries / max(total_mcp_queries + total_grep_count, 1),
                "most_used_tools": sorted(tool_usage.items(), key=lambda x: x[1], reverse=True)[:5],
            },
            "impact": {
                "bugs_prevented": total_bugs_prevented,
                "time_saved_minutes": total_time_saved,
                "time_saved_hours": round(total_time_saved / 60, 1),
            },
            "sessions": recent_sessions,
        }

    def _get_mcp_metrics(self) -> dict[str, Any]:
        """Get current MCP performance metrics."""
        try:
            # Try to import and use the dogfooding integration
            import sys
            from pathlib import Path

            # Add the src directory to Python path to import our module
            project_root = Path(__file__).parent.parent
            src_path = project_root / "src"
            if str(src_path) not in sys.path:
                sys.path.insert(0, str(src_path))

            from pyeye.dogfooding_integration import get_integration

            integration = get_integration()
            metrics: dict[str, Any] = integration.export_mcp_metrics_for_session()
            return metrics

        except ImportError:
            # Fallback: try subprocess call if integration not available
            try:
                result = subprocess.run(
                    ["mcp", "call", "get_performance_metrics"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return json.loads(result.stdout)  # type: ignore[no-any-return]
            except Exception:
                pass

        # Return empty metrics if MCP not available
        return {
            "operations": {},
            "cache": {"hits": 0, "misses": 0},
            "summary": {"total_operations": 0},
        }

    def _calculate_stats(self, session: dict[str, Any]) -> dict[str, Any]:
        """Calculate session statistics."""
        start = datetime.fromisoformat(session["start_time"])
        end = datetime.fromisoformat(session["end_time"])
        duration_minutes = (end - start).total_seconds() / 60

        # Get MCP call counts from final metrics if available
        final_metrics = session.get("final_metrics", {})
        baseline_metrics = session.get("baseline_metrics", {})

        # Calculate delta in MCP calls
        final_total = final_metrics.get("total_mcp_calls", 0)
        baseline_total = baseline_metrics.get("total_mcp_calls", 0)
        mcp_count = max(final_total - baseline_total, 0)

        # Fallback to old counting method if metrics not available
        if mcp_count == 0:
            mcp_count = len(session.get("mcp_queries", []))

        grep_count = session.get("grep_count", 0)

        return {
            "duration_minutes": round(duration_minutes, 1),
            "mcp_queries_count": mcp_count,
            "grep_count": grep_count,
            "mcp_ratio": mcp_count / max(mcp_count + grep_count, 1),
            "bugs_prevented": len(session.get("bugs_prevented", [])),
            "time_saved_minutes": sum(
                t["minutes"] for t in session.get("time_saved_estimates", [])
            ),
        }

    def _save_session(self, session: dict[str, Any]) -> None:
        """Save current session to file."""
        with self.session_file.open("w") as f:
            json.dump(session, f, indent=2)

    def _load_session(self) -> dict[str, Any]:
        """Load current session from file."""
        if not self.session_file.exists():
            return self.start_session()

        with self.session_file.open() as f:
            return json.load(f)  # type: ignore[no-any-return]


@click.group()
def cli() -> None:
    """Dogfooding metrics for Python Code Intelligence MCP."""
    pass


@cli.command()
@click.option("--issue", "-i", type=int, help="GitHub issue number")
def start(issue: int | None) -> None:
    """Start a new development session."""
    metrics = DogfoodingMetrics()
    session = metrics.start_session(issue)
    click.echo(f"Started session: {session['id']}")
    if issue:
        click.echo(f"Working on issue #{issue}")


@cli.command()
def end() -> None:
    """End current session and show stats."""
    metrics = DogfoodingMetrics()
    session = metrics.end_session()

    if "error" in session:
        click.echo(session["error"])
        return

    stats = session["stats"]
    click.echo("\n=== Session Summary ===")
    click.echo(f"Duration: {stats['duration_minutes']} minutes")
    click.echo(f"MCP queries: {stats['mcp_queries_count']}")
    click.echo(f"Grep/manual searches: {stats['grep_count']}")
    click.echo(f"MCP adoption rate: {stats['mcp_ratio']:.1%}")
    click.echo(f"Bugs prevented: {stats['bugs_prevented']}")
    click.echo(f"Time saved: {stats['time_saved_minutes']} minutes")


@cli.command()
@click.argument("tool")
def mcp(tool: str) -> None:
    """Log an MCP tool usage."""
    metrics = DogfoodingMetrics()
    # In production, this would be called automatically
    metrics.log_mcp_query(tool, 100)  # Dummy duration
    click.echo(f"Logged MCP usage: {tool}")


@cli.command()
def grep() -> None:
    """Log a grep/manual search usage."""
    metrics = DogfoodingMetrics()
    metrics.log_grep_usage()
    click.echo("Logged grep usage")


@cli.command()
@click.option("--days", "-d", default=7, help="Number of days to report")
def report(days: int) -> None:
    """Generate usage report."""
    metrics = DogfoodingMetrics()
    report = metrics.generate_report(days)

    if "error" in report:
        click.echo(report["error"])
        return

    click.echo(f"\n=== {days}-Day Report ===")
    click.echo(f"Sessions: {report['sessions_count']}")

    adoption = report["mcp_adoption"]
    click.echo("\nMCP Adoption:")
    click.echo(f"  Total MCP queries: {adoption['total_mcp_queries']}")
    click.echo(f"  Total grep usage: {adoption['total_grep_usage']}")
    click.echo(f"  MCP adoption rate: {adoption['mcp_ratio']:.1%}")

    if adoption["most_used_tools"]:
        click.echo("\nMost used tools:")
        for tool, count in adoption["most_used_tools"]:
            click.echo(f"  - {tool}: {count}")

    impact = report["impact"]
    click.echo("\nImpact:")
    click.echo(f"  Bugs prevented: {impact['bugs_prevented']}")
    click.echo(f"  Time saved: {impact['time_saved_hours']} hours")


@cli.command()
@click.argument("minutes", type=int)
@click.argument("reason")
def saved(minutes: int, reason: str) -> None:
    """Log time saved by using MCP."""
    metrics = DogfoodingMetrics()
    metrics.log_time_saved(minutes, reason)
    click.echo(f"Logged {minutes} minutes saved: {reason}")


@cli.command()
@click.argument("description")
def bug(description: str) -> None:
    """Log a bug prevented by MCP."""
    metrics = DogfoodingMetrics()
    metrics.log_bug_prevented(description)
    click.echo(f"Logged prevented bug: {description}")


@cli.command()
def sync() -> None:
    """Sync current MCP metrics to active session."""
    metrics = DogfoodingMetrics()
    result = metrics.sync_mcp_metrics()

    if "error" in result:
        click.echo(f"❌ {result['error']}")
        return

    mcp_calls = result.get("mcp_calls", 0)
    session_id = result.get("session_id", "unknown")
    click.echo(f"✅ Synced {mcp_calls} MCP calls for session {session_id}")


if __name__ == "__main__":
    cli()
