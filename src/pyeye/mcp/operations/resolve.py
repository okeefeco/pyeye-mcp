"""resolve(identifier) — convert any identifier form to a canonical Handle.

This is the entry point for Phase 2 of the PyEye resolve/inspect API.  Agents
call this to turn any name, path, or coordinate into a stable, canonical handle
that can be passed to inspect() and other operations.

Supported identifier forms
--------------------------
1. Bare name: ``Config``
2. Fully-qualified dotted name: ``a.b.c.Config``
3. Re-exported public path: ``package.Config``  (collapses to definition site)
4. File path with line: ``src/foo.py:42``
5. File path only: ``src/foo.py``

Resolution strategy
-------------------
- Bare names are resolved by enumerating *all* matches via
  ``JediAnalyzer.find_symbol``.  If exactly one match, return success; if
  multiple, return an ambiguous result with sorted candidates; if zero, return
  not-found.
- Dotted names are passed directly to ``resolve_canonical``, which follows
  multi-hop re-export chains and returns the definition-site Handle.
- File-with-line: read the line to locate the first non-whitespace column,
  then use ``script.goto()`` at that position to find the symbol's definition.
- File-only: convert the file path to a dotted module path via
  ``_get_import_path_for_file`` and return a module-scoped Handle.

Kind normalisation
------------------
Jedi's ``Name.type`` is mapped to the API kind vocabulary:

    class      → "class"
    function   → "function"
    module     → "module"
    statement  → "variable"
    param      → "variable"
    property   → "property"
    keyword    → "variable"  (rare; included for completeness)

Deterministic ambiguous ordering
---------------------------------
Candidates are sorted by ``(scope, file, line_start)`` ascending, where
``scope`` is ordered ``"project" < "external"`` (project first).

Public API
----------
.. code-block:: python

    result = await resolve("Config", analyzer)
    # → {"found": True, "handle": "mypackage._core.Config",
    #    "kind": "class", "scope": "project"}
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from pyeye import file_artifact_cache
from pyeye.canonicalization import resolve_canonical
from pyeye.handle import Handle
from pyeye.scope import classify_scope

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result TypedDicts (wire-format safe — serialise directly to JSON/MCP)
# ---------------------------------------------------------------------------


class _Location(TypedDict):
    file: str
    line_start: int
    line_end: int
    column_start: int
    column_end: int


class _Candidate(TypedDict):
    handle: str
    kind: str
    scope: Literal["project", "external"]
    location: _Location


class _SuccessResult(TypedDict):
    found: Literal[True]
    handle: str
    kind: str
    scope: Literal["project", "external"]


class _AmbiguousResult(TypedDict):
    found: Literal[True]
    ambiguous: Literal[True]
    candidates: list[_Candidate]


class _NotFoundResult(TypedDict):
    found: Literal[False]
    reason: str


ResolveResult = _SuccessResult | _AmbiguousResult | _NotFoundResult

# ---------------------------------------------------------------------------
# Identifier-form descriptor
# ---------------------------------------------------------------------------

# A simple tagged-union dict returned by _parse_identifier.
# We use plain dicts rather than TypedDict for the internal form since the
# fields differ per kind and TypedDict doesn't yet support discriminated unions
# cleanly in Python 3.10.

IdentifierForm = dict[str, Any]

# Regex: <some-path>:<positive-integer>
_FILE_LINE_RE = re.compile(r"^(.+):(\d+)$")


def _parse_identifier(identifier: str) -> IdentifierForm:
    r"""Parse an identifier string into a tagged-union form dict.

    Priority order:
    1. ``<path>:<integer>`` → file_with_line
    2. Contains ``/`` or ``\\`` or ends in ``.py`` → file_only
    3. Contains ``.`` (no slashes) → dotted_name
    4. No dots → bare_name

    Args:
        identifier: Raw identifier string from the caller.

    Returns:
        A dict with at minimum a ``"kind"`` key.  Additional keys depend on
        the kind:
        - ``file_with_line``: ``path`` (str), ``line`` (int)
        - ``file_only``: ``path`` (str)
        - ``dotted_name``: ``name`` (str)
        - ``bare_name``: ``name`` (str)
    """
    # 1. file_with_line: ends with :<integer>
    m = _FILE_LINE_RE.match(identifier)
    if m:
        path_part, line_str = m.group(1), m.group(2)
        # Only treat as file if the path part looks like a file path
        if "/" in path_part or "\\" in path_part or path_part.endswith(".py"):
            return {"kind": "file_with_line", "path": path_part, "line": int(line_str)}

    # 2. file_only: contains a path separator or .py extension
    if "/" in identifier or "\\" in identifier or identifier.endswith(".py"):
        return {"kind": "file_only", "path": identifier}

    # 3. dotted_name: contains dots (but no path separators)
    if "." in identifier:
        return {"kind": "dotted_name", "name": identifier}

    # 4. bare_name: no dots, no path separators
    return {"kind": "bare_name", "name": identifier}


# ---------------------------------------------------------------------------
# Kind normalisation
# ---------------------------------------------------------------------------

# Jedi type → API kind
_JEDI_TYPE_TO_KIND: dict[str, str] = {
    "class": "class",
    "function": "function",
    "module": "module",
    "instance": "variable",
    "statement": "variable",
    "param": "variable",
    "property": "property",
    "keyword": "variable",
    "import": "module",
}


def _normalise_kind(jedi_type: str | None) -> str:
    """Map Jedi's ``Name.type`` to the API kind vocabulary."""
    if jedi_type is None:
        return "variable"
    return _JEDI_TYPE_TO_KIND.get(jedi_type, jedi_type)


# ---------------------------------------------------------------------------
# Scope ordering helper
# ---------------------------------------------------------------------------

_SCOPE_ORDER: dict[str, int] = {"project": 0, "external": 1}


def _candidate_sort_key(candidate: _Candidate) -> tuple[int, str, int]:
    """Sort key for deterministic ambiguous ordering: (scope, file, line_start)."""
    return (
        _SCOPE_ORDER.get(candidate["scope"], 99),
        candidate["location"]["file"],
        candidate["location"]["line_start"],
    )


# ---------------------------------------------------------------------------
# File:line resolution helper
# ---------------------------------------------------------------------------


async def _resolve_file_line(file_path: Path, line: int, analyzer: JediAnalyzer) -> ResolveResult:
    """Resolve a file:line coordinate to a symbol handle.

    Strategy:
    1. Read the target line and find the column of the first non-whitespace
       character (skipping ``class``/``def`` keywords to land on the name).
    2. Call ``script.goto()`` at that position.
    3. Canonicalise the result via ``resolve_canonical``.
    4. Fall back to column 0 if step 1 yields no goto results.
    """
    if not file_path.exists():
        return _NotFoundResult(found=False, reason="file_not_found")

    # Determine a useful column on the target line.
    column = _find_symbol_column_on_line(file_path, line)

    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        definitions = script.goto(line, column)
    except Exception as exc:
        logger.debug("_resolve_file_line: goto(%d, %d) failed: %s", line, column, exc)
        return _NotFoundResult(found=False, reason="no_symbol_at_position")

    if not definitions:
        # Try column 0 as a last resort (reuse the same script object)
        with contextlib.suppress(Exception):
            definitions = script.goto(line, 0)

    if not definitions:
        return _NotFoundResult(found=False, reason="no_symbol_at_position")

    name = definitions[0]
    full_name = name.full_name
    if not full_name:
        return _NotFoundResult(found=False, reason="unresolved")

    # Canonicalise (may follow import chain)
    handle = await resolve_canonical(full_name, analyzer)
    if handle is None:
        # Fall back to raw full_name if it's a valid handle
        try:
            handle = Handle(full_name)
        except ValueError:
            return _NotFoundResult(found=False, reason="unresolved")

    # Determine file for scope classification
    def_file = name.module_path.as_posix() if name.module_path else Path(file_path).as_posix()
    scope = classify_scope(def_file, analyzer)
    kind = _normalise_kind(name.type)

    return _SuccessResult(
        found=True,
        handle=str(handle),
        kind=kind,
        scope=scope,
    )


def _find_symbol_column_on_line(file_path: Path, line: int) -> int:
    """Find the column of the first identifier on *line* (1-indexed).

    Skips leading whitespace and ``class``/``def`` keywords so that
    ``script.goto()`` lands on the symbol name rather than the keyword.

    Returns 0 if the line cannot be read or has no identifier.
    """
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line < 1 or line > len(lines):
            return 0
        raw = lines[line - 1]
        # Strip leading whitespace to get first token
        stripped = raw.lstrip()
        if not stripped:
            return 0
        # Skip 'class', 'def', 'async' keywords
        offset = len(raw) - len(stripped)
        token_match = re.match(r"^(class|def|async\s+def)\s+", stripped)
        if token_match:
            offset += len(token_match.group(0))
        return offset
    except Exception as exc:
        logger.debug("_find_symbol_column_on_line(%s, %d) failed: %s", file_path, line, exc)
        return 0


# ---------------------------------------------------------------------------
# Bare-name enumeration helper
# ---------------------------------------------------------------------------


async def _resolve_bare_name(name: str, analyzer: JediAnalyzer) -> ResolveResult:
    """Enumerate all project matches for a bare (no-dots) symbol name.

    Calls ``analyzer.find_symbol(name)`` to get all matches.  Returns:
    - success if exactly one project match is found
    - ambiguous if multiple project matches are found
    - not-found if no matches are found
    """
    try:
        matches = await analyzer.find_symbol(name)
    except Exception as exc:
        logger.debug("_resolve_bare_name(%r): find_symbol failed: %s", name, exc)
        return _NotFoundResult(found=False, reason="unresolved")

    if not matches:
        return _NotFoundResult(found=False, reason="unresolved")

    # Filter to matches that have a full_name (resolvable symbols)
    valid_matches = [m for m in matches if m.get("full_name")]

    if not valid_matches:
        return _NotFoundResult(found=False, reason="unresolved")

    if len(valid_matches) == 1:
        return await _build_success_from_match(valid_matches[0], analyzer)

    # Multiple matches — build ambiguous result
    candidates: list[_Candidate] = []
    for match in valid_matches:
        candidate = await _build_candidate_from_match(match, analyzer)
        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        return _NotFoundResult(found=False, reason="unresolved")

    if len(candidates) == 1:
        # After deduplication, only one valid candidate
        c = candidates[0]
        return _SuccessResult(
            found=True,
            handle=c["handle"],
            kind=c["kind"],
            scope=c["scope"],
        )

    # Sort candidates deterministically: (scope, file, line_start)
    candidates.sort(key=_candidate_sort_key)

    return _AmbiguousResult(
        found=True,
        ambiguous=True,
        candidates=candidates,
    )


async def _build_success_from_match(match: dict[str, Any], analyzer: JediAnalyzer) -> ResolveResult:
    """Build a _SuccessResult from a single find_symbol match dict."""
    full_name = match.get("full_name", "")
    file_str = match.get("file", "")
    kind = _normalise_kind(match.get("type"))

    # Canonicalise
    handle = await resolve_canonical(full_name, analyzer)
    if handle is None:
        try:
            handle = Handle(full_name)
        except ValueError:
            return _NotFoundResult(found=False, reason="unresolved")

    scope = classify_scope(file_str, analyzer) if file_str else "external"

    return _SuccessResult(
        found=True,
        handle=str(handle),
        kind=kind,
        scope=scope,
    )


async def _build_candidate_from_match(
    match: dict[str, Any], analyzer: JediAnalyzer
) -> _Candidate | None:
    """Build a _Candidate dict from a single find_symbol match dict."""
    full_name = match.get("full_name", "")
    file_str = match.get("file", "")
    kind = _normalise_kind(match.get("type"))

    if not full_name:
        return None

    # Canonicalise
    handle = await resolve_canonical(full_name, analyzer)
    if handle is None:
        try:
            handle = Handle(full_name)
        except ValueError:
            return None

    scope = classify_scope(file_str, analyzer) if file_str else "external"

    line = match.get("line") or 1
    column = match.get("column") or 0
    file_posix = Path(file_str).as_posix() if file_str else ""

    return _Candidate(
        handle=str(handle),
        kind=kind,
        scope=scope,
        location=_Location(
            file=file_posix,
            line_start=line,
            line_end=line,
            column_start=column,
            column_end=column,
        ),
    )


# ---------------------------------------------------------------------------
# Dotted-name resolution helper
# ---------------------------------------------------------------------------


def _kind_for_canonical(canonical_handle: str, analyzer: JediAnalyzer) -> str:
    """Look up kind by re-deriving from the canonical handle's definition site.

    Used as a fallback when ``find_symbol`` leaf search doesn't return the
    matching symbol.  Splits the handle into ``<module>.<leaf>``, resolves the
    module file, then searches ``jedi.Script.get_names`` for the symbol.

    Returns ``"module"`` for a bare module name (no dot), ``"variable"`` when
    the kind genuinely cannot be determined (safest Python kind — every binding
    is at minimum a name binding).
    """
    from pyeye.canonicalization import find_module_file

    parts = canonical_handle.rsplit(".", 1)
    if len(parts) != 2:
        return "module"  # bare module name
    module_path, _ = parts
    module_file = find_module_file(module_path, analyzer)
    if module_file is None:
        return "variable"  # safer default than "class"
    script = file_artifact_cache.get_script(module_file, analyzer.project)
    try:
        for name_obj in script.get_names(all_scopes=True, definitions=True, references=False):
            if name_obj.full_name == canonical_handle:
                return _normalise_kind(name_obj.type) or "variable"
    except Exception as exc:
        logger.debug("_kind_for_canonical(%r): get_names failed: %s", canonical_handle, exc)
    return "variable"


async def _resolve_dotted_name(name: str, analyzer: JediAnalyzer) -> ResolveResult:
    """Resolve a dotted name (FQN or re-exported path) to a canonical handle."""
    handle = await resolve_canonical(name, analyzer)
    if handle is None:
        return _NotFoundResult(found=False, reason="unresolved")

    # Find the definition file to classify scope and get kind.
    # We try to locate the definition by searching for the leaf symbol.
    leaf = name.split(".")[-1]
    try:
        matches = await analyzer.find_symbol(leaf)
    except Exception:
        matches = []

    # Try to find the match whose full_name matches our canonical handle
    file_str = ""
    kind: str | None = None
    for match in matches:
        if match.get("full_name") == str(handle):
            file_str = match.get("file", "")
            kind = _normalise_kind(match.get("type"))
            break
    else:
        # Fallback: use the file derived from the handle path
        file_str = _handle_to_file(handle, analyzer) or ""

    if kind is None:
        # Leaf search missed — recover kind from the canonical handle's definition site
        kind = _kind_for_canonical(str(handle), analyzer)

    scope = classify_scope(file_str, analyzer) if file_str else "external"

    return _SuccessResult(
        found=True,
        handle=str(handle),
        kind=kind,
        scope=scope,
    )


def _handle_to_file(handle: Handle, analyzer: JediAnalyzer) -> str | None:
    """Attempt to derive a file path from a canonical handle.

    Used as a fallback when find_symbol doesn't return the exact match.
    Converts the handle's module portion to a file path via the same logic
    as ``canonicalization.find_module_file``.
    # NOTE: relies on JediAnalyzer._get_import_path_for_file (private).
    # Stable in practice; revisit if jedi_analyzer is refactored.
    """
    from pyeye.canonicalization import find_module_file

    parts = str(handle).split(".")
    if len(parts) < 2:
        return None

    # The module is everything except the last component (the symbol name)
    module_dotted = ".".join(parts[:-1])
    module_file = find_module_file(module_dotted, analyzer)
    return module_file.as_posix() if module_file else None


# ---------------------------------------------------------------------------
# File-only resolution helper
# ---------------------------------------------------------------------------


async def _resolve_file_only(file_path: Path, analyzer: JediAnalyzer) -> ResolveResult:
    """Resolve a bare file path to its module handle."""
    if not file_path.exists():
        return _NotFoundResult(found=False, reason="file_not_found")

    module_path = analyzer._get_import_path_for_file(file_path)
    if not module_path:
        return _NotFoundResult(found=False, reason="unresolved")

    try:
        handle = Handle(module_path)
    except ValueError:
        return _NotFoundResult(found=False, reason="unresolved")

    scope = classify_scope(str(file_path), analyzer)

    return _SuccessResult(
        found=True,
        handle=str(handle),
        kind="module",
        scope=scope,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve(
    identifier: str,
    analyzer: JediAnalyzer,
) -> ResolveResult:
    """Resolve any identifier form to a canonical handle.

    Accepts bare names, fully-qualified dotted names, re-exported paths,
    file paths with or without line numbers.

    Args:
        identifier: Any identifier form supported by PyEye.  See module
            docstring for the full list of forms.
        analyzer: A configured :class:`~pyeye.analyzers.jedi_analyzer.JediAnalyzer`
            instance pointing at the project to analyse.

    Returns:
        A :data:`ResolveResult` dict.  On success, contains ``found=True``,
        a ``handle``, ``kind``, and ``scope``.  On ambiguity, contains
        ``found=True``, ``ambiguous=True``, and a sorted ``candidates`` list.
        On failure, contains ``found=False`` and a ``reason`` string.
    """
    form = _parse_identifier(identifier)
    kind = form["kind"]

    if kind == "file_with_line":
        return await _resolve_file_line(Path(form["path"]), form["line"], analyzer)

    if kind == "file_only":
        return await _resolve_file_only(Path(form["path"]), analyzer)

    if kind == "dotted_name":
        return await _resolve_dotted_name(form["name"], analyzer)

    # bare_name
    return await _resolve_bare_name(form["name"], analyzer)
