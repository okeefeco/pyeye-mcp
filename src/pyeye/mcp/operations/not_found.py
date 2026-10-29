"""The not-found response shared by ``inspect`` / ``outline`` / ``expand`` (#545).

When a handle does not resolve, all three operations return this one shape
instead of a fabricated answer::

    { "found":  False,
      "handle": str,          # the input handle, echoed
      "edge":   str,          # expand ONLY — the requested edge, echoed
      "reason": "unresolved",
      "detail": str }         # actionable next step: call resolve()

Every successful response from those operations carries ``found: True``, so a
consumer branches on the ``found`` value rather than on which keys are present.
``reason`` reuses ``resolve``'s vocabulary.  Built in one place so the three
operations cannot drift apart.
"""

from __future__ import annotations

from typing import Any

#: The ``reason`` for a handle that did not resolve — the same value
#: ``resolve`` uses for an unresolvable identifier.
NOT_FOUND_REASON = "unresolved"


def not_found(handle: str, *, edge: str | None = None) -> dict[str, Any]:
    """Build the not-found response for an unresolvable *handle*.

    Args:
        handle: The input handle that did not resolve (echoed back verbatim).
        edge: For ``expand`` only — the requested edge, echoed back.

    Returns:
        The not-found dict.  ``detail`` points at ``resolve`` on the handle's
        last dotted segment: an exact-path handle that misses usually has the
        right leaf name under the wrong module path.
    """
    leaf = handle.rsplit(".", 1)[-1]
    result: dict[str, Any] = {"found": False, "handle": handle}
    if edge is not None:
        result["edge"] = edge
    result["reason"] = NOT_FOUND_REASON
    result["detail"] = (
        f"Handle {handle!r} did not resolve to a symbol. "
        f"Call resolve({leaf!r}) to find its canonical handle."
    )
    return result
