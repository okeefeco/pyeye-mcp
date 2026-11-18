"""Unified metrics collection system for cross-session tracking.

This module provides persistent metrics storage that captures MCP operations
across all Claude sessions, including subagents and parallel sessions.
"""

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from .constants import METRICS_DIR

logger = logging.getLogger(__name__)

#: An active session with no activity for this long is closed at start-up (#914):
#: its process died without ending it (a killed server, a crashed test run).
STALE_SESSION_AGE = timedelta(hours=24)

#: How long an update waits for the store's file lock before it is skipped (#914).
_LOCK_TIMEOUT_S = 10.0

#: How often a write retries replacing a file that a reader holds open (Windows).
_REPLACE_ATTEMPTS = 50


def default_storage_dir() -> Path:
    """Where metrics are stored: ``PYEYE_METRICS_DIR`` if set, else ``~/.pyeye/metrics``.

    The test suite sets it so that neither it nor a server it launches writes
    the developer's real store (#914).
    """
    configured = os.environ.get("PYEYE_METRICS_DIR")
    return Path(configured) if configured else Path.home() / METRICS_DIR


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
    last_activity: str | None = None  # refreshed by every update; the prune clock (#914)


class UnifiedMetricsCollector:
    """Persistent metrics collector that aggregates across all sessions."""

    def __init__(self, storage_dir: Path | None = None):
        """Initialize collector with storage directory.

        Args:
            storage_dir: Directory for metrics storage (defaults to ~/.pyeye/metrics)
        """
        if storage_dir is None:
            storage_dir = default_storage_dir()

        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.active_sessions_file = self.storage_dir / "active_sessions.json"
        self.completed_sessions_file = self.storage_dir / "completed_sessions.jsonl"
        self.aggregated_stats_file = self.storage_dir / "aggregated_stats.json"

        # The process's current session. One per process, not per thread: tool
        # work runs on worker threads, and a thread-local id opened a new session
        # on every thread that recorded something (#914).
        self._session_id: str | None = None
        self._session_lock = threading.RLock()  # start_session re-enters it

        # Initialize files if they don't exist
        self._init_storage_files()
        self.prune_stale_sessions()

    def _init_storage_files(self) -> None:
        """Initialize storage files if they don't exist."""
        if not self.active_sessions_file.exists():
            self._write_json(self.active_sessions_file, {})

        if not self.aggregated_stats_file.exists():
            self._write_json(self.aggregated_stats_file, self._default_aggregated_stats())

    def _default_aggregated_stats(self) -> dict[str, Any]:
        """Create default aggregated statistics structure."""
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
        """Read JSON file safely."""
        if not file_path.exists():
            return {}

        try:
            with open(file_path) as f:
                content: dict[str, Any] = json.load(f)
                return content
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_json(self, file_path: Path, data: dict[str, Any]) -> None:
        """Write a JSON file whole: a reader sees the old file or the new one (#914).

        The data goes to a temporary file in the same directory, which then
        replaces the target. Writing in place let a reader see a truncated file.
        """
        fd, tmp = tempfile.mkstemp(dir=file_path.parent, prefix=f".{file_path.name}.")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
            for attempt in range(_REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp, file_path)
                    return
                except PermissionError:
                    # Windows refuses to replace a file another process has open;
                    # readers hold it only briefly.
                    if attempt == _REPLACE_ATTEMPTS - 1:
                        logger.warning(
                            "Metrics write skipped: %s stayed open elsewhere",
                            file_path.as_posix(),
                        )
                    else:
                        time.sleep(0.01)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _update_json_atomic(self, file_path: Path, update_func: Any) -> None:
        """Atomically read, update, and write JSON file using filelock.

        This ensures that read-modify-write operations are atomic,
        preventing race conditions on all platforms including Windows.
        """
        lock_path = f"{file_path}.lock"
        lock = FileLock(lock_path, timeout=_LOCK_TIMEOUT_S)

        try:
            with lock:
                # Read current data
                data = self._read_json(file_path)
                # Apply update function
                update_func(data)
                # Write updated data
                self._write_json(file_path, data)
        except Timeout:
            # An unlocked read-update-write could read a file another process is
            # mid-way through and write back only its own update (#914): skip it.
            logger.warning(
                "Metrics update skipped: could not lock %s within %ss",
                file_path.as_posix(),
                _LOCK_TIMEOUT_S,
            )

    def _append_jsonl(self, file_path: Path, data: dict[str, Any]) -> None:
        """Append to JSONL file with file locking."""
        lock_path = f"{file_path}.lock"
        lock = FileLock(lock_path, timeout=_LOCK_TIMEOUT_S)

        try:
            with lock, open(file_path, "a") as f:
                f.write(json.dumps(data, default=str) + "\n")
        except Timeout:
            logger.warning(
                "Metrics append skipped: could not lock %s within %ss",
                file_path.as_posix(),
                _LOCK_TIMEOUT_S,
            )

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
        session.last_activity = session.start_time
        session_dict = asdict(session)

        def update_sessions(data: dict[str, Any]) -> None:
            data[session_id] = session_dict

        self._update_json_atomic(self.active_sessions_file, update_sessions)

        # Set as the process's current session
        with self._session_lock:
            self._session_id = session_id

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
        session_id = session_id or self._current_or_new_session()

        def update_mcp_op(data: dict[str, Any]) -> None:
            if session_id in data:
                session = data[session_id]
                session["last_activity"] = datetime.now().isoformat()
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
        session_id = session_id or self._session_id
        if not session_id:
            return

        def update_grep_op(data: dict[str, Any]) -> None:
            if session_id in data:
                data[session_id]["last_activity"] = datetime.now().isoformat()
                data[session_id]["grep_operations"] += 1
                data[session_id]["total_operations"] += 1

        self._update_json_atomic(self.active_sessions_file, update_grep_op)

    def update_cache_stats(
        self, hits: int = 0, misses: int = 0, session_id: str | None = None
    ) -> None:
        """Update cache statistics for a session."""
        session_id = session_id or self._session_id
        if not session_id:
            return

        def update_cache(data: dict[str, Any]) -> None:
            if session_id in data:
                data[session_id]["last_activity"] = datetime.now().isoformat()
                data[session_id]["cache_hits"] += hits
                data[session_id]["cache_misses"] += misses

        self._update_json_atomic(self.active_sessions_file, update_cache)

    def end_session(self, session_id: str | None = None) -> dict[str, Any]:
        """End a metrics session and move to completed.

        Returns:
            Final session metrics
        """
        session_id = session_id or self._session_id
        if not session_id:
            return {}

        # First get the session to calculate stats
        active_sessions = self._read_json(self.active_sessions_file)
        if session_id not in active_sessions:
            return {}

        session = self._finalised(active_sessions[session_id], datetime.now().isoformat())

        # Move to completed sessions
        self._append_jsonl(self.completed_sessions_file, session)

        # Remove from active sessions atomically
        def remove_session(data: dict[str, Any]) -> None:
            if session_id in data:
                del data[session_id]

        self._update_json_atomic(self.active_sessions_file, remove_session)

        # Update aggregated statistics
        self._update_aggregated_stats(session)

        # Clear the process's current session
        with self._session_lock:
            if self._session_id == session_id:
                self._session_id = None

        return session

    def _current_or_new_session(self) -> str:
        """The process's session, opening an ``auto`` one if there is none yet.

        Checked and opened under a lock so that threads recording at once share
        one session.
        """
        with self._session_lock:
            if self._session_id is None:
                self.start_session(session_type="auto")
            assert self._session_id is not None  # nosec B101 - set by start_session
            return self._session_id

    @staticmethod
    def _finalised(active: dict[str, Any], end_time: str) -> dict[str, Any]:
        """A copy of an active session, ended at *end_time*, with its statistics."""
        session: dict[str, Any] = active.copy()
        session["end_time"] = end_time

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
        return session

    def prune_stale_sessions(self, now: datetime | None = None) -> int:
        """Close active sessions idle for longer than :data:`STALE_SESSION_AGE` (#914).

        Each is moved to the completed log, ended at its last activity (its
        start for a session written before ``last_activity`` existed), and
        counted in the aggregated statistics, as :meth:`end_session` would.
        Runs when a collector starts, so a store left behind by killed
        processes is cleaned by the next one. Writes nothing if nothing is stale.

        Returns:
            How many sessions were closed.
        """
        cutoff = (now or datetime.now()) - STALE_SESSION_AGE

        def last_seen(session: dict[str, Any]) -> str:
            return str(session.get("last_activity") or session.get("start_time") or "")

        def is_stale(session: dict[str, Any]) -> bool:
            try:
                return datetime.fromisoformat(last_seen(session)) < cutoff
            except ValueError:
                return False  # an unreadable timestamp is never pruned

        if not any(is_stale(s) for s in self._read_json(self.active_sessions_file).values()):
            return 0

        closed: list[dict[str, Any]] = []

        def take(data: dict[str, Any]) -> None:
            for sid in [sid for sid, s in data.items() if is_stale(s)]:
                session = data.pop(sid)
                closed.append(self._finalised(session, last_seen(session)))

        self._update_json_atomic(self.active_sessions_file, take)
        for session in closed:
            self._append_jsonl(self.completed_sessions_file, session)
            self._update_aggregated_stats(session)
        if closed:
            logger.info("Closed %d stale metrics session(s)", len(closed))
        return len(closed)

    def _update_aggregated_stats(self, session: dict[str, Any]) -> None:
        """Update aggregated statistics with completed session data."""

        def update_stats(stats: dict[str, Any]) -> None:
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
            stats["top_tools"] = sorted(
                stats["tool_usage"].items(), key=lambda x: x[1], reverse=True
            )[:10]

            stats["last_updated"] = datetime.now().isoformat()

        self._update_json_atomic(self.aggregated_stats_file, update_stats)

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
                    try:
                        session = json.loads(line)
                        session_date = datetime.fromisoformat(session["start_time"])
                        if session_date >= cutoff_date:
                            recent_sessions.append(session)
                    except (json.JSONDecodeError, KeyError):
                        continue

        return {
            "summary": stats,
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "recent_sessions": recent_sessions if include_sessions else None,
        }

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Clean up old completed sessions.

        Args:
            days: Remove sessions older than this many days

        Returns:
            Number of sessions removed
        """
        if not self.completed_sessions_file.exists():
            return 0

        cutoff_date = datetime.now() - timedelta(days=days)
        kept_sessions = []
        removed_count = 0

        # Use filelock for cleanup operation
        lock_path = f"{self.completed_sessions_file}.lock"
        lock = FileLock(lock_path, timeout=30)

        try:
            with lock:
                # Read all sessions
                with open(self.completed_sessions_file) as f:
                    for line in f:
                        try:
                            session = json.loads(line)
                            session_date = datetime.fromisoformat(session["start_time"])
                            if session_date >= cutoff_date:
                                kept_sessions.append(line.strip())
                            else:
                                removed_count += 1
                        except (json.JSONDecodeError, KeyError):
                            # Keep malformed lines to avoid data loss
                            kept_sessions.append(line.strip())

                # Rewrite file with kept sessions
                with open(self.completed_sessions_file, "w") as f:
                    for line in kept_sessions:
                        f.write(line + "\n")
        except Timeout:
            logger.warning("Could not acquire lock for cleanup operation")
            return 0

        return removed_count

    def export_metrics(self, output_path: Path) -> None:
        """Export all metrics to a JSON file.

        Args:
            output_path: Path for export file
        """
        report = self.get_aggregated_report(days=365, include_sessions=True)
        report["active_sessions"] = self.get_active_sessions()

        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)


# Singleton instance for global access
_collector: UnifiedMetricsCollector | None = None


def get_unified_collector(storage_dir: Path | None = None) -> UnifiedMetricsCollector:
    """Get or create the singleton unified metrics collector.

    Args:
        storage_dir: Optional custom storage directory

    Returns:
        The unified metrics collector instance
    """
    global _collector
    if _collector is None:
        _collector = UnifiedMetricsCollector(storage_dir)
    return _collector
