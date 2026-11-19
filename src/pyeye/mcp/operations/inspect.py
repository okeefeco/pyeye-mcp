"""inspect(handle) — return a structural Node for a canonical handle.

The canonical "what is this?" operation.  Returns kind, signature, location,
docstring, plus kind-dependent fields.  No source content.  No edge expansions
beyond the edge types measured in edge_counts.

Public API
----------
.. code-block:: python

    node = await inspect("pyeye.project_manager.ProjectManager", analyzer)
    # → {handle, kind, scope, location, docstring, edge_counts: {...}, ...}

Design notes
------------
- ``edge_counts`` is ALWAYS present.  It measures only edges derivable from the
  symbol's own definition: ``members`` (class/module) and ``superclasses``
  (class).  ``subclasses`` is intentionally OMITTED — counting it requires a
  project-wide inheritance scan with no cheap-preview value, so it is an
  expand-only edge (``expand(handle, "subclasses")``) (#392).  ``callers`` and
  ``references`` are likewise OMITTED — deferred to the Pyright reference backend
  (#333).  Unmeasured edge types are ABSENT (not 0).
- ``re_exports`` (non-module kinds) — **deprecated** in favour of
  ``expand(handle, "re_exports")`` (#393; removed in v3.0, tracked in #749):
  present when measured (``[]`` = measured, none found), or ABSENT if
  collection failed or any file in the package couldn't be parsed (couldn't
  measure; the edge lists such files in ``unparseable_files`` instead).  ABSENT
  for module kind (not computed for this kind).  Per the absence-vs-zero invariant,
  absence never means "none".  ``highlights``, ``tags``, ``properties`` are not
  currently computed and are therefore ABSENT.
- ``Param.kind`` values: lowercase 5-value enum
  (``"positional"``, ``"positional_or_keyword"``, ``"keyword_only"``,
  ``"var_positional"``, ``"var_keyword"``).
- ``default`` on params/attributes: simple literals only; complex expressions
  are omitted entirely (gated by ``ast.literal_eval``).
- No source content anywhere — ``location`` is a pointer-only dict.
- Per-measurement time budget (default 2 s): edges that exceed the budget are
  OMITTED from edge_counts — consistent with the absence-vs-zero invariant.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import time
from collections.abc import Awaitable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyeye import file_artifact_cache
from pyeye._ast_targets import (
    find_function_def_at_line as _find_function_def_at_line,
)
from pyeye._jedi_location import location_from_name
from pyeye.canonicalization import collect_re_exports
from pyeye.environment import not_found_note as environment_not_found_note
from pyeye.handle import Handle
from pyeye.mcp.operations.edges import (
    UnparseableSource,
    _enumerate_submodule_paths,
    edge_applies,
    resolve_members,
    resolve_superclasses,
    superclass_bases,
)
from pyeye.mcp.operations.not_found import not_found
from pyeye.mcp.operations.typeref import build_typeref
from pyeye.project_layout import package_kind
from pyeye.resolver import NotFound, in_restricted_dir, resolve_handle

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-measurement time budget
# ---------------------------------------------------------------------------

_DEFAULT_EDGE_BUDGET_SECONDS: float = 2.0

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _is_simple_literal(value_str: str) -> bool:
    """Return True if *value_str* is a simple literal (safe for the ``default`` field).

    Uses ``ast.literal_eval`` as the gate: if it parses as a literal value
    (str, int, float, bool, None, or a container thereof), include it.
    Complex expressions (function calls, lambdas, etc.) are rejected.

    Args:
        value_str: The string representation of a default value.

    Returns:
        ``True`` when ``ast.literal_eval`` succeeds; ``False`` otherwise.
    """
    try:
        ast.literal_eval(value_str)
        return True
    except (ValueError, SyntaxError):
        return False


def _extract_function_flags_from_ast(file_path: Path, line: int) -> tuple[bool, bool, bool]:
    """Extract is_async, is_classmethod, is_staticmethod from the AST of *file_path*.

    Walks the AST of *file_path* and locates the function definition at *line*.
    Detects async functions and the ``@classmethod`` / ``@staticmethod`` decorators.

    Args:
        file_path: Absolute path to the source file.
        line: 1-indexed line number of the function definition.

    Returns:
        A 3-tuple ``(is_async, is_classmethod, is_staticmethod)``.
    """
    # Reuse the cached-AST lookup (file_artifact_cache.get_ast) instead of a raw
    # read_text() + ast.parse(); avoids re-reading/re-parsing an unchanged file
    # (issue #339).
    node = _find_function_def_at_line(file_path, line)
    if node is None:
        return False, False, False

    is_async = isinstance(node, ast.AsyncFunctionDef)
    deco_names: set[str] = set()
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name):
            deco_names.add(deco.id)
        elif isinstance(deco, ast.Attribute):
            deco_names.add(deco.attr)
    return is_async, "classmethod" in deco_names, "staticmethod" in deco_names


def _build_param_kind_for_arg(fn: ast.FunctionDef | ast.AsyncFunctionDef, arg: ast.arg) -> str:
    """Determine the API ``Param.kind`` for an ``ast.arg`` based on its position.

    Mirrors the 5-value lowercase enum used elsewhere:

    - ``positional``: in ``fn.args.posonlyargs``
    - ``positional_or_keyword``: in ``fn.args.args``
    - ``keyword_only``: in ``fn.args.kwonlyargs``
    - ``var_positional``: ``fn.args.vararg`` (``*args``)
    - ``var_keyword``: ``fn.args.kwarg`` (``**kwargs``)
    """
    args = fn.args
    if arg in args.posonlyargs:
        return "positional"
    if arg in args.args:
        return "positional_or_keyword"
    if arg in args.kwonlyargs:
        return "keyword_only"
    if args.vararg is arg:
        return "var_positional"
    if args.kwarg is arg:
        return "var_keyword"
    return "positional_or_keyword"


def _iter_function_args(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.arg]:
    """Return all ``ast.arg`` entries in canonical signature order.

    Order mirrors how parameters appear in source: positional-only,
    positional-or-keyword, ``*args``, keyword-only, ``**kwargs``.
    """
    out: list[ast.arg] = []
    out.extend(fn.args.posonlyargs)
    out.extend(fn.args.args)
    if fn.args.vararg is not None:
        out.append(fn.args.vararg)
    out.extend(fn.args.kwonlyargs)
    if fn.args.kwarg is not None:
        out.append(fn.args.kwarg)
    return out


def _ast_arg_defaults(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.expr]:
    """Return a mapping ``arg_name → default_expr`` for params with defaults.

    Positional-or-keyword defaults align right-to-left with ``args.args``;
    keyword-only defaults align positionally with ``kwonlyargs`` (with
    ``None`` slots indicating "no default").
    """
    out: dict[str, ast.expr] = {}
    pos_args = fn.args.posonlyargs + fn.args.args
    pos_defaults = fn.args.defaults
    if pos_defaults:
        # defaults align with the LAST N entries of pos_args
        offset = len(pos_args) - len(pos_defaults)
        for i, default in enumerate(pos_defaults):
            out[pos_args[offset + i].arg] = default
    for kw_arg, kw_default in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=False):
        if kw_default is not None:
            out[kw_arg.arg] = kw_default
    return out


async def _build_parameters(
    jedi_name: Any, file_path: Path | None, analyzer: JediAnalyzer
) -> list[dict[str, Any]]:
    """Build the ``parameters`` list for a function/method node.

    For each parameter, populates ``name``, ``kind``, optional ``type``
    (recursive ``TypeRef``), and optional ``default`` (simple literals only).

    The implementation walks the source AST to extract annotations
    (rather than using Jedi's signature API), because Jedi's
    ``get_type_hint()`` normalises type strings — e.g. it rewrites
    ``dict[str, list[X]]`` to ``Dict[str, List[X]]`` and collapses
    ``Callable[[int], bool]`` to ``object``. The annotation site in the
    source AST is the source of truth for the recursive ``TypeRef`` shape.

    Implicit parameters (``self``, ``cls``) are included since they form
    part of the structural signature.

    Args:
        jedi_name: A Jedi ``Name`` object for a function/method.
        file_path: Absolute path to the source file containing the function.
        analyzer: Active analyzer for Jedi-based annotation resolution.

    Returns:
        A list of parameter dicts. Returns ``[]`` if the function definition
        cannot be located in the source AST.
    """
    if file_path is None or not file_path.exists():
        return []
    line = getattr(jedi_name, "line", None) or 0
    if not line:
        return []
    fn_node = _find_function_def_at_line(file_path, line)
    if fn_node is None:
        return []

    defaults = _ast_arg_defaults(fn_node)

    params: list[dict[str, Any]] = []
    for arg in _iter_function_args(fn_node):
        param_dict: dict[str, Any] = {
            "name": arg.arg,
            "kind": _build_param_kind_for_arg(fn_node, arg),
        }
        if arg.annotation is not None:
            param_dict["type"] = await build_typeref(arg.annotation, file_path, analyzer)
        default_expr = defaults.get(arg.arg)
        if default_expr is not None:
            try:
                raw_default = ast.unparse(default_expr)
            except Exception:
                raw_default = None
            if raw_default and _is_simple_literal(raw_default):
                param_dict["default"] = raw_default
        params.append(param_dict)
    return params


def _signature_from_source_ast(jedi_name: Any) -> str | None:
    """Reconstruct a function/method signature string from the source AST.

    Used to recover the real signature when Jedi leaks a decorator wrapper's
    signature (issue #437).  Returns ``None`` when the defining ``FunctionDef``
    cannot be located in source (builtins, C extensions, stub-only externals),
    so the caller can fall back to Jedi's render.

    Args:
        jedi_name: A Jedi ``Name`` object for a function/method.

    Returns:
        A single-line ``name(args) -> ret`` string, or ``None``.
    """
    module_path = getattr(jedi_name, "module_path", None)
    line = getattr(jedi_name, "line", None)
    name = getattr(jedi_name, "name", None)
    if module_path is None or not line or not name:
        return None
    fn_node = _find_function_def_at_line(Path(module_path), line)
    if fn_node is None:
        return None
    try:
        args = ast.unparse(fn_node.args)
        ret = f" -> {ast.unparse(fn_node.returns)}" if fn_node.returns is not None else ""
    except Exception:
        return None
    return f"{name}({args}){ret}"


def _build_signature(jedi_name: Any) -> str | None:
    """Extract a single-line signature string from a Jedi Name object.

    Uses Jedi's ``get_signatures()[0].to_string()`` to obtain the signature.
    Returns ``None`` if no signatures are available.  The returned string is
    guaranteed to be single-line (no embedded newlines) and non-empty — an
    empty/whitespace render normalises to ``None`` so callers never have to
    distinguish ``""`` from "absent" (the stub contract: present-with-real-value
    or omitted, never ``""``; issue #407).

    Decorator wrapper leak (issue #437): a decorated symbol resolves to the
    wrapper the decorator returns (e.g. ``@functools.cache`` →
    ``_lru_cache_wrapper(*args, **kwargs)``), so Jedi renders the wrapper's
    signature, not the symbol's own.  This is detected by the rendered leading
    identifier not matching the symbol name; when it happens the real signature
    is reconstructed from the source AST, falling back to the Jedi render if the
    source definition cannot be located.

    Args:
        jedi_name: A Jedi ``Name`` object.

    Returns:
        A non-empty single-line signature string, or ``None``.
    """
    try:
        # A signature Jedi infers from a definition in a restricted directory (an
        # inherited __init__, an alias of a function there) isn't shown (#999).
        sigs = [s for s in jedi_name.get_signatures() if not _restricted_signature(s)]
        if sigs:
            sig_str = sigs[0].to_string()
            # Guard: must be single-line
            if "\n" in sig_str:
                sig_str = sig_str.split("\n")[0]
            # Normalise an empty/whitespace render to None — never return "".
            if not (sig_str and sig_str.strip()):
                return None
            rendered_name = sig_str.split("(", 1)[0]
            symbol_name = getattr(jedi_name, "name", None)
            if symbol_name and rendered_name != symbol_name:
                ast_sig = _signature_from_source_ast(jedi_name)
                if ast_sig is not None:
                    return ast_sig
            return str(sig_str)
    except Exception:
        pass
    return None


def _restricted_signature(signature: Any) -> bool:
    """Whether *signature*, or any of its parameters, is defined in a restricted directory (#999).

    A subclass's signature belongs to the subclass, but its parameters (and
    their defaults) come from the ``__init__`` it inherits, so each is checked.
    """
    if in_restricted_dir(signature):
        return True
    try:
        params = signature.params
    except Exception:
        return True  # unreadable: fail closed
    return any(in_restricted_dir(param) for param in params)


async def _extract_return_type(
    jedi_name: Any, file_path: Path | None, analyzer: JediAnalyzer
) -> dict[str, Any] | None:
    """Extract the return-type ``TypeRef`` for a function/method.

    Walks the source AST (rather than using Jedi's signature string), because
    Jedi normalises return-type strings the same way it normalises parameter
    types (PEP 585 → typing forms, Callable → ``object``). The annotation
    in the source AST is the source of truth for the recursive ``TypeRef``
    shape.

    Args:
        jedi_name: A Jedi ``Name`` object for a function/method.
        file_path: Absolute path to the source file containing the function.
        analyzer: Active analyzer for Jedi-based annotation resolution.

    Returns:
        The return type as a ``TypeRef`` dict, or ``None`` when the function
        is unannotated or cannot be located in the source AST.
    """
    if file_path is None or not file_path.exists():
        return None
    line = getattr(jedi_name, "line", None) or 0
    if not line:
        return None
    fn_node = _find_function_def_at_line(file_path, line)
    if fn_node is None or fn_node.returns is None:
        return None
    return await build_typeref(fn_node.returns, file_path, analyzer)


async def _extract_attribute_info(
    file_path: Path, line: int, analyzer: JediAnalyzer
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract the ``TypeRef`` annotation and default value for an attribute / variable.

    Walks the file AST for an annotated or plain assignment at *line*. The
    annotation (when present) is converted to a recursive ``TypeRef``; the
    default value (when present) is included only when it parses as a simple
    literal via ``ast.literal_eval``.

    Args:
        file_path: Absolute path to the source file.
        line: 1-indexed line number of the attribute definition.
        analyzer: Active analyzer for Jedi-based annotation resolution.

    Returns:
        A 2-tuple ``(type_typeref, default_str)`` where either element may
        be ``None``.
    """
    type_typeref: dict[str, Any] | None = None
    default_str: str | None = None
    annotation_node: ast.expr | None = None

    try:
        tree = file_artifact_cache.get_ast(file_path)
    except Exception:
        return None, None

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.lineno == line:
            annotation_node = node.annotation
            if node.value is not None:
                try:
                    raw_default = ast.unparse(node.value)
                except Exception:
                    raw_default = ""
                if raw_default and _is_simple_literal(raw_default):
                    default_str = raw_default
            break
        elif isinstance(node, ast.Assign) and node.lineno == line:
            try:
                raw_default = ast.unparse(node.value)
            except Exception:
                raw_default = ""
            if raw_default and _is_simple_literal(raw_default):
                default_str = raw_default
            break

    if annotation_node is not None:
        type_typeref = await build_typeref(annotation_node, file_path, analyzer)

    return type_typeref, default_str


def _get_superclasses(jedi_name: Any, analyzer: JediAnalyzer) -> list[str] | None:
    """Return a class's direct superclasses for the ``superclasses`` field.

    Reads the ``superclasses`` edge's own walk, :func:`superclass_bases`
    (#624), so the field and the edge can't drift: declaration order, the
    canonical handle for each base that resolves, and the base's source text
    (``ast.unparse``) for one that doesn't.  The edge lists those unresolved
    bases in ``unresolved_superclasses``; ``edge_counts.superclasses`` counts
    only the resolved ones (see ``_count_superclasses``).

    Args:
        jedi_name: A Jedi ``Name`` object for a class.
        analyzer: Active analyzer for file-level Jedi access.

    Returns:
        A list of dotted-name strings (or raw base text) for direct superclasses,
        or ``None`` when the class's own file can't be parsed (#703).
    """
    try:
        bases = superclass_bases(jedi_name, analyzer) or []
    except UnparseableSource:
        # #703: the class's file doesn't parse, so its bases are unknown. The
        # field is omitted (not measured), never a measured ``[]``.
        return None
    return [str(pair[0]) if pair is not None else text for text, pair in bases]


# ---------------------------------------------------------------------------
# Symbol finder
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Edge-count helpers
# ---------------------------------------------------------------------------


async def _measure_with_budget(
    edge_name: str,
    measurement_coro: Awaitable[int],
    handle: str,
    budget_seconds: float = _DEFAULT_EDGE_BUDGET_SECONDS,
) -> int | None:
    """Run a measurement coroutine under a time budget.

    Returns the count, or ``None`` if the budget was exceeded or an error
    occurred.  The caller MUST use ``is not None`` (not truthiness) to decide
    whether the edge should be included — a count of 0 is a valid result.

    Args:
        edge_name: Name of the edge being measured (for logging).
        measurement_coro: The coroutine to run.
        handle: Canonical handle string (for logging context).
        budget_seconds: Maximum wall-clock time allowed.

    Returns:
        An integer count on success, or ``None`` on timeout/error.
    """
    start = time.perf_counter()
    try:
        return await asyncio.wait_for(measurement_coro, timeout=budget_seconds)
    except TimeoutError:
        elapsed = time.perf_counter() - start
        logger.warning(
            "inspect.edge_counts: %s timeout after %.2fs (handle=%r)",
            edge_name,
            elapsed,
            handle,
        )
        return None
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.warning(
            "inspect.edge_counts: %s failed after %.2fs (handle=%r): %s",
            edge_name,
            elapsed,
            handle,
            exc,
        )
        return None


async def _count_class_members(handle: str, jedi_name: Any, analyzer: JediAnalyzer) -> int:
    """Count direct class members for a class handle.

    Delegates to :func:`edges.resolve_members` — the single enumeration source
    for member counts since Phase 5.  Member counts are now driven by
    ``jedi_name.full_name`` (inside ``edges.resolve_members``) rather than the
    inbound ``handle``; for re-exported symbols these agree (both resolve to the
    definition site), so counts are unchanged, but the source-of-truth shifted.

    **Why ``async def`` with no ``await``**: ``_build_edge_counts`` gathers
    coroutines as ``Awaitable[int]`` and wraps each in ``asyncio.wait_for``
    (via ``_measure_with_budget``).  The coroutine protocol is required by that
    budget/gather contract — removing ``async`` would break the gather at runtime.

    **Why two separate named functions** (``_count_class_members`` vs
    ``_count_module_members``) rather than one: ``_build_edge_counts`` dispatches
    by kind to these exact names, and the per-edge budget isolation test patches
    ``_count_class_members`` by name (``monkeypatch`` / ``unittest.mock.patch``).
    Collapsing them into one function would break that dispatch and test seam.

    The ``handle`` parameter is retained for **call-site stability**:
    ``_build_edge_counts`` calls this function positionally as
    ``_count_class_members(handle, jedi_name, analyzer)``.  The timeout test uses
    ``side_effect=AsyncMock(*args, **kwargs)`` and does not depend on the parameter
    by name, but the positional signature must remain unchanged so existing call
    sites continue to work without modification.

    Args:
        handle: The class's canonical dotted-name string (retained for
            call-site positional-signature stability; not forwarded to the delegate).
        jedi_name: Jedi ``Name`` for the class.
        analyzer: Active analyzer.

    Returns:
        Count of direct class members.
    """
    _ = handle
    return len(resolve_members(jedi_name, analyzer).handles)


async def _count_module_members(jedi_name: Any, analyzer: JediAnalyzer) -> int:
    """Count top-level definitions in a module.

    Delegates to :func:`edges.resolve_members` — the single enumeration source
    for member counts since Phase 5.  Unlike the former flat ``get_names``
    approach, this **excludes import-bound names** (spec §3.3 correctness fix),
    so the count may be lower than before for modules with imports — including
    imports guarded by ``if TYPE_CHECKING:`` / ``try``-``except`` (#360).

    **Why ``async def`` with no ``await``**: ``_build_edge_counts`` gathers
    coroutines as ``Awaitable[int]`` and wraps each in ``asyncio.wait_for``
    (via ``_measure_with_budget``).  The coroutine protocol is required by that
    budget/gather contract — removing ``async`` would break the gather at runtime.

    **Why two separate named functions** (``_count_class_members`` vs
    ``_count_module_members``) rather than one: ``_build_edge_counts`` dispatches
    by kind to these exact names, and the per-edge budget isolation test patches
    ``_count_class_members`` by name (``monkeypatch`` / ``unittest.mock.patch``).
    Collapsing them into one function would break that dispatch and test seam.

    Args:
        jedi_name: Jedi ``Name`` or ``ModuleSentinel`` for the module.
        analyzer: Active analyzer.

    Returns:
        Count of top-level module members (imports excluded).
    """
    return len(resolve_members(jedi_name, analyzer).handles)


async def _count_submodules(jedi_name: Any, analyzer: JediAnalyzer) -> int:
    """Count a package's direct child modules/subpackages (#423).

    Delegates to :func:`edges._enumerate_submodule_paths` — the single
    containment source-of-truth — so for a **regular** package (one anchored on
    an ``__init__.py``) the count can never diverge from the ``submodules``
    expand edge:
    ``inspect(pkg).edge_counts["submodules"] == len(expand(pkg, "submodules").stubs)``.
    The enumerator is a pure ``iterdir`` scan (NO file reads), so this is the
    cheap counts-first signal the spec (§4) asks for.

    **Scope — regular packages only.** The equality above is guaranteed for
    regular packages. A PEP 420 **namespace** package surfaces (via Jedi) as an
    ``external``/``namespace`` handle that never reaches the package-counting
    branch in :func:`_build_edge_counts`, so ``inspect`` omits its ``submodules``
    count even though ``expand(pkg, "submodules")`` can still enumerate its
    children. Closing that asymmetry needs the namespace package anchored to a
    project handle first — deferred to #444.

    **Why ``async def`` with no ``await``**: identical to
    :func:`_count_module_members` — ``_build_edge_counts`` gathers coroutines
    as ``Awaitable[int]`` under per-edge budgets, so the coroutine protocol is
    required by that gather/budget contract.

    Caller gating (in ``_build_edge_counts``) restricts this to *package*
    handles, so a plain module never reports ``submodules`` (absence-vs-zero):
    a non-package handle would measure 0 here, but the count is simply not
    requested for it.

    Args:
        jedi_name: Jedi ``Name`` or ``ModuleSentinel`` for the package.
        analyzer: Active analyzer.

    Returns:
        Count of direct child modules + subpackages (a measured zero for an
        empty package).
    """
    return len(_enumerate_submodule_paths(jedi_name, analyzer))


async def _count_superclasses(
    jedi_name: Any, analyzer: JediAnalyzer, superclasses: list[str] | None = None
) -> int:
    """Count direct superclasses of a class (resolvable via goto only).

    Delegates to :func:`edges.resolve_superclasses` — the single enumeration
    source for the ``superclasses`` expand edge since #361.  This guarantees
    the progressive-disclosure contract:
    ``len(expand(h, "superclasses").stubs) == inspect(h).edge_counts.superclasses``.

    WHY count now derives from the resolver rather than ``_get_superclasses``:
    The resolver drops bases that cannot be resolved to a valid Jedi ``Name``
    via ``goto`` (no ``full_name`` → can't build a stub without a Name), while
    ``_get_superclasses`` keeps ALL declared bases (incl. raw-string fallbacks).
    Routing the count through the resolver guarantees equality BY CONSTRUCTION
    with the expandable edge, at the cost of a rare class with an unresolvable
    base showing that base in the ``superclasses`` FIELD but not in
    ``edge_counts.superclasses``.  This intentional divergence is acceptable
    (documented here, and in the ``_get_superclasses`` docstring).

    The ``superclasses`` parameter is RETAINED for call-site stability:
    ``_build_edge_counts`` passes it positionally as
    ``_count_superclasses(jedi_name, analyzer, superclasses)``.  The parameter
    is no longer used by the implementation (the count is now derived from the
    resolver, not the pre-resolved list), but removing it would require touching
    all callers with no safety benefit — the compiler/type-checker will simply
    ignore the unused argument.

    Args:
        jedi_name: Jedi ``Name`` for the class.
        analyzer: Active analyzer.
        superclasses: Pre-resolved superclass list (retained for call-site
            stability; no longer used by this implementation — the count is
            derived from ``resolve_superclasses`` instead).

    Returns:
        Count of direct superclasses resolvable via goto (the same count as
        the ``superclasses`` expand edge will return as stubs).
    """
    _ = superclasses  # retained for call-site stability; unused by this impl
    return len(resolve_superclasses(jedi_name, analyzer).handles)


async def _build_edge_counts(
    handle: str,
    kind: str,
    jedi_name: Any,
    analyzer: JediAnalyzer,
    budget_seconds: float = _DEFAULT_EDGE_BUDGET_SECONDS,
    superclasses: list[str] | None = None,
) -> dict[str, int]:
    """Build the edge_counts dict.

    Each edge measurement runs under an independent time budget.  Edges that
    time out or error are OMITTED from the returned dict (absence-vs-zero
    invariant).  Edges that succeed are included even when the count is 0.

    Measured edge types (only edges derivable from the symbol's own definition):
    - ``members``: count of direct members (class and module handles)
    - ``superclasses``: count of direct superclasses (class handles)

    **``subclasses`` is intentionally NOT measured** (see #392).  Counting
    project-internal subclasses requires the same project-wide inheritance scan
    as listing them, so it has no cheap-preview value and is an expand-only edge
    (``expand(handle, "subclasses")``).

    **``callers`` and ``references`` are intentionally NOT measured** (see #332).
    They were derived from Jedi's ``get_references``, which is budget-capped
    upstream ("broken since forever" per Jedi's author) and under-reports
    non-deterministically depending on the anchor position — anchored at a
    definition it can return a near-empty set for a heavily-used symbol.
    Emitting ``callers: 0`` for something with 80 live callers is worse than
    emitting nothing, and violates the absence-vs-zero invariant (a measured
    ``0`` must mean "measured, none found", not "couldn't measure").  These
    edges are therefore omitted entirely until an indexed reference backend
    (Pyright) lands — see #333.  Their absence reads correctly as "not
    measured"; restoring them later (absent → present) is non-breaking.

    Note: Jedi's API is synchronous internally, so ``asyncio.gather`` provides
    clean concurrent-looking code but execution is effectively serialized.

    Args:
        handle: Canonical dotted-name string.
        kind: Normalised kind string (``"class"``, ``"function"``, etc.).
        jedi_name: Jedi ``Name`` (or ``ModuleSentinel``) for the symbol.
        analyzer: Active analyzer.
        budget_seconds: Per-edge time budget in seconds.

    Returns:
        A dict containing the successfully measured edges.  May be empty
        (e.g. for function/method handles, whose only edges were the omitted
        ``callers``/``references``).
    """
    counts: dict[str, int] = {}

    # Build a dict of independent single-int coroutines per kind.
    # callers/references are deliberately excluded — see docstring / #332.
    coros: dict[str, Awaitable[int]] = {}

    # Which edges are counted is the applicability table's call (#626); the kind
    # only picks the member-counting strategy.
    if edge_applies("members", jedi_name):
        if kind == "class":
            coros["members"] = _count_class_members(handle, jedi_name, analyzer)
        else:
            coros["members"] = _count_module_members(jedi_name, analyzer)
    if edge_applies("superclasses", jedi_name):
        coros["superclasses"] = _count_superclasses(jedi_name, analyzer, superclasses)
        # subclasses is intentionally NOT measured here — counting subclasses
        # requires the same project-wide inheritance scan as listing them, so it
        # has no cheap-preview value (#392).  It is an expand-only edge:
        # expand(handle, "subclasses").  inspect's edge_counts reports only edges
        # derivable from the symbol's own definition (members, superclasses).

    if edge_applies("submodules", jedi_name):
        # submodules is counted only for a PACKAGE (#423): present (possibly a measured
        # 0) for a package handle, ABSENT for a plain module — the absence-vs-zero
        # invariant.  is_package == its module_path is an __init__.py (regular
        # package) OR a directory (a PEP 420 namespace package anchored on its
        # dir, #444) — the same rule _build_module_fields uses.  Since #444 a
        # top-level namespace package is anchored as a dir ModuleSentinel and
        # reaches this branch, so count==expand now holds for namespace packages
        # too.
        if _is_package_path(getattr(jedi_name, "module_path", None)):
            coros["submodules"] = _count_submodules(jedi_name, analyzer)

    # function, method, attribute, property, variable, statement: no measured
    # edges remain after callers/references were removed → counts stays empty.

    if not coros:
        return counts

    # Run all measurements via asyncio.gather, each under a per-edge budget.
    edge_names = list(coros.keys())
    budgeted = [
        _measure_with_budget(name, coro, handle, budget_seconds) for name, coro in coros.items()
    ]
    results = await asyncio.gather(*budgeted, return_exceptions=False)

    for edge_name, result in zip(edge_names, results, strict=False):
        if result is not None:  # CRITICAL: is not None — 0 is a valid measured result
            counts[edge_name] = result

    return counts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def inspect(handle: str, analyzer: JediAnalyzer) -> dict[str, Any]:
    """Return a structural Node for a canonical handle.

    The central "what is this?" operation.  Returns universal fields (handle,
    kind, scope, location, docstring) plus kind-dependent fields.  Never
    returns source content — signatures are single-line strings; ``location``
    is a pointer dict only; ``default`` fields are simple literals only.

    Always includes ``edge_counts`` (measures only edges derivable from the
    symbol's own definition: members, superclasses — for relevant kinds).
    ``subclasses`` is OMITTED — it is an expand-only edge
    (``expand(handle, "subclasses")``), since counting it needs a project-wide
    scan (#392).  ``callers`` and ``references`` are likewise OMITTED (deferred
    to the Pyright reference backend, #333).
    Edges that exceed their per-measurement budget are OMITTED, not zero.
    ``re_exports`` — for non-module kinds (class, function, method, property,
    variable, attribute): present when measured (``[]`` = measured, no
    re-exports), or ABSENT if collection failed (couldn't measure).  ABSENT for
    module kind (not computed for this kind).  Per the absence-vs-zero
    invariant, absence never means "none".
    ``highlights``, ``tags``, and ``properties`` are not currently computed and
    are therefore ABSENT.

    Args:
        handle: Canonical Python dotted-name string (from resolve/resolve_at).
        analyzer: Configured JediAnalyzer for the project.

    Returns:
        A Node dict carrying ``found: True`` plus universal fields +
        kind-dependent fields + ``edge_counts``.  Returns the dict even on
        partial/missing data; never raises.  If the handle cannot be resolved,
        returns the shared not-found shape (:func:`not_found`) — never a
        placeholder node (#545).
    """
    # ------------------------------------------------------------------
    # Step 1 — Locate the symbol via the one canonical resolver (#623).  On
    # success every field below describes, and echoes, the CANONICAL handle,
    # so a re-export alias input reports its definition-site handle.
    # ------------------------------------------------------------------
    resolved = resolve_handle(handle, analyzer)
    if isinstance(resolved, NotFound):
        logger.debug("inspect(%r): %s", handle, resolved.detail)
        if resolved.restricted:  # refused, with the honest reason (#999)
            return not_found(handle, detail=resolved.detail)
        response = not_found(handle)
        # "Doesn't exist" vs "couldn't see the project's venv" (#993, #568).
        if note := environment_not_found_note(analyzer, handle):
            response["detail"] = f"{response['detail']} {note}"
        return response
    jedi_name = resolved.anchor
    handle = resolved.handle
    kind = resolved.kind
    scope = resolved.scope

    # ------------------------------------------------------------------
    # Step 2 — Build universal fields
    # ------------------------------------------------------------------
    file_path: Path | None = jedi_name.module_path
    file_str: str = file_path.as_posix() if file_path else ""

    location = location_from_name(file_str, jedi_name)

    # Docstring — raw text (no HTML, no markdown rendering)
    docstring: str | None = None
    try:
        ds = jedi_name.docstring(raw=True)
    except Exception:
        try:
            ds = jedi_name.docstring()
        except Exception:
            ds = None
    docstring = ds if ds else None

    # ------------------------------------------------------------------
    # Step 3 — Kind-dependent fields
    # ------------------------------------------------------------------
    kind_fields: dict[str, Any] = {}

    # The resolved-bases list feeds the `superclasses` FIELD only.
    # `edge_counts.superclasses` is derived independently via `resolve_superclasses`
    # (delegated through `_count_superclasses`) — changed in #361 so that the count
    # matches the expandable edge (which drops unresolvable bases) rather than the
    # field (which keeps them as ast.unparse fallbacks).  The two values can therefore
    # diverge for classes whose bases cannot be resolved via goto.
    superclasses: list[str] | None = None
    if kind == "class":
        superclasses = _get_superclasses(jedi_name, analyzer)
        kind_fields.update(_build_class_fields(jedi_name, analyzer, superclasses))

    elif kind in ("function", "method"):
        kind_fields.update(await _build_function_fields(jedi_name, file_path, analyzer))

    elif kind == "module":
        kind_fields.update(_build_module_fields(jedi_name, handle))

    elif kind in ("attribute", "property", "variable", "enum_member"):
        # An enum member gets the attribute fields: ``default`` is its literal
        # value; ``type`` comes only from an annotation, never from the value's
        # inferred type (``RED = 1`` is a Color, not an int, #695).
        kind_fields.update(await _build_attribute_fields(jedi_name, kind, file_path, analyzer))

    # ------------------------------------------------------------------
    # Step 4 — Assemble node
    # ------------------------------------------------------------------
    node: dict[str, Any] = {
        "found": True,
        "handle": handle,
        "kind": kind,
        "scope": scope,
        "location": location,
        "docstring": docstring,
    }
    node.update(kind_fields)
    # Phase 4: edge_counts populated with per-measurement budgeted counts.
    # `superclasses` is passed for call-site stability but is unused by
    # `_count_superclasses` (which derives the count from `resolve_superclasses`).
    node["edge_counts"] = await _build_edge_counts(
        handle, kind, jedi_name, analyzer, superclasses=superclasses
    )

    # Phase 6: re_exports — always present (possibly []) for non-module kinds.
    # Per the absence-vs-zero invariant (spec):
    #   - PRESENT [] means "measured and found no re-exports"
    #   - ABSENT means "we don't compute re_exports for this kind"
    # Module kind is ABSENT — the BFS-based collect_re_exports walks __init__.py for
    # symbol names; traversing module re-exports requires a different strategy and is
    # deferred to a future phase.
    # Deprecated (#393, removal in v3.0, #749): the expand edge is the surface.
    # It reads the same cached scan (canonicalization.re_export_scan, invalidated
    # per project by the file watcher), so a repeat inspect costs a dict lookup.
    if kind != "module":
        try:
            raw_re_exports = await collect_re_exports(Handle(handle), analyzer)
            node["re_exports"] = [str(h) for h in raw_re_exports]
        except Exception as exc:
            # Per absence-vs-zero: if collection raises unexpectedly (malformed handle,
            # Jedi error), leave re_exports absent rather than falsely claiming [].
            # [] would mean "measured and empty"; an exception means "couldn't measure".
            logger.warning("inspect.re_exports: collection failed for %r: %s", handle, exc)

    return node


# ---------------------------------------------------------------------------
# Kind-dependent field builders
# ---------------------------------------------------------------------------


def _build_class_fields(
    jedi_name: Any, analyzer: JediAnalyzer, superclasses: list[str] | None = None
) -> dict[str, Any]:
    """Build kind-dependent fields for a class node.

    Extracts the class signature (from ``__init__``) and the list of direct
    superclass handles.

    Args:
        jedi_name: Jedi Name for the class.
        analyzer: Active analyzer.
        superclasses: Pre-resolved superclass list shared with edge_counts to
            avoid resolving the bases twice (issue #339).  Resolved on demand
            when omitted.

    Returns:
        A dict with ``superclasses: list[str]`` (omitted when the class's file
        can't be parsed, #703) and optionally ``signature: str``.
    """
    fields: dict[str, Any] = {}

    # Superclasses
    if superclasses is None:
        superclasses = _get_superclasses(jedi_name, analyzer)
    if superclasses is not None:  # None: the file doesn't parse; omitted (#703)
        fields["superclasses"] = superclasses

    # Class signature — from Jedi's get_signatures() which uses __init__
    sig = _build_signature(jedi_name)
    if sig is not None:
        fields["signature"] = sig

    return fields


async def _build_function_fields(
    jedi_name: Any, file_path: Path | None, analyzer: JediAnalyzer
) -> dict[str, Any]:
    """Build kind-dependent fields for a function or method node.

    Extracts signature, parameters (with recursive ``TypeRef`` types), return
    type (recursive ``TypeRef``), and async/classmethod/staticmethod flags.

    Args:
        jedi_name: Jedi Name for the function/method.
        file_path: Absolute path to the source file (for AST-based extraction).
        analyzer: Active analyzer (for ``TypeRef`` head resolution).

    Returns:
        A dict with ``signature``, ``parameters``, ``return_type``,
        ``is_async``, ``is_classmethod``, ``is_staticmethod``.
    """
    fields: dict[str, Any] = {}

    # Signature is OMITTED (never "") when Jedi can't render one — consistent with
    # the class branch and the stub contract (#407).  The structured ``parameters``
    # below remain available regardless, so consumers don't lose information.
    sig = _build_signature(jedi_name)
    if sig is not None:
        fields["signature"] = sig

    fields["parameters"] = await _build_parameters(jedi_name, file_path, analyzer)
    fields["return_type"] = await _extract_return_type(jedi_name, file_path, analyzer)

    # Async / decorator flags from AST
    if file_path is not None and file_path.exists():
        is_async, is_classmethod, is_staticmethod = _extract_function_flags_from_ast(
            file_path, jedi_name.line
        )
    else:
        is_async, is_classmethod, is_staticmethod = False, False, False

    fields["is_async"] = is_async
    fields["is_classmethod"] = is_classmethod
    fields["is_staticmethod"] = is_staticmethod

    return fields


def _is_package_path(module_path: Any) -> bool:
    """Return whether *module_path* anchors a package (#423/#444).

    A regular package (``__init__.py``) or a PEP 420 namespace package
    (dir-anchored since #444), per :func:`pyeye.project_layout.package_kind`,
    the one package predicate (#625). ``"unknown"`` (a ``None`` path, a stub or
    an extension module) is **not** a package here: ``is_package`` reports only
    what the path proves. The single rule shared by ``_build_module_fields``
    (the ``is_package`` field) and ``_build_edge_counts`` (the package-only
    ``submodules`` gate), so the two can never disagree.
    """
    return package_kind(module_path) in ("regular", "namespace")


def _build_module_fields(jedi_name: Any, handle: str) -> dict[str, Any]:
    """Build kind-dependent fields for a module node.

    Determines whether the module is a package (an ``__init__.py`` regular
    package, or a directory-anchored PEP 420 namespace package — #444) and the
    parent package handle.

    Args:
        jedi_name: Jedi Name (or ``ModuleSentinel``) for the module.
        handle: Canonical dotted-name string of the module.

    Returns:
        A dict with ``is_package: bool`` and optionally ``package: str``.
    """
    fields: dict[str, Any] = {}

    fields["is_package"] = _is_package_path(jedi_name.module_path)

    # Parent package (all but the last component of the handle)
    parts = handle.split(".")
    if len(parts) > 1:
        fields["package"] = ".".join(parts[:-1])

    return fields


async def _build_attribute_fields(
    jedi_name: Any, kind: str, file_path: Path | None, analyzer: JediAnalyzer
) -> dict[str, Any]:
    """Build kind-dependent fields for an attribute, property, or variable node.

    Extracts the recursive ``TypeRef`` annotation and default value (simple
    literals only) from the source AST. For ``property`` kind, only the
    return-type annotation is extracted (no ``default``).

    Args:
        jedi_name: Jedi Name for the attribute/property/variable.
        kind: ``"attribute"``, ``"property"``, ``"variable"`` or ``"enum_member"``.
        file_path: Absolute path to the source file (for AST-based extraction).
        analyzer: Active analyzer (for ``TypeRef`` head resolution).

    Returns:
        A dict with optional ``type: TypeRef`` and optional ``default: str``.
    """
    fields: dict[str, Any] = {}

    if file_path is None or not file_path.exists():
        return fields

    line = jedi_name.line
    if not line:
        return fields

    if kind == "property":
        # For properties, the return-type annotation is treated as the
        # property's type. Locate the FunctionDef and run it through the
        # TypeRef builder for a uniform shape with parameter / variable
        # types.
        fn_node = _find_function_def_at_line(file_path, line)
        if fn_node is not None and fn_node.returns is not None:
            fields["type"] = await build_typeref(fn_node.returns, file_path, analyzer)
    else:
        type_typeref, default_str = await _extract_attribute_info(file_path, line, analyzer)
        if type_typeref is not None:
            fields["type"] = type_typeref
        if default_str is not None:
            fields["default"] = default_str

    return fields
