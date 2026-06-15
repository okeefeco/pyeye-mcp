"""Edge-status registry and structural edge resolvers for ``expand``.

This module is the **single source of truth** for which traversal edges
``expand`` supports.  It provides two distinct lookups:

1. :func:`edge_status` — classify any edge name into exactly one of four
   machine-distinguishable statuses.  The status string IS the ``reason``
   string ``expand`` emits for unsupported edges.
2. :data:`EDGE_RESOLVERS` / the resolver registry — maps *implemented* edge
   names (``members``, ``callees``, ``imported_by``, ``subclasses``,
   ``superclasses``) to their resolver callables.  ``members``/``callees``/
   ``superclasses`` are synchronous and always return an :class:`EdgeResult`;
   ``imported_by`` and ``subclasses`` are **async**.  ``imported_by`` returns
   ``EdgeResult | None`` — ``None`` is its wrong-kind signal (the handle is
   not a module).  ``subclasses`` and ``superclasses`` ALWAYS return an
   :class:`EdgeResult` (never ``None``): a non-class handle yields
   ``EdgeResult([])`` because only a class CAN be subclassed/have superclasses,
   so ``[]`` for the wrong kind is true by definition (the
   ``members``/``callees`` case), not the absence-vs-zero lie that forces
   ``imported_by``'s ``None`` path.  An :class:`EdgeResult` carries the
   adjacent canonical handles plus, for ``callees`` only, the count of
   unresolved call sites.  ``expand`` awaits any awaitable resolver result.

Status model (spec §4.3)
------------------------
==============================  =========================================
status                          edges
==============================  =========================================
``"implemented"``               ``members``, ``callees``, ``imported_by``,
                                ``subclasses``, ``superclasses``
``"not_yet_implemented"``       ``imports``, ``enclosing_scope``
``"deferred_reference_backend"``  ``callers``, ``references``, ``read_by``,
                                ``written_by``, ``passed_by``,
                                ``overrides``, ``overridden_by``,
                                ``decorated_by``, ``decorates``
(unrecognised name)             ``"unknown_edge"``
==============================  =========================================

Architectural constraint
-------------------------
This module MUST NOT import from ``inspect.py``.  ``inspect`` imports
:func:`resolve_members` to derive ``edge_counts.members`` (landed in Phase 5)
and :func:`resolve_superclasses` to derive ``edge_counts.superclasses``
(landed in Phase 6 / #361) — importing back from ``inspect`` here would
create a circular import.  ``resolve_members`` and ``resolve_superclasses``
are therefore the **sole** enumeration sources for their respective edges.

The ``members`` resolver is pure structural enumeration — it never calls
``get_references`` / ``find_references``.  The module path uses Jedi
``get_names(all_scopes=False)`` to enumerate top-level definitions, then
subtracts import-bound names from the AST — guaranteeing the only divergence
from the legacy count is import exclusion (spec §3.3).
"""

from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyeye import file_artifact_cache
from pyeye._ast_targets import attr_target_position, find_function_def_at_line
from pyeye._module_sentinel import ModuleSentinel
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

    Carries the adjacent ``(canonical handle, Jedi Name)`` pairs, plus — for
    ``callees`` only — the count of call sites that could not be statically
    resolved.  The Jedi ``Name`` is retained per adjacent so ``expand`` can
    build a stub WITHOUT re-resolving the handle (re-resolution is wasteful and
    unreliable for builtins such as ``builtins.float``).  The resolvers already
    hold the exact ``Name`` at the point they construct each ``Handle``, so they
    pass it through here.

    Attributes:
        adjacents: The adjacent ``(canonical Handle, Jedi Name)`` pairs
            (deduplicated by handle string, deterministic first-seen order).
            The ``Name`` is the one used to build the adjacent's stub.
        unresolved_call_sites: For ``callees``, the number of call sites whose
            target could not be resolved via forward ``goto`` (a count only —
            never a partial/invented handle).  ``None`` for edges where the
            notion does not apply (e.g. ``members``).
    """

    adjacents: list[tuple[Handle, Any]]
    unresolved_call_sites: int | None = None

    @property
    def handles(self) -> list[Handle]:
        """Return just the adjacent canonical handles, dropping the carried Names.

        Preserves the existing ``.handles`` accessor used by callers (the edges
        tests and the Phase-5 ``inspect`` member count) so the
        ``(handle, name)`` refactor stays backwards-compatible.
        """
        return [h for h, _ in self.adjacents]


# ---------------------------------------------------------------------------
# Edge status model (spec §4.3)
# ---------------------------------------------------------------------------

#: Status value strings — these ARE the ``reason`` strings ``expand`` emits.
STATUS_IMPLEMENTED = "implemented"
STATUS_NOT_YET_IMPLEMENTED = "not_yet_implemented"
STATUS_DEFERRED_REFERENCE_BACKEND = "deferred_reference_backend"
STATUS_UNKNOWN_EDGE = "unknown_edge"

#: Edges with a working (or Phase-3-bound) resolver.
_IMPLEMENTED_EDGES = frozenset({"members", "callees", "imported_by", "subclasses", "superclasses"})

#: Edges recognised by the matrix but not yet built (no reference backend needed).
_NOT_YET_IMPLEMENTED_EDGES = frozenset({"imports", "enclosing_scope"})

#: Inbound / reference edges deferred until an indexed reference backend lands.
_DEFERRED_REFERENCE_BACKEND_EDGES = frozenset(
    {
        "callers",
        "references",
        "read_by",
        "written_by",
        "passed_by",
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
        jedi_name: Resolved Jedi ``Name`` (or :class:`ModuleSentinel`) for the
            container.  Container-ness is derived from its normalised kind.
        analyzer: Active analyzer (for the Jedi project used by ``get_script``).

    Returns:
        An :class:`EdgeResult` whose ``adjacents`` are the canonical member
        ``(handle, Name)`` pairs (empty for a non-container).
        ``unresolved_call_sites`` is always ``None`` — that notion is
        callees-only.
    """
    kind = _normalise_kind(getattr(jedi_name, "type", None))
    handle = getattr(jedi_name, "full_name", None)
    if not handle:
        return EdgeResult(adjacents=[])

    if kind == "class":
        return EdgeResult(adjacents=_class_members(jedi_name, handle, analyzer))
    if kind == "module":
        return EdgeResult(adjacents=_module_members(jedi_name, handle, analyzer))
    return EdgeResult(adjacents=[])


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


def _class_members(jedi_name: Any, handle: str, analyzer: JediAnalyzer) -> list[tuple[Handle, Any]]:
    """Enumerate direct class members via Jedi prefix + exact-depth filtering.

    Each kept member is paired with the Jedi ``Name`` that produced it, so a
    caller (``expand``) can build the member's stub without re-resolving the
    handle.  Dedup is by handle string, keeping the FIRST ``Name`` seen.

    Args:
        jedi_name: Resolved Jedi ``Name`` for the class.
        handle: The class's canonical dotted-name handle.
        analyzer: Active analyzer (for the Jedi project).

    Returns:
        A list of ``(canonical Handle, Jedi Name)`` pairs for direct members.
    """
    file_path = getattr(jedi_name, "module_path", None)
    if file_path is None:
        return []

    prefix = handle + "."
    handle_depth = len(handle.split("."))
    members: list[tuple[Handle, Any]] = []
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
            members.append((h, name))
    return members


def _module_members(
    jedi_name: Any, handle: str, analyzer: JediAnalyzer
) -> list[tuple[Handle, Any]]:
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
        jedi_name: Resolved Jedi ``Name`` (or :class:`ModuleSentinel`) for the
            module — its ``module_path`` is the module file.
        handle: The module's canonical dotted-name handle.
        analyzer: Active analyzer (for the Jedi project used by ``get_script``).

    Returns:
        A list of ``(canonical Handle, Jedi Name)`` pairs for the module's
        top-level definitions, with all import-bound names removed.  Each member
        is paired with its producing ``Name`` so ``expand`` can build the stub
        without re-resolving.  Dedup is by handle string, keeping the first
        ``Name``.
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

    # Step 3: emit (handle, name) pairs for every non-import top-level name.
    members: list[tuple[Handle, Any]] = []
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
            members.append((h, name))
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

    Note: decorators on a nested ``def``/``class`` are part of that nested
    scope's subtree and are intentionally NOT attributed to the enclosing
    function — the entire nested-scope node (decorators included) is skipped.
    This is a documented design choice, not an oversight.

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
        An :class:`EdgeResult` with the deduplicated callee ``(handle, Name)``
        pairs and the unresolved-call-site count.  Non-function sources yield
        ``EdgeResult(adjacents=[], unresolved_call_sites=0)``.
    """
    kind = _normalise_kind(getattr(jedi_name, "type", None))
    # Jedi reports BOTH module-level functions AND methods (instance, class,
    # static) with ``type="function"``, so ``_normalise_kind`` yields
    # ``"function"`` for all of them.  This gate therefore INCLUDES methods and
    # @property getters — they are not excluded.  Only non-function kinds
    # (class, module, variable, …) short-circuit here.
    if kind != "function":
        return EdgeResult(adjacents=[], unresolved_call_sites=0)

    file_path = getattr(jedi_name, "module_path", None)
    line = getattr(jedi_name, "line", None)
    if file_path is None or line is None:
        return EdgeResult(adjacents=[], unresolved_call_sites=0)

    func_node = find_function_def_at_line(Path(file_path), line)
    if func_node is None:
        return EdgeResult(adjacents=[], unresolved_call_sites=0)

    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
    except Exception:
        return EdgeResult(adjacents=[], unresolved_call_sites=0)

    seen: set[str] = set()
    adjacents: list[tuple[Handle, Any]] = []
    unresolved = 0

    for call in _collect_direct_calls(func_node.body):
        target = _call_target_position(call.func)
        if target is None:
            # No single identifier to goto (e.g. f()(), subscript call).
            unresolved += 1
            continue
        resolved = _resolve_call_target(script, target)
        if resolved is None:
            unresolved += 1
            continue
        callee, callee_name = resolved
        if str(callee) in seen:
            continue  # dedup repeated calls — already counted, not unresolved
        seen.add(str(callee))
        adjacents.append((callee, callee_name))

    return EdgeResult(adjacents=adjacents, unresolved_call_sites=unresolved)


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


def _resolve_call_target(script: Any, target: tuple[int, int]) -> tuple[Handle, Any] | None:
    """Forward-resolve a call target's (line, col) to a ``(Handle, Name)`` pair.

    Uses ``script.goto(line, col, follow_imports=True)`` — the import-following
    landing IS the canonicalization for callees.  Returns the first def with a
    ``full_name`` as a ``(Handle, Name)`` pair (the Jedi def ``Name`` is carried
    so ``expand`` can build the callee's stub without re-resolving — important
    for builtins/stdlib callees).  Returns ``None`` when nothing resolves, no
    def has a ``full_name``, or ``Handle`` construction fails.

    Args:
        script: The cached Jedi ``Script`` for the call's file.
        target: ``(line, col)`` of the call's target identifier.

    Returns:
        A ``(canonical Handle, Jedi Name)`` pair, or ``None`` (caller counts as
        unresolved).
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
                return h, d
    return None


# ---------------------------------------------------------------------------
# imported_by resolver (spec §5.3) — pure-AST reverse import scan
# ---------------------------------------------------------------------------


async def resolve_imported_by(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult | None:
    """Return the modules that import a target module as canonical handles.

    The inbound ``imported_by`` edge for a **module** handle.  Reuses
    :meth:`JediAnalyzer.find_importers` — a pure-AST reverse import scan (no
    ``get_references`` / ``find_references``, the same load-bearing trust
    constraint as ``callees``).  ``find_importers`` already dedups by importer
    module and returns a deterministic sorted order, so the adjacents are unique
    and stable across runs and platforms without further processing here.

    Each adjacent's ``Name`` is built as a :class:`ModuleSentinel` from the
    importer's OWN FILE — never by re-resolving the importer handle.  That is
    deliberate: a non-package importer (a standalone ``script_importer.py`` at a
    project root) has no importable dotted path to re-resolve, so handle-based
    re-resolution would drop it.  Constructing the sentinel from the file the
    scan already returned keeps that breadth (#345).

    Kind gate (the load-bearing #332 distinction):

    - **module** → measured: ``EdgeResult`` with the importer handles (possibly
      empty if nobody imports it — a genuine measured "none", NOT an error).
    - **non-module** (class / function / variable / …) → ``None``.  A *symbol*
      CAN be imported, so returning ``EdgeResult([])`` would be the "measured
      zero" lie; ``None`` signals "this edge does not apply to this kind" and
      becomes ``not_yet_implemented`` downstream in ``expand`` (Phase 4).  The
      caller MUST distinguish ``None`` from ``EdgeResult([])``.

    Asynchronous: ``find_importers`` reads project files asynchronously, so this
    resolver is ``async``.  ``expand`` awaits awaitable resolver results; the
    sync ``members``/``callees`` resolvers are unaffected.

    Args:
        jedi_name: Resolved Jedi ``Name`` (or :class:`ModuleSentinel`) for the
            target.  Module-ness is derived from its normalised kind; the
            ``full_name`` / ``module_path`` are the dotted handle and file.
        analyzer: Active analyzer (provides ``find_importers``).

    Returns:
        An :class:`EdgeResult` whose ``adjacents`` are the importer
        ``(canonical Handle, ModuleSentinel)`` pairs (kind module) for a module
        target, or ``None`` for a non-module target.  ``unresolved_call_sites``
        is always ``None`` — that notion is callees-only.
    """
    if _normalise_kind(getattr(jedi_name, "type", None)) != "module":
        return None

    module_path = getattr(jedi_name, "full_name", None)
    target_file = getattr(jedi_name, "module_path", None)
    if not module_path or target_file is None:
        return EdgeResult(adjacents=[])

    importer_pairs = await analyzer.find_importers(module_path, Path(target_file), scope="all")

    adjacents: list[tuple[Handle, Any]] = []
    for importer_module, importer_file in importer_pairs:
        h = _try_handle(importer_module)
        if h is None:
            continue
        # Build the Name from the importer's FILE, not by re-resolving the
        # handle — re-resolution drops non-package scripts (see docstring).
        name = ModuleSentinel(importer_file, str(h), analyzer)
        adjacents.append((h, name))

    return EdgeResult(adjacents=adjacents)


# ---------------------------------------------------------------------------
# subclasses resolver (#348) — forward AST class-graph walk, async
# ---------------------------------------------------------------------------


def _subclass_name_from_file(
    subclass_file: str, subclass_fqn: str, analyzer: JediAnalyzer
) -> Any | None:
    """Produce a Jedi ``Name`` for *subclass_fqn* by enumerating its OWN file.

    Mirrors :func:`_class_members`' approach: enumerate the file's definitions
    via Jedi ``get_names`` and return the one whose ``full_name`` matches the
    subclass's AST-derived FQN.  This is deliberately NOT a dotted-handle
    re-resolution — re-resolution drops subclasses defined in non-importable
    files (a root-level ``script.py`` has no importable dotted path) and is
    fragile on macOS symlinked temp dirs.  Building the ``Name`` from the file
    the AST scan already located preserves that breadth and is path-independent.

    Args:
        subclass_file: Posix path to the file declaring the subclass (from the
            ``find_subclasses`` result dict).
        subclass_fqn: The subclass's AST-derived ``full_name`` (the canonical
            handle string to match against Jedi's ``full_name``).
        analyzer: Active analyzer (for the Jedi project used by ``get_script``).

    Returns:
        The matching Jedi ``Name``, or ``None`` if the file cannot be scanned or
        no enumerated definition's ``full_name`` matches (the caller drops the
        adjacency rather than inventing a partial stub).
    """
    try:
        script = file_artifact_cache.get_script(Path(subclass_file), analyzer.project)
        names = script.get_names(all_scopes=True, definitions=True, references=False)
    except Exception:
        return None

    for name in names:
        if (name.full_name or "") == subclass_fqn:
            return name
    return None


async def resolve_subclasses(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult:
    """Return the project classes that subclass a class as canonical handles.

    The outbound-but-reliably-static ``subclasses`` edge for a **class** handle.
    Reuses :meth:`JediAnalyzer.find_subclasses` — an AST class-graph walk +
    forward ``goto``/``resolve_canonical`` (NO ``get_references`` /
    ``find_references``, the same load-bearing trust constraint as ``callees`` /
    ``imported_by``).  The call shape (``scope="main"``, ``include_indirect=True``,
    ``show_hierarchy=False``) is IDENTICAL to ``inspect._count_subclasses`` so
    ``len(adjacents) == inspect(handle).edge_counts.subclasses``.  As a
    single-hop edge it intentionally returns the full project subclass closure
    (direct + indirect), a deliberate divergence from ``members``/``callees``
    direct-only semantics justified by that count/list consistency.

    Each adjacent's ``Name`` is built from the subclass's OWN FILE (via
    :func:`_subclass_name_from_file`) — never by re-resolving the dotted handle —
    so a subclass defined in a non-importable root-level script is preserved and
    resolution stays path-independent (#335 macOS symlink robustness).

    Kind gate (the slice's defining decision):

    - **class** → measured: ``EdgeResult`` with the subclass handles (possibly
      empty if the class has no project subclasses — a genuine measured "none").
    - **non-class** (function / variable / module / …) → ``EdgeResult([])``,
      NEVER ``None``.  Only a class CAN be subclassed, so ``[]`` for the wrong
      kind is true by definition (exactly the ``members``/``callees`` case) —
      NOT the absence-vs-zero lie that forces ``imported_by``'s ``None`` path.
      Because this resolver never returns ``None``, ``expand`` needs no change.

    Asynchronous: ``find_subclasses`` reads project files asynchronously, so
    this resolver is ``async``.  ``expand`` awaits awaitable resolver results.

    Args:
        jedi_name: Resolved Jedi ``Name`` for the target.  Class-ness is derived
            from its normalised kind; ``full_name`` is the dotted handle.
        analyzer: Active analyzer (provides ``find_subclasses``).

    Returns:
        An :class:`EdgeResult` whose ``adjacents`` are the subclass
        ``(canonical Handle, Jedi Name)`` pairs (kind class) for a class target,
        or ``EdgeResult([])`` for any non-class target.  ``unresolved_call_sites``
        is always ``None`` — that notion is callees-only.
    """
    if _normalise_kind(getattr(jedi_name, "type", None)) != "class":
        return EdgeResult(adjacents=[])

    handle = getattr(jedi_name, "full_name", None)
    if not handle:
        return EdgeResult(adjacents=[])

    # Identical call shape to inspect._count_subclasses so len(stubs) == the
    # measured edge_counts.subclasses (the progressive-disclosure contract).
    result = await analyzer.find_subclasses(
        handle,
        scope="main",
        include_indirect=True,
        show_hierarchy=False,
    )
    # An FQN input never triggers the ambiguous variant (as _count_subclasses
    # asserts).  Carry the same defensive assert so a future regression surfaces
    # loudly instead of silently yielding an empty list.
    assert not result.get(
        "ambiguous", False
    ), f"FQN input to find_subclasses returned ambiguous variant: {handle!r}"

    adjacents: list[tuple[Handle, Any]] = []
    seen: set[str] = set()
    for subclass in result.get("subclasses", []):
        fqn = subclass.get("full_name")
        subclass_file = subclass.get("file")
        if not fqn or not subclass_file:
            continue
        h = _try_handle(fqn)
        if h is None:
            continue
        key = str(h)
        if key in seen:
            continue
        # Build the Name from the subclass's FILE, not by re-resolving the
        # handle — re-resolution drops non-package scripts (see helper docstring).
        name = _subclass_name_from_file(subclass_file, fqn, analyzer)
        if name is None:
            # No Jedi Name for this subclass — drop the adjacency rather than
            # invent a partial stub (keeps len(stubs) honest).
            continue
        seen.add(key)
        adjacents.append((h, name))

    # find_subclasses builds its result by iterating a Python set, so
    # result["subclasses"] arrives in PYTHONHASHSEED-dependent order; the
    # first-seen dedup above inherits that instability.  The edge contract
    # requires deterministic order (identical subclass set AND order every run),
    # so sort by the canonical handle string here — mirroring how
    # resolve_imported_by relies on find_importers' already-sorted output.
    adjacents.sort(key=lambda pair: str(pair[0]))

    return EdgeResult(adjacents=adjacents)


# ---------------------------------------------------------------------------
# superclasses resolver (#361) — direct-base AST walk + forward goto, sync
# ---------------------------------------------------------------------------


def resolve_superclasses(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult:
    """Return the DIRECT superclasses of a class as canonical handles.

    The inbound-but-reliably-static ``superclasses`` edge for a **class**
    handle.  Returns only DIRECT bases (no MRO closure), mirroring the count
    in ``inspect.edge_counts.superclasses``.  This is a deliberate asymmetry
    with ``subclasses``, which returns the full project closure.

    Mechanics:

    1. Walk the class's cached AST to locate its ``ClassDef.bases`` — the
       declared direct bases (source order).
    2. For each base expression, call ``script.goto(line, col,
       follow_imports=True)`` with the position from
       :func:`attr_target_position`, preferring ``class``-kind results, so
       ``pkg.sub.ClassName`` resolves to the class, not the package.
    3. Keep the first goto def that has a ``full_name`` and builds a valid
       :class:`Handle`.  The goto ``Name`` is carried directly as the
       adjacent's ``Name`` (no re-resolution).
    4. Dedup by canonical handle string; sort by handle string for
       deterministic order (like ``resolve_subclasses``).
    5. Bases that produce no goto result with a ``full_name`` are DROPPED
       (can't build a valid stub without a ``Name``).  This is intentional —
       the count derives from this resolver (see ``inspect._count_superclasses``)
       so ``len(stubs) == inspect.edge_counts.superclasses`` is guaranteed by
       construction.

    Kind gate (the defining decision of this edge):

    - **class** → measured: ``EdgeResult`` with the direct-base handles
      (possibly empty if the class has no explicit bases — a genuine measured
      "none").
    - **non-class** (function / variable / module / …) → ``EdgeResult([])``,
      NEVER ``None``.  Only a class CAN have superclasses, so ``[]`` for the
      wrong kind is true by definition (exactly the ``members``/``callees``
      case) — NOT the absence-vs-zero lie that forces ``imported_by``'s
      ``None`` path.  Because this resolver never returns ``None``,
      ``expand.py`` needs no change.

    Synchronous: AST walk + per-base Jedi ``goto`` + ``Handle`` construction
    are all sync, like ``resolve_members``/``resolve_callees``.  No
    ``get_references`` / ``find_references`` is ever called.

    Args:
        jedi_name: Resolved Jedi ``Name`` for the target.  Class-ness is
            derived from its normalised kind; ``module_path`` and ``line``
            are used to locate the ``ClassDef`` node.
        analyzer: Active analyzer (for the Jedi project used by
            ``get_script``).

    Returns:
        An :class:`EdgeResult` whose ``adjacents`` are the direct base-class
        ``(canonical Handle, Jedi Name)`` pairs for a class target, sorted by
        handle string; or ``EdgeResult([])`` for any non-class target.
        ``unresolved_call_sites`` is always ``None`` — that notion is
        callees-only.
    """
    if _normalise_kind(getattr(jedi_name, "type", None)) != "class":
        return EdgeResult(adjacents=[])

    file_path = getattr(jedi_name, "module_path", None)
    line = getattr(jedi_name, "line", None)
    if file_path is None or line is None:
        return EdgeResult(adjacents=[])

    try:
        tree = file_artifact_cache.get_ast(file_path)
        script = file_artifact_cache.get_script(file_path, analyzer.project)
    except Exception:
        return EdgeResult(adjacents=[])

    # Locate the ClassDef at the class's definition line.
    class_node: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.lineno == line:
            class_node = node
            break
    if class_node is None or not class_node.bases:
        return EdgeResult(adjacents=[])

    seen: set[str] = set()
    adjacents: list[tuple[Handle, Any]] = []

    for base in class_node.bases:
        # Resolve the base AST node to a (line, col) position for goto.
        # attr_target_position returns the rightmost identifier in an
        # attribute chain (e.g. pkg.sub.ClassName → ClassName), so goto
        # lands on the class definition, not the package.
        try:
            base_line, base_col = attr_target_position(base)
        except Exception:
            # Unresolvable base expression (e.g. complex subscript) — drop.
            continue

        try:
            defs = script.goto(base_line, base_col, follow_imports=True)
        except Exception:
            continue

        # Prefer class-kind results; fall back to any named result.
        # This matches _resolve_base_class_via_jedi in inspect.py.
        class_defs = [d for d in defs if d.type == "class" and d.full_name]
        named_defs = [d for d in defs if d.full_name]
        candidates = class_defs if class_defs else named_defs

        for candidate in candidates:
            full_name = candidate.full_name
            if not full_name:
                continue
            h = _try_handle(full_name)
            if h is None:
                continue
            key = str(h)
            if key in seen:
                break  # dedup: first occurrence wins; skip remaining candidates
            seen.add(key)
            adjacents.append((h, candidate))
            break  # first valid candidate for this base is sufficient

    # Sort by canonical handle string for deterministic order across runs
    # (mirrors resolve_subclasses — set iteration order is PYTHONHASHSEED-
    # dependent, but here we walk bases in source order, which IS deterministic;
    # sorting is still applied for consistency with the subclasses contract).
    adjacents.sort(key=lambda pair: str(pair[0]))

    return EdgeResult(adjacents=adjacents)


# ---------------------------------------------------------------------------
# Resolver registry
# ---------------------------------------------------------------------------

#: Maps *implemented* edge names → resolver callables.  ``members``/``callees``/
#: ``superclasses`` are synchronous and always return an :class:`EdgeResult`;
#: ``imported_by`` and ``subclasses`` are async.  ``imported_by`` may return
#: ``None`` (its wrong-kind signal); ``subclasses`` and ``superclasses`` always
#: return an :class:`EdgeResult`` (non-class → ``EdgeResult([])``, never ``None``).
#: The value type therefore admits a sync-or-async resolver returning
#: ``EdgeResult | None`` so ``expand`` can stay edge-agnostic (awaiting
#: awaitable results, treating ``None`` as not-yet-implemented).
EDGE_RESOLVERS: dict[
    str, Callable[[Any, JediAnalyzer], EdgeResult | None | Awaitable[EdgeResult | None]]
] = {
    "members": resolve_members,
    "callees": resolve_callees,
    "imported_by": resolve_imported_by,
    "subclasses": resolve_subclasses,
    "superclasses": resolve_superclasses,
}
