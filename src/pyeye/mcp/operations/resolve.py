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

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from pyeye import file_artifact_cache
from pyeye._jedi_location import location_from_name
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
    location: _Location


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


def _make_location(file_str: str, line: int | None, column: int | None) -> _Location:
    """Build a :class:`_Location` from raw file/line/column values.

    Uses sensible defaults when values are absent:
    - ``line`` defaults to 1 (start of file).
    - ``column`` defaults to 0 (start of line).

    Args:
        file_str: Posix-format file path string.  Empty string produces an
            ``"<unknown>"`` file entry.
        line: 1-indexed line number, or ``None`` if unavailable.
        column: 0-indexed column number, or ``None`` if unavailable.

    Returns:
        A :class:`_Location` TypedDict with ``file``, ``line_start``,
        ``line_end``, ``column_start``, and ``column_end``.
    """
    resolved_file = file_str if file_str else "<unknown>"
    resolved_line = line if line is not None else 1
    resolved_col = column if column is not None else 0
    return _Location(
        file=resolved_file,
        line_start=resolved_line,
        line_end=resolved_line,
        column_start=resolved_col,
        column_end=resolved_col,
    )


# ---------------------------------------------------------------------------
# File:line resolution helper
# ---------------------------------------------------------------------------


async def _resolve_at_position(
    file_path: Path, line: int, column: int, analyzer: JediAnalyzer
) -> ResolveResult:
    """Resolve an exact (file, line, column) position to a symbol handle.

    This is the shared core used by both ``_resolve_file_line`` (which computes
    the column heuristically) and ``resolve_at`` (which receives the column
    directly from the caller).

    Args:
        file_path: Absolute path to the source file.
        line: 1-indexed line number (Jedi convention).
        column: 0-indexed column number (Jedi convention).  A value of ``0``
            is valid and must be accepted as-is — callers must NOT pass
            ``column or <fallback>`` since that would silently drop column 0.
        analyzer: Configured :class:`~pyeye.analyzers.jedi_analyzer.JediAnalyzer`.

    Returns:
        A :data:`ResolveResult` on success or a not-found result on failure.
    """
    if not file_path.exists():
        return _NotFoundResult(found=False, reason="file_not_found")

    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        # follow_imports=True is intentional here: position-based resolution
        # should land on the definition site, not the use site. Callers that
        # want the symbol AT the position rather than its definition should
        # use a name-based form via resolve(identifier).
        definitions = script.goto(line, column, follow_imports=True)
    except Exception as exc:
        logger.debug("_resolve_at_position: goto(%d, %d) failed: %s", line, column, exc)
        return _NotFoundResult(found=False, reason="no_symbol_at_position")

    if not definitions:
        return _NotFoundResult(found=False, reason="no_symbol_at_position")

    name = definitions[0]
    full_name = name.full_name
    if not full_name:
        return _NotFoundResult(found=False, reason="no_symbol_at_position")

    # Canonicalise (may follow import chain)
    handle = await resolve_canonical(full_name, analyzer)
    if handle is None:
        # Fall back to raw full_name if it's a valid handle
        try:
            handle = Handle(full_name)
        except ValueError:
            return _NotFoundResult(found=False, reason="unresolved")

    # Determine file for scope classification
    def_file = name.module_path.as_posix() if name.module_path else file_path.as_posix()
    scope = classify_scope(def_file, analyzer)
    kind = _normalise_kind(name.type)

    return _SuccessResult(
        found=True,
        handle=str(handle),
        kind=kind,
        scope=scope,
        location=cast(_Location, location_from_name(def_file, name)),
    )


async def _resolve_file_line(file_path: Path, line: int, analyzer: JediAnalyzer) -> ResolveResult:
    """Resolve a file:line coordinate to a symbol handle.

    Strategy:
    1. Read the target line and find the column of the first non-whitespace
       character (skipping ``class``/``def`` keywords to land on the name).
    2. Delegate to ``_resolve_at_position`` with the computed column.
    3. Fall back to column 0 if the heuristic column yields no results.
    """
    if not file_path.exists():
        return _NotFoundResult(found=False, reason="file_not_found")

    # Determine a useful column on the target line.
    heuristic_column = _find_symbol_column_on_line(file_path, line)

    result = await _resolve_at_position(file_path, line, heuristic_column, analyzer)
    if result["found"] is True:
        return result

    # Fall back to column 0 as a last resort
    if heuristic_column != 0:
        fallback = await _resolve_at_position(file_path, line, 0, analyzer)
        if fallback["found"] is True:
            return fallback

    return result


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


def _get_jedi_name_from_match(
    file_posix: str,
    line: int | None,
    column: int | None,
    analyzer: JediAnalyzer,
) -> Any | None:
    """Return the Jedi Name object at (file, line, column), or None on failure.

    Used to upgrade a match-dict location to a full span via
    :func:`~pyeye._jedi_location.location_from_name`.  The lookup is best-effort;
    callers fall back to the degenerate point-location when ``None`` is returned.

    Args:
        file_posix: POSIX path string of the source file.
        line: 1-indexed line number (may be None if unavailable).
        column: 0-indexed column (may be None if unavailable).
        analyzer: Active analyzer for file-level Jedi access.

    Returns:
        A Jedi ``Name`` object on success, or ``None`` on any failure.
    """
    if not file_posix or line is None:
        return None
    try:
        file_path = Path(file_posix)
        if not file_path.exists():
            return None
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        resolved_col = column if column is not None else 0
        defs = script.goto(line, resolved_col, follow_imports=False)
        if defs:
            return defs[0]
    except Exception:
        pass
    return None


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
            location=c["location"],
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
    file_posix = Path(file_str).as_posix() if file_str else ""
    match_line = match.get("line")
    match_col = match.get("column")

    # Attempt to get a real Jedi Name for the span (column_end + line_end).
    # Falls back to the degenerate _make_location shape when lookup fails.
    jedi_name = _get_jedi_name_from_match(file_posix, match_line, match_col, analyzer)
    if jedi_name is not None:
        location = cast(_Location, location_from_name(file_posix, jedi_name))
    else:
        location = _make_location(file_posix, match_line, match_col)

    return _SuccessResult(
        found=True,
        handle=str(handle),
        kind=kind,
        scope=scope,
        location=location,
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

    match_line = match.get("line") or 1
    match_col = match.get("column") or 0
    file_posix = Path(file_str).as_posix() if file_str else ""

    # Attempt to get a real Jedi Name for the span (column_end + line_end).
    # Falls back to the degenerate point shape when lookup fails.
    jedi_name = _get_jedi_name_from_match(file_posix, match_line, match_col, analyzer)
    if jedi_name is not None:
        loc = cast(_Location, location_from_name(file_posix, jedi_name))
    else:
        loc = _Location(
            file=file_posix,
            line_start=match_line,
            line_end=match_line,
            column_start=match_col,
            column_end=match_col,
        )

    return _Candidate(
        handle=str(handle),
        kind=kind,
        scope=scope,
        location=loc,
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
    match_line: int | None = None
    match_column: int | None = None
    for match in matches:
        if match.get("full_name") == str(handle):
            file_str = match.get("file", "")
            kind = _normalise_kind(match.get("type"))
            match_line = match.get("line")
            match_column = match.get("column")
            break
    else:
        # Fallback: use the file derived from the handle path
        file_str = _handle_to_file(handle, analyzer) or ""

    if kind is None:
        # Leaf search missed — recover kind from the canonical handle's definition site
        kind = _kind_for_canonical(str(handle), analyzer)

    scope = classify_scope(file_str, analyzer) if file_str else "external"
    file_posix = Path(file_str).as_posix() if file_str else ""

    # Attempt span location via Jedi Name; fall back to degenerate point location.
    jedi_name = _get_jedi_name_from_match(file_posix, match_line, match_column, analyzer)
    if jedi_name is not None:
        location = cast(_Location, location_from_name(file_posix, jedi_name))
    else:
        location = _make_location(file_posix, match_line, match_column)

    return _SuccessResult(
        found=True,
        handle=str(handle),
        kind=kind,
        scope=scope,
        location=location,
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
        location=_make_location(file_path.as_posix(), 1, None),
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
        a ``handle``, ``kind``, ``scope``, and ``location``.  On ambiguity,
        contains ``found=True``, ``ambiguous=True``, and a sorted
        ``candidates`` list (each candidate also carries ``location``).
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


async def resolve_at(
    file: str,
    line: int,
    column: int,
    analyzer: JediAnalyzer,
) -> ResolveResult:
    """Resolve a (file, line, column) position to a canonical handle.

    Used when the agent has coordinates (from a stack trace, error report, or
    pasted excerpt) rather than a name.  Same return shape as :func:`resolve`.

    Args:
        file: Absolute or relative path to the source file.
        line: 1-indexed line number (e.g. line 1 is the first line of the file).
        column: 0-indexed column number (Jedi convention).  Column ``0`` is the
            start of the line and is fully valid — the implementation must NOT
            test ``if column:`` (which would treat ``0`` as falsy).  Always use
            ``column is not None`` when a guard is needed.
        analyzer: A configured :class:`~pyeye.analyzers.jedi_analyzer.JediAnalyzer`
            instance pointing at the project to analyse.

    Returns:
        A :data:`ResolveResult` dict.  On success, contains ``found=True``,
        a ``handle``, ``kind``, and ``scope``.  On failure, contains
        ``found=False`` and a ``reason`` string (e.g. ``"no_symbol_at_position"``
        or ``"file_not_found"``).
    """
    file_path = Path(file)
    return await _resolve_at_position(file_path, line, column, analyzer)
