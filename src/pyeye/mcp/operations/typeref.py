"""Recursive ``TypeRef`` builder for ``inspect()``'s type-bearing fields.

The :func:`build_typeref` function turns a Python annotation expression into the
recursive ``TypeRef`` shape mandated by the 2026-05-02 progressive-disclosure
API spec::

    type TypeRef = {
      raw: string              # always present — annotation slice as written
      handle?: Handle          # canonical handle when the head has exactly one
                               # canonical referent; absent otherwise
      args?: TypeRef[]         # recursive children for parameterized types;
                               # absent for bare names
    }

Resolution discipline
---------------------
The implementation follows the spec's "Resolution must not guess" rule:

* ``handle`` is populated **only** when the head's resolution yields exactly
  one definition. For annotations parsed from a file's whole AST (positions
  are absolute), this means ``jedi.Script.goto`` returning exactly one entry
  after deduping by ``full_name``. For annotations re-parsed from a
  forward-ref string (positions point inside the string, not the file), it
  means :func:`pyeye.canonicalization.resolve_canonical` returning a value.
* Annotation handles are what Jedi resolves at the **annotation site** — they
  are not rewritten to a normalised canonical form. ``Dict`` from ``typing``
  resolves to ``"typing.Dict"`` even though Python ≥3.9 treats it as an alias
  for ``builtins.dict``. The PEP 585 lowercase ``dict`` resolves to
  ``"builtins.dict"``. Both are correct; the wire format reflects what was
  written.
* PEP 604 unions (``X | Y``) have no single canonical head — ``handle`` is
  absent; ``args`` carry each alternative as its own TypeRef.
* Forward-ref strings (``"FutureType"``) are re-parsed and recursed; head
  resolution falls back to :func:`pyeye.canonicalization.resolve_canonical`
  (project-wide canonicalisation) since the re-parsed AST has no useful
  position. Unresolvable forward refs degrade to ``{raw: "..."}`` only.
* Callable, Literal, Annotated, ParamSpec, etc. — the spec explicitly permits
  ``args`` / ``handle`` to be absent on these (the "degraded path"). The
  expression as written is preserved in ``raw``.

Implementation note: position vs. project-wide head resolution
-------------------------------------------------------------
The recursion shape is identical for both modes; only the *head resolver*
differs. The shared :func:`_build_with_resolver` walks the AST and delegates
head lookups to a callable supplied by the entry point:

* :func:`build_typeref` (file-scope, absolute positions) →
  :func:`_resolve_head_via_jedi`
* Forward-ref re-parse (no positions) → :func:`_resolve_head_via_canonical`

Caching
-------
TypeRef builds are memoised per ``(file_resolved_posix, mtime_ns,
type_string)``. Leaf annotations like ``Path`` / ``str`` / ``int`` repeat
heavily inside a single module, and the cache prevents redundant resolution
calls. Because the key includes ``mtime_ns``, file edits invalidate
naturally — after a save, the next build sees a different ``mtime_ns`` and
the prior cache entry is no longer reachable. (Old entries remain in memory
until the cache is cleared; for v1 this is acceptable, since the dominant
cost we are avoiding is Jedi inference, not memory.)

Telemetry
---------
The spec asks implementations to track which annotation shapes hit the
degraded path so that future passes (proper ``Callable`` shape, etc.) can be
prioritised empirically. v1 maintains a module-level ``degraded_counts``
dict (category -> int), bumped at each degraded-path site, plus a
``logger.debug("typeref_degraded:<category>")`` for live debugging. Operators
read the snapshot via :func:`get_and_reset_degraded_counts`. Debug-level
logs are silenced in production by default, so the counter is the
authoritative source of empirical category data; wiring into
:mod:`pyeye.metrics` is left as a follow-up.
"""

from __future__ import annotations

import ast
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyeye import file_artifact_cache
from pyeye.canonicalization import resolve_canonical
from pyeye.handle import Handle

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)


# A "head resolver" is an async callable that takes a Name / Attribute AST
# node and returns either a canonical Handle (when resolution yields exactly
# one definition) or None. The two production resolvers are
# _resolve_head_via_jedi (positional, file-scope) and
# _resolve_head_via_canonical (forward-ref, project-scope).
HeadResolver = Callable[[ast.expr], Awaitable["Handle | None"]]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
#
# Per-process TypeRef cache keyed by (file_resolved_posix, mtime_ns, raw).
# mtime_ns participates in the key, so file edits naturally invalidate (the
# key changes; the prior entry is unreachable). The cached value is the fully
# built TypeRef dict — agents may not mutate the returned dict, since it may
# be shared across builds.
#
# An LRU bound is intentionally NOT enforced in v1: per-module annotation
# count is small (tens, occasionally hundreds), and a single inspect() call
# tops out at one module's worth of types. If profiling shows pathological
# memory growth across long-running processes, replace the dict with an
# OrderedDict-backed LRU.

_TypeRefKey = tuple[str, int, str]
_typeref_cache: dict[_TypeRefKey, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
#
# Per-process counter of degraded-path categories (e.g. ``"Callable"``,
# ``"Literal"``, ``"Annotated"``, AST node-type names). Incremented at every
# degraded-path site alongside the ``logger.debug`` line. Operators / future
# passes call :func:`get_and_reset_degraded_counts` to snapshot and reset.
# Using a module-level dict (rather than fixed module-level integers) keeps
# the category set open-ended without needing to enumerate kinds upfront.
degraded_counts: dict[str, int] = {}


def _bump_degraded(kind: str) -> None:
    """Increment the degraded-path counter for *kind*."""
    degraded_counts[kind] = degraded_counts.get(kind, 0) + 1


def get_and_reset_degraded_counts() -> dict[str, int]:
    """Return current degraded-path counts and reset the counter.

    Used by operators / future passes to count which annotation shapes fall
    into the degraded-resolution path (``Callable``, ``Literal``,
    ``Annotated``, etc.) and prioritise where to invest proper recursion.
    Debug-level logs are silenced in production by default, so the counter is
    the authoritative empirical source.

    Returns:
        A snapshot of the counter as a fresh dict. The internal counter is
        cleared, so subsequent calls report only newly-recorded categories.
    """
    snapshot = dict(degraded_counts)
    degraded_counts.clear()
    return snapshot


def _cache_key(file_path: Path | None, raw: str) -> _TypeRefKey | None:
    """Return a cache key for *(file_path, raw)*, or ``None`` when uncacheable.

    Returns ``None`` when *file_path* is ``None`` or ``os.stat`` fails — in
    those cases the build runs uncached. Failure paths must not raise into
    the build pipeline.
    """
    if file_path is None:
        return None
    try:
        mtime_ns = os.stat(file_path).st_mtime_ns
    except OSError:
        return None
    return (file_path.resolve().as_posix(), mtime_ns, raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_typeref(
    annotation: ast.expr,
    file_path: Path,
    analyzer: JediAnalyzer,
) -> dict[str, Any]:
    """Build a TypeRef dict for *annotation*.

    Args:
        annotation: An ``ast.expr`` node parsed from the source file. Its
            ``lineno`` / ``col_offset`` are absolute (i.e. line-based positions
            into *file_path*'s source, suitable for ``jedi.Script.goto``).
        file_path: Absolute path to the source file containing *annotation*.
            Used to (a) construct the Jedi ``Script`` and (b) form the cache
            key.
        analyzer: Configured ``JediAnalyzer`` for the project.

    Returns:
        A TypeRef dict — always with a non-empty ``raw``. ``handle`` and
        ``args`` are present per the rules in this module's docstring.
    """
    raw = _annotation_source(annotation)
    key = _cache_key(file_path, raw)
    if key is not None and key in _typeref_cache:
        return _typeref_cache[key]

    # Closure capturing file_path/analyzer — the resolver gets just the head
    # node and produces a Handle or None.
    async def head_via_jedi(node: ast.expr) -> Handle | None:
        return _resolve_head_via_jedi(node, file_path, analyzer)

    node = await _build_with_resolver(
        annotation, file_path, analyzer, head_resolver=head_via_jedi, raw_override=raw
    )

    if key is not None:
        _typeref_cache[key] = node
    return node


def _annotation_source(annotation: ast.expr) -> str:
    """Return the annotation as written (best effort).

    For nodes parsed from the file's whole AST, ``ast.unparse`` produces a
    canonical textual form that round-trips the spec's "raw" expectation
    closely enough for the conformance tests (``"Path"`` for a bare Name,
    ``"Dict[str, List[CustomModel]]"`` for the typing-aliased generic, etc.).
    For ``Constant(value=str)`` (PEP 484 forward-ref strings), ``ast.unparse``
    would re-quote the string; we strip the wrapping quotes so that ``raw``
    is the *unquoted* forward-ref content (matching test scenario (e)).
    """
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    return ast.unparse(annotation)


# ---------------------------------------------------------------------------
# Internal builder — resolver-parameterised so file-scope and forward-ref
# recursion share one code path.
# ---------------------------------------------------------------------------


async def _build_with_resolver(
    annotation: ast.expr,
    file_path: Path,
    analyzer: JediAnalyzer,
    *,
    head_resolver: HeadResolver,
    raw_override: str | None = None,
) -> dict[str, Any]:
    """Construct a TypeRef dict for *annotation* using *head_resolver*.

    Args:
        annotation: AST expression to convert.
        file_path: File the annotation belongs to (used for cache continuity
            inside recursive build_typeref calls).
        analyzer: Active analyzer.
        head_resolver: Async callable that resolves a head Name/Attribute to
            a Handle (or None per the no-guess rule).
        raw_override: When supplied, use this as the node's ``raw``. Used by
            forward-ref recursion to preserve the unquoted string. Defaults
            to ``_annotation_source(annotation)``.
    """
    raw = raw_override if raw_override is not None else _annotation_source(annotation)

    # ----- PEP 604 union: ``X | Y`` -----
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        # No single canonical head for unions; args carry the alternatives.
        # Flatten left-recursive chains: ``A | B | C`` parses as
        # BinOp(BinOp(A, |, B), |, C); we emit args=[A, B, C].
        alternatives: list[ast.expr] = []
        _collect_union_alternatives(annotation, alternatives)
        args = [
            await _build_with_resolver(alt, file_path, analyzer, head_resolver=head_resolver)
            for alt in alternatives
        ]
        return {"raw": raw, "args": args}

    # ----- Forward-ref string: ``"FutureType"`` -----
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return await _build_from_forward_ref(annotation.value, file_path, analyzer)

    # ----- Bare ``None`` / numeric / etc. literal -----
    if isinstance(annotation, ast.Constant):
        # ``None`` in annotation context. Per the no-guess rule, we don't
        # invent a handle. Numeric / boolean constants (used inside e.g.
        # Literal[1, 2]) likewise carry no handle.
        return {"raw": raw}

    # ----- Subscript: parameterized generic ``Head[args...]`` -----
    if isinstance(annotation, ast.Subscript):
        head_node = annotation.value
        head_handle = await head_resolver(head_node)
        slice_node = annotation.slice

        # Special case: ``Callable[[A, B], C]`` has a Tuple slice whose first
        # element is itself a List of args. The spec explicitly permits the
        # degraded path here (preserve raw, omit args). Detect this shape and
        # bail out before recursing — recursing into the List would mis-shape
        # the args.
        if _is_callable_shape(head_handle, slice_node):
            logger.debug("typeref_degraded:Callable raw=%r", raw)
            _bump_degraded("Callable")
            node: dict[str, Any] = {"raw": raw}
            if head_handle is not None:
                node["handle"] = str(head_handle)
            return node

        # Same degraded-path policy for Literal / Annotated / etc. — these
        # have type-system-specific argument semantics that don't fit the
        # uniform recursion.
        degraded_kind = _degraded_head_kind(head_handle)
        if degraded_kind is not None:
            logger.debug("typeref_degraded:%s raw=%r", degraded_kind, raw)
            _bump_degraded(degraded_kind)
            node = {"raw": raw}
            if head_handle is not None:
                node["handle"] = str(head_handle)
            return node

        # Standard recursion: each slice element becomes a TypeRef arg.
        arg_nodes = list(slice_node.elts) if isinstance(slice_node, ast.Tuple) else [slice_node]

        args = [
            await _build_with_resolver(a, file_path, analyzer, head_resolver=head_resolver)
            for a in arg_nodes
        ]
        node = {"raw": raw, "args": args}
        if head_handle is not None:
            node["handle"] = str(head_handle)
        return node

    # ----- Bare Name or Attribute leaf -----
    if isinstance(annotation, (ast.Name, ast.Attribute)):
        head_handle = await head_resolver(annotation)
        node = {"raw": raw}
        if head_handle is not None:
            node["handle"] = str(head_handle)
        return node

    # ----- Anything else: degraded path, raw only -----
    kind = type(annotation).__name__
    logger.debug("typeref_degraded:%s raw=%r", kind, raw)
    _bump_degraded(kind)
    return {"raw": raw}


def _collect_union_alternatives(node: ast.expr, out: list[ast.expr]) -> None:
    """Flatten left-recursive ``A | B | C`` BinOp chains into a list of leaves."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        _collect_union_alternatives(node.left, out)
        _collect_union_alternatives(node.right, out)
    else:
        out.append(node)


def _attribute_target_position(node: ast.expr) -> tuple[int, int]:
    """Return ``(line, col)`` of the rightmost identifier in a head expression.

    For ``ast.Name`` (e.g. ``Dict``): the name's own start position.
    For ``ast.Attribute`` (e.g. ``typing.Dict``): the position of the rightmost
    attribute name, so that ``goto`` lands on ``Dict`` rather than the
    ``typing`` module receiver.

    The returned ``(line, col)`` is **file-AST-absolute** — only meaningful
    for nodes parsed from the source file (the file-scope head resolver,
    :func:`_resolve_head_via_jedi`, feeds these positions to ``script.goto``).
    The forward-ref re-parse path (:func:`_resolve_head_via_canonical`)
    deliberately ignores this output: re-parsed AST positions live inside the
    forward-ref string, not the source file, so ``script.goto`` would land
    nowhere useful.

    Mirrors the strategy used by ``inspect._attr_target_position`` for base
    classes.
    """
    if isinstance(node, ast.Attribute):
        end_line = node.end_lineno or node.lineno
        end_col = node.end_col_offset or 0
        return end_line, max(0, end_col - len(node.attr))
    return node.lineno, node.col_offset


# ---------------------------------------------------------------------------
# Head resolvers
# ---------------------------------------------------------------------------


def _resolve_head_via_jedi(
    head_node: ast.expr,
    file_path: Path,
    analyzer: JediAnalyzer,
) -> Handle | None:
    """Resolve the head of a TypeRef expression to a canonical handle via Jedi goto.

    Calls ``jedi.Script.goto`` at the head's annotation-site position. Per
    the no-guess rule, returns a handle only when ``goto`` produces exactly
    one definition (after deduping by ``full_name``). Any other outcome —
    zero results, multiple distinct ``full_name`` values, malformed handle —
    yields ``None``.
    """
    if not isinstance(head_node, (ast.Name, ast.Attribute)):
        # Heads inside e.g. nested Subscripts aren't handled here; recursion
        # picks them up via the Subscript branch in _build_with_resolver.
        return None

    line, col = _attribute_target_position(head_node)
    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        defs = script.goto(line, col, follow_imports=True)
    except Exception as exc:
        logger.debug("typeref._resolve_head_via_jedi: goto failed at (%d,%d): %s", line, col, exc)
        return None

    # Dedupe by full_name; require exactly one distinct candidate.
    full_names = {d.full_name for d in defs if d.full_name}
    if len(full_names) != 1:
        return None

    full_name = next(iter(full_names))
    try:
        return Handle(full_name)
    except ValueError:
        logger.debug(
            "typeref._resolve_head_via_jedi: invalid handle %r at (%d,%d)",
            full_name,
            line,
            col,
        )
        return None


async def _resolve_head_via_canonical(
    head_node: ast.expr,
    analyzer: JediAnalyzer,
) -> Handle | None:
    """Resolve a forward-ref head via project-wide canonicalisation.

    The forward-ref sub-AST has no useful source position, so we cannot use
    ``script.goto``. Instead we pass the dotted name to
    :func:`resolve_canonical`, which already knows how to walk the project's
    import graph from a name alone. ``None`` on any failure (no match,
    invalid name, exception during resolution) — preserving the no-guess rule.
    """
    name_str = _dotted_name(head_node)
    if name_str is None:
        return None
    try:
        return await resolve_canonical(name_str, analyzer)
    except Exception as exc:
        logger.debug(
            "typeref._resolve_head_via_canonical(%r): resolve_canonical raised: %s",
            name_str,
            exc,
        )
        return None


async def _build_from_forward_ref(
    text: str,
    file_path: Path,
    analyzer: JediAnalyzer,
) -> dict[str, Any]:
    """Build a TypeRef from the contents of a forward-ref string annotation.

    Re-parses *text* with ``ast.parse(mode="eval")``. The re-parsed tree has
    positions relative to the string, not the source file, so head resolution
    cannot use the standard ``script.goto`` path. Instead we drive the
    shared builder with the project-wide canonicalisation resolver.

    On any parse error the result degrades to ``{raw: text}`` (no handle,
    no args).
    """
    raw = text
    try:
        sub_tree = ast.parse(text, mode="eval")
    except SyntaxError:
        logger.debug("typeref._build_from_forward_ref: parse failed for %r", text)
        return {"raw": raw}

    sub = sub_tree.body

    async def head_via_canonical(node: ast.expr) -> Handle | None:
        return await _resolve_head_via_canonical(node, analyzer)

    return await _build_with_resolver(
        sub,
        file_path,
        analyzer,
        head_resolver=head_via_canonical,
        raw_override=raw,
    )


def _dotted_name(node: ast.expr) -> str | None:
    """Return the dotted name for a Name / Attribute chain, or ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        receiver = _dotted_name(node.value)
        if receiver is None:
            return None
        return f"{receiver}.{node.attr}"
    return None


# ---------------------------------------------------------------------------
# Degraded-path detection
# ---------------------------------------------------------------------------


# Heads whose subscript shape doesn't fit the uniform TypeRef recursion
# (Literal[...] arguments are values; Annotated[X, metadata] mixes a type
# with non-type metadata; ParamSpec / TypeVarTuple etc. carry parameter
# specifications). The spec explicitly accepts these as the v1 degraded path:
# preserve ``raw`` and ``handle``; omit ``args``.
_DEGRADED_HANDLES: frozenset[str] = frozenset(
    {
        "typing.Literal",
        "typing.Annotated",
        "typing.ParamSpec",
        "typing.TypeVarTuple",
        "typing.Unpack",
        "typing.Concatenate",
    }
)


def _is_callable_shape(head_handle: Handle | None, slice_node: ast.expr) -> bool:
    """Return True when this looks like ``Callable[[A, B], C]``.

    Detection is twofold:
    - The head canonicalises to ``typing.Callable`` (or
      ``collections.abc.Callable``), OR
    - The slice is a Tuple whose first element is a List (the bracket-list
      of argument types). This shape-based fallback catches calls where the
      head can't be resolved (e.g. when ``Callable`` isn't imported), so the
      degraded path still fires.
    """
    if head_handle in {"typing.Callable", "collections.abc.Callable"}:
        return True
    if isinstance(slice_node, ast.Tuple) and slice_node.elts:
        first = slice_node.elts[0]
        if isinstance(first, ast.List):
            return True
    return False


def _degraded_head_kind(head_handle: Handle | None) -> str | None:
    """Return a short category label when *head_handle* belongs to the degraded set.

    Returns the head's name (e.g. ``"Literal"``, ``"Annotated"``) so it can
    be logged via the ``typeref_degraded:<kind>`` debug-log convention. Used
    by future telemetry to prioritise which shapes deserve proper recursion.
    """
    if head_handle is None:
        return None
    if str(head_handle) in _DEGRADED_HANDLES:
        return str(head_handle).rsplit(".", 1)[-1]
    return None
