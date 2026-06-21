"""outline(handle) — structural skeleton of a module or class.

Returns a nested ``OutlineTree`` — a tree of ``(node, children?)`` entries
covering the ``members`` hierarchy of the given handle, with no source content.

Two load-bearing absence contracts (spec §4.2) guard the response:

**Contract 1 — ``children`` absent ⇔ not expanded.**
``children`` present (including ``[]``) means *measured*: the complete set of
direct members.  ``children`` absent means a cap fired; the consumer MUST treat
it as "unknown," never "empty."

**Contract 2 — ``truncated`` absent-not-false.**
``truncated: true`` is present ONLY on a node that a cap cut off, always
co-occurring with ``truncation_reason`` and an absent ``children``.  Fully-walked
nodes OMIT ``truncated`` entirely — never ``truncated: false``.

``outline`` is a pure *consumer* of the existing edge registry (spec §2 "Out"):
it CALLS ``edges.resolve_members`` (member mode) or ``edges.resolve_submodules``
(package survey mode, #423) plus ``stubs.build_stub``; it adds NO new edge logic
and MUST NOT modify ``edges.py``/the resolvers.

Public API
----------
.. code-block:: python

    tree = await outline("mypackage._core.widgets.Widget", analyzer)
    # → {"node": Stub, "children": [...OutlineTree...]}

    tree = await outline("mypackage._core.widgets", analyzer, max_depth=2)
    # → root with children; containers at depth 2 are truncated

``async def`` matches the surrounding tool surface (``inspect``/``trace`` are
async) and leaves room for an async edge resolver in the future.  The body does
not currently await — ``resolve_members`` is synchronous today — but the
``async`` signature is kept for surface uniformity with the rest of the API.

Truncation reasons (spec §5.4)
-------------------------------
- ``"max_depth"`` — node is at the depth frontier and has non-empty members
  (detected by a single peek call to ``resolve_members``).  Genuine empty
  containers at the frontier receive ``children: []`` instead of truncation.
- ``"max_nodes"`` — the node budget is exhausted.  No peek is performed.
- ``"external"`` — the node is an external-scope container at depth ≥ 1.  The
  external cap allows one level of members from the root and one from its
  immediate children, but no deeper walk into third-party code.  No peek.

Tiebreaker (spec §5.4): when both ``max_nodes`` AND ``max_depth``/``external``
could fire on the same node, ``truncation_reason`` is ``"max_nodes"`` (the harder
global bound).  In all cases ``children`` is omitted.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyeye.mcp.operations.edges import resolve_members, resolve_submodules
from pyeye.mcp.operations.inspect import _resolve_handle_to_jedi_name
from pyeye.mcp.operations.stubs import build_stub

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

# ---------------------------------------------------------------------------
# Truncation reason constants (single string per node — not a list; see spec §5.4)
# ---------------------------------------------------------------------------

_REASON_MAX_DEPTH: str = "max_depth"
_REASON_MAX_NODES: str = "max_nodes"
_REASON_EXTERNAL: str = "external"

# ---------------------------------------------------------------------------
# Container kinds — resolve_members returns [] for non-containers by definition,
# so non-container nodes always get children: [] without calling resolve_members.
# ---------------------------------------------------------------------------

_CONTAINER_KINDS: frozenset[str] = frozenset({"class", "module"})


def _is_container(kind: str) -> bool:
    """Return True if *kind* is a container (class or module) that can have members."""
    return kind in _CONTAINER_KINDS


def _is_package(jedi_name: Any) -> bool:
    """Return whether *jedi_name* is a package (drives survey mode, #423).

    A package is a module whose ``module_path`` is an ``__init__.py`` (regular
    package) OR a bare directory (a PEP 420 namespace subpackage, anchored on its
    directory by the ``submodules`` resolver).  A plain ``X.py`` module is not a
    package; in survey mode it becomes a leaf.
    """
    module_path = getattr(jedi_name, "module_path", None)
    if module_path is None:
        return False
    module_path = Path(module_path)
    if module_path.name == "__init__.py":
        return True
    # A namespace-subpackage stub is anchored on its directory (never .py).
    return module_path.is_dir()


def _child_adjacents(
    jedi_name: Any, analyzer: JediAnalyzer, survey_mode: bool
) -> list[tuple[Any, Any]]:
    """Return the adjacents to walk for *jedi_name* under the active mode.

    In **survey mode** a package node yields its ``submodules`` children (the
    containment edge); in member mode (or for a non-package node) it yields its
    ``members``.  This is the single switch that makes ``outline(pkg)`` a
    drillable submodule tree while leaving ``outline(module)`` / ``outline(class)``
    byte-for-byte unchanged (survey_mode is False for those roots).
    """
    if survey_mode and _is_package(jedi_name):
        return resolve_submodules(jedi_name, analyzer).adjacents
    return resolve_members(jedi_name, analyzer).adjacents


def _is_expandable(jedi_name: Any, kind: str, survey_mode: bool) -> bool:
    """Return whether a node should be walked under the active mode.

    Survey mode expands ONLY packages (plain modules become leaves — their
    members are not part of a package survey); member mode expands any container
    (class or module).
    """
    if survey_mode:
        return _is_package(jedi_name)
    return _is_container(kind)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def outline(
    handle: str,
    analyzer: JediAnalyzer,
    max_depth: int | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Return the structural skeleton of *handle* as a nested ``OutlineTree``.

    Walks the ``members`` edge from *handle* via BFS-bounded recursion, building
    each node with ``stubs.build_stub`` and stopping at depth, budget, or
    external-scope limits.

    **Package survey mode (#423).** When *handle* resolves to a PACKAGE, the walk
    switches to the ``submodules`` containment edge instead of ``members``: the
    tree is the package's child modules/subpackages (drill on demand), plain
    modules are leaves (their members are not walked), and — when ``max_depth``
    is left ``None`` — the default depth is **1** (top-level submodules only) so
    the survey is never a full recursive dump.  A module/class root is unchanged:
    survey mode is off, ``members`` is walked, and ``max_depth=None`` stays
    unbounded.  This kind-dependent default (package root → depth-1; module/class
    root → unbounded) is intentional.

    Static-surface ceiling: because the walk is over ``members``, the tree is
    complete over statically-defined members but NOT over runtime-injected ones
    (metaclass / ``setattr`` / ``__getattr__`` / ``type()`` /
    ``__init_subclass__``) — e.g. a Django ``Model`` omits its metaclass-injected
    ``_meta`` / ``objects`` / ``DoesNotExist``.

    The §4.2 absence contracts are enforced on every node:

    - ``children`` present ⇔ the node was expanded (walked).
    - ``truncated: true`` + ``truncation_reason`` present ⇔ a cap prevented expansion.
    - Fully-walked nodes omit ``truncated`` entirely.

    Args:
        handle: Canonical dotted-name handle of the root symbol.
        analyzer: Configured ``JediAnalyzer`` for the project.
        max_depth: Maximum depth of recursion from the root (depth 0).  ``None``
            means unbounded within scope for a module/class root (the external cap
            and ``max_nodes`` still apply regardless); for a PACKAGE root, ``None``
            defaults to depth-1 (survey mode, #423).  An explicit value overrides
            the package default.
        max_nodes: Maximum total nodes in the tree (root counts as 1, default
            200).  Containers that cannot be expanded due to an exhausted budget
            are marked ``truncated: "max_nodes"`` without peeking.

    Returns:
        A nested ``OutlineTree`` dict.  Never raises; an unresolvable root
        yields a minimal single-node tree ``{"node": ..., "children": []}``.

    Note:
        ``async def`` for surface uniformity with ``inspect``/``trace``.  The body
        does not currently await — ``resolve_members`` is synchronous today.
    """
    # ------------------------------------------------------------------
    # 1. Resolve root handle to a Jedi Name.
    # ------------------------------------------------------------------
    root_jedi_name = await _resolve_handle_to_jedi_name(handle, analyzer)

    if root_jedi_name is None:
        # Unresolvable — return minimal single-node fallback (mirrors inspect).
        stub = _make_fallback_stub(handle)
        return {"node": stub, "children": []}

    root_stub = build_stub(root_jedi_name, handle, analyzer)

    # ------------------------------------------------------------------
    # Survey mode (#423): a PACKAGE root walks the `submodules` containment edge
    # instead of `members`, giving a drillable project/package tree.  It is set
    # from the ROOT handle only — a module/class root keeps the unchanged
    # members behavior.  Kind-dependent default depth: a package root with no
    # explicit max_depth is treated as depth-1 (top-level submodules first, drill
    # on demand) so the survey is not a full recursive dump; module/class roots
    # keep `None` (unbounded within scope).
    # ------------------------------------------------------------------
    survey_mode = _is_package(root_jedi_name)
    effective_max_depth = max_depth
    if survey_mode and max_depth is None:
        effective_max_depth = 1

    # ------------------------------------------------------------------
    # 2. Build root tree node and initialise BFS state.
    # ------------------------------------------------------------------
    root_tree: dict[str, Any] = {"node": root_stub}

    # node_count tracks every node added to the tree (root + all children).
    # The root always counts as node 1.
    node_count: int = 1

    # BFS queue entries: (jedi_name, depth, tree_node_dict)
    # tree_node_dict is the MUTABLE dict for this node — we fill in "children"
    # or "truncated"/"truncation_reason" as we process it.
    queue: deque[tuple[Any, int, dict[str, Any]]] = deque()
    queue.append((root_jedi_name, 0, root_tree))

    # ------------------------------------------------------------------
    # 3. BFS — decide whether to expand each node, build children.
    # ------------------------------------------------------------------
    while queue:
        jedi_name, depth, tree_node = queue.popleft()
        stub = tree_node["node"]
        kind = stub["kind"]
        scope = stub["scope"]

        # Non-expandable nodes: a genuine leaf.  In member mode that is any
        # non-container; in survey mode a plain module (non-package) is also a
        # leaf (its members are not part of a package survey).  No adjacents
        # call, no budget consumed for a peek.
        if not _is_expandable(jedi_name, kind, survey_mode):
            tree_node["children"] = []
            continue

        # --- Container: determine which cap (if any) fires. ---

        # TIEBREAKER (spec §5.4): budget check wins over depth/external.
        # Check it FIRST so that when both could fire, we report "max_nodes".
        if node_count >= max_nodes:
            # Budget is full; this container was added but cannot be expanded.
            # No peek — that would defeat the budget.
            tree_node["truncated"] = True
            tree_node["truncation_reason"] = _REASON_MAX_NODES
            continue

        # External-scope cap: external containers at depth ≥ 1 are capped.
        # The root (depth 0) always gets one level of members even if external.
        if scope == "external" and depth >= 1:
            # No peek deeper into third-party code.
            tree_node["truncated"] = True
            tree_node["truncation_reason"] = _REASON_EXTERNAL
            continue

        # Depth-frontier peek (spec §5.3): at the (effective) max_depth, call the
        # child-adjacents resolver ONCE to distinguish genuine empty containers
        # from cut-off ones.  In survey mode the peek checks `submodules`.
        if effective_max_depth is not None and depth >= effective_max_depth:
            adjacents = _child_adjacents(jedi_name, analyzer, survey_mode)
            if not adjacents:
                # Genuine empty container (no members / no submodules).
                tree_node["children"] = []
            else:
                # Has children but cannot be walked — cut off.
                tree_node["truncated"] = True
                tree_node["truncation_reason"] = _REASON_MAX_DEPTH
            continue

        # --- Expand: add children and enqueue for BFS. ---

        adjacents = _child_adjacents(jedi_name, analyzer, survey_mode)

        children: list[dict[str, Any]] = []
        for child_handle, child_jedi_name in adjacents:
            # Budget: add a child only if there is room.
            if node_count >= max_nodes:
                # Budget exhausted mid-expansion: remaining children silently
                # not added.  (The parent's children list is partial, but the
                # contract does not require a sentinel — the consumer can infer
                # incompleteness from any truncated nodes elsewhere in the tree
                # and from the tree's overall node count vs the budget.)
                break

            child_handle_str = str(child_handle)
            child_stub = build_stub(child_jedi_name, child_handle_str, analyzer)
            child_tree: dict[str, Any] = {"node": child_stub}
            children.append(child_tree)
            node_count += 1
            queue.append((child_jedi_name, depth + 1, child_tree))

        # Sort children by (line_start, handle) — source order (spec §5.2).
        # BFS inclusion order is independent of presentation order: BFS decides
        # WHICH nodes are in the tree; (line_start, handle) decides HOW they are
        # arranged within each parent's children list.
        children.sort(key=lambda t: (t["node"]["line_start"], t["node"]["handle"]))

        tree_node["children"] = children

    return root_tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fallback_stub(handle: str) -> dict[str, Any]:
    """Build a minimal fallback stub for an unresolvable *handle*.

    Mirrors ``inspect``'s minimal-node fallback: returns a dict with all
    required Stub fields populated with reasonable defaults so the caller can
    return a well-formed (but clearly minimal) ``OutlineTree``.

    Args:
        handle: The unresolvable handle string.

    Returns:
        A dict with ``handle``, ``kind``, ``scope``, ``line_start``, ``line_end``.
    """
    return {
        "handle": handle,
        "kind": "variable",  # safest default for an unknown symbol
        "scope": "external",
        "line_start": 1,
        "line_end": 1,
    }
