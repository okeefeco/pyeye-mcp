"""Integration between MCP performance metrics and dogfooding metrics tracking.

This module provides the bridge between the internal MCP performance metrics
and the external dogfooding metrics tracking system, enabling automatic
recording of MCP tool usage during development sessions.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .metrics import metrics as mcp_metrics

logger = logging.getLogger(__name__)


class DogfoodingIntegration:
    """Bridge between MCP metrics and dogfooding tracker."""

    def __init__(self, metrics_dir: Path | None = None):
        """Initialize the integration.

        Args:
            metrics_dir: Optional directory for metrics storage
        """
        self.metrics_dir = metrics_dir or Path.home() / ".pycodemcp" / "metrics"
        self.session_file = self.metrics_dir / "current_session.json"
        self.mcp_log_file = self.metrics_dir / "mcp_calls.jsonl"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure metrics directories exist."""
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

    def export_mcp_metrics_for_session(self) -> dict[str, Any]:
        """Export current MCP metrics for dogfooding session.

        Returns:
            Dictionary containing MCP usage statistics
        """
        # Get the full performance report
        report = mcp_metrics.get_performance_report()

        # Extract tool-specific metrics
        tool_calls = []
        total_mcp_calls = 0

        # Look for all MCP tool metrics
        for category in ["symbol_search", "file_operations", "other"]:
            operations = report.get("operations", {}).get(category, {})
            for tool_name, stats in operations.items():
                if stats.get("count", 0) > 0:
                    total_mcp_calls += stats["count"]
                    tool_calls.append(
                        {
                            "tool": tool_name,
                            "count": stats["count"],
                            "avg_ms": stats.get("avg_ms", 0),
                            "errors": stats.get("errors", 0),
                        }
                    )

        # Sort by usage count
        tool_calls.sort(key=lambda x: x["count"], reverse=True)

        return {
            "total_mcp_calls": total_mcp_calls,
            "tool_calls": tool_calls,
            "cache_stats": report.get("cache", {}),
            "memory_stats": report.get("memory", {}),
            "timestamp": datetime.now().isoformat(),
        }

    def log_mcp_call(self, tool_name: str, params: dict[str, Any] | None = None) -> None:
        """Log an individual MCP tool call for detailed tracking.

        Args:
            tool_name: Name of the MCP tool called
            params: Parameters passed to the tool
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "params": params or {},
        }

        try:
            with open(self.mcp_log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to log MCP call: {e}")

    def update_session_with_mcp_stats(self) -> bool:
        """Update current dogfooding session with MCP statistics.

        Returns:
            True if session was updated, False otherwise
        """
        if not self.session_file.exists():
            logger.debug("No active dogfooding session found")
            return False

        try:
            # Read current session
            with open(self.session_file) as f:
                session = json.load(f)

            # Get MCP metrics
            mcp_stats = self.export_mcp_metrics_for_session()

            # Update session with MCP data
            session["mcp_metrics"] = mcp_stats
            session["mcp_queries"] = mcp_stats.get("tool_calls", [])

            # Count MCP queries for the session
            current_count = session.get("mcp_queries_count", 0)
            new_calls = mcp_stats.get("total_mcp_calls", 0)

            # Only update if we have new calls
            if new_calls > current_count:
                session["mcp_queries_count"] = new_calls
                session["last_mcp_update"] = datetime.now().isoformat()

                # Write back updated session
                with open(self.session_file, "w") as f:
                    json.dump(session, f, indent=2)

                logger.info(f"Updated session with {new_calls} MCP calls")
                return True

        except Exception as e:
            logger.error(f"Failed to update session with MCP stats: {e}")

        return False

    def get_mcp_adoption_rate(self) -> dict[str, Any]:
        """Calculate MCP adoption rate for current session.

        Returns:
            Dictionary with adoption metrics
        """
        if not self.session_file.exists():
            return {"error": "No active session"}

        try:
            with open(self.session_file) as f:
                session = json.load(f)

            mcp_count = session.get("mcp_queries_count", 0)
            grep_count = session.get("grep_count", 0)
            total = mcp_count + grep_count

            return {
                "mcp_queries": mcp_count,
                "grep_usage": grep_count,
                "total_searches": total,
                "mcp_adoption_rate": (mcp_count / total * 100) if total > 0 else 0,
                "session_id": session.get("id"),
                "issue": session.get("issue"),
            }

        except Exception as e:
            logger.error(f"Failed to calculate adoption rate: {e}")
            return {"error": str(e)}


# Global instance for easy access
_integration: DogfoodingIntegration | None = None


def get_integration() -> DogfoodingIntegration:
    """Get or create the global integration instance."""
    global _integration
    if _integration is None:
        _integration = DogfoodingIntegration()
    return _integration


def sync_mcp_metrics() -> bool:
    """Sync current MCP metrics to dogfooding session.

    This should be called periodically or after significant operations.
    """
    integration = get_integration()
    return integration.update_session_with_mcp_stats()
