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
  means :func:`_resolve_head_in_scope` placing the name through the one
  resolver (#623).
* Annotation handles are what Jedi resolves at the **annotation site** — they
  are not rewritten to a normalised canonical form. ``Dict`` from ``typing``
  resolves to ``"typing.Dict"`` even though Python ≥3.9 treats it as an alias
  for ``builtins.dict``. The PEP 585 lowercase ``dict`` resolves to
  ``"builtins.dict"``. Both are correct; the wire format reflects what was
  written.
* PEP 604 unions (``X | Y``) have no single canonical head — ``handle`` is
  absent; ``args`` carry each alternative as its own TypeRef.
* Forward-ref strings (``"FutureType"``) are re-parsed and recursed; the head is
  resolved lexically in the annotation's own module (then builtins, then as an
  absolute path) through :func:`pyeye.resolver.resolve_handle`, since the
  re-parsed AST has no useful position. So ``x: "Foo"`` names what ``x: Foo``
  names. Unresolvable forward refs degrade to ``{raw: "..."}`` only.
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
* Forward-ref re-parse (no positions) → :func:`_resolve_head_in_scope`

Caching
-------
TypeRef builds are memoised per annotation **site**: ``(project_root, file,
mtime_ns, position, source text)``. What a head resolves to depends on where
the annotation sits, so the raw text alone is not a key (#620). Because the
key includes ``mtime_ns``, edits to the annotation's own file invalidate
naturally. An edit elsewhere (the referenced type moving to another file)
does not change the key; :func:`invalidate_project` drops a project's entries
for that case. The cache is an LRU bounded at ``_TYPEREF_CACHE_MAX`` entries.

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
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyeye import file_artifact_cache
from pyeye._ast_targets import attr_target_position
from pyeye._goto import goto_target
from pyeye.handle import Handle
from pyeye.project_layout import module_name_for_file
from pyeye.resolver import Resolved, resolve_handle

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)


# A "head resolver" is an async callable that takes a Name / Attribute AST
# node and returns either a canonical Handle (when resolution yields exactly
# one definition) or None. The two production resolvers are
# _resolve_head_via_jedi (positional, file-scope) and
# _resolve_head_in_scope (forward-ref, lexical in the annotation's module).
HeadResolver = Callable[[ast.expr], Awaitable["Handle | None"]]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
#
# Per-process TypeRef cache, keyed per annotation SITE (#620):
#
#   (project_root, file, mtime_ns, lineno, col, end_lineno, end_col, source)
#
# * Position, not raw text: head resolution is positional. Two ``Foo``
#   annotations in one file can name different classes (module-level vs a
#   nested ``Outer.Foo``). The enclosing scope would NOT be enough either: a
#   name can be rebound within one scope between two annotations
#   (``from a import X`` ... ``from b import X``), and Jedi's goto is
#   flow-sensitive. The position is the smallest key that is always right.
# * Source text (``ast.unparse``, which keeps quotes) distinguishes the forward
#   ref ``"Foo"`` from the bare ``Foo``; their ``raw`` is the same.
# * Project root: handles are project-relative (the same file under two roots
#   yields different full names), and forward refs resolve project-wide.
# * mtime_ns: edits to the annotation's own file invalidate naturally. An edit
#   to ANOTHER file (the referenced type moved) is not visible in the key;
#   ``invalidate_project(root)`` is the hook for that.
#
# The cached value is the fully built TypeRef dict, shared across builds;
# callers must not mutate it. The cache is an LRU bounded at
# ``_TYPEREF_CACHE_MAX`` entries.

_TypeRefKey = tuple[str, str, int, int, int, int, int, str]
_TYPEREF_CACHE_MAX = 4096
_typeref_cache: OrderedDict[_TypeRefKey, dict[str, Any]] = OrderedDict()
# The file watcher calls invalidate_project from its own thread while analysis
# reads and writes the LRU (#617), so every access to it takes this lock. It is
# held only for the dict operations, never across an await.
_typeref_lock = threading.Lock()


def _cached_typeref(key: _TypeRefKey) -> dict[str, Any] | None:
    """Return the cached TypeRef for *key*, marking it recently used, or ``None``."""
    with _typeref_lock:
        node = _typeref_cache.get(key)
        if node is not None:
            _typeref_cache.move_to_end(key)
        return node


def _store_typeref(key: _TypeRefKey, node: dict[str, Any]) -> None:
    """Cache *node* under *key*, evicting the least recently used past the cap."""
    with _typeref_lock:
        _typeref_cache[key] = node
        while len(_typeref_cache) > _TYPEREF_CACHE_MAX:
            _typeref_cache.popitem(last=False)


def invalidate_project(root: Path | str) -> None:
    """Drop every cached TypeRef built under the project at *root*.

    Any change under a project can change what another file's annotations
    resolve to (a referenced type moved or was renamed), so invalidation is
    per project, not per file.
    """
    key = Path(root).resolve().as_posix()
    with _typeref_lock:
        for cached in [k for k in _typeref_cache if k[0] == key]:
            del _typeref_cache[cached]


def invalidate_all() -> None:
    """Drop every cached TypeRef."""
    with _typeref_lock:
        _typeref_cache.clear()


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


def _cache_key(
    file_path: Path | None, annotation: ast.expr, project_root: str
) -> _TypeRefKey | None:
    """Return the cache key for *annotation*'s site, or ``None`` when uncacheable.

    Returns ``None`` when *file_path* is ``None``, ``os.stat`` fails, or the
    node carries no position (a synthesised node has no site to key on). In
    those cases the build runs uncached. Failure paths must not raise into
    the build pipeline.
    """
    if file_path is None:
        return None
    lineno = getattr(annotation, "lineno", None)
    col = getattr(annotation, "col_offset", None)
    if lineno is None or col is None:
        return None
    try:
        mtime_ns = os.stat(file_path).st_mtime_ns
    except OSError:
        return None
    end_lineno = getattr(annotation, "end_lineno", None)
    end_col = getattr(annotation, "end_col_offset", None)
    return (
        project_root,
        file_path.resolve().as_posix(),
        mtime_ns,
        lineno,
        col,
        lineno if end_lineno is None else end_lineno,
        col if end_col is None else end_col,
        ast.unparse(annotation),
    )


def _project_root(analyzer: JediAnalyzer) -> str:
    """The analyzer's project root, as the cache's project component."""
    return Path(analyzer.project_path).resolve().as_posix()


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
            key, together with the annotation's position and the project.
        analyzer: Configured ``JediAnalyzer`` for the project.

    Returns:
        A TypeRef dict — always with a non-empty ``raw``. ``handle`` and
        ``args`` are present per the rules in this module's docstring.
    """
    raw = _annotation_source(annotation)
    key = _cache_key(file_path, annotation, _project_root(analyzer))
    if key is not None:
        cached = _cached_typeref(key)
        if cached is not None:
            return cached

    # Closure capturing file_path/analyzer — the resolver gets just the head
    # node and produces a Handle or None.
    async def head_via_jedi(node: ast.expr) -> Handle | None:
        return _resolve_head_via_jedi(node, file_path, analyzer)

    node = await _build_with_resolver(
        annotation, file_path, analyzer, head_resolver=head_via_jedi, raw_override=raw
    )

    if key is not None:
        _store_typeref(key, node)
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


# ---------------------------------------------------------------------------
# Head resolvers
# ---------------------------------------------------------------------------


def _resolve_head_via_jedi(
    head_node: ast.expr,
    file_path: Path,
    analyzer: JediAnalyzer,
) -> Handle | None:
    """Resolve the head of a TypeRef expression to a canonical handle via Jedi goto.

    Calls ``goto`` at the head's annotation-site position through the one
    goto policy (:func:`pyeye._goto.goto_target`, #624): a handle only when
    ``goto`` names exactly one distinct target. Any other outcome — zero
    results, several distinct targets, malformed handle — yields ``None``.
    """
    if not isinstance(head_node, (ast.Name, ast.Attribute)):
        # Heads inside e.g. nested Subscripts aren't handled here; recursion
        # picks them up via the Subscript branch in _build_with_resolver.
        return None

    line, col = attr_target_position(head_node)
    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
    except Exception as exc:
        logger.debug("typeref._resolve_head_via_jedi: no script for %s: %s", file_path, exc)
        return None
    target = goto_target(script, line, col)
    if target is None:
        return None

    full_name = target.full_name
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


async def _resolve_head_in_scope(
    head_node: ast.expr,
    file_path: Path,
    analyzer: JediAnalyzer,
) -> Handle | None:
    """Resolve a forward-ref head the way Python would: in the annotation's module.

    The forward-ref sub-AST has no useful source position, so ``goto`` can't
    be used.  Instead the name is resolved LEXICALLY through the one resolver
    (#623), first match wins:

    1. ``<annotation's module>.<name>``: a definition in that module, or a name
       imported into it (placement follows the import to its definition), so
       ``x: "Foo"`` names exactly what ``x: Foo`` names;
    2. ``builtins.<name>`` for a single name (``"int"``), as Python falls back to
       builtins;
    3. ``<name>`` as an absolute dotted path (``"pkg.models.Foo"``).

    ``None`` when none resolves, preserving the no-guess rule: a same-named
    class elsewhere in the project is never picked by name alone.
    """
    name_str = _dotted_name(head_node)
    if name_str is None:
        return None
    paths: list[str] = []
    module = module_name_for_file(analyzer, file_path)
    if module:
        paths.append(f"{module}.{name_str}")
    if "." not in name_str:
        paths.append(f"builtins.{name_str}")
    paths.append(name_str)
    for path in paths:
        resolved = resolve_handle(path, analyzer)
        if isinstance(resolved, Resolved):
            return Handle(resolved.handle)  # always a valid dotted path
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
    shared builder with :func:`_resolve_head_in_scope` (lexical, #623).

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

    async def head_in_scope(node: ast.expr) -> Handle | None:
        return await _resolve_head_in_scope(node, file_path, analyzer)

    return await _build_with_resolver(
        sub,
        file_path,
        analyzer,
        head_resolver=head_in_scope,
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
