"""expand(handle, edge) — single-hop traversal returning a discriminated union.

``expand`` is the user-facing primitive that walks ONE edge from a canonical
source handle and returns the adjacent symbols as lightweight stubs.  It is the
composition layer over the Phase-2/3 edge resolvers (``members``, ``callees``)
and the Phase-1 stub builder — it adds NO new resolution logic of its own.

Discriminated union (spec §4.2)
-------------------------------
The response is one of two mutually-exclusive shapes, distinguished by the
presence of ``unsupported``:

**Supported edge** (the edge has a working resolver)::

    { "source": str,                # canonical source handle
      "edge": str,
      "stubs": [Stub, ...],         # [] means MEASURED, none found
      "unresolved_call_sites": int  # callees ONLY — ABSENT for members }

**Not-supported edge** (the edge is recognised-but-unbuilt, a deferred
reference edge, or an unknown name)::

    { "source": str,
      "edge": str,
      "unsupported": True,
      "reason": "deferred_reference_backend" | "not_yet_implemented"
                | "unknown_edge",
      "detail": str }

Design invariants
-----------------
- The two branches are MUTUALLY EXCLUSIVE: a supported result NEVER carries
  ``unsupported`` / ``reason``; an unsupported result NEVER carries ``stubs``.
- ``stubs: []`` is a SUPPORTED result meaning "measured, none found" — it is NOT
  the unsupported branch.  Conflating "measured empty" with "unsupported" is the
  #332 failure these shapes guard against.
- ``unresolved_call_sites`` is present ONLY for ``callees`` (the resolver returns
  an ``int``); for ``members`` the resolver returns ``None`` and the key is
  omitted.
- NO ``cursor`` field in this slice — an absent cursor means "complete".
- ``expand`` NEVER raises: an unresolvable source handle yields a graceful
  supported empty result (consistent with how ``inspect`` returns a minimal node
  rather than raising).  Source-not-found is intentionally NOT surfaced as a
  distinct discriminator in this slice; callers are expected to
  ``resolve``/``inspect`` before calling ``expand``, so a ghost handle is
  ruled out upstream — this is deliberate, not an oversight.
- ``reason`` IS the ``edge_status`` value — the status string doubles as the
  unsupported reason (single source of truth in :mod:`edges`).

``expand`` is ``async`` to match the server's ``resolve`` / ``inspect`` pattern
(and to leave room for future pagination), even though the body is currently
synchronous.
"""

from __future__ import annotations

from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from pyeye.mcp.operations.edges import (
    EDGE_RESOLVERS,
    STATUS_DEFERRED_REFERENCE_BACKEND,
    STATUS_IMPLEMENTED,
    STATUS_NOT_YET_IMPLEMENTED,
    edge_status,
)
from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle
from pyeye.mcp.operations.stubs import build_stub

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


# ---------------------------------------------------------------------------
# Unsupported-reason detail messages
# ---------------------------------------------------------------------------


def _unsupported_detail(edge: str, reason: str) -> str:
    """Return a human-readable ``detail`` string for an unsupported *reason*.

    Args:
        edge: The requested edge name (interpolated into the message).
        reason: The :func:`edge_status` value classifying why the edge is
            unsupported.

    Returns:
        A clear, reason-specific sentence for the ``detail`` field.
    """
    if reason == STATUS_NOT_YET_IMPLEMENTED:
        return f"Edge '{edge}' is reliable and planned but not implemented in this slice."
    if reason == STATUS_DEFERRED_REFERENCE_BACKEND:
        return (
            f"Edge '{edge}' is an inbound/reference edge requiring the Pyright "
            f"reference backend (#333); deferred."
        )
    # STATUS_UNKNOWN_EDGE (and any unforeseen status) → generic unknown message.
    return f"Unknown edge '{edge}'."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def expand(handle: str, edge: str, analyzer: JediAnalyzer) -> dict[str, Any]:
    """Walk one *edge* from *handle*, returning a discriminated-union result.

    Consults the edge registry (:func:`edge_status`); for unsupported edges it
    returns the unsupported branch immediately (no handle resolution needed).
    For implemented edges it resolves the source handle to a Jedi ``Name``, runs
    the edge's resolver, and builds a stub per adjacent from the ``Name`` the
    resolver carried (avoiding a wasteful — and, for builtins, unreliable —
    re-resolution).

    Args:
        handle: Canonical Python dotted-name string (from resolve/resolve_at)
            for the source symbol.
        edge: The traversal edge to walk (e.g. ``"members"``, ``"callees"``).
        analyzer: Configured ``JediAnalyzer`` for the project.

    Returns:
        Either the supported branch (``source``/``edge``/``stubs`` and, for
        ``callees`` only, ``unresolved_call_sites``) or the unsupported branch
        (``unsupported``/``reason``/``detail``).  Never raises.
    """
    status = edge_status(edge)

    # ------------------------------------------------------------------
    # Unsupported edge — short-circuit with the mapped reason.  No handle
    # resolution is needed (the edge is unsupported regardless of the source).
    # ------------------------------------------------------------------
    if status != STATUS_IMPLEMENTED:
        return {
            "source": handle,
            "edge": edge,
            "unsupported": True,
            "reason": status,
            "detail": _unsupported_detail(edge, status),
        }

    # ------------------------------------------------------------------
    # Implemented edge — resolve the source handle to a Jedi Name.
    # ------------------------------------------------------------------
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)

    if jedi_name is None:
        # Source handle unresolvable → graceful supported-empty result, mirroring
        # how inspect returns a minimal node (never raises) for the same case.
        result: dict[str, Any] = {"source": handle, "edge": edge, "stubs": []}
        if edge == "callees":
            # Mirror resolve_callees, which always sets unresolved_call_sites for the
            # callees edge; no resolver runs on this not-found path so we synthesize count=0.
            result["unresolved_call_sites"] = 0
        return result

    # Prefer the canonical resolved full_name; fall back to the input handle.
    source = jedi_name.full_name if getattr(jedi_name, "full_name", None) else handle

    # ------------------------------------------------------------------
    # Run the edge resolver and build a stub per carried (handle, Name) pair.
    # The resolver carries the Jedi Name so builtin/stdlib callee stubs build
    # without re-resolution (the load-bearing reason EdgeResult carries Names).
    # ------------------------------------------------------------------
    # A resolver may be sync (members/callees → EdgeResult) or async
    # (imported_by → Awaitable[EdgeResult | None]); await any awaitable result.
    # A ``None`` result is the wrong-kind signal — Phase 4 will surface that as a
    # distinct discriminator; for now a missing edge_result yields the graceful
    # supported-empty shape (no stubs), consistent with the source-not-found path.
    raw = EDGE_RESOLVERS[edge](jedi_name, analyzer)
    edge_result = await raw if isawaitable(raw) else raw

    if edge_result is None:
        return {"source": source, "edge": edge, "stubs": []}

    stubs = [
        build_stub(name, str(adj_handle), analyzer) for adj_handle, name in edge_result.adjacents
    ]

    result = {"source": source, "edge": edge, "stubs": stubs}
    # unresolved_call_sites: int for callees → key present; None for members →
    # key absent.  This automatically yields the callees-only field.
    if edge_result.unresolved_call_sites is not None:
        result["unresolved_call_sites"] = edge_result.unresolved_call_sites

    return result
