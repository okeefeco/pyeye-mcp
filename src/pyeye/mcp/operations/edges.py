"""Edge-status registry and structural edge resolvers for ``expand``.

This module is the **single source of truth** for which traversal edges
``expand`` supports.  It provides two distinct lookups:

1. :func:`edge_status` — classify any edge name into exactly one of four
   machine-distinguishable statuses.  The status string IS the ``reason``
   string ``expand`` emits for unsupported edges.
2. :data:`EDGE_RESOLVERS` / the resolver registry — maps *implemented* edge
   names to their resolver callables.  In this phase only ``members`` has a
   resolver; ``callees`` is classified ``implemented`` in the status matrix but
   its resolver lands in Phase 3.

Status model (spec §4.3)
------------------------
==============================  =========================================
status                          edges
==============================  =========================================
``"implemented"``               ``members``, ``callees``
``"not_yet_implemented"``       ``superclasses``, ``subclasses``,
                                ``imports``, ``enclosing_scope``
``"deferred_reference_backend"``  ``callers``, ``references``, ``read_by``,
                                ``written_by``, ``passed_by``,
                                ``imported_by``, ``overrides``,
                                ``overridden_by``, ``decorated_by``,
                                ``decorates``
(unrecognised name)             ``"unknown_edge"``
==============================  =========================================

Architectural constraint
-------------------------
This module MUST NOT import from ``inspect.py``.  In Phase 5 ``inspect`` will
import :func:`resolve_members` to derive ``edge_counts.members`` — importing
back from ``inspect`` here would create a circular import.  Member enumeration
is therefore implemented FRESH in this module (deliberate, temporary
duplication of ``inspect._count_*_members``, removed in Phase 5).

The ``members`` resolver is pure structural enumeration — it never calls
``get_references`` / ``find_references``.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyeye import file_artifact_cache
from pyeye.handle import Handle
from pyeye.mcp.operations.resolve import _normalise_kind

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


# ---------------------------------------------------------------------------
# Edge status model (spec §4.3)
# ---------------------------------------------------------------------------

#: Status value strings — these ARE the ``reason`` strings ``expand`` emits.
STATUS_IMPLEMENTED = "implemented"
STATUS_NOT_YET_IMPLEMENTED = "not_yet_implemented"
STATUS_DEFERRED_REFERENCE_BACKEND = "deferred_reference_backend"
STATUS_UNKNOWN_EDGE = "unknown_edge"

#: Edges with a working (or Phase-3-bound) resolver.
_IMPLEMENTED_EDGES = frozenset({"members", "callees"})

#: Edges recognised by the matrix but not yet built (no reference backend needed).
_NOT_YET_IMPLEMENTED_EDGES = frozenset({"superclasses", "subclasses", "imports", "enclosing_scope"})

#: Inbound / reference edges deferred until an indexed reference backend lands.
_DEFERRED_REFERENCE_BACKEND_EDGES = frozenset(
    {
        "callers",
        "references",
        "read_by",
        "written_by",
        "passed_by",
        "imported_by",
        "overrides",
        "overridden_by",
        "decorated_by",
        "decorates",
    }
)


def edge_status(edge: str) -> str:
    """Classify *edge* into exactly one of the four edge statuses.

    The returned string is the canonical status value and doubles as the
    ``reason`` string ``expand`` emits for unsupported edges.

    Args:
        edge: The edge name to classify (e.g. ``"members"``, ``"callers"``).

    Returns:
        One of :data:`STATUS_IMPLEMENTED`, :data:`STATUS_NOT_YET_IMPLEMENTED`,
        :data:`STATUS_DEFERRED_REFERENCE_BACKEND`, or :data:`STATUS_UNKNOWN_EDGE`
        (for any name not present in the matrix).
    """
    if edge in _IMPLEMENTED_EDGES:
        return STATUS_IMPLEMENTED
    if edge in _NOT_YET_IMPLEMENTED_EDGES:
        return STATUS_NOT_YET_IMPLEMENTED
    if edge in _DEFERRED_REFERENCE_BACKEND_EDGES:
        return STATUS_DEFERRED_REFERENCE_BACKEND
    return STATUS_UNKNOWN_EDGE


# ---------------------------------------------------------------------------
# members resolver (spec §5.1)
# ---------------------------------------------------------------------------


def resolve_members(jedi_name: Any, analyzer: JediAnalyzer) -> list[Handle]:
    """Return the direct structural members of a container as canonical handles.

    Two distinct mechanisms are used (this divergence is intentional):

    - **class** → direct methods / nested classes / class-level attributes &
      properties DEFINED in the class (inherited excluded).  Jedi ``get_names``
      filtered by ``full_name`` prefix + exact depth.
    - **module** → top-level classes / functions / module-level variables
      DEFINED in the module.  Imports / re-exports are EXCLUDED (the deliberate
      divergence keeping ``members`` disjoint from the ``imports`` edge).
      AST top-level walk; ``ast.Import`` / ``ast.ImportFrom`` are skipped.
    - **non-container** (function / method / variable / attribute / property /
      …) → ``[]`` (measured: genuinely no members).

    Synchronous: Jedi ``get_names`` + AST walk + ``Handle`` construction are all
    sync, so the resolver is sync (a sync resolver called from async ``expand``
    is fine).

    Args:
        jedi_name: Resolved Jedi ``Name`` (or ``_ModuleSentinel``) for the
            container.  Container-ness is derived from its normalised kind.
        analyzer: Active analyzer (for the Jedi project used by ``get_script``).

    Returns:
        A list of canonical member :class:`Handle` objects, or ``[]`` for a
        non-container.
    """
    kind = _normalise_kind(getattr(jedi_name, "type", None))
    handle = getattr(jedi_name, "full_name", None)
    if not handle:
        return []

    if kind == "class":
        return _class_members(jedi_name, handle, analyzer)
    if kind == "module":
        return _module_members(jedi_name, handle)
    return []


def _class_members(jedi_name: Any, handle: str, analyzer: JediAnalyzer) -> list[Handle]:
    """Enumerate direct class members via Jedi prefix + exact-depth filtering.

    Args:
        jedi_name: Resolved Jedi ``Name`` for the class.
        handle: The class's canonical dotted-name handle.
        analyzer: Active analyzer (for the Jedi project).

    Returns:
        A list of canonical direct-member :class:`Handle` objects.
    """
    file_path = getattr(jedi_name, "module_path", None)
    if file_path is None:
        return []

    prefix = handle + "."
    handle_depth = len(handle.split("."))
    members: list[Handle] = []
    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        names = script.get_names(all_scopes=True, definitions=True, references=False)
    except Exception:
        return []

    seen: set[str] = set()
    for name in names:
        full_name = name.full_name or ""
        if not full_name.startswith(prefix):
            continue
        if len(full_name.split(".")) != handle_depth + 1:
            continue
        if full_name in seen:
            continue
        seen.add(full_name)
        members.append(Handle(full_name))
    return members


def _module_members(jedi_name: Any, handle: str) -> list[Handle]:
    """Enumerate top-level module members via an AST top-level walk.

    Iterates ``tree.body`` (TOP LEVEL only — never ``ast.walk``, which would
    descend into class bodies).  Imports are skipped entirely so re-exported
    names do not appear (keeping ``members`` disjoint from the ``imports`` edge).

    Args:
        jedi_name: Resolved Jedi ``Name`` (or ``_ModuleSentinel``) for the
            module — its ``module_path`` is the module file.
        handle: The module's canonical dotted-name handle.

    Returns:
        A list of canonical member :class:`Handle` objects for the module's
        top-level definitions.
    """
    file_path = getattr(jedi_name, "module_path", None)
    if file_path is None:
        return []

    try:
        tree = file_artifact_cache.get_ast(file_path)
    except Exception:
        return []

    member_names: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            member_names.append(name)

    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                _add(node.target.id)
        # ast.Import / ast.ImportFrom: skipped — the import-exclusion fix.

    return [Handle(f"{handle}.{name}") for name in member_names]


# ---------------------------------------------------------------------------
# Resolver registry
# ---------------------------------------------------------------------------

#: Maps *implemented* edge names → resolver callables.  Separate from the status
#: matrix on purpose: ``edge_status("callees") == "implemented"`` but ``callees``
#: has no resolver here yet (Phase 3 wires it in).
EDGE_RESOLVERS: dict[str, Callable[[Any, JediAnalyzer], list[Handle]]] = {
    "members": resolve_members,
}
