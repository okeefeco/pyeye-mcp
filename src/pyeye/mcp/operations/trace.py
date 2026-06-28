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
      "unresolved_call_sites": { handle: count, ... },  # #488 — present iff callees traced
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

Termination: each handle is visited (expanded) at most once; edges *to* an
already-visited handle are still recorded so cycles stay visible to the agent,
but do not trigger re-expansion.  This guarantees termination on cyclic graphs.
"""

from __future__ import annotations

from collections import deque
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from pyeye.mcp import meta
from pyeye.mcp.operations.edges import EDGE_RESOLVERS, STATUS_IMPLEMENTED, edge_status
from pyeye.mcp.operations.expand import _unsupported_detail
from pyeye.mcp.operations.inspect import _resolve_handle_to_jedi_name
from pyeye.mcp.operations.stubs import build_stub

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


async def _single_hop(
    jedi_name: Any, edge: str, analyzer: JediAnalyzer
) -> tuple[list[tuple[str, Any]], int | None]:
    """Resolve ONE edge from *jedi_name*.

    Pure registry consumption: consults :func:`edge_status` and runs the
    registered resolver (awaiting async resolvers like ``imported_by``).  An
    unsupported edge or a wrong-kind (``None``) resolver result yields no
    adjacents — honest no-op handling for the traversal layer.

    Args:
        jedi_name: Resolved Jedi ``Name`` (or sentinel) for the source handle.
        edge: The edge to walk.
        analyzer: Active analyzer.

    Returns:
        A 2-tuple ``(adjacents, unresolved_call_sites)``:

        - ``adjacents``: ``(canonical_handle_string, adjacent_jedi_name)`` pairs —
          the adjacent name is carried so the caller can build a stub without a
          re-resolution (the load-bearing reason ``EdgeResult`` carries Names).
        - ``unresolved_call_sites``: the ``callees`` count of call sites ``goto``
          could not resolve (dynamic/un-inferable, or a flaky miss, #419), or
          ``None`` for every non-``callees`` edge (the notion is callees-only).
          Carried forward so ``trace`` can surface interior call-resolution loss
          instead of silently dropping it (#488).
    """
    if edge_status(edge) != STATUS_IMPLEMENTED:
        return [], None
    raw = EDGE_RESOLVERS[edge](jedi_name, analyzer)
    edge_result = await raw if isawaitable(raw) else raw
    if edge_result is None:
        return [], None
    adjacents = [(str(adj_handle), name) for adj_handle, name in edge_result.adjacents]
    return adjacents, edge_result.unresolved_call_sites


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
    queue: deque[tuple[str, Any, int]] = deque()

    # #488 (interior honesty): per-source-node count of call sites a ``callees``
    # hop could not resolve (dynamic/un-inferable, or a flaky goto miss, #419).
    # ``expand(callees)`` already reports this; without carrying it forward a
    # ``trace`` subgraph would look more complete than it is. Surfaced ONLY when
    # ``callees`` was actually traced (absent ⇒ not measured), and only nodes with
    # a non-zero count are recorded.
    callees_traced = "callees" in supported_follow
    unresolved_call_sites: dict[str, int] = {}

    # #488: a root that fails to resolve is recorded here, not silently dropped.
    # Without it an internal resolution miss (cold-start non-determinism, #419)
    # renders as a confident-empty subgraph — the agent reads ``nodes: {}`` as
    # "this root has no neighbours" when really the root was never resolved. This
    # is the absence-vs-zero trap applied to *root resolution*.
    unresolved_roots: list[str] = []

    for root in starts:
        jedi_name = await _resolve_handle_to_jedi_name(root, analyzer)
        if jedi_name is None:
            if root not in unresolved_roots:
                unresolved_roots.append(root)
            continue
        canonical = getattr(jedi_name, "full_name", None) or root
        if canonical not in nodes:
            nodes[canonical] = build_stub(jedi_name, canonical, analyzer)
            queue.append((canonical, jedi_name, 0))

    while queue:
        handle, jedi_name, depth = queue.popleft()
        # Resolve a node's edges even at the depth frontier — peeking one hop past
        # the frontier is how truncation is detected (a reachable-but-unvisited
        # neighbour) and how cycle edges back into the closure stay visible.
        can_expand = depth < max_depth
        for edge in supported_follow:
            adjacents, hop_unresolved = await _single_hop(jedi_name, edge, analyzer)
            if edge == "callees" and hop_unresolved:
                # A node is popped (and its callees hop runs) exactly once, so this
                # records each source node's count a single time. Only > 0 is kept:
                # 0 means "callees complete here", which the absent key already says.
                unresolved_call_sites[handle] = hop_unresolved
            for adj_handle, adj_name in adjacents:
                if adj_handle in nodes:
                    # Already in the closure: record the (possibly cyclic) edge so
                    # it stays visible, but never re-expand — this bounds the walk.
                    edges.append({"from": handle, "to": adj_handle, "kind": edge})
                    continue
                # New adjacent — build its stub once.  The stub carries the
                # resolved ``scope`` that the boundary predicate needs, and is
                # reused as the node value when the adjacent is kept.
                stub = build_stub(adj_name, adj_handle, analyzer)
                if _stops_at(adj_handle, stub["scope"], stop_when):
                    # Boundary: prune entirely — no node, no edge, no expansion.
                    # NOT truncation: a deliberately-excluded handle (e.g. an
                    # external node) is not a cap cutoff, so it never sets
                    # ``truncated`` and never consumes the ``max_nodes`` budget.
                    continue
                if not can_expand:
                    # A reachable handle one hop past the depth frontier: cut off.
                    truncation_reasons.add("max_depth")
                    continue
                if len(nodes) >= max_nodes:
                    # Node budget exhausted: this reachable handle is cut off.
                    truncation_reasons.add("max_nodes")
                    continue
                nodes[adj_handle] = stub
                edges.append({"from": handle, "to": adj_handle, "kind": edge})
                queue.append((adj_handle, adj_name, depth + 1))

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
    }
    # #488 (interior honesty): present ONLY when ``callees`` was traced — call
    # sites are not measured otherwise, so an absent key honestly means "not
    # measured" (absence-vs-zero), distinct from the always-present
    # ``unresolved_roots``. ``{}`` means callees were traced and all resolved.
    if callees_traced:
        result["unresolved_call_sites"] = unresolved_call_sites
    # #458: when a requested edge was unsupported, point at where to report it.
    # Top-level and conditional — not duplicated onto every unsupported entry,
    # and absent entirely when nothing was unsupported (no noise on clean traces).
    if unsupported_edges:
        result["report_issues"] = meta.issues_url()
    return result
