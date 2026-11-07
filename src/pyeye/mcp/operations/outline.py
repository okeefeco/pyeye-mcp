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
    # → {"found": True, "node": Stub, "children": [...OutlineTree...]}
    #   (nested OutlineTrees carry no "found"; an unresolvable handle returns
    #   the shared not-found shape from ``not_found``)

    tree = await outline("mypackage._core.widgets", analyzer)
    # → default depth-1 (#474): direct members; non-empty nested containers
    #   are truncated: "max_depth" — drill on demand by outlining them

    tree = await outline("mypackage._core.widgets", analyzer, max_depth=2)
    # → root with children; containers at depth 2 are truncated

    tree = await outline("mypackage._core.widgets", analyzer, max_depth=None)
    # → unbounded walk (still bounded by max_nodes and the external cap)

``async def`` matches the surrounding tool surface (``inspect``/``trace`` are
async) and leaves room for an async edge resolver in the future.  The body does
not currently await — ``resolve_members`` is synchronous today — but the
``async`` signature is kept for surface uniformity with the rest of the API.

Truncation reasons (spec §5.4)
-------------------------------
- ``"max_depth"`` — node is at the depth frontier and has non-empty members
  (detected by a single peek call to ``resolve_members``).  Genuine empty
  containers at the frontier receive ``children: []`` instead of truncation.
- ``"max_nodes"`` — the node budget cannot admit ALL of the container's direct
  members, so it is **reserved-before-expand**: rather than expand partway and
  silently drop the rest (the #358 bug), the whole container is cut off.  A
  single peek counts the members (adding no nodes) so the cut-off node carries an
  honest ``member_count`` — the count of direct members withheld — alongside
  ``truncated``/``truncation_reason``.  Recovery is a fresh re-outline with a
  larger budget or a targeted subtree.  Genuinely empty containers are leaves
  (``children: []``), never a ``max_nodes`` truncation.
- ``"external"`` — the node is an external-scope container at depth ≥ 1.  The
  external cap allows one level of members from the root and one from its
  immediate children, but no deeper walk into third-party code.  No peek, no
  ``member_count``.
- ``"survey_leaf"`` — package survey mode only (#596): a module (plain module, or
  a package with no submodules) that HAS members.  Survey mode walks
  ``submodules``, never ``members``, so such a node is not walked; ``children:
  []`` would falsely claim it measured-empty.  One emptiness peek; no
  ``member_count`` (a count per leaf is too costly on large surveys).  Recovery:
  ``outline`` the node itself.  A module with no members stays ``children: []``.

Survey disclosure (#596): a walked package in survey mode carries
``init_member_count`` — the count of members its own ``__init__`` defines, which
the submodules-only tree does not list — present only when > 0.  A package ROOT
with no submodules is outlined in member mode instead.

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
from pyeye.mcp.operations.not_found import not_found
from pyeye.mcp.operations.stubs import build_stub

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

# ---------------------------------------------------------------------------
# Truncation reason constants (single string per node — not a list; see spec §5.4)
# ---------------------------------------------------------------------------

_REASON_MAX_DEPTH: str = "max_depth"
_REASON_MAX_NODES: str = "max_nodes"
_REASON_EXTERNAL: str = "external"
_REASON_SURVEY_LEAF: str = "survey_leaf"

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


def _has_members(jedi_name: Any, analyzer: JediAnalyzer) -> bool:
    """Return whether *jedi_name* statically defines any direct members."""
    return bool(resolve_members(jedi_name, analyzer).adjacents)


def _mark_unwalked_survey_node(
    tree_node: dict[str, Any], jedi_name: Any, analyzer: JediAnalyzer
) -> None:
    """Classify a survey-mode node whose members the survey does not walk (#596).

    Survey mode walks ``submodules`` only, so a plain module — or a package with
    no submodules — is never member-walked.  ``children: []`` would claim it is
    *measured empty* (Contract 1), which is false when it has members.  One cheap
    emptiness peek decides:

    - members present → ``truncated: "survey_leaf"`` with ``children`` absent
      (recovery: ``outline`` the node itself, which walks its members);
    - no members → ``children: []`` — a genuine, measured leaf.

    No ``member_count``: counting every leaf of a large survey is too costly; the
    flag only has to stop the node claiming to be empty.
    """
    if _has_members(jedi_name, analyzer):
        tree_node["truncated"] = True
        tree_node["truncation_reason"] = _REASON_SURVEY_LEAF
    else:
        tree_node["children"] = []


def _mark_empty_adjacents(
    tree_node: dict[str, Any], jedi_name: Any, analyzer: JediAnalyzer, survey_mode: bool
) -> None:
    """Mark a node whose child-adjacents peek came back empty.

    In member mode that is a genuine empty container.  In survey mode an empty
    ``submodules`` set says nothing about members, so defer to
    :func:`_mark_unwalked_survey_node`.
    """
    if survey_mode:
        _mark_unwalked_survey_node(tree_node, jedi_name, analyzer)
    else:
        tree_node["children"] = []


def _is_expandable(jedi_name: Any, kind: str, survey_mode: bool) -> bool:
    """Return whether a node should be walked under the active mode.

    Survey mode expands ONLY packages (plain modules are not walked — their
    members are not part of a package survey, see
    :func:`_mark_unwalked_survey_node`); member mode expands any container
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
    max_depth: int | None = 1,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Return the structural skeleton of *handle* as a nested ``OutlineTree``.

    Walks the ``members`` edge from *handle* via BFS-bounded recursion, building
    each node with ``stubs.build_stub`` and stopping at depth, budget, or
    external-scope limits.

    **Package survey mode (#423).** When *handle* resolves to a PACKAGE, the walk
    switches to the ``submodules`` containment edge instead of ``members``: the
    tree is the package's child modules/subpackages (drill on demand); module
    members are not walked — a module that has members is ``truncated:
    "survey_leaf"``, a walked package discloses its own ``__init__`` members as
    ``init_member_count`` (#596).  A module/class root, or a package root with no
    submodules, keeps survey mode off and walks ``members``.

    **Default depth is 1 for every root kind (#474).**  With no ``max_depth``
    argument the tree is the root's *direct* structure: direct members (or
    top-level submodules for a package), with non-empty nested containers cut off
    as ``truncated: "max_depth"`` — drill on demand by outlining them.  Deeper
    walks are explicit: ``max_depth=N``, or ``max_depth=None`` for unbounded.

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
        max_depth: Maximum depth of recursion from the root (depth 0).  Defaults
            to ``1`` (direct members only, #474) for every root kind.  ``None``
            means unbounded within scope (the external cap and ``max_nodes``
            still apply regardless).
        max_nodes: Maximum total nodes in the tree (root counts as 1, default
            200).  Containers that cannot be expanded due to an exhausted budget
            are marked ``truncated: "max_nodes"`` without peeking.

    Returns:
        A nested ``OutlineTree`` dict whose root carries ``found: True``.  Never
        raises; an unresolvable root yields the shared not-found shape
        (:func:`not_found`) — never a placeholder tree (#545).

    Note:
        ``async def`` for surface uniformity with ``inspect``/``trace``.  The body
        does not currently await — ``resolve_members`` is synchronous today.
    """
    # ------------------------------------------------------------------
    # 1. Resolve root handle to a Jedi Name.
    # ------------------------------------------------------------------
    root_jedi_name = await _resolve_handle_to_jedi_name(handle, analyzer)

    if root_jedi_name is None:
        return not_found(handle)

    root_stub = build_stub(root_jedi_name, handle, analyzer)

    # ------------------------------------------------------------------
    # Survey mode (#423): a PACKAGE root walks the `submodules` containment edge
    # instead of `members`, giving a drillable project/package tree.  It is set
    # from the ROOT handle only — a module/class root keeps the unchanged
    # members behavior.  Depth is NOT kind-dependent: the depth-1 default lives
    # in the signature for every root kind (#474), and ``None`` is unbounded.
    # ------------------------------------------------------------------
    # A package root with NO submodules gets member mode (#596): a survey of
    # nothing is useless, and marking the root ``survey_leaf`` ("outline it to
    # see its members") would point back at this very call.
    survey_mode = _is_package(root_jedi_name) and bool(
        resolve_submodules(root_jedi_name, analyzer).adjacents
    )

    # ------------------------------------------------------------------
    # 2. Build root tree node and initialise BFS state.  ``found`` is a
    # response-level field, so only the root tree carries it (#545).
    # ------------------------------------------------------------------
    root_tree: dict[str, Any] = {"found": True, "node": root_stub}

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

        # Non-expandable nodes.  In member mode that is any non-container — a
        # genuine leaf, no peek.  In survey mode a plain module (non-package) is
        # not walked either, but it may HAVE members, so it is classified by a
        # cheap emptiness peek rather than claimed empty (#596).
        if not _is_expandable(jedi_name, kind, survey_mode):
            if survey_mode and _is_container(kind):
                _mark_unwalked_survey_node(tree_node, jedi_name, analyzer)
            else:
                tree_node["children"] = []
            continue

        # --- Container: determine which cap (if any) fires. ---

        # TIEBREAKER (spec §5.4): budget check wins over depth/external.
        # Check it FIRST so that when both could fire, we report "max_nodes".
        if node_count >= max_nodes:
            # Budget already full: this container cannot admit any child.  Peek
            # the member count ONCE so a max_nodes truncation carries an honest
            # signpost (#358 / spec §3) — the peek counts members but adds no
            # nodes, so it does not "defeat" the budget.  A genuinely empty
            # container is a leaf (children: []), never a truncation.
            adjacents = _child_adjacents(jedi_name, analyzer, survey_mode)
            if not adjacents:
                _mark_empty_adjacents(tree_node, jedi_name, analyzer, survey_mode)
            else:
                tree_node["truncated"] = True
                tree_node["truncation_reason"] = _REASON_MAX_NODES
                tree_node["member_count"] = len(adjacents)
            continue

        # External-scope cap: external containers at depth ≥ 1 are capped.
        # The root (depth 0) always gets one level of members even if external.
        if scope == "external" and depth >= 1:
            # No peek deeper into third-party code.
            tree_node["truncated"] = True
            tree_node["truncation_reason"] = _REASON_EXTERNAL
            continue

        # Depth-frontier peek (spec §5.3): at max_depth, call the
        # child-adjacents resolver ONCE to distinguish genuine empty containers
        # from cut-off ones.  In survey mode the peek checks `submodules`.
        if max_depth is not None and depth >= max_depth:
            adjacents = _child_adjacents(jedi_name, analyzer, survey_mode)
            if not adjacents:
                # Empty container (member mode) or a submodule-less package
                # (survey mode — classified by its members, #596).
                _mark_empty_adjacents(tree_node, jedi_name, analyzer, survey_mode)
            else:
                # Has children but cannot be walked — cut off.
                tree_node["truncated"] = True
                tree_node["truncation_reason"] = _REASON_MAX_DEPTH
            continue

        # --- Expand: reserve-before-expand (spec §4, #358). ---
        # Peek the direct members ONCE.  Reserve the whole set up front: if the
        # remaining budget cannot admit ALL of them, do NOT produce a partial
        # children list — mark this container truncated: "max_nodes" with an
        # honest member_count and omit children (Contract 1/2).  Recovery is a
        # fresh re-outline with a larger budget or a targeted subtree.  The old
        # code broke mid-loop and assigned the partial list with no marker.
        adjacents = _child_adjacents(jedi_name, analyzer, survey_mode)
        if not adjacents:
            # Member mode: a genuine empty container — a measured leaf.  Survey
            # mode: a submodule-less package, classified by its members (#596).
            _mark_empty_adjacents(tree_node, jedi_name, analyzer, survey_mode)
            continue

        if node_count + len(adjacents) > max_nodes:
            tree_node["truncated"] = True
            tree_node["truncation_reason"] = _REASON_MAX_NODES
            tree_node["member_count"] = len(adjacents)
            continue

        children: list[dict[str, Any]] = []
        for child_handle, child_jedi_name in adjacents:
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

        # Survey disclosure (#596): a walked package lists only its submodules,
        # so the members its own ``__init__`` defines would vanish silently.
        # Disclose their count (present only when > 0); recovery is
        # ``expand(pkg, "members")``.
        if survey_mode:
            init_members = len(resolve_members(jedi_name, analyzer).adjacents)
            if init_members:
                tree_node["init_member_count"] = init_members

    return root_tree
