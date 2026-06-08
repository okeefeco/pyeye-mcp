"""Edge-status registry and structural edge resolvers for ``expand``.

This module is the **single source of truth** for which traversal edges
``expand`` supports.  It provides two distinct lookups:

1. :func:`edge_status` — classify any edge name into exactly one of four
   machine-distinguishable statuses.  The status string IS the ``reason``
   string ``expand`` emits for unsupported edges.
2. :data:`EDGE_RESOLVERS` / the resolver registry — maps *implemented* edge
   names (``members``, ``callees``) to their resolver callables.  Each resolver
   is synchronous and returns an :class:`EdgeResult` (adjacent canonical handles
   plus, for ``callees`` only, the count of unresolved call sites).

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
``get_references`` / ``find_references``.  The module path uses Jedi
``get_names(all_scopes=False)`` to enumerate top-level definitions (same
source as ``inspect._count_module_members``), then subtracts import-bound
names from the AST — guaranteeing the only divergence from the legacy count
is import exclusion (spec §3.3).
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyeye import file_artifact_cache
from pyeye._ast_targets import attr_target_position, find_function_def_at_line
from pyeye.handle import Handle
from pyeye.mcp.operations.resolve import _normalise_kind

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


# ---------------------------------------------------------------------------
# Uniform resolver return type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeResult:
    """Result of an implemented edge resolver.

    Carries the adjacent canonical handles, plus — for ``callees`` only — the
    count of call sites that could not be statically resolved.

    Attributes:
        handles: The adjacent canonical :class:`Handle` objects (deduplicated,
            deterministic order).
        unresolved_call_sites: For ``callees``, the number of call sites whose
            target could not be resolved via forward ``goto`` (a count only —
            never a partial/invented handle).  ``None`` for edges where the
            notion does not apply (e.g. ``members``).
    """

    handles: list[Handle]
    unresolved_call_sites: int | None = None


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


def resolve_members(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult:
    """Return the direct structural members of a container as canonical handles.

    Two distinct mechanisms are used (this divergence is intentional):

    - **class** → direct methods / nested classes / class-level attributes &
      properties DEFINED in the class (inherited excluded).  Jedi ``get_names``
      filtered by ``full_name`` prefix + exact depth.
    - **module** → top-level definitions enumerated via Jedi
      ``get_names(all_scopes=False)`` (same source as the legacy
      ``inspect._count_module_members``), **minus** names bound by top-level
      ``import`` / ``from-import`` statements.  The ONLY divergence from the
      legacy count is import exclusion (spec §3.3) — all other definition forms
      (tuple-unpacking, annotated vars, guarded ``def``/``class``) are included.
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
        An :class:`EdgeResult` whose ``handles`` are the canonical member
        handles (empty for a non-container).  ``unresolved_call_sites`` is always
        ``None`` — that notion is callees-only.
    """
    kind = _normalise_kind(getattr(jedi_name, "type", None))
    handle = getattr(jedi_name, "full_name", None)
    if not handle:
        return EdgeResult(handles=[])

    if kind == "class":
        return EdgeResult(handles=_class_members(jedi_name, handle, analyzer))
    if kind == "module":
        return EdgeResult(handles=_module_members(jedi_name, handle, analyzer))
    return EdgeResult(handles=[])


def _try_handle(s: str) -> Handle | None:
    """Attempt to construct a :class:`Handle` from *s*, returning ``None`` on failure.

    Jedi occasionally yields names with non-identifier scope components such as
    ``<lambda>`` or ``<listcomp>`` that slip through kind-based filtering.
    Rather than crashing the entire resolver, we skip those per-member here.

    Args:
        s: Candidate handle string.

    Returns:
        A :class:`Handle` on success, or ``None`` if construction raises
        :exc:`ValueError`.
    """
    try:
        return Handle(s)
    except ValueError:
        return None


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
        h = _try_handle(full_name)
        if h is not None:
            members.append(h)
    return members


def _module_members(jedi_name: Any, handle: str, analyzer: JediAnalyzer) -> list[Handle]:
    """Enumerate top-level module members via Jedi ``get_names`` minus imports.

    Uses the same Jedi enumeration as the legacy ``inspect._count_module_members``
    (``get_names(all_scopes=False, definitions=True, references=False)``), then
    subtracts names bound by top-level ``import`` / ``from-import`` statements
    from the module's AST.  This guarantees the ONLY divergence from the legacy
    module-member count is **import exclusion** (spec §3.3): every definition form
    that Jedi counts (plain ``def``/``class``, tuple-unpacking assignments,
    annotated variables, defs/assignments guarded under ``if``/``try``/``with``/
    ``for``) is included, while imported names are excluded so ``members`` stays
    disjoint from the ``imports`` edge.

    Known gap: ``from x import *`` wildcards are ignored — their bound names are
    neither included nor excluded (rare in well-typed codebases).

    Args:
        jedi_name: Resolved Jedi ``Name`` (or ``_ModuleSentinel``) for the
            module — its ``module_path`` is the module file.
        handle: The module's canonical dotted-name handle.
        analyzer: Active analyzer (for the Jedi project used by ``get_script``).

    Returns:
        A list of canonical member :class:`Handle` objects for the module's
        top-level definitions, with all import-bound names removed.
    """
    file_path = getattr(jedi_name, "module_path", None)
    if file_path is None:
        return []

    try:
        # Step 1: enumerate top-level definitions the same way the legacy counter
        # does — this guarantees parity with inspect._count_module_members for
        # all definition forms (tuple-unpacking, guarded defs, annotated vars…).
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        names = script.get_names(all_scopes=False, definitions=True, references=False)

        # Step 2: build the set of names bound by top-level import statements.
        tree = file_artifact_cache.get_ast(file_path)
    except Exception:
        return []

    import_bound_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                # `import foo.bar` binds "foo"; `import foo as f` binds "f".
                import_bound_names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    # `from x import *` — unknown bound names; skip (known gap).
                    continue
                # `from x import y` binds "y"; `from x import y as z` binds "z".
                import_bound_names.add(alias.asname or alias.name)

    # Step 3: emit handles for every non-import top-level name.
    members: list[Handle] = []
    seen: set[str] = set()
    for name in names:
        if name.name in import_bound_names:
            continue
        full_name = name.full_name or f"{handle}.{name.name}"
        if full_name in seen:
            continue
        seen.add(full_name)
        h = _try_handle(full_name)
        if h is not None:
            members.append(h)
    return members


# ---------------------------------------------------------------------------
# callees resolver (spec §5.2)
# ---------------------------------------------------------------------------

#: Node types that open a NEW lexical scope — calls inside them belong to that
#: inner scope, not the enclosing function, so the call collector stops here.
_NESTED_SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _collect_direct_calls(body: list[ast.stmt]) -> list[ast.Call]:
    """Collect ``ast.Call`` nodes in *body*, NOT descending into nested scopes.

    Walks every statement in the function's body, recording each ``ast.Call`` it
    encounters, but stops at nested-scope boundaries (``FunctionDef`` /
    ``AsyncFunctionDef`` / ``Lambda`` / ``ClassDef``) — calls inside those belong
    to the inner scope's callees, not the enclosing function's.

    A ``Call``'s own children (its ``func`` and ``args``) ARE recursed, so
    ``foo(bar())`` yields both ``foo`` and ``bar``.  ``ast.walk`` is deliberately
    NOT used (it descends through everything, ignoring scope boundaries).

    Args:
        body: The statement list of the function body (``func_node.body``).

    Returns:
        The direct ``ast.Call`` nodes in source order.
    """
    calls: list[ast.Call] = []

    def _recurse(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _NESTED_SCOPE_TYPES):
                # New scope — its calls are its own; do not descend.
                continue
            if isinstance(child, ast.Call):
                calls.append(child)
            _recurse(child)

    for stmt in body:
        # Top-level body statements cannot themselves be a bare Call expr without
        # an Expr wrapper, but guard anyway for symmetry with the recursion.
        if isinstance(stmt, _NESTED_SCOPE_TYPES):
            continue
        if isinstance(stmt, ast.Call):
            calls.append(stmt)
        _recurse(stmt)
    return calls


def resolve_callees(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult:
    """Return the outbound callees of a function/method as canonical handles.

    Forward resolution only: ONE ``goto`` per call site.  This NEVER touches
    ``get_references`` / ``find_references`` (the non-deterministic reverse-search
    path) — that is the load-bearing trust constraint for this edge.

    Mechanics (spec §5.2):

    1. Locate the def node at ``jedi_name.line`` in the function's cached AST.
    2. Collect ``ast.Call`` nodes within ``func_node.body``, stopping at nested
       scope boundaries (a nested function/lambda/class's calls are its own).
    3. For each call, compute the target identifier's (line, col) from
       ``call.func`` and ``script.goto(line, col, follow_imports=True)`` — the
       ``follow_imports`` landing IS the canonicalization.  Builtins/stdlib
       callees are included.
    4. Dedup by handle string (deterministic first-seen order).
    5. Count call sites that ``goto`` could not resolve (no def, no ``full_name``,
       ``Handle`` construction failure, or a ``call.func`` with no single
       identifier to goto) as ``unresolved_call_sites`` — a COUNT only.

    Synchronous (AST walk + per-call Jedi ``goto`` + ``Handle`` construction).

    Args:
        jedi_name: Resolved Jedi ``Name`` for the source symbol.  Only
            ``function``-kind sources have callees.
        analyzer: Active analyzer (for the Jedi project used by ``get_script``).

    Returns:
        An :class:`EdgeResult` with the deduplicated callee handles and the
        unresolved-call-site count.  Non-function sources yield
        ``EdgeResult(handles=[], unresolved_call_sites=0)``.
    """
    kind = _normalise_kind(getattr(jedi_name, "type", None))
    if kind != "function":
        return EdgeResult(handles=[], unresolved_call_sites=0)

    file_path = getattr(jedi_name, "module_path", None)
    line = getattr(jedi_name, "line", None)
    if file_path is None or line is None:
        return EdgeResult(handles=[], unresolved_call_sites=0)

    func_node = find_function_def_at_line(Path(file_path), line)
    if func_node is None:
        return EdgeResult(handles=[], unresolved_call_sites=0)

    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
    except Exception:
        return EdgeResult(handles=[], unresolved_call_sites=0)

    seen: set[str] = set()
    handles: list[Handle] = []
    unresolved = 0

    for call in _collect_direct_calls(func_node.body):
        target = _call_target_position(call.func)
        if target is None:
            # No single identifier to goto (e.g. f()(), subscript call).
            unresolved += 1
            continue
        callee = _resolve_call_target(script, target)
        if callee is None:
            unresolved += 1
            continue
        if str(callee) in seen:
            continue  # dedup repeated calls — already counted, not unresolved
        seen.add(str(callee))
        handles.append(callee)

    return EdgeResult(handles=handles, unresolved_call_sites=unresolved)


def _call_target_position(func: ast.expr) -> tuple[int, int] | None:
    """Return the (line, col) to ``goto`` for a call target, or ``None``.

    For ``ast.Name`` → the name's own position.  For ``ast.Attribute`` → the
    rightmost identifier (via :func:`attr_target_position`), so ``obj.method()``
    resolves ``method`` rather than the receiver ``obj``.  For any other form
    (e.g. ``f()()``, a subscript) there is no single identifier to goto.

    Args:
        func: The ``call.func`` expression node.

    Returns:
        A ``(line, col)`` tuple, or ``None`` when no single identifier applies.
    """
    if isinstance(func, (ast.Name, ast.Attribute)):
        return attr_target_position(func)
    return None


def _resolve_call_target(script: Any, target: tuple[int, int]) -> Handle | None:
    """Forward-resolve a call target's (line, col) to a canonical :class:`Handle`.

    Uses ``script.goto(line, col, follow_imports=True)`` — the import-following
    landing IS the canonicalization for callees.  Returns the first def with a
    ``full_name`` as a :class:`Handle`, or ``None`` when nothing resolves, no
    def has a ``full_name``, or ``Handle`` construction fails.

    Args:
        script: The cached Jedi ``Script`` for the call's file.
        target: ``(line, col)`` of the call's target identifier.

    Returns:
        A canonical :class:`Handle`, or ``None`` (caller counts as unresolved).
    """
    line, col = target
    try:
        defs = script.goto(line, col, follow_imports=True)
    except Exception:
        return None
    for d in defs:
        full_name = getattr(d, "full_name", None)
        if full_name:
            h = _try_handle(full_name)
            if h is not None:
                return h
    return None


# ---------------------------------------------------------------------------
# Resolver registry
# ---------------------------------------------------------------------------

#: Maps *implemented* edge names → resolver callables.  Each resolver is
#: synchronous and returns an :class:`EdgeResult` (uniform across edges so
#: ``expand`` stays edge-agnostic).
EDGE_RESOLVERS: dict[str, Callable[[Any, JediAnalyzer], EdgeResult]] = {
    "members": resolve_members,
    "callees": resolve_callees,
}
