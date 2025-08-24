"""Unified metrics collection system for cross-session tracking.

This module provides persistent metrics storage that captures MCP operations
across all Claude sessions, including subagents and parallel sessions.
"""

import contextlib
import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Platform-specific file locking
if sys.platform == "win32":
    try:
        import msvcrt

        HAS_FILE_LOCKING = True

        def lock_file(file_obj: Any, exclusive: bool = True) -> None:
            """Lock file on Windows."""
            with contextlib.suppress(OSError):
                msvcrt.locking(
                    file_obj.fileno(), msvcrt.LK_NBLCK if exclusive else msvcrt.LK_NBRLCK, 1
                )

        def unlock_file(file_obj: Any) -> None:
            """Unlock file on Windows."""
            with contextlib.suppress(OSError):
                msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)

    except ImportError:
        HAS_FILE_LOCKING = False
else:
    try:
        import fcntl

        HAS_FILE_LOCKING = True

        def lock_file(file_obj: Any, exclusive: bool = True) -> None:
            """Lock file on Unix."""
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

        def unlock_file(file_obj: Any) -> None:
            """Unlock file on Unix."""
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)

    except ImportError:
        HAS_FILE_LOCKING = False

# Fallback if no file locking available
if not HAS_FILE_LOCKING:

    def lock_file(file_obj: Any, exclusive: bool = True) -> None:
        """No-op when file locking not available."""
        pass

    def unlock_file(file_obj: Any) -> None:
        """No-op when file locking not available."""
        pass


@dataclass
class SessionMetrics:
    """Metrics for a single Claude session."""

    session_id: str
    session_type: str  # "main", "subagent", "task"
    parent_session: str | None = None
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: str | None = None
    mcp_operations: dict[str, int] = field(default_factory=dict)  # Use dict, not defaultdict
    grep_operations: int = 0
    total_operations: int = 0
    errors: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    memory_peak_mb: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class UnifiedMetricsCollector:
    """Persistent metrics collector that aggregates across all sessions."""

    def __init__(self, storage_dir: Path | None = None):
        """Initialize unified metrics collector.

        Args:
            storage_dir: Directory for metrics storage (defaults to ~/.pycodemcp/unified_metrics)
        """
        self.storage_dir = storage_dir or Path.home() / ".pycodemcp" / "unified_metrics"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.active_sessions_file = self.storage_dir / "active_sessions.json"
        self.completed_sessions_file = self.storage_dir / "completed_sessions.jsonl"
        self.aggregated_stats_file = self.storage_dir / "aggregated_stats.json"

        # Thread-local storage for current session
        self._local = threading.local()

        # Initialize files if they don't exist
        if not self.active_sessions_file.exists():
            self._write_json(self.active_sessions_file, {})
        if not self.completed_sessions_file.exists():
            self.completed_sessions_file.touch()
        if not self.aggregated_stats_file.exists():
            self._write_json(self.aggregated_stats_file, self._empty_aggregated_stats())

    def _empty_aggregated_stats(self) -> dict[str, Any]:
        """Create empty aggregated statistics structure."""
        return {
            "last_updated": datetime.now().isoformat(),
            "total_sessions": 0,
            "total_mcp_operations": 0,
            "total_grep_operations": 0,
            "mcp_adoption_rate": 0.0,
            "tool_usage": {},
            "hourly_activity": {},
            "daily_activity": {},
            "session_types": {},
            "top_tools": [],
            "error_rate": 0.0,
            "cache_hit_rate": 0.0,
        }

    def _read_json(self, file_path: Path) -> dict[str, Any]:
        """Read JSON file with file locking."""
        with open(file_path) as f:
            lock_file(f, exclusive=False)
            try:
                data: dict[str, Any] = json.load(f)
                return data
            finally:
                unlock_file(f)

    def _write_json(self, file_path: Path, data: dict[str, Any]) -> None:
        """Write JSON file with file locking."""
        with open(file_path, "w") as f:
            lock_file(f, exclusive=True)
            try:
                json.dump(data, f, indent=2, default=str)
            finally:
                unlock_file(f)

    def _update_json_atomic(self, file_path: Path, update_func: Any) -> None:
        """Atomically read, update, and write JSON file.

        This ensures that read-modify-write operations are atomic,
        preventing race conditions on Windows where file locking
        may not work as expected.
        """
        # Use a lock file to ensure atomicity across processes
        lock_path = file_path.with_suffix(file_path.suffix + ".lock")
        max_retries = 10
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                # Try to create lock file exclusively
                lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    # Read current data
                    data = self._read_json(file_path)
                    # Apply update function
                    update_func(data)
                    # Write updated data
                    self._write_json(file_path, data)
                finally:
                    # Always release lock
                    os.close(lock_fd)
                    lock_path.unlink(missing_ok=True)
                return
            except FileExistsError:
                # Lock file exists, another process is updating
                if attempt < max_retries - 1:
                    import time

                    time.sleep(retry_delay)
                else:
                    # Fall back to non-atomic operation
                    data = self._read_json(file_path)
                    update_func(data)
                    self._write_json(file_path, data)

    def _append_jsonl(self, file_path: Path, data: dict[str, Any]) -> None:
        """Append to JSONL file with file locking."""
        with open(file_path, "a") as f:
            lock_file(f, exclusive=True)
            try:
                f.write(json.dumps(data, default=str) + "\n")
            finally:
                unlock_file(f)

    def start_session(
        self,
        session_id: str | None = None,
        session_type: str = "main",
        parent_session: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Start a new metrics session.

        Args:
            session_id: Optional session ID (auto-generated if not provided)
            session_type: Type of session ("main", "subagent", "task")
            parent_session: Parent session ID for subagents
            metadata: Additional metadata (e.g., issue number, task description)

        Returns:
            Session ID
        """
        if session_id is None:
            session_id = f"{session_type}_{datetime.now().isoformat()}"

        session = SessionMetrics(
            session_id=session_id,
            session_type=session_type,
            parent_session=parent_session,
            metadata=metadata or {},
        )

        # Store in active sessions using atomic update
        session_dict = asdict(session)

        def update_sessions(data: dict[str, Any]) -> None:
            data[session_id] = session_dict

        self._update_json_atomic(self.active_sessions_file, update_sessions)

        # Set as current session for this thread
        self._local.session_id = session_id

        return session_id

    def record_mcp_operation(
        self,
        tool_name: str,
        session_id: str | None = None,
        success: bool = True,
        duration_ms: float | None = None,
    ) -> None:
        """Record an MCP tool operation.

        Args:
            tool_name: Name of the MCP tool
            session_id: Session ID (uses current if not provided)
            success: Whether operation succeeded
            duration_ms: Operation duration in milliseconds
        """
        session_id = session_id or getattr(self._local, "session_id", None)
        if not session_id:
            # Auto-create session if needed
            session_id = self.start_session(session_type="auto")

        def update_mcp_op(data: dict[str, Any]) -> None:
            if session_id in data:
                session = data[session_id]
                session["mcp_operations"][tool_name] = (
                    session["mcp_operations"].get(tool_name, 0) + 1
                )
                session["total_operations"] += 1
                if not success:
                    session["errors"] = session.get("errors", 0) + 1

                # Store duration if provided
                if duration_ms is not None:
                    if "operation_times" not in session:
                        session["operation_times"] = {}
                    if tool_name not in session["operation_times"]:
                        session["operation_times"][tool_name] = []
                    session["operation_times"][tool_name].append(duration_ms)

        self._update_json_atomic(self.active_sessions_file, update_mcp_op)

    def record_grep_operation(self, session_id: str | None = None) -> None:
        """Record a grep/text search operation."""
        session_id = session_id or getattr(self._local, "session_id", None)
        if not session_id:
            return

        def update_grep_op(data: dict[str, Any]) -> None:
            if session_id in data:
                data[session_id]["grep_operations"] += 1
                data[session_id]["total_operations"] += 1

        self._update_json_atomic(self.active_sessions_file, update_grep_op)

    def update_cache_stats(
        self, hits: int = 0, misses: int = 0, session_id: str | None = None
    ) -> None:
        """Update cache statistics for a session."""
        session_id = session_id or getattr(self._local, "session_id", None)
        if not session_id:
            return

        def update_cache(data: dict[str, Any]) -> None:
            if session_id in data:
                data[session_id]["cache_hits"] += hits
                data[session_id]["cache_misses"] += misses

        self._update_json_atomic(self.active_sessions_file, update_cache)

    def end_session(self, session_id: str | None = None) -> dict[str, Any]:
        """End a metrics session and move to completed.

        Returns:
            Final session metrics
        """
        session_id = session_id or getattr(self._local, "session_id", None)
        if not session_id:
            return {}

        # First get the session to calculate stats
        active_sessions = self._read_json(self.active_sessions_file)
        if session_id not in active_sessions:
            return {}

        # Get session for calculations
        session: dict[str, Any] = active_sessions[session_id].copy()
        session["end_time"] = datetime.now().isoformat()

        # Calculate session statistics
        duration_seconds = (
            datetime.fromisoformat(session["end_time"])
            - datetime.fromisoformat(session["start_time"])
        ).total_seconds()

        mcp_count = sum(session["mcp_operations"].values())
        grep_count = session["grep_operations"]

        session["statistics"] = {
            "duration_minutes": duration_seconds / 60,
            "mcp_operations_count": mcp_count,
            "grep_operations_count": grep_count,
            "mcp_adoption_rate": (
                mcp_count / (mcp_count + grep_count) if (mcp_count + grep_count) > 0 else 0
            ),
            "error_rate": (
                session["errors"] / session["total_operations"]
                if session["total_operations"] > 0
                else 0
            ),
            "cache_hit_rate": (
                session["cache_hits"] / (session["cache_hits"] + session["cache_misses"])
                if (session["cache_hits"] + session["cache_misses"]) > 0
                else 0
            ),
        }

        # Move to completed sessions
        self._append_jsonl(self.completed_sessions_file, session)

        # Remove from active sessions atomically
        def remove_session(data: dict[str, Any]) -> None:
            if session_id in data:
                del data[session_id]

        self._update_json_atomic(self.active_sessions_file, remove_session)

        # Update aggregated statistics
        self._update_aggregated_stats(session)

        # Clear thread-local session
        if hasattr(self._local, "session_id") and self._local.session_id == session_id:
            delattr(self._local, "session_id")

        return session

    def _update_aggregated_stats(self, session: dict[str, Any]) -> None:
        """Update aggregated statistics with completed session data."""
        stats = self._read_json(self.aggregated_stats_file)

        stats["total_sessions"] += 1
        stats["total_mcp_operations"] += sum(session["mcp_operations"].values())
        stats["total_grep_operations"] += session["grep_operations"]

        # Update tool usage counts
        for tool, count in session["mcp_operations"].items():
            stats["tool_usage"][tool] = stats["tool_usage"].get(tool, 0) + count

        # Update session type counts
        session_type = session.get("session_type", "unknown")
        stats["session_types"][session_type] = stats["session_types"].get(session_type, 0) + 1

        # Update activity patterns
        start_time = datetime.fromisoformat(session["start_time"])
        hour_key = start_time.strftime("%H")
        day_key = start_time.strftime("%Y-%m-%d")
        stats["hourly_activity"][hour_key] = stats["hourly_activity"].get(hour_key, 0) + 1
        stats["daily_activity"][day_key] = stats["daily_activity"].get(day_key, 0) + 1

        # Recalculate rates
        total_ops = stats["total_mcp_operations"] + stats["total_grep_operations"]
        stats["mcp_adoption_rate"] = (
            stats["total_mcp_operations"] / total_ops if total_ops > 0 else 0
        )

        # Update top tools
        stats["top_tools"] = sorted(stats["tool_usage"].items(), key=lambda x: x[1], reverse=True)[
            :10
        ]

        stats["last_updated"] = datetime.now().isoformat()

        self._write_json(self.aggregated_stats_file, stats)

    def get_active_sessions(self) -> dict[str, Any]:
        """Get all active sessions."""
        return self._read_json(self.active_sessions_file)

    def get_session_tree(self) -> dict[str, Any]:
        """Get hierarchical view of sessions (main -> subagents)."""
        active = self.get_active_sessions()

        # Build tree structure
        tree = {}
        for session_id, session in active.items():
            if session["parent_session"] is None:
                # Root session
                tree[session_id] = {**session, "children": []}

        # Add children
        for _session_id, session in active.items():
            if session["parent_session"] is not None:
                parent = session["parent_session"]
                if parent in tree:
                    tree[parent]["children"].append(session)

        return tree

    def get_aggregated_report(
        self, days: int = 7, include_sessions: bool = False
    ) -> dict[str, Any]:
        """Generate comprehensive metrics report.

        Args:
            days: Number of days to include in report
            include_sessions: Whether to include individual session details

        Returns:
            Comprehensive metrics report
        """
        stats = self._read_json(self.aggregated_stats_file)

        # Filter recent sessions
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_sessions = []

        if include_sessions and self.completed_sessions_file.exists():
            with open(self.completed_sessions_file) as f:
                for line in f:
                    session = json.loads(line)
                    if datetime.fromisoformat(session["start_time"]) >= cutoff_date:
                        recent_sessions.append(session)

        # Calculate period statistics
        period_mcp = sum(sum(s["mcp_operations"].values()) for s in recent_sessions)
        period_grep = sum(s["grep_operations"] for s in recent_sessions)

        report = {
            "period": f"Last {days} days",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_sessions": len(recent_sessions),
                "active_sessions": len(self.get_active_sessions()),
                "mcp_operations": period_mcp,
                "grep_operations": period_grep,
                "mcp_adoption_rate": (
                    period_mcp / (period_mcp + period_grep) if (period_mcp + period_grep) > 0 else 0
                ),
            },
            "global_stats": stats,
            "active_sessions": self.get_session_tree(),
        }

        if include_sessions:
            report["recent_sessions"] = recent_sessions

        return report

    def export_for_dashboard(self) -> dict[str, Any]:
        """Export metrics in format suitable for dashboard/visualization."""
        stats = self._read_json(self.aggregated_stats_file)
        active = self.get_active_sessions()

        return {
            "timestamp": datetime.now().isoformat(),
            "overview": {
                "active_sessions": len(active),
                "total_sessions": stats["total_sessions"],
                "mcp_adoption": f"{stats['mcp_adoption_rate'] * 100:.1f}%",
                "total_operations": stats["total_mcp_operations"] + stats["total_grep_operations"],
            },
            "charts": {
                "tool_usage": dict(stats["top_tools"]),
                "hourly_activity": dict(stats["hourly_activity"]),
                "daily_trend": dict(sorted(stats["daily_activity"].items())[-30:]),  # Last 30 days
                "session_types": dict(stats["session_types"]),
            },
            "live_activity": [
                {
                    "session": sid,
                    "type": s["session_type"],
                    "operations": sum(s["mcp_operations"].values()),
                    "duration": (
                        datetime.now() - datetime.fromisoformat(s["start_time"])
                    ).total_seconds()
                    / 60,
                }
                for sid, s in active.items()
            ],
        }


# Global instance for easy access
_unified_collector = None


def get_unified_collector() -> UnifiedMetricsCollector:
    """Get or create the global unified metrics collector."""
    global _unified_collector
    if _unified_collector is None:
        _unified_collector = UnifiedMetricsCollector()
    return _unified_collector
