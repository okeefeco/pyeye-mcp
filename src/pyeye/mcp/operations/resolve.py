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
- Bare names go through :func:`pyeye.resolver.resolve_name`: a #423 shadow is
  ambiguous, an exact top-level module wins, otherwise every project
  definition of the name is a canonical candidate (one → success, several →
  ambiguous with sorted candidates, none → not-found).  Methods and class-body
  attributes are a **fallback** (#508): they are candidates only when no module
  or top-level definition matches, so a top-level ``helper`` hides a
  same-named ``Class.helper``.  Dunder names are never member candidates; a
  bare dunder miss's ``detail`` points at ``expand(<class>, "members")``.
- Dotted names go through :func:`pyeye.resolver.resolve_handle`, which follows
  re-export chains and returns the definition-site handle (#623).
- File-with-line: read the line to locate the first non-whitespace column,
  then use ``script.goto()`` at that position to find the symbol's definition,
  canonicalized through the resolver.
- File-only: convert the file path to a dotted module path via
  ``_get_import_path_for_file`` and return a module-scoped Handle.

Kind normalisation
------------------
Jedi's ``Name.type`` is mapped to the closed kind vocabulary by
:mod:`pyeye.kinds` (#623), which also promotes a class-enclosed function to
``"method"`` (#406), so every primitive agrees on ``kind`` for the same symbol.

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
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Required, TypedDict, cast

from pyeye import file_artifact_cache
from pyeye._jedi_location import location_from_name
from pyeye._jedi_names import is_attribute_target
from pyeye.handle import Handle
from pyeye.mcp.operations.completeness import (
    DEFAULT_MAX_CANDIDATES,
    MAX_CANDIDATES,
    cap_items,
    check_cap,
)
from pyeye.mcp.operations.not_found import not_found_for
from pyeye.resolver import Ambiguous, NotFound, Resolved, resolve_handle, resolve_name
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


class _Miss(TypedDict, total=False):
    """Internal not-found signal from the resolution helpers.

    Never returned to a caller: :func:`resolve` / :func:`resolve_at` render it
    through :func:`~pyeye.mcp.operations.not_found.not_found_for`, which adds the
    operation's lookup echo and an actionable ``detail`` (#626).
    """

    found: Required[Literal[False]]
    reason: Required[str]
    #: Overrides the default ``detail`` when the miss has a better next step.
    detail: str
    #: Appended to whichever ``detail`` is used: a known limit on the miss (#729).
    note: str


def _miss(reason: str, detail: str | None = None) -> _Miss:
    miss = _Miss(found=False, reason=reason)
    if detail is not None:
        miss["detail"] = detail
    return miss


#: What the internal helpers return.
_HelperResult = _SuccessResult | _AmbiguousResult | _Miss

#: What :func:`resolve` / :func:`resolve_at` return. The not-found member is the
#: shared ``{found: false, <echo>, reason, detail}`` dict (#626).
ResolveResult = _SuccessResult | _AmbiguousResult | dict[str, Any]

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
) -> _HelperResult:
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
        return _miss("file_not_found")

    # A position outside the file is the caller's miss; Jedi would raise on it.
    # Any OTHER failure of goto is internal and propagates (#704).
    if not _position_in_file(file_path, line, column):
        return _miss("no_symbol_at_position")
    script = file_artifact_cache.get_script(file_path, analyzer.project)
    # follow_imports=True is intentional here: position-based resolution
    # should land on the definition site, not the use site. Callers that
    # want the symbol AT the position rather than its definition should
    # use a name-based form via resolve(identifier).
    definitions = script.goto(line, column, follow_imports=True)

    if not definitions:
        return _miss("no_symbol_at_position")

    name = definitions[0]
    full_name = name.full_name
    if not full_name:
        return _miss("no_symbol_at_position")
    # ``goto`` on the ``x`` of ``self.x = …`` lands on the target itself, whose
    # full_name reads as a local of the method.  It binds nothing there, and
    # placing its full_name could find an unrelated same-named binding (#567).
    if is_attribute_target(name):
        return _miss("unresolved")

    # Canonicalise through the one resolver (#623).  A definition the resolver
    # can't place is not-found: returning Jedi's raw full_name would hand the
    # caller a handle no other tool accepts (audit row 3).
    return _from_resolver(full_name, analyzer)


async def _resolve_file_line(file_path: Path, line: int, analyzer: JediAnalyzer) -> _HelperResult:
    """Resolve a file:line coordinate to a symbol handle.

    Strategy:
    1. Read the target line and find the column of the first non-whitespace
       character (skipping ``class``/``def`` keywords to land on the name).
    2. Delegate to ``_resolve_at_position`` with the computed column.
    3. Fall back to column 0 if the heuristic column yields no results.
    """
    if not file_path.exists():
        return _miss("file_not_found")

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


def _position_in_file(file_path: Path, line: int, column: int) -> bool:
    """Whether (*line*, *column*) is a position Jedi accepts in *file_path*.

    Mirrors Jedi's ``validate_line_column``: ``1 <= line <= len(lines)`` and
    ``0 <= column <=`` that line's length without its line ending. Checked up
    front so an out-of-range position is a miss and a Jedi failure is not
    mistaken for one (#704).
    """
    import parso

    lines = parso.split_lines(file_path.read_text(encoding="utf-8"), keepends=True)
    if not 0 < line <= len(lines):
        return False
    text = lines[line - 1]
    length = len(text) - (2 if text.endswith("\r\n") else 1 if text.endswith("\n") else 0)
    return 0 <= column <= length


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


async def _resolve_bare_name(
    name: str, analyzer: JediAnalyzer, max_candidates: int | None = None
) -> _HelperResult:
    """Resolve a bare (no-dots) name through the one resolver (#623).

    :func:`pyeye.resolver.resolve_name` decides: a #423 shadow is ambiguous, an
    exact top-level module wins, otherwise every project definition of the
    name is a canonical candidate.
    """
    result = await resolve_name(name, analyzer)
    if isinstance(result, NotFound):
        # A bare dunder is never a member candidate (#508): say where to look.
        miss = _miss("unresolved", result.detail if _is_dunder(name) else None)
        note = await _unparseable_note(analyzer)
        if note:
            miss["note"] = note
        return miss
    if isinstance(result, Ambiguous):
        candidates = sorted(
            (_candidate_from_resolved(r) for r in result.candidates), key=_candidate_sort_key
        )
        # #435 slice B: the sorted list is capped; ``total`` says how many matched.
        kept, truncation = cap_items(candidates, max_candidates, MAX_CANDIDATES, "max_candidates")
        ambiguous = _AmbiguousResult(found=True, ambiguous=True, candidates=kept)
        ambiguous.update(truncation)  # type: ignore[typeddict-item]
        return ambiguous
    return _success_from_resolved(result)


async def _unparseable_note(analyzer: JediAnalyzer) -> str | None:
    """Say how much of the project a bare-name miss couldn't see (#729), or ``None``."""
    try:
        files = await analyzer.index_unparseable_files()
    except Exception as exc:  # never fail a miss over its explanation
        logger.debug("resolve: unparseable-file lookup failed: %s", exc)
        return None
    if not files:
        return None
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    count = f"{len(files)} project file{'' if len(files) == 1 else 's'}"
    return (
        f"Note: {count} can't be parsed by the server's Python {version} (e.g. "
        f"{files[0]}), so a definition there is invisible to a bare-name search; "
        "Read it, or run pyeye on a newer Python."
    )


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


async def _resolve_dotted_name(name: str, analyzer: JediAnalyzer) -> _HelperResult:
    """Resolve a dotted name (FQN or re-exported path) through the one resolver (#623)."""
    return _from_resolver(name, analyzer)


def _from_resolver(path: str, analyzer: JediAnalyzer) -> _HelperResult:
    """Render :func:`pyeye.resolver.resolve_handle` as a resolve result."""
    resolved = resolve_handle(path, analyzer)
    if isinstance(resolved, NotFound):
        return _miss("unresolved")
    return _success_from_resolved(resolved)


def _candidate_from_resolved(resolved: Resolved) -> _Candidate:
    """Build an ambiguous-result candidate from a :class:`~pyeye.resolver.Resolved`."""
    success = _success_from_resolved(resolved)
    return _Candidate(
        handle=success["handle"],
        kind=success["kind"],
        scope=success["scope"],
        location=success["location"],
    )


def _success_from_resolved(resolved: Resolved) -> _SuccessResult:
    """Build a success result from a :class:`~pyeye.resolver.Resolved`."""
    anchor = resolved.anchor
    module_path = getattr(anchor, "module_path", None)
    file_str = module_path.as_posix() if module_path else ""
    return _SuccessResult(
        found=True,
        handle=resolved.handle,
        kind=resolved.kind,
        scope=resolved.scope,
        location=cast(_Location, location_from_name(file_str, anchor)),
    )


# ---------------------------------------------------------------------------
# File-only resolution helper
# ---------------------------------------------------------------------------


async def _resolve_file_only(file_path: Path, analyzer: JediAnalyzer) -> _HelperResult:
    """Resolve a bare file path to its module handle."""
    if not file_path.exists():
        return _miss("file_not_found")

    # _get_import_path_for_file matches via relative_to() against absolute
    # source_roots and project_path; a relative input would silently miss
    # those and fall through to either an unresolved result or a wrongly
    # path-prefixed handle (e.g. "src.pkg.mod" instead of "pkg.mod").
    file_path = file_path.resolve()

    module_path = analyzer._get_import_path_for_file(file_path)
    if not module_path:
        return _miss("unresolved")

    try:
        handle = Handle(module_path)
    except ValueError:
        return _miss("unresolved")

    scope = classify_scope(file_path, analyzer)

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
    max_candidates: int | None = DEFAULT_MAX_CANDIDATES,
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
        ``candidates`` list (each candidate also carries ``location``), capped
        at *max_candidates* (#435; default 50, ``None`` for all): when more
        match, the result also carries ``truncated: true``,
        ``truncation_reasons: ["max_candidates"]`` and ``total``.
        On failure, the shared not-found shape (#626):
        ``{found: False, identifier, reason, detail}``, with ``reason`` one of
        ``unresolved``, ``file_not_found`` or ``no_symbol_at_position``.
    """
    check_cap(max_candidates, "max_candidates")  # a caller error, before any work
    result = await _resolve_identifier(identifier, analyzer, max_candidates)
    if result["found"] is False:
        response = not_found_for(
            "resolve", {"identifier": identifier}, result["reason"], result.get("detail")
        )
        if result.get("note"):
            response["detail"] = f"{response['detail']} {result['note']}"
        return response
    return result


async def _resolve_identifier(
    identifier: str, analyzer: JediAnalyzer, max_candidates: int | None = None
) -> _HelperResult:
    """Dispatch *identifier* to the resolver for its form."""
    form = _parse_identifier(identifier)
    kind = form["kind"]

    if kind == "file_with_line":
        return await _resolve_file_line(Path(form["path"]), form["line"], analyzer)

    if kind == "file_only":
        return await _resolve_file_only(Path(form["path"]), analyzer)

    if kind == "dotted_name":
        return await _resolve_dotted_name(form["name"], analyzer)

    # bare_name
    return await _resolve_bare_name(form["name"], analyzer, max_candidates)


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
        a ``handle``, ``kind``, and ``scope``.  On failure, the shared not-found
        shape (#626): ``{found: False, file, line, column, reason, detail}``,
        echoing the arguments as given, with ``reason`` one of
        ``file_not_found``, ``no_symbol_at_position`` or ``unresolved``.
    """
    result = await _resolve_at_position(Path(file), line, column, analyzer)
    if result["found"] is False:
        echo = {"file": file, "line": line, "column": column}
        return not_found_for("resolve_at", echo, result["reason"])
    return result
