"""expand(handle, edge) — single-hop traversal returning a discriminated union.

``expand`` is the user-facing primitive that walks ONE edge from a canonical
source handle and returns the adjacent symbols as lightweight stubs.  It is the
composition layer over the Phase-2/3 edge resolvers (``members``, ``callees``,
``imported_by``)
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
from pyeye.mcp.operations.resolve import _normalise_kind
from pyeye.mcp.operations.stubs import build_stub

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


#: Static discoverability pointer attached to a CLASS ``subclasses`` result
#: (#422).  ``expand(subclasses)`` returns DIRECT children only (one hop); this
#: constant tells the agent where the full transitive closure lives.  It is
#: deliberately a CONSTANT — it MUST NOT encode a computed descendant count, as
#: counting deeper subclasses is the expensive reverse scan gated on #333/#397.
SUBCLASSES_TRANSITIVE_HINT = (
    "expand returns DIRECT subclasses only; for the full transitive closure use "
    "trace(follow=['subclasses'], max_depth=k, max_nodes=N)"
)


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
        edge: The traversal edge to walk
            (e.g. ``"members"``, ``"callees"``, ``"imported_by"``).
        analyzer: Configured ``JediAnalyzer`` for the project.

    Returns:
        Either the supported branch (``source``/``edge``/``stubs`` and, for
        ``callees`` only, ``unresolved_call_sites``) or the unsupported branch
        (``unsupported``/``reason``/``detail``).  The unsupported branch is
        also returned for an *implemented* edge when its resolver returns
        ``None`` — the wrong-kind signal meaning the edge does not apply to
        this handle's kind (e.g. ``imported_by`` on a non-module).  That case
        is distinct from both a source-not-found unresolvable handle (which
        yields a graceful supported empty result) and a measured-empty
        ``EdgeResult`` (resolver matched the kind but found no adjacents →
        supported ``stubs: []``).  Never raises.
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
    # A ``None`` result is the WRONG-KIND signal: the edge genuinely does not
    # apply to this handle's kind (e.g. ``imported_by`` on a class — a symbol
    # CAN be imported, so claiming ``stubs: []`` would be the #332 measured-zero
    # lie).  Surface it as the UNSUPPORTED branch with a KIND-SPECIFIC detail
    # (synthesized inline — the generic _unsupported_detail can't name the kind).
    # This is DISTINCT from the source-not-found path above (jedi_name is None →
    # graceful supported-empty) and from a measured-empty EdgeResult (the
    # resolver matched the kind but found no adjacents → supported ``stubs: []``).
    raw = EDGE_RESOLVERS[edge](jedi_name, analyzer)
    edge_result = await raw if isawaitable(raw) else raw

    if edge_result is None:
        kind = _normalise_kind(getattr(jedi_name, "type", None))
        # NOTE: The detail message below uses affirmative "supported for modules
        # only" wording. Both ``imported_by`` and ``imports`` are module-only
        # edges whose resolvers return ``None`` for non-module handles; this
        # branch handles them generically.  If a future edge adds a
        # ``None``-returning resolver with a DIFFERENT kind restriction, this
        # branch must be revisited to generate an edge-specific detail rather
        # than the hardcoded module-only hint.
        return {
            "source": source,
            "edge": edge,
            "unsupported": True,
            "reason": STATUS_NOT_YET_IMPLEMENTED,
            "detail": (
                f"Edge '{edge}' does not apply to a {kind} handle; it is "
                f"supported for modules only in this slice."
            ),
        }

    stubs = [
        build_stub(name, str(adj_handle), analyzer) for adj_handle, name in edge_result.adjacents
    ]

    result = {"source": source, "edge": edge, "stubs": stubs}
    # unresolved_call_sites: int for callees → key present; None for members →
    # key absent.  This automatically yields the callees-only field.
    if edge_result.unresolved_call_sites is not None:
        result["unresolved_call_sites"] = edge_result.unresolved_call_sites
    # subclasses is direct-only (#422); a CLASS result carries a static pointer to
    # the trace route for the full closure.  Class-gated: a non-class subclasses
    # result is a measured-empty [], where the "use trace" hint would be noise.
    if edge == "subclasses" and _normalise_kind(getattr(jedi_name, "type", None)) == "class":
        result["transitive_hint"] = SUBCLASSES_TRANSITIVE_HINT

    return result
