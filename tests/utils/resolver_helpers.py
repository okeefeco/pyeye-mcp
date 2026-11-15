"""Test helper: the Jedi anchor for a handle, via the one canonical resolver (#623)."""

from __future__ import annotations

from typing import Any

from pyeye.handle import Handle
from pyeye.resolver import Resolved, resolve_handle


def anchor_for(handle: str, analyzer: Any) -> Any | None:
    """Return ``resolve_handle(handle).anchor``, or ``None`` when it doesn't resolve."""
    resolved = resolve_handle(handle, analyzer)
    return resolved.anchor if isinstance(resolved, Resolved) else None


def canonical_handle(identifier: str, analyzer: Any) -> Handle | None:
    """The canonical handle for *identifier*, or ``None`` (the former ``resolve_canonical``)."""
    resolved = resolve_handle(identifier, analyzer)
    if not isinstance(resolved, Resolved):
        return None
    try:
        return Handle(resolved.handle)
    except ValueError:
        return None
