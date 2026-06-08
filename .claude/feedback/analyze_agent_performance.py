#!/usr/bin/env python3
"""Agent Performance Analysis Tool.

Analyzes feedback logs to identify patterns, track improvements, and suggest updates.
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class AgentPerformanceAnalyzer:
    """Analyzes agent performance from feedback logs."""

    def __init__(self, feedback_dir: Path | None = None):
        """Initialize the analyzer with the feedback directory."""
        if feedback_dir is None:
            feedback_dir = Path.home() / ".claude" / "feedback"
        self.feedback_dir = feedback_dir
        self.logs_dir = feedback_dir / "logs"
        self.metrics_dir = feedback_dir / "metrics"

    def load_logs(self, agent_name: str, days: int = 30) -> list[dict[str, Any]]:
        """Load feedback logs for a specific agent from the last N days."""
        logs = []
        cutoff_date = datetime.now() - timedelta(days=days)

        for log_file in self.logs_dir.glob(f"*-{agent_name}.json"):
            try:
                # Parse date from filename
                date_str = log_file.stem.split("-")[0:3]
                file_date = datetime.strptime("-".join(date_str), "%Y-%m-%d")

                if file_date >= cutoff_date:
                    with open(log_file) as f:
                        file_logs = json.load(f)
                        if isinstance(file_logs, list):
                            logs.extend(file_logs)
                        else:
                            logs.append(file_logs)
            except (ValueError, json.JSONDecodeError) as e:
                print(f"Warning: Error reading {log_file}: {e}", file=sys.stderr)

        return logs

    def analyze_issues(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze issues from feedback logs."""
        issue_types: Counter[str] = Counter()
        issue_impacts: Counter[str] = Counter()
        issue_descriptions = []

        for log in logs:
            if "issues" in log:
                for issue in log["issues"]:
                    issue_types[issue.get("type", "unknown")] += 1
                    issue_impacts[issue.get("impact", "unknown")] += 1
                    issue_descriptions.append(issue.get("description", ""))

        return {
            "total_issues": sum(issue_types.values()),
            "types": dict(issue_types),
            "impacts": dict(issue_impacts),
            "top_issues": issue_types.most_common(5),
            "high_impact_count": issue_impacts.get("high", 0),
        }

    def analyze_successes(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze successes from feedback logs."""
        success_types: Counter[str] = Counter()

        for log in logs:
            if "successes" in log:
                for success in log["successes"]:
                    success_types[success.get("type", "unknown")] += 1

        return {
            "total_successes": sum(success_types.values()),
            "types": dict(success_types),
            "top_successes": success_types.most_common(5),
        }

    def calculate_metrics(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate performance metrics from logs."""
        if not logs:
            return {"error": "No logs found"}

        outcomes = Counter(log.get("outcome", "unknown") for log in logs)
        total_executions = len(logs)

        # Calculate success rate
        successful = outcomes.get("success", 0) + outcomes.get("partial_success", 0) * 0.5
        success_rate = (successful / total_executions) * 100 if total_executions > 0 else 0

        # Calculate error recovery rate
        recoveries = sum(1 for log in logs if log.get("error_recovery", False))
        errors = outcomes.get("failure", 0) + outcomes.get("partial_success", 0)
        recovery_rate = (recoveries / errors) * 100 if errors > 0 else 100

        # Calculate average execution time
        exec_times = [log.get("execution_time_ms", 0) for log in logs if "execution_time_ms" in log]
        avg_exec_time = sum(exec_times) / len(exec_times) if exec_times else 0

        # User intervention rate
        interventions = sum(1 for log in logs if log.get("user_intervention_required", False))
        intervention_rate = (interventions / total_executions) * 100 if total_executions > 0 else 0

        return {
            "total_executions": total_executions,
            "success_rate": round(success_rate, 1),
            "error_recovery_rate": round(recovery_rate, 1),
            "avg_execution_time_ms": round(avg_exec_time, 0),
            "user_intervention_rate": round(intervention_rate, 1),
            "outcomes": dict(outcomes),
        }

    def extract_patterns(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract recurring patterns from logs."""
        patterns: dict[str, Any] = {
            "repeated_issues": [],
            "common_suggestions": [],
            "tool_usage": Counter(),
            "failure_patterns": [],
        }

        # Track repeated issues
        issue_counts = defaultdict(list)
        for log in logs:
            if "issues" in log:
                for issue in log["issues"]:
                    key = (issue.get("type", ""), issue.get("description", ""))
                    issue_counts[key].append(log.get("timestamp", ""))

        # Find issues that occurred multiple times
        for (issue_type, desc), timestamps in issue_counts.items():
            if len(timestamps) >= 2:
                patterns["repeated_issues"].append(
                    {
                        "type": issue_type,
                        "description": desc,
                        "frequency": len(timestamps),
                        "first_seen": min(timestamps) if timestamps else None,
                        "last_seen": max(timestamps) if timestamps else None,
                    }
                )

        # Collect suggestions
        suggestion_counts: Counter[str] = Counter()
        for log in logs:
            if "suggestions" in log:
                for suggestion in log["suggestions"]:
                    suggestion_counts[suggestion] += 1

        patterns["common_suggestions"] = [
            {"suggestion": sugg, "frequency": count}
            for sugg, count in suggestion_counts.most_common(5)
        ]

        # Tool usage patterns
        for log in logs:
            if "tools_used" in log:
                for tool in log["tools_used"]:
                    patterns["tool_usage"][tool] += 1

        patterns["tool_usage"] = dict(patterns["tool_usage"])

        return patterns

    def generate_report(self, agent_name: str, days: int = 30) -> str:
        """Generate a comprehensive performance report for an agent."""
        logs = self.load_logs(agent_name, days)

        if not logs:
            return f"No logs found for agent '{agent_name}' in the last {days} days."

        issues = self.analyze_issues(logs)
        successes = self.analyze_successes(logs)
        metrics = self.calculate_metrics(logs)
        patterns = self.extract_patterns(logs)

        report = f"""
# Agent Performance Report: {agent_name}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Analysis Period: Last {days} days

## Executive Summary
- Total Executions: {metrics['total_executions']}
- Success Rate: {metrics['success_rate']}%
- Error Recovery Rate: {metrics['error_recovery_rate']}%
- Average Execution Time: {metrics['avg_execution_time_ms']}ms
- User Intervention Rate: {metrics['user_intervention_rate']}%

## Issues Analysis
- Total Issues: {issues['total_issues']}
- High Impact Issues: {issues['high_impact_count']}

### Top Issue Types:
"""
        for issue_type, count in issues["top_issues"]:
            report += f"  - {issue_type}: {count} occurrences\n"

        report += f"""
## Success Analysis
- Total Successes: {successes['total_successes']}

### Top Success Types:
"""
        for success_type, count in successes["top_successes"]:
            report += f"  - {success_type}: {count} occurrences\n"

        report += "\n## Patterns & Insights\n"

        if patterns["repeated_issues"]:
            report += "\n### Repeated Issues (Requiring Attention):\n"
            for issue in patterns["repeated_issues"][:5]:
                report += f"  - {issue['type']}: {issue['description'][:50]}... (occurred {issue['frequency']} times)\n"

        if patterns["common_suggestions"]:
            report += "\n### Common Improvement Suggestions:\n"
            for sugg in patterns["common_suggestions"]:
                report += (
                    f"  - {sugg['suggestion'][:80]}... (suggested {sugg['frequency']} times)\n"
                )

        report += "\n### Tool Usage:\n"
        for tool, count in sorted(patterns["tool_usage"].items(), key=lambda x: x[1], reverse=True):
            report += f"  - {tool}: {count} uses\n"

        report += "\n## Recommendations\n"

        # Generate recommendations based on metrics
        if metrics["success_rate"] < 70:
            report += (
                "- ⚠️ Success rate is below 70%. Review repeated issues and implement fixes.\n"
            )

        if metrics["user_intervention_rate"] > 25:
            report += "- ⚠️ High user intervention rate. Improve error handling and recovery.\n"

        if issues["high_impact_count"] > metrics["total_executions"] * 0.2:
            report += "- ⚠️ Many high-impact issues. Prioritize fixing critical problems.\n"

        if patterns["repeated_issues"]:
            report += f"- 🔄 {len(patterns['repeated_issues'])} repeated issues detected. Update agent instructions.\n"

        if metrics["avg_execution_time_ms"] > 5000:
            report += "- ⏱️ Long execution times. Consider optimizing agent workflows.\n"

        return report

    def save_metrics(self, agent_name: str, metrics: dict[str, Any]) -> None:
        """Save metrics to a file for tracking over time."""
        metrics_file = self.metrics_dir / f"{agent_name}-metrics.json"

        # Load existing metrics
        existing_metrics = []
        if metrics_file.exists():
            try:
                with open(metrics_file) as f:
                    existing_metrics = json.load(f)
            except json.JSONDecodeError:
                pass

        # Add timestamp and append new metrics
        metrics["timestamp"] = datetime.now().isoformat()
        existing_metrics.append(metrics)

        # Keep only last 90 days of metrics
        cutoff = datetime.now() - timedelta(days=90)
        existing_metrics = [
            m for m in existing_metrics if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]

        # Save updated metrics
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        with open(metrics_file, "w") as f:
            json.dump(existing_metrics, f, indent=2)

    def compare_periods(self, agent_name: str, period1_days: int = 7, period2_days: int = 7) -> str:
        """Compare agent performance between two periods."""
        # Load logs for current period
        current_logs = self.load_logs(agent_name, period1_days)
        current_metrics = self.calculate_metrics(current_logs)

        # Load logs for previous period
        previous_start = period1_days + period2_days
        all_logs = self.load_logs(agent_name, previous_start)

        # Filter to get only previous period logs
        cutoff = datetime.now() - timedelta(days=period1_days)
        previous_logs = [
            log
            for log in all_logs
            if "timestamp" in log and datetime.fromisoformat(log["timestamp"]) < cutoff
        ]
        previous_metrics = self.calculate_metrics(previous_logs)

        # Calculate changes
        changes = {}
        for key in [
            "success_rate",
            "error_recovery_rate",
            "avg_execution_time_ms",
            "user_intervention_rate",
        ]:
            if key in current_metrics and key in previous_metrics:
                current = current_metrics[key]
                previous = previous_metrics[key]
                if previous != 0:
                    change = ((current - previous) / previous) * 100
                    changes[key] = {
                        "current": current,
                        "previous": previous,
                        "change_percent": round(change, 1),
                    }

        # Generate comparison report
        report = f"""
# Performance Comparison: {agent_name}
Current Period: Last {period1_days} days
Previous Period: {period1_days}-{previous_start} days ago

## Metrics Comparison
"""
        for metric, data in changes.items():
            symbol = (
                "📈" if data["change_percent"] > 0 else "📉" if data["change_percent"] < 0 else "➡️"
            )
            report += f"- {metric}: {data['current']} (was {data['previous']}) {symbol} {data['change_percent']}%\n"

        return report


def main() -> None:
    """Main entry point for the analysis tool."""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze agent performance from feedback logs")
    parser.add_argument("agent", help="Agent name to analyze")
    parser.add_argument(
        "--days", type=int, default=30, help="Number of days to analyze (default: 30)"
    )
    parser.add_argument(
        "--compare", action="store_true", help="Compare current week to previous week"
    )
    parser.add_argument("--save-metrics", action="store_true", help="Save metrics for tracking")
    parser.add_argument("--feedback-dir", type=Path, help="Path to feedback directory")

    args = parser.parse_args()

    # Initialize analyzer
    analyzer = AgentPerformanceAnalyzer(args.feedback_dir)

    if args.compare:
        # Compare last 7 days to previous 7 days
        report = analyzer.compare_periods(args.agent, 7, 7)
    else:
        # Generate standard report
        report = analyzer.generate_report(args.agent, args.days)

        # Optionally save metrics
        if args.save_metrics:
            logs = analyzer.load_logs(args.agent, args.days)
            metrics = analyzer.calculate_metrics(logs)
            analyzer.save_metrics(args.agent, metrics)
            report += "\n\n✅ Metrics saved for tracking.\n"

    print(report)


if __name__ == "__main__":
    main()
