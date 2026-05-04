"""inspect(handle) — return a structural Node for a canonical handle.

The canonical "what is this?" operation.  Returns kind, signature, location,
docstring, plus kind-dependent fields.  No source content.  No edge expansions
beyond the 5 Phase 4 edge types in edge_counts.

Public API
----------
.. code-block:: python

    node = await inspect("pyeye.cache.GranularCache", analyzer)
    # → {handle, kind, scope, location, docstring, edge_counts: {...}, ...}

Design notes
------------
- ``edge_counts`` is ALWAYS present.  Phase 4 populates 5 edge types:
  ``members`` (class/module), ``superclasses`` (class), ``subclasses`` (class,
  project-scoped), ``callers`` (function/method), ``references`` (all kinds,
  excludes call sites).  Unmeasured edge types are ABSENT (not 0).
- ``re_exports``, ``highlights``, ``tags``, ``properties`` are ABSENT in Phase 4.
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
import functools
import logging
import time
from collections.abc import Awaitable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyeye import file_artifact_cache
from pyeye._jedi_location import location_from_name
from pyeye.canonicalization import collect_re_exports, find_module_file
from pyeye.handle import Handle
from pyeye.mcp.operations.resolve import _normalise_kind  # reuse kind table
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
# Param.kind mapping  (enum .name → API lowercase 5-value enum)
# Jedi's .kind is a Python inspect.Parameter.ParameterKind enum; we key on
# its .name string which is stable and avoids int-cast ambiguity.
# ---------------------------------------------------------------------------

_PARAM_KIND_MAP: dict[str, str] = {
    "POSITIONAL_ONLY": "positional",
    "POSITIONAL_OR_KEYWORD": "positional_or_keyword",
    "KEYWORD_ONLY": "keyword_only",
    "VAR_POSITIONAL": "var_positional",
    "VAR_KEYWORD": "var_keyword",
}

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


def _normalise_param_kind(jedi_param_kind: Any) -> str:
    """Map Jedi's param .kind enum to the API lowercase 5-value string.

    Jedi returns a ``jedi.api.classes.Parameter`` whose ``.kind`` attribute is
    a Python ``inspect.Parameter.ParameterKind`` enum value.  We map via its
    ``.name`` string, which is stable across Python versions.  Falls back to
    ``"positional_or_keyword"`` if unrecognised.

    Args:
        jedi_param_kind: The ``.kind`` attribute from a Jedi parameter object.

    Returns:
        One of the 5 lowercase kind strings.
    """
    return _PARAM_KIND_MAP.get(
        getattr(jedi_param_kind, "name", None) or "", "positional_or_keyword"
    )


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


def _is_method(handle: str, jedi_type: str, analyzer: JediAnalyzer) -> bool:
    """Return True if the symbol identified by *handle* is a method (not a module-level function).

    Checks whether the direct parent of the symbol in the dotted-name hierarchy
    is a class definition.  A standalone function at module level returns False.

    Args:
        handle: Fully-qualified dotted-name string.
        jedi_type: Jedi's ``Name.type`` string (e.g. ``"function"``).
        analyzer: Active analyzer for the project.

    Returns:
        ``True`` when the parent symbol is a class.
    """
    if jedi_type != "function":
        return False

    parts = handle.split(".")
    if len(parts) < 3:
        # Needs at least: module.Class.method
        return False

    parent_handle = ".".join(parts[:-1])
    parent_parts = parent_handle.split(".")
    if len(parent_parts) < 2:
        return False

    parent_module = ".".join(parent_parts[:-1])
    mod_file = find_module_file(parent_module, analyzer)
    if mod_file is None:
        return False

    try:
        script = file_artifact_cache.get_script(mod_file, analyzer.project)
        for name in script.get_names(all_scopes=True, definitions=True, references=False):
            if name.full_name == parent_handle and name.type == "class":
                return True
    except Exception:
        pass
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
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno == line:
                    is_async = isinstance(node, ast.AsyncFunctionDef)
                    deco_names: set[str] = set()
                    for deco in node.decorator_list:
                        if isinstance(deco, ast.Name):
                            deco_names.add(deco.id)
                        elif isinstance(deco, ast.Attribute):
                            deco_names.add(deco.attr)
                    return (
                        is_async,
                        "classmethod" in deco_names,
                        "staticmethod" in deco_names,
                    )
    except Exception:
        pass
    return False, False, False


def _find_function_def_at_line(
    file_path: Path, line: int
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the FunctionDef / AsyncFunctionDef whose ``lineno`` equals *line*.

    Uses the cached file AST. Returns ``None`` when no match is found or any
    error occurs (file missing, parse error, etc.).
    """
    try:
        tree = file_artifact_cache.get_ast(file_path)
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == line:
            return node
    return None


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
    guaranteed to be single-line (no embedded newlines).

    Args:
        jedi_name: A Jedi ``Name`` object.

    Returns:
        A single-line signature string, or ``None``.
    """
    try:
        sigs = jedi_name.get_signatures()
        if sigs:
            sig_str = sigs[0].to_string()
            # Guard: must be single-line
            if "\n" in sig_str:
                sig_str = sig_str.split("\n")[0]
            return str(sig_str)
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
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.lineno == line:
                for base in node.bases:
                    base_str = ast.unparse(base)
                    # Attempt Jedi-based resolution for the base class handle
                    resolved = _resolve_base_class_via_jedi(
                        str(file_path), base, base_str, analyzer
                    )
                    superclasses.append(resolved)
                break
    except Exception:
        pass

    return superclasses


def _attr_target_position(base_node: ast.expr) -> tuple[int, int]:
    """Return (line, col) of the rightmost identifier in a base-class expression.

    For ``ast.Name`` (e.g. ``Widget``): the position of the name itself.
    For ``ast.Attribute`` (e.g. ``pkg.sub.Widget``): the position of the
    rightmost attribute name (``Widget``), not the leftmost receiver (``pkg``).

    Using the rightmost position ensures ``jedi.Script.goto()`` resolves the
    actual class, not the package/module that acts as the receiver.

    Args:
        base_node: AST node representing the base class expression.

    Returns:
        ``(line, col)`` tuple suitable for passing to ``jedi.Script.goto()``.
    """
    if isinstance(base_node, ast.Attribute):
        # ast.Attribute stores end_lineno/end_col_offset for the entire chain.
        # The rightmost attr name ends there and starts len(attr) characters before.
        end_line = base_node.end_lineno or base_node.lineno
        end_col = base_node.end_col_offset or 0
        return end_line, max(0, end_col - len(base_node.attr))
    # ast.Name or any other node type — use the node's own start position.
    return base_node.lineno, base_node.col_offset


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
        return _ModuleSentinel(mod_file, handle, analyzer)

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
                    return name
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


class _ModuleSentinel:
    """Lightweight stand-in for a Jedi Name when the handle *is* a module.

    Stores the module file path and enough info for ``inspect`` to build the
    location and docstring without a real ``Name`` object.
    """

    def __init__(self, mod_file: Path, handle: str, analyzer: JediAnalyzer) -> None:
        self.mod_file = mod_file
        self.handle = handle
        self._analyzer = analyzer

        # Populate Jedi-Name-like attributes from the module file
        self.module_path: Path | None = mod_file
        self.type = "module"
        self.full_name: str = handle
        self.name: str = handle.split(".")[-1]
        self.line: int = 1
        self.column: int = 0

        # Read docstring from module-level AST
        self.docstring_text: str = ""
        try:
            source = mod_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
            ds = ast.get_docstring(tree)
            if ds:
                self.docstring_text = ds
        except Exception:
            pass

    def docstring(self, **kwargs: object) -> str:
        _ = kwargs  # accepted-and-ignored for Jedi Name.docstring() signature compat
        return self.docstring_text

    def get_signatures(self) -> list:
        return []

    def infer(self) -> list:
        return []


# ---------------------------------------------------------------------------
# Edge-count helpers
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=256)
def _read_file_lines(file_str: str) -> tuple[str, ...]:
    """Read a file's lines; cached to avoid re-reading per reference site.

    Keyed by POSIX file path string.  LRU-evicts at 256 entries to bound
    memory.  Returns an empty tuple on any I/O or encoding error.

    Args:
        file_str: POSIX file path string.

    Returns:
        A tuple of line strings (no trailing newlines).
    """
    try:
        with open(file_str, encoding="utf-8", errors="replace") as f:
            return tuple(f.read().splitlines())
    except (OSError, UnicodeDecodeError):
        return ()


def _is_call_site(file_str: str, line: int, col: int, name: str) -> bool:
    """Return True if the symbol reference at (file, line, col) is a call site.

    Checks whether the character immediately after the symbol name at column
    ``col`` is an opening parenthesis ``(``.  This is a source-level heuristic
    that works reliably for simple call patterns (``f()``, ``obj.method()``,
    ``pkg.func(*args)``).

    File lines are read via ``_read_file_lines`` which is LRU-cached, so a
    file with N reference sites is read from disk only once per inspect call.

    Args:
        file_str: POSIX file path string.
        line: 1-indexed line number.
        col: 0-indexed column of the name start.
        name: The symbol name (to compute the end column).

    Returns:
        ``True`` when the character at ``col + len(name)`` is ``(``.
    """
    try:
        lines = _read_file_lines(file_str)
        if 0 <= line - 1 < len(lines):
            src_line = lines[line - 1]
            check_pos = col + len(name)
            if check_pos < len(src_line):
                return src_line[check_pos] == "("
    except Exception:
        pass
    return False


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

    Walks the class definition's file via Jedi and counts names whose
    ``full_name`` has exactly one more dotted component than the class handle.

    Args:
        handle: The class's canonical dotted-name string.
        jedi_name: Jedi ``Name`` for the class.
        analyzer: Active analyzer (unused here, but consistent with API).

    Returns:
        Count of direct class members.
    """
    _ = analyzer
    file_path: Path | None = jedi_name.module_path
    if file_path is None:
        return 0
    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        names = script.get_names(all_scopes=True, definitions=True, references=False)
        prefix = handle + "."
        handle_depth = len(handle.split("."))
        count = 0
        for n in names:
            fn = n.full_name or ""
            if fn.startswith(prefix) and len(fn.split(".")) == handle_depth + 1:
                count += 1
        return count
    except Exception:
        return 0


async def _count_module_members(jedi_name: Any, analyzer: JediAnalyzer) -> int:
    """Count top-level definitions in a module.

    Uses Jedi's ``get_names(all_scopes=False)`` on the module file to find all
    top-level definitions.

    Args:
        jedi_name: Jedi ``Name`` or ``_ModuleSentinel`` for the module.
        analyzer: Active analyzer.

    Returns:
        Count of top-level module members.
    """
    file_path: Path | None = jedi_name.module_path
    if file_path is None:
        return 0
    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        names = script.get_names(all_scopes=False, definitions=True, references=False)
        return len(names)
    except Exception:
        return 0


async def _count_superclasses(jedi_name: Any, analyzer: JediAnalyzer) -> int:
    """Count direct superclasses of a class.

    Re-uses ``_get_superclasses`` (the AST + Jedi goto approach already
    implemented for the ``superclasses`` kind-dependent field) and returns
    the count of the resolved list.

    Args:
        jedi_name: Jedi ``Name`` for the class.
        analyzer: Active analyzer.

    Returns:
        Count of direct superclasses.
    """
    return len(_get_superclasses(jedi_name, analyzer))


async def _count_subclasses(handle: str, analyzer: JediAnalyzer) -> int:
    """Count project-internal subclasses of a class.

    Delegates to ``analyzer.find_subclasses`` with ``scope="main"`` so only
    project files are searched.  External subclasses (stdlib, third-party)
    are excluded.

    Args:
        handle: The class's canonical dotted-name string.
        analyzer: Active analyzer.

    Returns:
        Count of project-internal subclasses (direct + indirect).
    """
    try:
        result = await analyzer.find_subclasses(
            handle,  # Pass the full FQN for unambiguous, FQN-strict resolution
            scope="main",
            include_indirect=True,
            show_hierarchy=False,
        )
        # Unambiguous path (FQN input never triggers ambiguous variant)
        assert not result.get(
            "ambiguous", False
        ), f"FQN input to find_subclasses returned ambiguous variant: {handle!r}"
        return len(result.get("subclasses", []))
    except Exception:
        return 0


async def _count_callers_and_refs(
    handle: str,
    jedi_name: Any,
    analyzer: JediAnalyzer,
) -> tuple[int, int]:
    """Count callers and non-call references for a function/method.

    Uses Jedi ``get_references`` (excluding definitions) then partitions
    results into call sites vs non-call references using a source-level
    heuristic (character immediately after the name is ``(``) .

    Args:
        handle: Canonical dotted-name string.
        jedi_name: Jedi ``Name`` for the function/method.
        analyzer: Active analyzer.

    Returns:
        ``(callers, references)`` tuple where ``callers`` is the count of
        call sites and ``references`` is the count of non-call usages.
    """
    file_path: Path | None = jedi_name.module_path
    if file_path is None:
        return 0, 0
    try:
        file_str = file_path.as_posix()
        line = jedi_name.line
        col = jedi_name.column
        if not line:
            return 0, 0
        refs = await analyzer.find_references(file_str, line, col, include_definitions=False)
        name = handle.split(".")[-1]
        callers = 0
        references = 0
        for ref in refs:
            ref_file = ref.get("file", "")
            ref_line = ref.get("line", 0)
            ref_col = ref.get("column", 0)
            if ref_file and _is_call_site(ref_file, ref_line, ref_col, name):
                callers += 1
            else:
                references += 1
        return callers, references
    except Exception:
        return 0, 0


async def _count_references_only(
    handle: str,
    jedi_name: Any,
    analyzer: JediAnalyzer,
) -> int:
    """Count non-call references for a non-callable symbol (attr/variable/module/class).

    For non-callable kinds (attributes, variables, modules, and classes when
    accessed as a reference), all non-definition uses count as references.
    There is no separate callers count.

    Args:
        handle: Canonical dotted-name string.
        jedi_name: Jedi ``Name`` for the symbol.
        analyzer: Active analyzer.

    Returns:
        Count of non-definition, non-call references.
    """
    file_path: Path | None = jedi_name.module_path
    if file_path is None:
        return 0
    try:
        file_str = file_path.as_posix()
        line = jedi_name.line
        col = jedi_name.column
        if not line:
            return 0
        refs = await analyzer.find_references(file_str, line, col, include_definitions=False)
        name = handle.split(".")[-1]
        # For non-callable kinds, exclude call sites from references count
        # (a class used as a constructor call is a caller, not a reference)
        count = 0
        for ref in refs:
            ref_file = ref.get("file", "")
            ref_line = ref.get("line", 0)
            ref_col = ref.get("column", 0)
            if ref_file and not _is_call_site(ref_file, ref_line, ref_col, name):
                count += 1
        return count
    except Exception:
        return 0


async def _count_callers_only(
    handle: str,
    jedi_name: Any,
    analyzer: JediAnalyzer,
) -> int:
    """Count call sites for a class handle (instantiation calls).

    For classes, we measure callers as the number of times the class is
    instantiated (called with ``()``).

    Args:
        handle: Canonical dotted-name string.
        jedi_name: Jedi ``Name`` for the class.
        analyzer: Active analyzer.

    Returns:
        Count of call sites (instantiation/call usages).
    """
    file_path: Path | None = jedi_name.module_path
    if file_path is None:
        return 0
    try:
        file_str = file_path.as_posix()
        line = jedi_name.line
        col = jedi_name.column
        if not line:
            return 0
        refs = await analyzer.find_references(file_str, line, col, include_definitions=False)
        name = handle.split(".")[-1]
        count = 0
        for ref in refs:
            ref_file = ref.get("file", "")
            ref_line = ref.get("line", 0)
            ref_col = ref.get("column", 0)
            if ref_file and _is_call_site(ref_file, ref_line, ref_col, name):
                count += 1
        return count
    except Exception:
        return 0


async def _measure_callers_and_refs_with_budget(
    handle: str,
    jedi_name: Any,
    analyzer: JediAnalyzer,
    budget_seconds: float = _DEFAULT_EDGE_BUDGET_SECONDS,
) -> tuple[int, int] | None:
    """Run ``_count_callers_and_refs`` under a single shared time budget.

    Uses ONE ``find_references`` call to derive both ``callers`` and
    ``references`` counts.  A timeout or error on the shared query omits
    BOTH edges — this is correct: if we couldn't finish the query, neither
    count is reliable.

    Note: Jedi's API is synchronous internally, so the ``asyncio.wait_for``
    wrapper provides clean budget enforcement but does not provide true
    concurrency with other async tasks.

    Args:
        handle: Canonical dotted-name string (for logging).
        jedi_name: Jedi ``Name`` for the function/method.
        analyzer: Active analyzer.
        budget_seconds: Maximum wall-clock time for the combined measurement.

    Returns:
        ``(callers, references)`` tuple on success, or ``None`` on
        timeout/error (both edges are absent when ``None`` is returned).
    """
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            _count_callers_and_refs(handle, jedi_name, analyzer),
            timeout=budget_seconds,
        )
        return result
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - start
        logger.warning(
            "inspect.edge_counts: callers+references timeout after %.2fs (handle=%r)",
            elapsed,
            handle,
        )
        return None
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.warning(
            "inspect.edge_counts: callers+references failed after %.2fs (handle=%r): %s",
            elapsed,
            handle,
            exc,
        )
        return None


async def _build_edge_counts(
    handle: str,
    kind: str,
    jedi_name: Any,
    analyzer: JediAnalyzer,
    budget_seconds: float = _DEFAULT_EDGE_BUDGET_SECONDS,
) -> dict[str, int]:
    """Build the edge_counts dict per Phase 4 contract.

    Each edge measurement runs under an independent time budget.  Edges that
    time out or error are OMITTED from the returned dict (absence-vs-zero
    invariant).  Edges that succeed are included even when the count is 0.

    For function/method handles, ``callers`` and ``references`` share ONE
    ``find_references`` call via ``_measure_callers_and_refs_with_budget``.
    A timeout on that shared query omits BOTH edges — if the underlying query
    didn't complete, neither derived count is reliable.

    Phase 4 measures exactly 5 edge types:
    - ``members``: count of direct members (class and module handles)
    - ``superclasses``: count of direct superclasses (class handles)
    - ``subclasses``: count of project-internal subclasses (class handles)
    - ``callers``: count of call sites (function/method handles; also class)
    - ``references``: non-call usages aggregate (all kinds)

    Note: Jedi's API is synchronous internally, so ``asyncio.gather`` provides
    clean concurrent-looking code but execution is effectively serialized.

    Args:
        handle: Canonical dotted-name string.
        kind: Normalised kind string (``"class"``, ``"function"``, etc.).
        jedi_name: Jedi ``Name`` (or ``_ModuleSentinel``) for the symbol.
        analyzer: Active analyzer.
        budget_seconds: Per-edge time budget in seconds.

    Returns:
        A dict containing the successfully measured edges.
    """
    counts: dict[str, int] = {}

    if kind in ("function", "method"):
        # ONE find_references call shared between callers and references.
        # A timeout omits BOTH — we couldn't measure either reliably.
        pair = await _measure_callers_and_refs_with_budget(
            handle, jedi_name, analyzer, budget_seconds
        )
        if pair is not None:
            callers, references = pair
            counts["callers"] = callers
            counts["references"] = references
        return counts

    # For all other kinds, build a dict of independent single-int coroutines.
    coros: dict[str, Awaitable[int]] = {}

    if kind == "class":
        coros["members"] = _count_class_members(handle, jedi_name, analyzer)
        coros["superclasses"] = _count_superclasses(jedi_name, analyzer)
        coros["subclasses"] = _count_subclasses(handle, analyzer)
        coros["callers"] = _count_callers_only(handle, jedi_name, analyzer)
        coros["references"] = _count_references_only(handle, jedi_name, analyzer)

    elif kind == "module":
        coros["members"] = _count_module_members(jedi_name, analyzer)
        coros["references"] = _count_references_only(handle, jedi_name, analyzer)

    elif kind in ("attribute", "property", "variable", "statement"):
        coros["references"] = _count_references_only(handle, jedi_name, analyzer)

    # else: kind not handled → no measurements; counts stays empty

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

    Always includes ``edge_counts`` (Phase 4 measures: members, superclasses,
    subclasses, callers, references — for relevant kinds).  Edges that exceed
    their per-measurement budget are OMITTED, not zero.
    Phase 6 adds ``re_exports`` for non-module kinds (class, function, method,
    property, variable, attribute).  For module kind, ``re_exports`` is ABSENT
    (not computed in Phase 6 — per the absence-vs-zero spec invariant: absent
    means "we don't compute re_exports for this kind").
    ``highlights``, ``tags``, and ``properties`` remain absent (later phases).

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
    # Step 1 — Locate the symbol
    # ------------------------------------------------------------------
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)

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

    jedi_type: str = getattr(jedi_name, "type", None) or "statement"
    # Determine if this function is actually a method
    raw_kind = _normalise_kind(jedi_type)
    if raw_kind == "function" and _is_method(handle, jedi_type, analyzer):
        kind = "method"
    else:
        kind = raw_kind

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

    if kind == "class":
        kind_fields.update(_build_class_fields(jedi_name, analyzer))

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
    # Phase 4: edge_counts populated with per-measurement budgeted counts
    node["edge_counts"] = await _build_edge_counts(handle, kind, jedi_name, analyzer)

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


def _build_class_fields(jedi_name: Any, analyzer: JediAnalyzer) -> dict[str, Any]:
    """Build kind-dependent fields for a class node.

    Extracts the class signature (from ``__init__``) and the list of direct
    superclass handles.

    Args:
        jedi_name: Jedi Name for the class.
        analyzer: Active analyzer.

    Returns:
        A dict with ``superclasses: list[str]`` and optionally ``signature: str``.
    """
    fields: dict[str, Any] = {}

    # Superclasses
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

    sig = _build_signature(jedi_name)
    fields["signature"] = sig or ""

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
        jedi_name: Jedi Name (or ``_ModuleSentinel``) for the module.
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
