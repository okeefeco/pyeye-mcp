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
      "unsupported_edges": [ {"edge", "reason", "detail"}, ... ] }

``unsupported_edges`` is an additive honesty field (beyond the spec's bare
``Subgraph`` triple): any edge in ``follow`` that is not an implemented edge
(deferred reference-backend, not-yet-implemented, or unknown) is listed here
rather than silently dropped from the walk — silently omitting it would falsely
read as "no such neighbours" (the #332 absence-vs-zero trap).  It is ``[]`` when
every requested edge is supported.

Termination: each handle is visited (expanded) at most once; edges *to* an
already-visited handle are still recorded so cycles stay visible to the agent,
but do not trigger re-expansion.  This guarantees termination on cyclic graphs.
"""

from __future__ import annotations

from collections import deque
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from pyeye.mcp.operations.edges import EDGE_RESOLVERS, STATUS_IMPLEMENTED, edge_status
from pyeye.mcp.operations.expand import _unsupported_detail
from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle
from pyeye.mcp.operations.stubs import build_stub

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


async def _single_hop(jedi_name: Any, edge: str, analyzer: JediAnalyzer) -> list[tuple[str, Any]]:
    """Resolve ONE edge from *jedi_name*, returning ``(handle_str, jedi_name)`` pairs.

    Pure registry consumption: consults :func:`edge_status` and runs the
    registered resolver (awaiting async resolvers like ``imported_by``).  An
    unsupported edge or a wrong-kind (``None``) resolver result yields no
    adjacents — honest no-op handling for the traversal layer.

    Args:
        jedi_name: Resolved Jedi ``Name`` (or sentinel) for the source handle.
        edge: The edge to walk.
        analyzer: Active analyzer.

    Returns:
        A list of ``(canonical_handle_string, adjacent_jedi_name)`` pairs — the
        adjacent name is carried so the caller can build a stub without a
        re-resolution (the load-bearing reason ``EdgeResult`` carries Names).
    """
    if edge_status(edge) != STATUS_IMPLEMENTED:
        return []
    raw = EDGE_RESOLVERS[edge](jedi_name, analyzer)
    edge_result = await raw if isawaitable(raw) else raw
    if edge_result is None:
        return []
    return [(str(adj_handle), name) for adj_handle, name in edge_result.adjacents]


async def trace(
    start: str | list[str],
    follow: list[str],
    analyzer: JediAnalyzer,
    max_depth: int = 3,
    max_nodes: int = 50,
) -> dict[str, Any]:
    """Walk *follow* edges from *start* via bounded BFS, returning a ``Subgraph``.

    The spec signature also carries ``stop_when``; that lands in its own TDD
    cycle (a traversal-boundary predicate) and is deliberately omitted here
    until a test drives it.

    Args:
        start: One canonical handle or a list of them (the BFS roots).
        follow: Edge names to traverse at every hop.
        analyzer: Configured ``JediAnalyzer`` for the project.
        max_depth: Maximum hop distance from a root before a node becomes a
            non-expanded frontier leaf (default 3).
        max_nodes: Maximum number of distinct nodes in the subgraph; reaching it
            stops adding new nodes and sets ``truncated`` (default 50).

    Returns:
        A ``Subgraph`` dict: ``nodes`` (handle → Stub), ``edges`` (``from``/``to``/
        ``kind``), and ``truncated``.  Never raises; an unresolvable root simply
        contributes no node.
    """
    starts = [start] if isinstance(start, str) else list(start)

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    truncated = False

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

    for root in starts:
        jedi_name = _find_jedi_name_for_handle(root, analyzer)
        if jedi_name is None:
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
            for adj_handle, adj_name in await _single_hop(jedi_name, edge, analyzer):
                if adj_handle in nodes:
                    # Already in the closure: record the (possibly cyclic) edge so
                    # it stays visible, but never re-expand — this bounds the walk.
                    edges.append({"from": handle, "to": adj_handle, "kind": edge})
                elif can_expand:
                    if len(nodes) >= max_nodes:
                        # Node budget exhausted: this reachable handle is cut off.
                        truncated = True
                        continue
                    nodes[adj_handle] = build_stub(adj_name, adj_handle, analyzer)
                    edges.append({"from": handle, "to": adj_handle, "kind": edge})
                    queue.append((adj_handle, adj_name, depth + 1))
                else:
                    # A reachable handle one hop past the depth frontier: cut off.
                    # Don't add a node or a dangling edge — just flag truncation.
                    truncated = True

    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
        "unsupported_edges": unsupported_edges,
    }
