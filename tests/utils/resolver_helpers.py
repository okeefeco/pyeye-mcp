"""Test helper: the Jedi anchor for a handle, via the one canonical resolver (#623)."""

from __future__ import annotations

from typing import Any

from pyeye.resolver import Resolved, resolve_handle


def anchor_for(handle: str, analyzer: Any) -> Any | None:
    """Return ``resolve_handle(handle).anchor``, or ``None`` when it doesn't resolve."""
    resolved = resolve_handle(handle, analyzer)
    return resolved.anchor if isinstance(resolved, Resolved) else None
