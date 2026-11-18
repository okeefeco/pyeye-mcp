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
      "unresolved_imports": [target, ...],   # imports ONLY (#494) — ABSENT otherwise
      "unresolved_superclasses": [text, ...],  # superclasses ONLY (#624) — ABSENT otherwise
      "unresolved_importers": [file, ...],   # imported_by ONLY (#668) — ABSENT otherwise
      "unparseable_files": [file, ...] }     # edges.UNPARSEABLE_FILE_EDGES ONLY (#729) — ABSENT otherwise

**Not-supported edge** (the edge is recognised-but-unbuilt, a deferred
reference edge, an unknown name, or ``not_applicable``: an implemented edge that
doesn't apply to the source's kind, per ``edges.EDGE_APPLIES_TO``, #626)::

    { "found": True,
      "source": str,
      "edge": str,
      "unsupported": True,
      "reason": "deferred_reference_backend" | "not_yet_implemented"
                | "unknown_edge" | "not_applicable",
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
- ``unresolved_importers`` is present ONLY for ``imported_by`` (#668): the POSIX
  paths of files that import the target but have no module name, so no handle
  and no stub (``my-script.py``, ``tools-dir/x.py``). ``[]`` when every
  importer has one. They are real dependents: count them for fan-in.
- ``unparseable_files`` is present ONLY for the edges in
  ``edges.UNPARSEABLE_FILE_EDGES`` (#729, #874): the POSIX paths of files in
  scope that the server's interpreter couldn't parse (e.g. newer syntax), so an
  adjacent defined there is unknown, not absent.  ``[]`` when every file parsed.
- NO ``cursor`` field in this slice — an absent cursor means "complete".
- ``expand`` NEVER raises: an unresolvable source handle yields the not-found
  shape, NOT a supported ``stubs: []`` (which would claim "measured, none
  found" for a handle pyeye could not resolve).  The source is resolved BEFORE the
  edge registry is consulted, so the unsupported branch is never returned for
  a ghost handle either (#545 — reverses the earlier "callers rule ghosts out
  upstream" design, whose upstream guard, ``inspect``, itself fabricated).
- ``reason`` IS the ``edge_status`` value — the status string doubles as the
  unsupported reason (single source of truth in :mod:`edges`) — or
  ``not_applicable`` when :func:`edges.edge_applies` says the edge doesn't apply
  to the source's kind (#626).

``expand`` is ``async`` to match the server's ``resolve`` / ``inspect`` pattern
(and to leave room for future pagination), even though the body is currently
synchronous.
"""

from __future__ import annotations

from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from pyeye.mcp import meta
from pyeye.mcp.operations.completeness import (
    DEFAULT_MAX_STUBS,
    MAX_STUBS,
    cap_items,
    check_cap,
)
from pyeye.mcp.operations.edges import (
    EDGE_CEILINGS,
    EDGE_RESOLVERS,
    STATUS_DEFERRED_REFERENCE_BACKEND,
    STATUS_IMPLEMENTED,
    STATUS_NOT_APPLICABLE,
    STATUS_NOT_YET_IMPLEMENTED,
    STATUS_UNPARSEABLE,
    UnparseableSource,
    edge_applies,
    edge_kind,
    edge_status,
    not_applicable_detail,
)
from pyeye.mcp.operations.not_found import not_found
from pyeye.mcp.operations.stubs import build_stub
from pyeye.resolver import NotFound, resolve_handle

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


async def expand(
    handle: str, edge: str, analyzer: JediAnalyzer, max_stubs: int | None = DEFAULT_MAX_STUBS
) -> dict[str, Any]:
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
        max_stubs: Most stubs to return (#435), default 200; ``None`` for all.
            When the edge has more, the first *max_stubs* are kept and the
            result carries ``truncated: true``, ``truncation_reasons:
            ["max_stubs"]`` and ``total``.

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
        kind but found no adjacents → supported ``stubs: []``).  It is also
        returned, with ``reason: "unparseable"`` (#703), when the source's own
        file can't be parsed by the server's interpreter.  Never raises.
    """
    # ------------------------------------------------------------------
    # Resolve the source handle first.  A ghost handle is reported as not-found
    # — never as ``stubs: []`` (the #332 measured-zero lie) and never as an
    # unsupported result implying the handle was found (#545).
    # ------------------------------------------------------------------
    check_cap(max_stubs, "max_stubs")  # a bad cap is a caller error, before any work
    resolved = resolve_handle(handle, analyzer)  # the one resolver (#623)
    if isinstance(resolved, NotFound):
        return not_found(handle, edge=edge)

    return await expand_resolved(
        resolved.anchor, resolved.handle, edge, analyzer, max_stubs=max_stubs
    )


async def expand_resolved(
    jedi_name: Any,
    source: str,
    edge: str,
    analyzer: JediAnalyzer,
    max_stubs: int | None = None,
) -> dict[str, Any]:
    """Walk one *edge* from an ALREADY-resolved source — expand minus resolution.

    This is the whole of :func:`expand` after the source resolved (through
    :func:`pyeye.resolver.resolve_handle`): the edge-status check, the
    resolver's wrong-kind (``None``) signal, and the stub build.  ``trace``
    calls it for every hop (#621) so that it walks exactly what ``expand``
    would answer found + supported for, with the same unsupported
    ``reason``/``detail`` — one copy of the expandability logic, not two.

    Args:
        jedi_name: The resolved anchor (Jedi ``Name`` or sentinel) for the source.
        source: The source's canonical handle, as the resolver reported it.
        edge: The traversal edge to walk.
        analyzer: Configured ``JediAnalyzer`` for the project.

    Returns:
        The supported or unsupported branch of :func:`expand` (always
        ``found: True``).
    """
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
    # Wrong kind — the edge exists but not for this source's kind, per the ONE
    # applicability table (#626).  Unsupported, never a measured ``stubs: []``:
    # "imports doesn't exist for a class" is not "this class imports nothing".
    # Distinct from the not-found path above and from a measured-empty result.
    # ------------------------------------------------------------------
    if not edge_applies(edge, jedi_name):
        return {
            "found": True,
            "source": source,
            "edge": edge,
            "unsupported": True,
            "reason": STATUS_NOT_APPLICABLE,
            "detail": not_applicable_detail(edge, edge_kind(jedi_name)),
            # Kept from the pre-#626 wrong-kind branch (no field is removed in 2.x).
            "report_issues": meta.issues_url(),
        }

    # ------------------------------------------------------------------
    # Run the edge resolver and build a stub per carried (handle, Name) pair.
    # The resolver carries the Jedi Name so builtin/stdlib callee stubs build
    # without re-resolution (the load-bearing reason EdgeResult carries Names).
    # A resolver may be sync or async; await any awaitable result.
    # ------------------------------------------------------------------
    try:
        raw = EDGE_RESOLVERS[edge](jedi_name, analyzer)
        edge_result = await raw if isawaitable(raw) else raw
    except UnparseableSource as exc:
        # #703: the source's own file doesn't parse under the server's Python, so
        # the edge wasn't measured.  Unsupported, never a measured ``stubs: []``.
        return {
            "found": True,
            "source": source,
            "edge": edge,
            "unsupported": True,
            "reason": STATUS_UNPARSEABLE,
            "detail": exc.detail(),
            "report_issues": meta.issues_url(),
        }

    # #435 slice B: cap before building stubs, so a 900-wide edge costs 200
    # stub builds.  ``trace`` passes no cap: it has its own node budget.
    kept, truncation = cap_items(edge_result.adjacents, max_stubs, MAX_STUBS, "max_stubs")
    extras = edge_result.stub_extras or {}
    stubs = [
        {
            **build_stub(name, str(adj_handle), analyzer),
            **extras.get(str(adj_handle), {}),
        }
        for adj_handle, name in kept
    ]

    result: dict[str, Any] = {"found": True, "source": source, "edge": edge, "stubs": stubs}
    result.update(truncation)
    # #417: the scope the list is complete over, as data (absent for an exact edge).
    if edge in EDGE_CEILINGS:
        result["ceiling"] = EDGE_CEILINGS[edge]
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
    # unresolved_superclasses (#624): superclasses ONLY — the declared bases
    # whose goto named no single class, by source text ([] when all resolved).
    if edge_result.unresolved_superclasses is not None:
        result["unresolved_superclasses"] = edge_result.unresolved_superclasses
    # unresolved_importers (#668): the same mechanic for imported_by — an
    # importing file with no module name has no handle, so it is listed here
    # ([] when every importer has one) instead of silently missing.
    if edge_result.unresolved_importers is not None:
        result["unresolved_importers"] = edge_result.unresolved_importers
    # unparseable_files (#729): the edges in UNPARSEABLE_FILE_EDGES list the
    # files the server couldn't parse ([] when all parsed), so an adjacent
    # defined there is unknown, not absent.  Absent on every other edge.
    if edge_result.unparseable_files is not None:
        result["unparseable_files"] = edge_result.unparseable_files
    # subclasses is direct-only (#422); its (class-only, #626) result carries a
    # static pointer to the trace route for the full closure.
    if edge == "subclasses":
        result["transitive_hint"] = SUBCLASSES_TRANSITIVE_HINT

    return result
