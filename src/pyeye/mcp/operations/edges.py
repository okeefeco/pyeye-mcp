"""Edge-status registry and structural edge resolvers for ``expand``.

This module is the **single source of truth** for which traversal edges
``expand`` supports.  It provides two distinct lookups:

1. :func:`edge_status` — classify any edge name into exactly one of four
   machine-distinguishable statuses.  The status string IS the ``reason``
   string ``expand`` emits for unsupported edges.
2. :data:`EDGE_RESOLVERS` / the resolver registry — maps *implemented* edge
   names (``members``, ``callees``, ``imported_by``, ``subclasses``,
   ``superclasses``, ``imports``, ``enclosing_scope``, ``submodules``) to their
   resolver callables.  ``members``/``callees``/``superclasses``/``imports``/
   ``enclosing_scope``/``submodules`` are synchronous and always return an
   :class:`EdgeResult` or ``None``; ``imported_by`` and ``subclasses`` are
   **async**.  ``imported_by`` and ``imports`` return ``EdgeResult | None``
   — ``None`` is their wrong-kind signal (the handle is not a module).
   ``subclasses``, ``superclasses``, and ``enclosing_scope`` ALWAYS return an
   :class:`EdgeResult` (never ``None``): a module handle yields
   ``EdgeResult([])`` for ``enclosing_scope`` because modules have no lexical
   enclosing scope; non-class handles yield ``EdgeResult([])`` for
   ``subclasses``/``superclasses``.  An :class:`EdgeResult` carries the
   adjacent canonical handles plus, for ``callees`` only, the count of
   unresolved call sites.  ``expand`` awaits any awaitable resolver result.

Status model (spec §4.3)
------------------------
==============================  =========================================
status                          edges
==============================  =========================================
``"implemented"``               ``members``, ``callees``, ``imported_by``,
                                ``subclasses``, ``superclasses``,
                                ``imports``, ``enclosing_scope``,
                                ``submodules``
``"not_yet_implemented"``       *(currently empty — all recognised edges
                                are implemented)*
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
from typing import TYPE_CHECKING, Any, NamedTuple

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


class _SubmoduleEntry(NamedTuple):
    """One DIRECT child of a package, derived from a pure directory scan.

    Produced by :func:`_enumerate_submodule_paths` — the single containment
    source-of-truth for the ``submodules`` edge (#423).  Each field comes from
    ``iterdir`` metadata only (name / suffix / ``is_dir`` / ``exists``); NO file
    is read, so a later task can ``len()`` the list as a cheap count.

    Attributes:
        handle: The child's dotted handle (parent ``full_name`` + ``.`` + the
            child's name), e.g. ``"mypkg.alpha"``.
        file: The on-disk path that *anchors* the child — ``X.py`` for a module,
            ``X/__init__.py`` for a regular subpackage, or the bare ``X/``
            directory for a PEP 420 namespace subpackage.
        is_subpackage: ``True`` for a (regular or namespace) subpackage, ``False``
            for a plain module child.
    """

    handle: str
    file: Path
    is_subpackage: bool


# ---------------------------------------------------------------------------
# Edge status model (spec §4.3)
# ---------------------------------------------------------------------------

#: Status value strings — these ARE the ``reason`` strings ``expand`` emits.
STATUS_IMPLEMENTED = "implemented"
STATUS_NOT_YET_IMPLEMENTED = "not_yet_implemented"
STATUS_DEFERRED_REFERENCE_BACKEND = "deferred_reference_backend"
STATUS_UNKNOWN_EDGE = "unknown_edge"

#: Edges with a working (or Phase-3-bound) resolver.
_IMPLEMENTED_EDGES = frozenset(
    {
        "members",
        "callees",
        "imported_by",
        "subclasses",
        "superclasses",
        "imports",
        "enclosing_scope",
        "submodules",
    }
)

#: Edges recognised by the matrix but not yet built (no reference backend needed).
#: Currently empty — all recognised structural edges are implemented.  The set
#: is retained so the 4-status taxonomy remains consistent for future additions.
_NOT_YET_IMPLEMENTED_EDGES: frozenset[str] = frozenset()

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

    Static-surface ceiling: members are enumerated from source.  Runtime-injected
    members (metaclass / ``setattr`` / ``__getattr__`` / ``type()`` /
    ``__init_subclass__``) are NOT captured — e.g. a Django ``Model`` returns none
    of its metaclass-injected ``_meta`` / ``objects`` / ``DoesNotExist``.  This is
    the same static-only boundary ``resolve_imported_by`` carries for dynamic
    imports; ``[]`` therefore means "no statically-defined members," not "no
    members at runtime."

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
    ``imported_by``).  ``subclasses`` is an **expand-only** edge: ``inspect``
    does NOT measure it (dropped in #392; a cheap direct count is gated on the
    Pyright reference backend / class-graph cache — #333/#397 — because even the
    DIRECT count needs the same project-wide scan, exactly like ``callers`` /
    ``references``).

    Single-hop semantics (#422): ``expand`` walks ONE edge to the IMMEDIATE
    neighbours, so this resolver returns the **DIRECT** subclasses only (depth 1,
    ``include_indirect=False``) — symmetric with ``superclasses`` (direct bases).
    The full transitive closure is served exclusively by
    ``trace(follow=["subclasses"], max_depth=k, max_nodes=N)``, which already owns
    the cap + ``truncated`` contract; ``expand`` carries a static pointer to that
    route.  (Before #422 this returned the full direct+indirect closure, which
    overflowed the MCP token cap on widely-subclassed bases and collapsed trace's
    per-hop BFS onto depth 1.)

    Static-surface ceiling: the result is "complete" only over literal
    ``class B(A):`` subclassing.  Dynamically-created subclasses
    (``type('B', (A,), {})``, factory-built classes, ``__init_subclass__``
    registration) are NOT captured — the same static-only boundary
    ``resolve_imported_by`` carries for dynamic imports.  ``[]`` therefore means
    "no statically-declared direct subclasses," not "no subclasses at runtime."

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

    # Project-internal DIRECT subclasses only (#422), project-scoped.  ``expand``
    # walks ONE edge to the IMMEDIATE neighbours, so ``subclasses`` returns the
    # depth-1 children — symmetric with ``superclasses`` (direct bases).  The full
    # transitive closure is served by ``trace(follow=["subclasses"], max_depth=k)``,
    # which already owns the cap + ``truncated`` contract; routing it there also
    # makes trace's per-hop BFS correct (a closure-per-hop resolver collapsed the
    # whole closure onto depth 1).
    result = await analyzer.find_subclasses(
        handle,
        scope="main",
        include_indirect=False,
        show_hierarchy=False,
    )
    # An FQN input never triggers the ambiguous variant.  Carry a defensive
    # assert so a future regression surfaces loudly instead of silently yielding
    # an empty list.
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
    in ``inspect.edge_counts.superclasses``.  Symmetric with ``subclasses``,
    which also returns DIRECT children only since #422 (expand = one hop in
    both inheritance directions; the closure is served by ``trace``).

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
# imports resolver (#367) — top-level AST import nodes + forward goto, sync
# ---------------------------------------------------------------------------


def resolve_imports(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult | None:
    """Return the top-level imports of a module as canonical handles.

    The outbound ``imports`` edge — the FORWARD complement of ``imported_by``
    (#345).  Walks the module's TOP-LEVEL ``ast.Import`` and
    ``ast.ImportFrom`` statements and, for each imported name, forward-resolves
    via ``script.goto(line, col, follow_imports=True)`` to obtain the canonical
    handle and Jedi ``Name``.  This is the same forward-goto mechanic as
    ``resolve_superclasses``/``resolve_callees`` — NO ``get_references``/
    ``find_references`` anywhere on this path.

    Kind gate (mirrors ``resolve_imported_by``):

    - **module** → measured: ``EdgeResult`` with the imported handles (possibly
      empty if the module has no top-level imports — a genuine measured "none",
      NOT an error).
    - **non-module** (class / function / variable / …) → ``None``.  A non-module
      CAN contain local imports, so returning ``EdgeResult([])`` would be the
      "measured zero" lie; ``None`` signals "this edge does not apply to this
      kind" and becomes ``not_yet_implemented`` downstream in ``expand`` /
      treated as no-adjacents in ``trace._single_hop`` — those paths already
      handle ``None`` correctly and require NO modification.

    Positioning logic (verified against real Jedi):

    - ``import foo`` / ``import foo as f`` → goto ``alias.col_offset``
      (the start of the import name, which points to the whole dotted name's
      first component; ``follow_imports=True`` resolves to the target module).
    - ``import foo.bar.baz`` → goto the RIGHTMOST identifier: col =
      ``alias.col_offset + len(alias.name) - len(alias.name.split(".")[-1])``
      so goto lands on ``baz`` and resolves to ``foo.bar.baz``.
    - ``from foo import bar`` / ``from foo import bar as b`` → goto
      ``alias.col_offset`` (the imported name's position; resolves to the
      target symbol or module).
    - ``from . import x`` (relative) → same: goto ``alias.col_offset``.
    - ``from foo import *`` → SKIP (cannot enumerate targets without running
      the wildcard; mirrors ``_module_members``'s wildcard gap).

    Unresolvable imports (goto yields no def / no ``full_name`` / ``Handle``
    construction failure) are DROPPED — cannot build a stub without a Name.

    Dedup by canonical handle string; deterministic order (sorted by handle
    string, mirroring ``resolve_subclasses``/``resolve_superclasses``).

    Synchronous: cached AST walk + per-import Jedi ``goto`` + ``Handle``
    construction are all sync.  No ``get_references``/``find_references`` is
    ever called.

    Args:
        jedi_name: Resolved Jedi ``Name`` (or :class:`ModuleSentinel`) for the
            target.  Module-ness is derived from its normalised kind; the
            ``module_path`` is the module's source file.
        analyzer: Active analyzer (for the Jedi project used by ``get_script``).

    Returns:
        An :class:`EdgeResult` whose ``adjacents`` are the imported
        ``(canonical Handle, Jedi Name)`` pairs for a module target, sorted by
        handle string; or ``None`` for a non-module target.
        ``unresolved_call_sites`` is always ``None`` — that notion is
        callees-only.
    """
    if _normalise_kind(getattr(jedi_name, "type", None)) != "module":
        return None

    file_path = getattr(jedi_name, "module_path", None)
    if file_path is None:
        return EdgeResult(adjacents=[])

    try:
        tree = file_artifact_cache.get_ast(file_path)
        script = file_artifact_cache.get_script(file_path, analyzer.project)
    except Exception:
        return EdgeResult(adjacents=[])

    seen: set[str] = set()
    adjacents: list[tuple[Handle, Any]] = []

    # ``_resolve_call_target`` (shared with ``resolve_callees``) is a
    # domain-neutral ``goto(follow_imports=True)`` → ``(Handle, Name)`` wrapper;
    # the goto mechanic for an import target is identical to that for a call
    # target, so it is reused here despite the callee-flavoured name.
    for node in tree.body:
        if isinstance(node, ast.Import):
            # ``import foo`` / ``import foo.bar`` / ``import foo as f``
            # → goto the RIGHTMOST identifier of the dotted module name so
            #   Jedi resolves to the full module path, not just the top package.
            for alias in node.names:
                last = alias.name.split(".")[-1]
                col = alias.col_offset + len(alias.name) - len(last)
                pair = _resolve_call_target(script, (alias.lineno, col))
                if pair is None:
                    continue
                h, name = pair
                key = str(h)
                if key in seen:
                    continue
                seen.add(key)
                adjacents.append((h, name))

        elif isinstance(node, ast.ImportFrom):
            # ``from foo import bar`` / ``from foo import bar as b``
            # ``from . import x`` (relative)
            # ``from foo import *`` → SKIP (cannot enumerate wildcard targets)
            for alias in node.names:
                if alias.name == "*":
                    continue
                # alias.col_offset is the column of the imported name itself
                # (Jedi resolves the symbol/module at that position).
                pair = _resolve_call_target(script, (alias.lineno, alias.col_offset))
                if pair is None:
                    continue
                h, name = pair
                key = str(h)
                if key in seen:
                    continue
                seen.add(key)
                adjacents.append((h, name))

    # Sort by canonical handle string for deterministic order (mirrors
    # resolve_subclasses / resolve_superclasses).
    adjacents.sort(key=lambda pair: str(pair[0]))

    return EdgeResult(adjacents=adjacents)


# ---------------------------------------------------------------------------
# enclosing_scope resolver (#370) — Jedi parent() navigation, sync
# ---------------------------------------------------------------------------


def resolve_enclosing_scope(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult:
    """Return the immediate lexical enclosing scope of a symbol as a canonical handle.

    The inverse of ``members``: where ``members`` enumerates a container's
    direct children, ``enclosing_scope`` returns the one parent scope.  At most
    ONE adjacent is returned:

    - **method** → its class.
    - **nested class** → its enclosing class.
    - **nested function** → its enclosing function.
    - **top-level def/class/variable** → its module.
    - **module** → ``EdgeResult([])`` (a module has no enclosing LEXICAL scope;
      Python packages are NOT lexical scopes — that is the ``package`` concept).

    Resolution uses ``jedi_name.parent()`` — the Jedi ``Name`` for the adjacent
    scope — NOT dotted-name string arithmetic.  String arithmetic cannot see
    class nesting (the #337 lesson applied here): for ``pkg.Outer.Inner.method``
    the arithmetic would mis-identify ``Outer`` as a module, failing to find it.
    ``parent()`` returns the true lexical parent at any nesting depth.

    See also: ``inspect._is_method`` uses the same ``jedi_name.parent()`` Jedi
    API for method-vs-function classification (method detection, #337).

    Synchronous: ``parent()`` is a pure Jedi API call (no file I/O); ``Handle``
    construction is synchronous.  No ``get_references`` / ``find_references`` is
    ever called.

    Args:
        jedi_name: Resolved Jedi ``Name`` (or :class:`ModuleSentinel`) for the
            target.  Module-ness is derived from its normalised kind; for a
            module the resolver returns immediately with ``EdgeResult([])``.
        analyzer: Active analyzer (unused except for structural consistency with
            all other resolver signatures — the parent() API is self-contained).

    Returns:
        An :class:`EdgeResult` whose ``adjacents`` is a single-element list
        ``[(Handle, parent_Name)]`` for any non-module symbol, or ``[]`` for a
        module handle or any symbol whose parent cannot be resolved (defensive
        empty — callers can rely on the absence-vs-zero invariant).
        ``unresolved_call_sites`` is always ``None`` — that notion is
        callees-only.  NEVER returns ``None``.
    """
    _ = analyzer  # unused: kept for the EDGE_RESOLVERS (jedi_name, analyzer) signature contract
    # Module gate: a module has no lexical enclosing scope.  Gate on kind BEFORE
    # calling parent() — a ModuleSentinel may not have a parent() method at all.
    if _normalise_kind(getattr(jedi_name, "type", None)) == "module":
        return EdgeResult(adjacents=[])

    # Retrieve the parent Jedi Name via the Jedi API (not dotted-name arithmetic).
    try:
        parent = jedi_name.parent()
    except Exception:
        return EdgeResult(adjacents=[])

    if parent is None:
        return EdgeResult(adjacents=[])

    # Build the Handle from the parent's full_name.
    full_name = getattr(parent, "full_name", None)
    if not full_name:
        return EdgeResult(adjacents=[])

    h = _try_handle(full_name)
    if h is None:
        return EdgeResult(adjacents=[])

    return EdgeResult(adjacents=[(h, parent)])


# ---------------------------------------------------------------------------
# submodules edge (#423) — package → on-disk directory base case
# ---------------------------------------------------------------------------


def _package_dirs(jedi_name: Any, analyzer: JediAnalyzer) -> list[Path]:
    """Return the on-disk directories a *package* handle maps to.

    This is the base case the ``submodules`` enumerator (Task 3) builds on: a
    package handle is resolved to the directory (or directories) whose children
    are its candidate submodules / subpackages.

    The regular-vs-namespace decision is made **once**, here, by inspecting the
    resolved handle's ``module_path``:

    - ends in ``__init__.py`` → **regular package** → return the SINGLE parent
      directory of that ``__init__.py`` (a regular package has exactly one
      on-disk directory).
    - a ``.py`` ``module_path`` that is not ``__init__.py`` → a plain module or
      a class/function handle (defined in some ``X.py``) → NOT a package → ``[]``.
    - otherwise (``None`` or a directory ``module_path``) → the **namespace
      branch**.  A PEP 420 namespace package has no ``__init__.py`` and may be
      spread across several portions; its directory(ies) are found by matching
      the dotted ``full_name`` under each :func:`_analyzer_roots` root.

    The namespace branch returns the **union** of the matching portion
    directories in ``roots`` (sys.path precedence) order — a regular package
    portion (one carrying ``__init__.py``) is excluded, and the order is what
    :func:`_enumerate_submodule_paths` rides on for first-portion-wins collision
    determinism (#419 class).

    A ``None``/empty ``full_name`` (e.g. a builtin or unresolved handle with no
    matching root dir) yields ``[]``.

    Args:
        jedi_name: Resolved Jedi ``Name`` or :class:`ModuleSentinel`.  Its
            ``module_path`` drives the regular-vs-namespace split; its
            ``full_name`` seeds the namespace-portion directory match.
        analyzer: Active analyzer.  The namespace branch consults
            :func:`_analyzer_roots` (``source_roots`` / ``project_path`` /
            ``added_sys_path``).

    Returns:
        For a regular package, a single-element ``[<package dir>]``.  For a
        namespace package, the union of its portion directories in roots order.
        For any non-package handle (plain module, class/function, or an
        unmatched ``full_name``), ``[]``.
    """
    module_path = getattr(jedi_name, "module_path", None)
    if module_path is not None:
        module_path = Path(module_path)
        if module_path.name == "__init__.py":
            # Regular package: exactly one on-disk directory — the __init__'s parent.
            return [module_path.parent]
        if module_path.suffix == ".py":
            # A plain X.py module or a class/function handle (defined in some
            # X.py) — NOT a package.  Stays [] permanently; never a namespace.
            return []
        # A directory module_path (some namespace handles) falls through to the
        # namespace branch below.

    # Namespace branch — PEP 420 portion union (first-portion-wins on name
    # collisions).  A namespace package has no __init__.py, so Jedi gives it a
    # None (or directory) module_path; its directory is found by matching the
    # dotted handle under each sys.path root.
    full_name = getattr(jedi_name, "full_name", None)
    if not full_name:
        return []

    parts = full_name.split(".")
    dirs: list[Path] = []
    seen: set[str] = set()
    for root in _analyzer_roots(analyzer):
        candidate = root.joinpath(*parts)
        try:
            if not candidate.is_dir():
                continue
            if (candidate / "__init__.py").exists():
                # A regular package portion is not a namespace portion.
                continue
        except OSError:
            continue
        if not _dir_shallow_qualifies(candidate):
            continue
        key = candidate.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        dirs.append(candidate)
    return dirs


def _analyzer_roots(analyzer: JediAnalyzer) -> list[Path]:
    """Return the analyzer's sys.path-precedence-ordered package roots.

    Built **list-derived** (never set-derived) from ``source_roots``,
    ``project_path``, and ``added_sys_path`` so the order is stable run-to-run.
    The order is the namespace collision-winner's determinism guarantee: the
    first root holding a portion wins (first-portion-wins, #419 class).  Duplicate
    roots are dropped, keeping the first (highest-precedence) occurrence.
    """
    # roots order = sys.path precedence; collision-winner determinism depends on
    # it (#419 class).  source_roots (src-layout) and project_path come before
    # the configured added_sys_path package roots.
    ordered: list[Path] = [*analyzer.source_roots, analyzer.project_path, *analyzer.added_sys_path]
    roots: list[Path] = []
    seen: set[str] = set()
    for root in ordered:
        key = root.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _dir_shallow_qualifies(path: Path) -> bool:
    """Return whether *path* looks like an importable dir (the §3.5 filter).

    This separates PEP 420 namespace subpackages from obvious junk/data dirs
    WITHOUT reading any file.  The check is deliberately **shallow and capped at
    one extra level** — it is NOT a recursive "any ``.py`` anywhere" walk (which
    would be both slow and over-eager).

    A directory qualifies iff, among its DIRECT entries, ANY of:

    - **(a)** a direct ``*.py`` file; or
    - **(b)** a direct child dir containing an ``__init__.py`` (a regular
      subpackage one level down); or
    - **(c)** a direct child dir that *itself* shallow-qualifies — checked with
      ``_recurse=False`` so the recursion stops after exactly ONE extra level
      (a namespace subpackage one level down).

    Purpose: skip junk such as a ``data/`` dir holding only ``notes.txt`` or a
    ``__pycache__`` dir holding only ``.pyc`` files.  NO file reads — ``iterdir``,
    ``.suffix``, ``.is_dir`` / ``.is_file`` and ``.exists`` only.

    Args:
        path: The candidate directory.

    Returns:
        ``True`` if *path* qualifies as an importable dir per the rules above,
        else ``False`` (including when *path* is unreadable).
    """
    return _dir_shallow_qualifies_capped(path, _recurse=True)


def _dir_shallow_qualifies_capped(path: Path, *, _recurse: bool) -> bool:
    """Back the :func:`_dir_shallow_qualifies` filter with an explicit recursion cap.

    ``_recurse`` is consumed on the FIRST extra level: the rule-(c) descent calls
    this helper with ``_recurse=False``, so a grandchild dir can only satisfy
    rules (a)/(b) — never trigger a further descent.  This caps the total depth
    at one extra level (see the public wrapper's docstring for the rule list).

    Args:
        path: The candidate directory.
        _recurse: Whether a rule-(c) one-level descent is still permitted.

    Returns:
        ``True`` if *path* qualifies, else ``False`` (including on read errors).
    """
    try:
        entries = list(path.iterdir())
    except OSError:
        return False

    for entry in entries:
        name = entry.name
        if name.startswith(".") or name == "__pycache__":
            continue
        # (a) a direct .py file.
        if entry.is_file() and entry.suffix == ".py":
            return True
        if entry.is_dir():
            # (b) a direct child dir that is a regular package.
            if (entry / "__init__.py").exists():
                return True
            # (c) a direct child dir that itself shallow-qualifies — but only
            # one extra level deep (cap: _recurse=False on the descent).
            if _recurse and _dir_shallow_qualifies_capped(entry, _recurse=False):
                return True
    return False


def _enumerate_submodule_paths(jedi_name: Any, analyzer: JediAnalyzer) -> list[_SubmoduleEntry]:
    """Enumerate a package's DIRECT children from a PURE directory scan (#423).

    This is the single containment source-of-truth for the ``submodules`` edge:
    given a package handle, it returns its direct module / subpackage children as
    :class:`_SubmoduleEntry` tuples, derived ENTIRELY from ``iterdir`` metadata —
    NO file is read (so a later task can ``len()`` this list as a cheap count).

    The package-vs-non-package decision and the directory resolution are both
    delegated to :func:`_package_dirs` (no duplication): a non-package handle
    (plain module, class/function, ``None``) yields ``[]`` because
    ``_package_dirs`` yields ``[]``.  The enumerator loops over EVERY directory
    ``_package_dirs`` returns; for Task 3 that is at most one (the regular case),
    but iterating already prepares for Task 4's multi-portion namespace union
    (which extends ``_package_dirs`` + adds cross-directory dedup, not this body).

    Per directory, scanning DIRECT entries only (one ``iterdir``), with
    ``__pycache__`` and dot-names always skipped:

    - ``X.py`` (``X != "__init__"``) → module child, ``file = X.py``,
      ``is_subpackage=False``.
    - ``X/`` with ``X/__init__.py`` → regular subpackage, ``file = X/__init__.py``,
      ``is_subpackage=True``.
    - ``X/`` with no ``__init__.py`` that :func:`_dir_shallow_qualifies` →
      namespace subpackage, ``file = X/`` (the directory itself),
      ``is_subpackage=True``.

    The parent handle for building child handles is the resolved name's
    ``full_name`` (e.g. parent ``"mypkg"`` + child ``alpha`` → ``"mypkg.alpha"``).
    The result is sorted by child name (the last dotted component) for
    determinism.

    Args:
        jedi_name: Resolved Jedi ``Name`` or :class:`ModuleSentinel`.  Its
            ``full_name`` seeds the child handles; ``_package_dirs`` resolves it
            to the directory(ies) scanned.
        analyzer: Active analyzer (passed through to :func:`_package_dirs`).

    Returns:
        The direct children as :class:`_SubmoduleEntry` tuples, sorted by child
        name.  ``[]`` for any non-package handle.
    """
    dirs = _package_dirs(jedi_name, analyzer)
    if not dirs:
        return []

    parent_handle = getattr(jedi_name, "full_name", None)
    if not parent_handle:
        return []

    entries: list[_SubmoduleEntry] = []
    # Dedup children by handle across portions: dirs are in roots (sys.path
    # precedence) order, so the FIRST occurrence wins — the first-portion-wins
    # invariant for namespace collisions (e.g. company.shared in two portions).
    seen_handles: set[str] = set()
    for pkg_dir in dirs:
        try:
            children = list(pkg_dir.iterdir())
        except OSError:
            continue
        for child in children:
            name = child.name
            if name.startswith(".") or name == "__pycache__":
                continue

            if child.is_file():
                if child.suffix != ".py" or child.stem == "__init__":
                    continue
                handle = f"{parent_handle}.{child.stem}"
                if handle in seen_handles:
                    continue
                seen_handles.add(handle)
                entries.append(_SubmoduleEntry(handle=handle, file=child, is_subpackage=False))
                continue

            if child.is_dir():
                handle = f"{parent_handle}.{name}"
                init_py = child / "__init__.py"
                if init_py.exists():
                    if handle in seen_handles:
                        continue
                    seen_handles.add(handle)
                    entries.append(_SubmoduleEntry(handle=handle, file=init_py, is_subpackage=True))
                elif _dir_shallow_qualifies(child):
                    if handle in seen_handles:
                        continue
                    seen_handles.add(handle)
                    entries.append(_SubmoduleEntry(handle=handle, file=child, is_subpackage=True))

    entries.sort(key=lambda e: e.handle.rsplit(".", 1)[-1])
    return entries


def resolve_submodules(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult:
    """Return a package's DIRECT child modules/subpackages as canonical handles.

    The ``submodules`` containment edge (#423): a thin wrapper over the
    :func:`_enumerate_submodule_paths` source-of-truth.  It adds NO containment
    logic of its own — it turns each :class:`_SubmoduleEntry` into a
    ``(Handle, ModuleSentinel)`` adjacent so ``expand``/``outline`` can build the
    child's stub WITHOUT a Jedi ``goto`` (the children come from a pure directory
    scan, so there is no Jedi ``Name`` to carry — the sentinel is the stand-in).

    The sentinel is anchored on the child's ``file`` — ``X.py`` /
    ``X/__init__.py`` for module / regular-subpackage children, or the bare
    ``X/`` DIRECTORY for a PEP 420 namespace subpackage.  A directory-anchored
    sentinel is never byte-read (the §3.6 dir-anchored stub contract;
    :class:`ModuleSentinel` guards its docstring read on ``is_file()``).

    Synchronous (the enumerator is a pure ``iterdir`` scan — no Jedi, no I/O
    beyond directory listing).  ``expand`` happily runs a sync resolver.

    Args:
        jedi_name: Resolved Jedi ``Name`` or :class:`ModuleSentinel`.  Its
            ``module_path``/``full_name`` drive the enumeration.
        analyzer: Active analyzer (passed through to the enumerator).

    Returns:
        An :class:`EdgeResult` whose ``adjacents`` are the child
        ``(Handle, ModuleSentinel)`` pairs.  For any non-package handle the
        enumerator yields no entries, so this returns ``EdgeResult([])`` — the
        "wrong kind → measured-empty, never ``None``" convention.
    """
    adjacents: list[tuple[Handle, Any]] = []
    for entry in _enumerate_submodule_paths(jedi_name, analyzer):
        handle = _try_handle(entry.handle)
        if handle is None:
            continue
        sentinel = ModuleSentinel(entry.file, entry.handle, analyzer)
        adjacents.append((handle, sentinel))
    return EdgeResult(adjacents=adjacents)


# ---------------------------------------------------------------------------
# Resolver registry
# ---------------------------------------------------------------------------

#: Maps *implemented* edge names → resolver callables.  ``members``/``callees``/
#: ``superclasses``/``imports``/``enclosing_scope``/``submodules`` are synchronous;
#: ``members``/``callees``/``superclasses``/``enclosing_scope``/``submodules``
#: always return an :class:`EdgeResult` (``submodules`` → ``EdgeResult([])`` for a
#: non-package handle); ``imports`` returns ``EdgeResult | None`` (``None`` for
#: non-module handles, mirroring ``imported_by``).  ``imported_by`` and
#: ``subclasses`` are async.  ``imported_by`` may return ``None`` (its
#: wrong-kind signal); ``subclasses``, ``superclasses``, and ``enclosing_scope``
#: always return an :class:`EdgeResult` (non-applicable kind → ``EdgeResult([])``,
#: never ``None``).  The value type therefore admits a sync-or-async resolver
#: returning ``EdgeResult | None`` so ``expand`` can stay edge-agnostic
#: (awaiting awaitable results, treating ``None`` as not-yet-implemented).
EDGE_RESOLVERS: dict[
    str, Callable[[Any, JediAnalyzer], EdgeResult | None | Awaitable[EdgeResult | None]]
] = {
    "members": resolve_members,
    "callees": resolve_callees,
    "imported_by": resolve_imported_by,
    "subclasses": resolve_subclasses,
    "superclasses": resolve_superclasses,
    "imports": resolve_imports,
    "enclosing_scope": resolve_enclosing_scope,
    "submodules": resolve_submodules,
}
