"""inspect(handle) — return a structural Node for a canonical handle.

The canonical "what is this?" operation.  Returns kind, signature, location,
docstring, plus kind-dependent fields.  No source content.  No edge expansions
beyond the edge types measured in edge_counts.

Public API
----------
.. code-block:: python

    node = await inspect("pyeye.cache.GranularCache", analyzer)
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
- ``re_exports`` (non-module kinds): present when measured (``[]`` = measured,
  none found), or ABSENT if collection failed (couldn't measure).  ABSENT for
  module kind (not computed for this kind).  Per the absence-vs-zero invariant,
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
    attr_target_position as _attr_target_position,
    find_function_def_at_line as _find_function_def_at_line,
)
from pyeye._jedi_location import location_from_name
from pyeye._module_sentinel import ModuleSentinel
from pyeye.canonicalization import collect_re_exports, find_module_file, resolve_canonical
from pyeye.handle import Handle
from pyeye.mcp.operations.edges import resolve_members, resolve_superclasses

# Kind normalisation + method detection live in resolve (the lower-level module)
# so resolve, inspect, and stubs share one source of truth (#406).
from pyeye.mcp.operations.resolve import _normalise_kind_from_name
from pyeye.mcp.operations.typeref import build_typeref
from pyeye.scope import classify_scope

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


def _make_location(
    file_str: str,
    line_start: int,
    line_end: int,
    column_start: int | None = None,
    column_end: int | None = None,
) -> dict[str, Any]:
    """Build a location pointer dict.

    Returns a dict with ``file``, ``line_start``, ``line_end``, and optionally
    ``column_start`` / ``column_end`` when provided and non-None.

    Args:
        file_str: POSIX file path string.
        line_start: 1-indexed start line.
        line_end: 1-indexed end line (must be >= line_start).
        column_start: Optional 0-indexed start column.
        column_end: Optional 0-indexed end column.

    Returns:
        A location pointer dict — never contains ``source``, ``text``, or ``snippet``.
    """
    loc: dict[str, Any] = {
        "file": file_str,
        "line_start": line_start,
        "line_end": line_end,
    }
    if column_start is not None:
        loc["column_start"] = column_start
    if column_end is not None:
        loc["column_end"] = column_end
    return loc


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


def _build_signature(jedi_name: Any) -> str | None:
    """Extract a single-line signature string from a Jedi Name object.

    Uses Jedi's ``get_signatures()[0].to_string()`` to obtain the signature.
    Returns ``None`` if no signatures are available.  The returned string is
    guaranteed to be single-line (no embedded newlines) and non-empty — an
    empty/whitespace render normalises to ``None`` so callers never have to
    distinguish ``""`` from "absent" (the stub contract: present-with-real-value
    or omitted, never ``""``; issue #407).

    Args:
        jedi_name: A Jedi ``Name`` object.

    Returns:
        A non-empty single-line signature string, or ``None``.
    """
    try:
        sigs = jedi_name.get_signatures()
        if sigs:
            sig_str = sigs[0].to_string()
            # Guard: must be single-line
            if "\n" in sig_str:
                sig_str = sig_str.split("\n")[0]
            # Normalise an empty/whitespace render to None — never return "".
            return str(sig_str) if sig_str and sig_str.strip() else None
    except Exception:
        pass
    return None


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


def _get_superclasses(jedi_name: Any, analyzer: JediAnalyzer) -> list[str]:
    """Extract direct superclasses from a class definition.

    NOTE: This is intentionally a parallel implementation to
    JediAnalyzer._get_class_inheritance_info (jedi_analyzer.py line ~3278),
    which uses Jedi's MRO via py__mro__() with C3 linearization. The two
    implementations may diverge if the analyzer's logic is improved without
    matching changes here. A future refactor should consolidate by extracting
    shared base-extraction logic into a public helper.

    Approach: ast.parse + ast.ClassDef.bases for source-level extraction,
    then jedi script.goto() per base to resolve to canonical handles.
    Falls back to ast.unparse of the base expression when goto fails.

    NOTE — field-vs-count divergence: this function keeps ALL declared bases
    (including raw ``ast.unparse`` fallback strings when goto fails).  Such
    fallback entries appear in the ``superclasses`` field but are EXCLUDED from
    ``edge_counts.superclasses``, which counts only goto-resolvable bases
    (see ``_count_superclasses``).

    Args:
        jedi_name: A Jedi ``Name`` object for a class.
        analyzer: Active analyzer for file-level Jedi access.

    Returns:
        A list of dotted-name strings for direct superclasses.
    """
    file_path = jedi_name.module_path
    if file_path is None:
        return []

    line = jedi_name.line
    superclasses: list[str] = []

    try:
        # Reuse the mtime-keyed cached AST instead of read_text() + ast.parse()
        # (issue #339).
        tree = file_artifact_cache.get_ast(file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.lineno == line:
                for base in node.bases:
                    base_str = ast.unparse(base)
                    # Attempt Jedi-based resolution for the base class handle
                    resolved = _resolve_base_class_via_jedi(
                        file_path.as_posix(), base, base_str, analyzer
                    )
                    superclasses.append(resolved)
                break
    except Exception:
        pass

    return superclasses


def _resolve_base_class_via_jedi(
    file_str: str,
    base_node: ast.expr,
    base_str: str,
    analyzer: JediAnalyzer,
) -> str:
    """Attempt to resolve a base class AST node to a full dotted name via Jedi.

    Uses ``jedi.Script.goto()`` at the rightmost identifier in the base class
    expression to navigate to its definition.  Falls back to the raw
    ``ast.unparse`` representation on failure.

    For attribute-chain bases (e.g. ``pkg.sub.Widget``), positions goto at
    ``Widget`` rather than ``pkg`` to avoid resolving to the package instead of
    the class.  Results are filtered to prefer ``class``-kind definitions.

    Args:
        file_str: POSIX path to the file containing the class definition.
        base_node: The AST node representing the base class expression.
        base_str: The ``ast.unparse``-formatted string of the base class.
        analyzer: Active analyzer.

    Returns:
        The resolved full dotted name, or *base_str* as fallback.
    """
    try:
        base_line, base_col = _attr_target_position(base_node)
        file_path = Path(file_str)
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        defs = script.goto(base_line, base_col, follow_imports=True)
        # Part B: prefer class-kind results; fall back to any named result.
        class_defs = [d for d in defs if d.type == "class" and d.full_name]
        if class_defs:
            return str(class_defs[0].full_name)
        named_defs = [d for d in defs if d.full_name]
        if named_defs:
            return str(named_defs[0].full_name)
    except Exception:
        pass
    return base_str


# ---------------------------------------------------------------------------
# Symbol finder
# ---------------------------------------------------------------------------


def _anchor_on_definition(name: Any, handle: str) -> Any:
    """Anchor a matched Jedi ``Name`` on its definition site (issue #429).

    A re-export import binding in an ``__init__.py`` reports the *same*
    ``full_name`` as the class it re-exports — Jedi follows the import one hop —
    and even reports ``type == "class"``. So the handle→``Name`` walk can match
    that binding and land on the re-export line instead of the class body,
    silently reporting ``members: 0`` for a real class. This happens whenever
    the deepest (definition) module's pass fails to produce a ``full_name``
    match (the #419-class non-determinism) and the walk falls through to a
    shallower ``__init__``.

    ``goto`` repairs this deterministically: it is idempotent on a true
    definition (returns itself) and follows a re-export binding through to the
    definition. It rides the same ``goto(follow_imports=True)`` path
    ``resolve_at`` uses, so it does not depend on the flaky ``full_name`` match —
    making ``inspect``/``expand``/``trace``/``outline`` agree with ``resolve_at``
    (acceptance criterion #2). The ``full_name``/``module_path`` guard keeps a
    genuine definition if ``goto`` ever wanders.

    Args:
        name: The matched Jedi ``Name`` (definition or re-export binding).
        handle: The canonical dotted-name string being resolved.

    Returns:
        The definition-site ``Name`` when ``goto`` resolves it, else *name*.
    """
    try:
        targets = name.goto(follow_imports=True)
    except Exception:
        return name
    for target in targets:
        if target.full_name == handle and target.module_path is not None:
            return target
    return name


def _find_jedi_name_for_handle(handle: str, analyzer: JediAnalyzer) -> Any | None:
    """Find the Jedi Name object that corresponds to *handle*.

    For module handles (no leaf symbol), locates the module file and returns
    a synthetic-ish Name by getting the module-level name object from Jedi.
    For all other handles, splits into ``module.leaf``, locates the module
    file, and searches ``get_names(all_scopes=True)`` for a Name whose
    ``full_name`` matches.

    For external symbols (e.g. ``pathlib.Path``), falls through to a Jedi
    project-level search.

    Args:
        handle: Canonical dotted-name string.
        analyzer: Active analyzer for the project.

    Returns:
        A Jedi ``Name`` object, or ``None`` if not found.
    """
    parts = handle.split(".")

    # Case 1: bare module name or dotted module path (check if it's a module)
    mod_file = find_module_file(handle, analyzer)
    if mod_file is not None:
        # handle is itself a module — return a module-level name from that file
        try:
            script = file_artifact_cache.get_script(mod_file, analyzer.project)
            names = script.get_names(all_scopes=False, definitions=True, references=False)
            # Prefer to find a module-type match
            for name in names:
                if name.type == "module" and name.full_name == handle:
                    return name
            # No explicit module name entry — return a synthetic by finding ANY name
            # but we must ensure we return info for the module itself not a member.
            # We'll return None here and handle module specially below.
        except Exception:
            pass
        return ModuleSentinel(mod_file, handle, analyzer)

    # Case 2: leaf symbol inside a module
    if len(parts) < 2:
        return None

    # Try progressively shorter module paths
    for split_at in range(len(parts) - 1, 0, -1):
        module_dotted = ".".join(parts[:split_at])
        mod_file = find_module_file(module_dotted, analyzer)
        if mod_file is None:
            continue
        try:
            script = file_artifact_cache.get_script(mod_file, analyzer.project)
            for name in script.get_names(all_scopes=True, definitions=True, references=False):
                if name.full_name == handle:
                    # Anchor on the definition: a match here may be a re-export
                    # import binding in an __init__ (issue #429) — goto-follow it.
                    return _anchor_on_definition(name, handle)
        except Exception:
            continue

    # Case 3: external symbol — try Jedi project-level search
    leaf_name = parts[-1]
    try:
        results = list(analyzer.project.search(leaf_name))
        for r in results:
            if r.full_name == handle:
                return r
    except Exception:
        pass

    # Final fallback: synthetic-import inference for stdlib/third-party symbols
    # (e.g. pathlib.Path) where project.search returns nothing.
    # Tested by TestFindJediNameForHandleFallbacks.test_synthetic_import_fallback_for_external_symbol.
    try:
        import jedi

        module_dotted = ".".join(parts[:-1])
        leaf_sym = parts[-1]
        fake_code = f"import {module_dotted}\n{module_dotted}.{leaf_sym}"
        script = jedi.Script(code=fake_code, project=analyzer.project)
        inferred = script.infer(2, len(module_dotted) + 1 + len(leaf_sym))
        for n in inferred:
            if n.full_name == handle:
                return n
    except Exception:
        pass

    return None


async def _resolve_handle_to_jedi_name(handle: str, analyzer: JediAnalyzer) -> Any | None:
    """Resolve a handle to a Jedi ``Name``, canonicalizing re-export aliases (#431).

    First tries the direct handle→``Name`` walk (:func:`_find_jedi_name_for_handle`).
    A re-export *alias* path — a public import path such as
    ``package.Thing`` rather than the canonical definition handle
    ``package._impl.Thing`` — never matches any ``full_name``: Jedi reports the
    re-export binding's ``full_name`` as the *canonical* handle, not the alias
    string, so the direct walk misses and ``inspect`` would emit a not-found
    ``kind: variable`` node.

    On a miss, canonicalize via :func:`resolve_canonical` (which matches by
    *name*, not ``full_name``, so it resolves the alias) and retry once with the
    canonical handle. This is the shared entry point for
    ``inspect``/``expand``/``trace``/``outline`` so all four agree with
    ``resolve``/``resolve_at`` on alias inputs (issue #431, acceptance #2).

    The canonicalization is paid only on a miss — the common case (a canonical
    handle that resolves directly) returns from the first call with no extra
    work.

    Args:
        handle: Any dotted-name handle (canonical or re-export alias).
        analyzer: Active analyzer for the project.

    Returns:
        A Jedi ``Name`` object, or ``None`` if the handle cannot be resolved
        even after canonicalization.
    """
    name = _find_jedi_name_for_handle(handle, analyzer)
    if name is not None:
        return name

    canonical = await resolve_canonical(handle, analyzer)
    if canonical is not None and str(canonical) != handle:
        return _find_jedi_name_for_handle(str(canonical), analyzer)

    return None


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
    except asyncio.TimeoutError:
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
    so the count may be lower than before for modules with top-level imports.

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

    if kind == "class":
        coros["members"] = _count_class_members(handle, jedi_name, analyzer)
        coros["superclasses"] = _count_superclasses(jedi_name, analyzer, superclasses)
        # subclasses is intentionally NOT measured here — counting subclasses
        # requires the same project-wide inheritance scan as listing them, so it
        # has no cheap-preview value (#392).  It is an expand-only edge:
        # expand(handle, "subclasses").  inspect's edge_counts reports only edges
        # derivable from the symbol's own definition (members, superclasses).

    elif kind == "module":
        coros["members"] = _count_module_members(jedi_name, analyzer)

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
        A Node dict with universal fields + kind-dependent fields +
        ``edge_counts``.  Returns the dict even on partial/missing data;
        never raises.  If the handle cannot be resolved, returns a minimal node
        with kind ``"variable"`` as the safest default.
    """
    # ------------------------------------------------------------------
    # Step 1 — Locate the symbol (canonicalizing re-export aliases, #431)
    # ------------------------------------------------------------------
    jedi_name = await _resolve_handle_to_jedi_name(handle, analyzer)

    if jedi_name is None:
        # Minimal fallback — handle not found
        logger.debug("inspect(%r): symbol not found; returning minimal node", handle)
        return {
            "handle": handle,
            "kind": "variable",
            "scope": "external",
            "location": _make_location("", 1, 1, 0, 0),
            "docstring": None,
            "edge_counts": {},
        }

    # ------------------------------------------------------------------
    # Step 2 — Build universal fields
    # ------------------------------------------------------------------
    file_path: Path | None = jedi_name.module_path
    file_str: str = file_path.as_posix() if file_path else ""

    scope = classify_scope(file_str, analyzer) if file_str else "external"

    # Normalise kind, promoting class-enclosed functions to "method" (#406).
    kind = _normalise_kind_from_name(jedi_name)

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

    elif kind in ("attribute", "property", "variable"):
        kind_fields.update(await _build_attribute_fields(jedi_name, kind, file_path, analyzer))

    # ------------------------------------------------------------------
    # Step 4 — Assemble node
    # ------------------------------------------------------------------
    node: dict[str, Any] = {
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
    # No new cache is added here: collect_re_exports calls file_artifact_cache.get_script
    # per file, so each source file is loaded at most once across all calls. The BFS
    # walk is O(package_files) per inspect call and typically completes in single-digit ms.
    # If profiling reveals a bottleneck, a per-handle cache on JediAnalyzer can be wired
    # in a later phase (see TODO below).
    # TODO(perf): if repeated inspect calls on the same handle become a bottleneck,
    # add a dict[str, list[str]] on JediAnalyzer, lazily populated and invalidated
    # by the existing file watcher on source changes.
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
        A dict with ``superclasses: list[str]`` and optionally ``signature: str``.
    """
    fields: dict[str, Any] = {}

    # Superclasses
    if superclasses is None:
        superclasses = _get_superclasses(jedi_name, analyzer)
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


def _build_module_fields(jedi_name: Any, handle: str) -> dict[str, Any]:
    """Build kind-dependent fields for a module node.

    Determines whether the module is a package (i.e. its file is
    ``__init__.py``) and the parent package handle.

    Args:
        jedi_name: Jedi Name (or ``ModuleSentinel``) for the module.
        handle: Canonical dotted-name string of the module.

    Returns:
        A dict with ``is_package: bool`` and optionally ``package: str``.
    """
    fields: dict[str, Any] = {}

    file_path = jedi_name.module_path
    is_package = False
    if file_path is not None:
        is_package = file_path.name == "__init__.py"
    fields["is_package"] = is_package

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
        kind: ``"attribute"``, ``"property"``, or ``"variable"``.
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
