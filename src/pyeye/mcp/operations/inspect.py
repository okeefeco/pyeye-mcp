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
from pyeye.canonicalization import find_module_file
from pyeye.mcp.operations.resolve import _normalise_kind  # reuse kind table
from pyeye.scope import classify_scope

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-measurement time budget
# ---------------------------------------------------------------------------

_DEFAULT_EDGE_BUDGET_SECONDS: float = 2.0

# ---------------------------------------------------------------------------
# Node-type constants
# ---------------------------------------------------------------------------

_DEFINITION_TYPES: frozenset[str] = frozenset(
    ("funcdef", "classdef", "async_funcdef", "async_stmt", "decorated")
)

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


def _get_end_line(jedi_name: Any) -> int:
    """Extract the end line from a Jedi Name object by walking its internal tree.

    Walks the internal ``tree_name`` hierarchy to find the enclosing function/
    class definition node, then reads its ``end_pos`` attribute.  Falls back to
    the start line if the end cannot be determined.

    Args:
        jedi_name: A Jedi ``Name`` object.

    Returns:
        The 1-indexed end line number.
    """
    start_line: int = jedi_name.line or 1
    try:
        internal = getattr(jedi_name, "_name", None)
        if internal is None:
            return start_line
        tree_name = getattr(internal, "tree_name", None)
        if tree_name is None:
            return start_line

        # Walk up to the nearest definition node with end_pos
        node = tree_name.parent
        while node is not None:
            if getattr(node, "type", None) in _DEFINITION_TYPES:
                end_pos = getattr(node, "end_pos", None)
                if end_pos is not None:
                    return int(end_pos[0])
                break
            node = getattr(node, "parent", None)
    except Exception:
        pass
    return start_line


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


def _build_parameters(jedi_name: Any) -> list[dict[str, Any]]:
    """Build the ``parameters`` list for a function/method node.

    Extracts parameter information from Jedi's signature API.  Each parameter
    dict contains ``name``, ``kind``, and optionally ``type`` (from the
    annotation string) and ``default`` (simple literals only).

    Implicit parameters (``self``, ``cls``) are included since they form part
    of the structural signature.

    Args:
        jedi_name: A Jedi ``Name`` object for a function/method.

    Returns:
        A list of parameter dicts.
    """
    try:
        sigs = jedi_name.get_signatures()
        if not sigs:
            return []
        sig = sigs[0]
        params: list[dict[str, Any]] = []
        for p in sig.params:
            pname = p.name
            param_dict: dict[str, Any] = {
                "name": pname,
                "kind": _normalise_param_kind(p.kind),
            }
            # Type annotation — from Jedi's description string
            desc = p.description  # e.g. "param name: str='anon'"
            # Extract type hint from description if present
            try:
                type_hint = p.get_type_hint()
                if type_hint:
                    param_dict["type"] = type_hint
            except Exception:
                pass

            # Default value — only simple literals
            try:
                # desc format: "param name: type=default" or "param name=default"
                if "=" in desc:
                    default_part = desc.split("=", 1)[1].strip()
                    # Remove trailing ) or other noise
                    default_part = default_part.rstrip(")")
                    if default_part and _is_simple_literal(default_part):
                        param_dict["default"] = default_part
            except Exception:
                pass

            params.append(param_dict)
        return params
    except Exception:
        return []


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


def _extract_return_type(jedi_name: Any) -> str | None:
    """Extract the return type annotation string from a Jedi Name's signature.

    Parses the ``->`` portion of the signature string.  Returns ``None`` when
    no return type is annotated.

    Args:
        jedi_name: A Jedi ``Name`` object for a function/method.

    Returns:
        The return type string, or ``None``.
    """
    try:
        sigs = jedi_name.get_signatures()
        if not sigs:
            return None
        sig_str = sigs[0].to_string()
        arrow_idx = sig_str.rfind("->")
        if arrow_idx != -1:
            return_type = sig_str[arrow_idx + 2 :].strip().strip("\"'")
            return return_type if return_type else None
    except Exception:
        pass
    return None


def _extract_attribute_info(file_path: Path, line: int) -> tuple[str | None, str | None]:
    """Extract type annotation and default value for an attribute/variable at *line*.

    Parses the AST of *file_path* to find an annotated assignment or plain
    assignment at *line*.  Returns the annotation string and default value
    string (only when the default is a simple literal).

    Args:
        file_path: Absolute path to the source file.
        line: 1-indexed line number of the attribute definition.

    Returns:
        A 2-tuple ``(type_annotation_str, default_str)`` where either element
        may be ``None`` if not found or not a simple literal.
    """
    type_annotation: str | None = None
    default_str: str | None = None

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and node.lineno == line:
                type_annotation = ast.unparse(node.annotation)
                if node.value is not None:
                    raw_default = ast.unparse(node.value)
                    if _is_simple_literal(raw_default):
                        default_str = raw_default
                break
            elif isinstance(node, ast.Assign) and node.lineno == line:
                raw_default = ast.unparse(node.value)
                if _is_simple_literal(raw_default):
                    default_str = raw_default
                break
    except Exception:
        pass

    return type_annotation, default_str


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
    # Simple name is the last component of the dotted handle
    simple_name = handle.split(".")[-1]
    try:
        subclasses = await analyzer.find_subclasses(
            simple_name,
            scope="main",
            include_indirect=True,
            show_hierarchy=False,
        )
        return len(subclasses)
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
    Never includes ``re_exports``, ``highlights``, ``tags``, or ``properties``
    (those are wired in later phases).

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

    line_start: int = jedi_name.line or 1
    line_end: int = _get_end_line(jedi_name)
    if line_end < line_start:
        line_end = line_start

    col_start: int | None = jedi_name.column

    location = _make_location(file_str, line_start, line_end, col_start)

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
        kind_fields.update(_build_function_fields(jedi_name, file_path))

    elif kind == "module":
        kind_fields.update(_build_module_fields(jedi_name, handle))

    elif kind in ("attribute", "property", "variable"):
        kind_fields.update(_build_attribute_fields(jedi_name, kind, file_path))

    # ------------------------------------------------------------------
    # Step 4 — Assemble node (no re_exports, highlights, tags, properties)
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


def _build_function_fields(jedi_name: Any, file_path: Path | None) -> dict[str, Any]:
    """Build kind-dependent fields for a function or method node.

    Extracts signature, parameters, return type, and async/classmethod/
    staticmethod flags.

    Args:
        jedi_name: Jedi Name for the function/method.
        file_path: Absolute path to the source file (for AST-based flag detection).

    Returns:
        A dict with ``signature``, ``parameters``, ``return_type``,
        ``is_async``, ``is_classmethod``, ``is_staticmethod``.
    """
    fields: dict[str, Any] = {}

    sig = _build_signature(jedi_name)
    fields["signature"] = sig or ""

    fields["parameters"] = _build_parameters(jedi_name)
    fields["return_type"] = _extract_return_type(jedi_name)

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


def _build_attribute_fields(jedi_name: Any, kind: str, file_path: Path | None) -> dict[str, Any]:
    """Build kind-dependent fields for an attribute, property, or variable node.

    Extracts type annotation and default value (simple literals only) from
    the source AST.  For ``property`` kind, only the return type annotation
    is extracted (no ``default``).

    Args:
        jedi_name: Jedi Name for the attribute/property/variable.
        kind: ``"attribute"``, ``"property"``, or ``"variable"``.
        file_path: Absolute path to the source file (for AST-based extraction).

    Returns:
        A dict with optional ``type: str`` and optional ``default: str``.
    """
    fields: dict[str, Any] = {}

    if file_path is None or not file_path.exists():
        return fields

    line = jedi_name.line
    if not line:
        return fields

    if kind == "property":
        # For properties, extract the return type from the function signature
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.lineno == line
                ):
                    if node.returns is not None:
                        fields["type"] = ast.unparse(node.returns)
                    break
        except Exception:
            pass
    else:
        type_annotation, default_str = _extract_attribute_info(file_path, line)
        if type_annotation is not None:
            fields["type"] = type_annotation
        if default_str is not None:
            fields["default"] = default_str

    return fields
