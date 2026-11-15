"""trace(start, follow) — bounded multi-hop BFS returning a Subgraph.

``trace`` is the progressive-disclosure traversal primitive that composes the
single-hop edge registry (``members``, ``callees``, ``imported_by``) across
multiple hops.  It is a pure *consumer* of the edge registry in
:mod:`pyeye.mcp.operations.edges` — it adds traversal/bookkeeping (dedup, cycle
handling, caps) but NO new edge-resolution logic, and it MUST NOT modify the
registry.

Return shape — ``Subgraph`` (spec §``trace``)::

    { "nodes": { handle: Stub, ... },               # deduped by handle
      "edges": [ {"from": h, "to": h, "kind": edge}, ... ],  # NOT deduped across kinds
      "truncated": bool,                             # caps hit before natural termination
      "truncation_reasons": ["max_depth"? , "max_nodes"?],  # WHICH cap(s) fired
      "unsupported_edges": [ {"edge", "reason", "detail"}, ... ],
      "unresolved_roots": [ handle, ... ],  # #488 — always present; [] when every root resolved
      "unresolved_nodes": [ handle, ... ],  # #621 — always present; interior nodes not walked
      "unresolved_call_sites": { handle: count, ... },  # #488 — present iff callees walked
      "unresolved_imports": { handle: [target, ...], ... },  # #494 — present iff imports walked
      "unresolved_importers": { handle: [file, ...], ... },  # #668 — present iff imported_by walked
      "unparseable_files": { handle: [file, ...], ... },  # #729 — present iff subclasses/imported_by walked
      "report_issues": url }   # #458 — present ONLY when unsupported_edges is non-empty

``truncation_reasons`` (#352) distinguishes the two causes so the agent knows
which cap to raise: ``"max_depth"`` (a reachable node was cut at the depth
frontier) and/or ``"max_nodes"`` (the node budget filled).  Both can fire in one
walk.  ``truncated`` is derived — true iff ``truncation_reasons`` is non-empty —
and kept for back-compat.

``unsupported_edges`` is an additive honesty field (beyond the spec's bare
``Subgraph`` triple): any edge in ``follow`` that is not an implemented edge
(deferred reference-backend, not-yet-implemented, or unknown) is listed here
rather than silently dropped from the walk — silently omitting it would falsely
read as "no such neighbours" (the #332 absence-vs-zero trap).  It is ``[]`` when
every requested edge is supported.

``unresolved_roots`` (#488) is the same honesty guard applied to *root
resolution*: a ``start`` handle that Jedi cannot resolve to a ``Name`` (a
cold-start miss, #419, or a genuinely bad handle) is listed here instead of
being silently skipped.  Without it an all-roots-miss returns a clean
``nodes: {}`` that an agent reads as "this root calls/contains nothing" — a
false-confident negative.  Like ``unsupported_edges`` it is **always present**:
root resolution is always measured, so it is ``[]`` when every root resolved and
the failed handles otherwise.  Absence is never a meaningful "all resolved"
signal — it would be a broken response (the absence-vs-zero invariant reserves
absence for "not measured").  So ``nodes: {}`` with ``unresolved_roots: []`` is
a genuine zero, and with a non-empty list it tells the agent to retry or fall
back to Read/LSP.

``unresolved_imports`` (#494) is the exact same guard for the ``imports`` edge:
a statically-present ``from X import Y`` that ``goto`` could not resolve is
recorded (by its intended dotted target) per source node instead of vanishing —
present only when ``imports`` was traced, ``{}`` when every traced import
resolved.  Without it a dependency closure built with ``trace(follow=["imports"])``
would silently omit edges it could not resolve.

``unresolved_importers`` (#668) does the same for ``imported_by``: an importing
file with no module name has no handle, so it can't be a node; it is listed per
target node instead of being dropped.

``unparseable_files`` (#729) does the same for the reverse scans ``subclasses``
and ``imported_by``: a file in scope that the server's interpreter couldn't parse
may hold a subclass or importer, so it is listed per node (the union across both
edges), present only when one of them was traced.

``unresolved_call_sites`` (#488) carries the same honesty *one hop in*: a
``callees`` walk that can't resolve a call target (dynamic/un-inferable site, or
a flaky goto miss, #419) leaves that node's outbound calls incomplete.
``expand(callees)`` already reports the per-node count; ``trace`` surfaces it as
a ``{source_handle: count}`` map so a populated-but-lossy subgraph never reads as
complete.  Unlike ``unresolved_roots`` it is **present only when ``callees`` was
actually traced** — call sites are otherwise not measured, so an absent key is
the honest "not measured" (absence-vs-zero), ``{}`` means callees were traced and
every site resolved, and only nodes with a non-zero count appear.  It does NOT
cover flaky misses on the *other* edges (``members``/``imported_by``/
``subclasses`` resolve largely via deterministic AST); whole-walk determinism is
the #419 / #333 backend concern, not something this field claims to solve.

Every hop is ``expand`` (#621).  A node is walked along an edge only when
``expand(node, edge)`` would answer found + supported for it — trace calls
:func:`~pyeye.mcp.operations.expand.expand_resolved`, the body of ``expand``
after resolution, so there is ONE copy of the expandability logic:

- an interior node is resolved by handle (as ``expand`` resolves its source)
  before it is walked; one that does not resolve is never walked and is listed
  in the always-present ``unresolved_nodes`` (walking the Jedi ``Name`` the edge
  carried is how trace used to expand handles every other primitive rejects);
- an edge that does not apply to a node's kind is reported in
  ``unsupported_edges`` with ``expand``'s reason and kind-specific detail —
  never walked as a measured-empty hop;
- ``unresolved_call_sites`` / ``unresolved_imports`` / ``unresolved_importers``
  are present iff their edge was actually walked on at least one node;
- each hop is ALL-OR-NOTHING (reserve before expand, the #358 outline rule): if
  any new adjacent would be cut by ``max_depth`` or ``max_nodes``, the hop adds
  and records nothing and sets the truncation reason, so a recorded hop is
  always complete.

Termination: each handle is visited (expanded) at most once; edges *to* an
already-visited handle are still recorded so cycles stay visible to the agent,
but do not trigger re-expansion.  This guarantees termination on cyclic graphs.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from pyeye.mcp import meta
from pyeye.mcp.operations.completeness import MAX_DEPTH, MAX_NODES
from pyeye.mcp.operations.edges import EDGE_CEILINGS, STATUS_IMPLEMENTED, edge_status
from pyeye.mcp.operations.expand import _unsupported_detail, expand_resolved
from pyeye.mcp.operations.stubs import build_stub
from pyeye.resolver import NotFound, resolve_item

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


def _stops_at(handle: str, scope: str, stop_when: dict[str, Any] | None) -> bool:
    """Return True if an adjacent is a traversal boundary under *stop_when*.

    Honoured ``StopPredicate`` keys (spec §``trace``):

    - ``exclude_external``: stop at external (stdlib / site-packages) nodes —
      keeps a trace inside the project and frees the ``max_nodes`` budget for
      project nodes (#351).
    - ``module_pattern``: stop when the pattern appears in the handle (substring).
    - ``exclude_tests``: stop at test modules — any dotted segment equal to
      ``tests`` or beginning ``test_``.

    A missing/empty predicate never stops.  ``module_pattern`` / ``exclude_tests``
    match on the handle string; ``exclude_external`` matches on *scope* (which is
    NOT derivable from the handle), so the caller passes the adjacent's resolved
    scope.

    Args:
        handle: Canonical handle of a candidate adjacent.
        scope: The adjacent's resolved scope (``"project"`` / ``"external"``).
        stop_when: The predicate dict, or ``None``.

    Returns:
        ``True`` if traversal should treat the adjacent as a boundary (prune it).
    """
    if not stop_when:
        return False
    if stop_when.get("exclude_external") and scope == "external":
        return True
    pattern = stop_when.get("module_pattern")
    if pattern and pattern in handle:
        return True
    if stop_when.get("exclude_tests"):
        segments = handle.split(".")
        if any(seg == "tests" or seg.startswith("test_") for seg in segments):
            return True
    return False


def _note_unsupported(
    hop: dict[str, Any], edge: str, unsupported_edges: list[dict[str, str]]
) -> None:
    """Record an unsupported hop's ``{edge, reason, detail}`` once (de-duplicated)."""
    entry = {"edge": edge, "reason": hop["reason"], "detail": hop["detail"]}
    if entry not in unsupported_edges:
        unsupported_edges.append(entry)


def _record_hop_losses(
    hop: dict[str, Any],
    handle: str,
    unresolved_call_sites: dict[str, int],
    unresolved_imports: dict[str, list[str]],
    unresolved_importers: dict[str, list[str]],
    unparseable_files: dict[str, list[str]],
) -> None:
    """Carry a walked hop's unresolved call sites / imports onto the Subgraph maps.

    A node is popped (and each of its hops runs) exactly once, so each source
    node is recorded a single time.  Only non-zero counts and non-empty lists are
    kept: ``0`` / ``[]`` means "complete here", which the absent key already says.
    """
    if hop.get("unresolved_call_sites"):
        unresolved_call_sites[handle] = hop["unresolved_call_sites"]
    if hop.get("unresolved_imports"):
        unresolved_imports[handle] = hop["unresolved_imports"]
    if hop.get("unresolved_importers"):
        unresolved_importers[handle] = hop["unresolved_importers"]
    if hop.get("unparseable_files"):  # #729: subclasses AND imported_by may both report
        merged = set(unparseable_files.get(handle, ())) | set(hop["unparseable_files"])
        unparseable_files[handle] = sorted(merged)


def _partition_hop(
    stubs: list[dict[str, Any]], nodes: dict[str, Any], stop_when: dict[str, Any] | None
) -> tuple[list[str], list[dict[str, Any]]]:
    """Split a hop's stubs into (handles already in the closure, new stubs).

    Boundary adjacents pruned by ``stop_when`` are in neither list: they are
    never added, edged, expanded, or counted — and are NOT truncation.
    """
    known: list[str] = []
    new: list[dict[str, Any]] = []
    for stub in stubs:
        adj = stub["handle"]
        if adj in nodes:
            known.append(adj)
        elif not _stops_at(adj, stub["scope"], stop_when):
            new.append(stub)
    return known, new


async def trace(
    start: str | list[str],
    follow: list[str],
    analyzer: JediAnalyzer,
    max_depth: int = 3,
    max_nodes: int = 50,
    stop_when: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk *follow* edges from *start* via bounded BFS, returning a ``Subgraph``.

    Args:
        start: One canonical handle or a list of them (the BFS roots).
        follow: Edge names to traverse at every hop.
        analyzer: Configured ``JediAnalyzer`` for the project.
        max_depth: Maximum hop distance from a root before a node becomes a
            non-expanded frontier leaf (default 3).
        max_nodes: Maximum number of distinct nodes in the subgraph; reaching it
            stops adding new nodes and sets ``truncated`` (default 50).
        stop_when: Optional ``StopPredicate`` (``exclude_external`` /
            ``module_pattern`` / ``exclude_tests``).  An adjacent matching it is a
            boundary — pruned (never added, edged, expanded, or counted against
            ``max_nodes``).  Roots are never pruned.  ``exclude_external`` keeps a
            trace inside the project (the common ``callees`` case).

    Returns:
        A ``Subgraph`` dict: ``nodes`` (handle → Stub), ``edges`` (``from``/``to``/
        ``kind``), ``truncated``, the always-present ``unresolved_roots`` list, and
        — when ``callees`` is traced — the ``unresolved_call_sites`` map (#488).
        Never raises; an unresolvable root contributes no node but is listed in
        ``unresolved_roots``, and a node's unresolved callee count is surfaced in
        ``unresolved_call_sites`` rather than silently dropped.
    """
    starts = [start] if isinstance(start, str) else list(start)

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    # Distinct truncation causes accumulate here (#352): "max_depth" when the
    # depth frontier cuts a reachable node, "max_nodes" when the node budget
    # fills.  ``truncated`` is derived (true iff any cause fired).
    truncation_reasons: set[str] = set()

    # Partition the requested edges: traverse only the implemented ones.  Every
    # other edge (deferred reference-backend, not-yet-implemented, unknown) is
    # surfaced in ``unsupported_edges`` rather than silently dropped — a silent
    # drop would falsely read as "this symbol has no such neighbours" (the #332
    # absence-vs-zero trap the whole surface guards against).
    supported_follow: list[str] = []
    unsupported_edges: list[dict[str, str]] = []
    for edge in follow:
        status = edge_status(edge)
        if status == STATUS_IMPLEMENTED:
            supported_follow.append(edge)
        else:
            unsupported_edges.append(
                {"edge": edge, "reason": status, "detail": _unsupported_detail(edge, status)}
            )

    # ``nodes`` doubles as the visited set: a handle is added to ``nodes`` and
    # enqueued together, so membership in ``nodes`` means "already discovered".
    # A queue entry carries the source's resolved Jedi ``Name`` for a ROOT (it
    # was resolved above) and ``None`` for an interior node, which is resolved
    # when popped — the same way ``expand`` resolves its source (#621).
    queue: deque[tuple[str, Any, int]] = deque()

    # #488 / #494 (interior honesty): per-node unresolved call sites / imports,
    # carried from each walked hop.  Each map is surfaced ONLY if its edge was
    # actually walked on at least one node (#621): a requested edge that was
    # wrong-kind everywhere was never measured, so ``{}`` ("all resolved")
    # would be a measured-zero claim about nothing.
    unresolved_call_sites: dict[str, int] = {}
    unresolved_imports: dict[str, list[str]] = {}
    unresolved_importers: dict[str, list[str]] = {}  # #668
    unparseable_files: dict[str, list[str]] = {}  # #729
    walked_edges: set[str] = set()

    # #488: a root that fails to resolve is recorded here, not silently dropped.
    # Without it an internal resolution miss (cold-start non-determinism, #419)
    # renders as a confident-empty subgraph — the agent reads ``nodes: {}`` as
    # "this root has no neighbours" when really the root was never resolved. This
    # is the absence-vs-zero trap applied to *root resolution*.
    unresolved_roots: list[str] = []
    # #621: the same guard for INTERIOR nodes.  A node ``expand`` cannot resolve
    # is never walked (walking the Jedi ``Name`` the edge carried is how trace
    # used to expand handles every other primitive rejects, #602) — so it is
    # listed here rather than left as a silent leaf.
    unresolved_nodes: list[str] = []

    for root in starts:
        resolved = resolve_item(
            root, analyzer
        )  # per root: one bad root can't sink the trace (#704)
        if isinstance(resolved, NotFound):
            if root not in unresolved_roots:
                unresolved_roots.append(root)
            continue
        jedi_name = resolved.anchor
        canonical = resolved.handle
        if canonical not in nodes:
            nodes[canonical] = build_stub(jedi_name, canonical, analyzer)
            queue.append((canonical, jedi_name, 0))

    while queue:
        handle, jedi_name, depth = queue.popleft()
        if jedi_name is None:
            resolved = resolve_item(handle, analyzer)  # per node, as expand resolves (#623, #704)
            if isinstance(resolved, NotFound):
                unresolved_nodes.append(handle)
                continue
            jedi_name = resolved.anchor
        # Resolve a node's edges even at the depth frontier — peeking one hop past
        # the frontier is how truncation is detected (a reachable-but-unvisited
        # neighbour) and how cycle edges back into the closure stay visible.
        can_expand = depth < max_depth
        for edge in supported_follow:
            hop = await expand_resolved(jedi_name, handle, edge, analyzer)
            if hop.get("unsupported"):
                # #621: wrong kind for this node — expand's own reason/detail,
                # reported once per distinct (edge, reason, detail).
                _note_unsupported(hop, edge, unsupported_edges)
                continue
            walked_edges.add(edge)
            _record_hop_losses(
                hop,
                handle,
                unresolved_call_sites,
                unresolved_imports,
                unresolved_importers,
                unparseable_files,
            )
            known, new = _partition_hop(hop["stubs"], nodes, stop_when)

            # #621 item 2 — a hop is recorded ALL-OR-NOTHING (reserve before
            # expand, the #358 outline rule): if any new adjacent is cut, by the
            # depth frontier or the node budget, the hop records no edges at all,
            # so a walked hop is never silently partial.
            if new and not can_expand:
                truncation_reasons.add(MAX_DEPTH)
                continue
            if len(nodes) + len(new) > max_nodes:
                truncation_reasons.add(MAX_NODES)
                continue
            for adj in known:
                edges.append({"from": handle, "to": adj, "kind": edge})
            for stub in new:
                nodes[stub["handle"]] = stub
                edges.append({"from": handle, "to": stub["handle"], "kind": edge})
                queue.append((stub["handle"], None, depth + 1))

    result: dict[str, Any] = {
        "nodes": nodes,
        "edges": edges,
        "truncated": bool(truncation_reasons),
        "truncation_reasons": sorted(truncation_reasons),
        "unsupported_edges": unsupported_edges,
        # #488: always present (root resolution is always measured) — ``[]`` when
        # every root resolved, the failed handles otherwise.  Like its sibling
        # ``unsupported_edges``: absence would be a broken response, never a
        # meaningful "all resolved" signal.
        "unresolved_roots": unresolved_roots,
        # #621: always present, for the same reason — every discovered interior
        # node is resolved before it is walked.
        "unresolved_nodes": unresolved_nodes,
    }
    # #488 / #494 (interior honesty): present ONLY when the edge was walked on at
    # least one node — absent means "not measured" (absence-vs-zero); ``{}``
    # means walked and everything resolved.
    if "callees" in walked_edges:
        result["unresolved_call_sites"] = unresolved_call_sites
    if "imports" in walked_edges:
        result["unresolved_imports"] = unresolved_imports
    if "imported_by" in walked_edges:
        result["unresolved_importers"] = unresolved_importers
    if walked_edges & {"subclasses", "imported_by", "re_exports"}:  # #729, #393
        result["unparseable_files"] = unparseable_files
    # #458: when a requested edge was unsupported, point at where to report it.
    # Top-level and conditional — not duplicated onto every unsupported entry,
    # and absent entirely when nothing was unsupported (no noise on clean traces).
    if unsupported_edges:
        result["report_issues"] = meta.issues_url()
    # #417: the ceiling of each edge actually walked, as data.  Absent when no
    # walked edge has one (leave out, never ``{}``).
    ceilings = {e: EDGE_CEILINGS[e] for e in sorted(walked_edges) if e in EDGE_CEILINGS}
    if ceilings:
        result["ceilings"] = ceilings
    return result
