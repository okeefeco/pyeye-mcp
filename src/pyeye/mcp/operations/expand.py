"""expand(handle, edge) — single-hop traversal returning a discriminated union.

``expand`` is the user-facing primitive that walks ONE edge from a canonical
source handle and returns the adjacent symbols as lightweight stubs.  It is the
composition layer over the Phase-2/3 edge resolvers (``members``, ``callees``,
``imported_by``)
and the Phase-1 stub builder — it adds NO new resolution logic of its own.

Discriminated union (spec §4.2)
-------------------------------
The response is one of three mutually-exclusive shapes.  ``found`` is always
present: ``False`` for the not-found shape, ``True`` otherwise; a found result
is then supported or unsupported, distinguished by the presence of
``unsupported``:

**Source not found** (the handle does not resolve — whatever the edge, #545)::

    { "found": False, "handle": str, "edge": str,
      "reason": "unresolved", "detail": str }   # shared shape — see not_found

**Supported edge** (the edge has a working resolver)::

    { "found": True,
      "source": str,                # canonical source handle
      "edge": str,
      "stubs": [Stub, ...],         # [] means MEASURED, none found
      "unresolved_call_sites": int, # callees ONLY — ABSENT otherwise
      "unresolved_imports": [target, ...] }  # imports ONLY (#494) — ABSENT otherwise

**Not-supported edge** (the edge is recognised-but-unbuilt, a deferred
reference edge, or an unknown name)::

    { "found": True,
      "source": str,
      "edge": str,
      "unsupported": True,
      "reason": "deferred_reference_backend" | "not_yet_implemented"
                | "unknown_edge",
      "detail": str,
      "report_issues": url }   # #458 — where to report this limitation

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
- ``unresolved_imports`` is present ONLY for ``imports`` (#494): the resolver
  returns a list (``[]`` when every import resolved, the unresolvable targets
  otherwise); for every other edge it returns ``None`` and the key is omitted.
- NO ``cursor`` field in this slice — an absent cursor means "complete".
- ``expand`` NEVER raises: an unresolvable source handle yields the not-found
  shape, NOT a supported ``stubs: []`` (which would claim "measured, none
  found" for a symbol that does not exist).  The source is resolved BEFORE the
  edge registry is consulted, so the unsupported branch is never returned for
  a ghost handle either (#545 — reverses the earlier "callers rule ghosts out
  upstream" design, whose upstream guard, ``inspect``, itself fabricated).
- ``reason`` IS the ``edge_status`` value — the status string doubles as the
  unsupported reason (single source of truth in :mod:`edges`).

``expand`` is ``async`` to match the server's ``resolve`` / ``inspect`` pattern
(and to leave room for future pagination), even though the body is currently
synchronous.
"""

from __future__ import annotations

from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from pyeye.mcp import meta
from pyeye.mcp.operations.edges import (
    EDGE_RESOLVERS,
    STATUS_DEFERRED_REFERENCE_BACKEND,
    STATUS_IMPLEMENTED,
    STATUS_NOT_YET_IMPLEMENTED,
    edge_status,
)
from pyeye.mcp.operations.inspect import _resolve_handle_to_jedi_name
from pyeye.mcp.operations.not_found import not_found
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

    Resolves the source handle to a Jedi ``Name`` FIRST — an unresolvable handle
    returns the shared not-found shape whatever the edge (#545), so ``found:
    True`` on any later branch is always a claim about a handle that really was
    resolved.  Then consults the edge registry (:func:`edge_status`): an
    unsupported edge returns the unsupported branch; an implemented edge runs its
    resolver and builds a stub per adjacent from the ``Name`` the resolver
    carried (avoiding a wasteful — and, for builtins, unreliable —
    re-resolution).

    Args:
        handle: Canonical Python dotted-name string (from resolve/resolve_at)
            for the source symbol.
        edge: The traversal edge to walk
            (e.g. ``"members"``, ``"callees"``, ``"imported_by"``).
        analyzer: Configured ``JediAnalyzer`` for the project.

    Returns:
        The not-found shape (``found: False``) for an unresolvable source, else
        — with ``found: True`` — either the supported branch
        (``source``/``edge``/``stubs`` and, for ``callees`` only,
        ``unresolved_call_sites``) or the unsupported branch
        (``unsupported``/``reason``/``detail``).  The unsupported branch is
        also returned for an *implemented* edge when its resolver returns
        ``None`` — the wrong-kind signal meaning the edge does not apply to
        this handle's kind (e.g. ``imported_by`` on a non-module).  That case
        is distinct from a measured-empty ``EdgeResult`` (resolver matched the
        kind but found no adjacents → supported ``stubs: []``).  Never raises.
    """
    # ------------------------------------------------------------------
    # Resolve the source handle first.  A ghost handle is reported as not-found
    # — never as ``stubs: []`` (the #332 measured-zero lie) and never as an
    # unsupported result implying the handle was found (#545).
    # ------------------------------------------------------------------
    jedi_name = await _resolve_handle_to_jedi_name(handle, analyzer)

    if jedi_name is None:
        return not_found(handle, edge=edge)

    # Prefer the canonical resolved full_name; fall back to the input handle.
    source = jedi_name.full_name if getattr(jedi_name, "full_name", None) else handle

    # ------------------------------------------------------------------
    # Unsupported edge — the mapped reason, independent of the source's kind.
    # ------------------------------------------------------------------
    status = edge_status(edge)
    if status != STATUS_IMPLEMENTED:
        return {
            "found": True,
            "source": source,
            "edge": edge,
            "unsupported": True,
            "reason": status,
            "detail": _unsupported_detail(edge, status),
            # #458: this is a limitation moment — point at where to report it.
            "report_issues": meta.issues_url(),
        }

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
    # found: False) and from a measured-empty EdgeResult (the resolver matched
    # the kind but found no adjacents → supported ``stubs: []``).
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
            "found": True,
            "source": source,
            "edge": edge,
            "unsupported": True,
            "reason": STATUS_NOT_YET_IMPLEMENTED,
            "detail": (
                f"Edge '{edge}' does not apply to a {kind} handle; it is "
                f"supported for modules only in this slice."
            ),
            # #458: this is a limitation moment — point at where to report it.
            "report_issues": meta.issues_url(),
        }

    stubs = [
        build_stub(name, str(adj_handle), analyzer) for adj_handle, name in edge_result.adjacents
    ]

    result: dict[str, Any] = {"found": True, "source": source, "edge": edge, "stubs": stubs}
    # unresolved_call_sites: int for callees → key present; None for members →
    # key absent.  This automatically yields the callees-only field.
    if edge_result.unresolved_call_sites is not None:
        result["unresolved_call_sites"] = edge_result.unresolved_call_sites
    # unresolved_imports (#494): list for imports → key present ([] when every
    # import resolved); None for every other edge → key absent. Same imports-only
    # mechanic as unresolved_call_sites is for callees — a statically-present
    # import that goto missed is surfaced, never silently dropped.
    if edge_result.unresolved_imports is not None:
        result["unresolved_imports"] = edge_result.unresolved_imports
    # subclasses is direct-only (#422); a CLASS result carries a static pointer to
    # the trace route for the full closure.  Class-gated: a non-class subclasses
    # result is a measured-empty [], where the "use trace" hint would be noise.
    if edge == "subclasses" and _normalise_kind(getattr(jedi_name, "type", None)) == "class":
        result["transitive_hint"] = SUBCLASSES_TRANSITIVE_HINT

    return result
