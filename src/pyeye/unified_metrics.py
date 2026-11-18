"""Deprecated: the unified metrics store was removed (#943).

The server no longer records MCP sessions or writes ``~/.pyeye/metrics/``.
Nothing shipped read that store, and recording it cost every MCP call a locked
rewrite of a file. :func:`get_unified_collector` stays for 2.x so existing
callers don't break: it warns and returns a collector that records nothing.
It is deleted under #749.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

_MESSAGE = (
    "pyeye.unified_metrics is deprecated and records nothing: the unified metrics "
    "store was removed (#943). It will be deleted in a future major release."
)


class _NoOpCollector:
    """Accepts the old collector's calls and does nothing. Writes no files."""

    def start_session(self, session_id: str | None = None, *_args: Any, **_kwargs: Any) -> str:
        return session_id or "deprecated"

    def record_mcp_operation(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def record_grep_operation(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def update_cache_stats(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def end_session(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    def prune_stale_sessions(self, *_args: Any, **_kwargs: Any) -> int:
        return 0

    def get_active_sessions(self) -> dict[str, Any]:
        return {}

    def get_session_tree(self) -> dict[str, Any]:
        return {}

    def get_aggregated_report(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    def cleanup_old_sessions(self, *_args: Any, **_kwargs: Any) -> int:
        return 0


def get_unified_collector(storage_dir: Path | None = None) -> Any:  # noqa: ARG001
    """Deprecated (#943): warn, and return a collector that records nothing."""
    warnings.warn(_MESSAGE, DeprecationWarning, stacklevel=2)
    return _NoOpCollector()
