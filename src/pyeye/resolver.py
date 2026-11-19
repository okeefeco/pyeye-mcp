"""The one canonical handle resolver (#623).

:func:`resolve_handle` turns an exact dotted path into its definition. It is the
single implementation behind ``inspect``, ``outline``, ``expand`` and the
``trace`` roots, so those tools cannot disagree about whether a handle exists,
which definition it names, or which handle to echo back.

The strategy is data, so the code and the docs can't disagree about it
(``resolver.strategy`` docs facts, #830): :data:`STRATEGY` runs first, then the
path's top-level package picks :data:`PROJECT_STRATEGY` (inside the project,
with no fallback after a miss) or :data:`EXTERNAL_STRATEGY` (outside it, so
the external steps never run on a project path, #506). The first step that
answers wins.

A handle in a platform-selected module (``os.path``, #329) is located at the
``sys.platform`` branch that selects its implementation, the same on every OS.

The external steps that infer read one :func:`_synthetic_import`, the one place a
``jedi.Script(code=...)`` is built (``tests/test_decision_invariants_fitness.py``).

This module sits below ``pyeye.mcp`` (``tests/test_import_layers_fitness.py``).
"""

from __future__ import annotations

import ast
import errno
import logging
import os
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pyeye import file_artifact_cache
from pyeye._goto import goto_target
from pyeye._jedi_names import is_attribute_target
from pyeye._module_sentinel import ModuleSentinel
from pyeye._stdlib_static import StdlibDefinition, relocate_platform, stdlib_definition
from pyeye.handle import Handle
from pyeye.kinds import normalise_kind_from_name
from pyeye.path_utils import normalize_path, normalize_path_strict, path_to_key, paths_equal
from pyeye.project_layout import (
    RootsBoundary,
    file_for_module,
    find_namespace_package_dirs,
    module_name_for_file,
    project_roots,
)
from pyeye.scope import classify_scope

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

#: Bound on alias hops while placing a dotted path (``a.Alias.attr`` → ...).
_MAX_ALIAS_HOPS = 8


@dataclass(frozen=True)
class Resolved:
    """A handle resolved to its definition.

    Attributes:
        handle: The canonical (definition-site) handle. Callers echo this, not
            their input, so every tool reports the same handle for a symbol.
        kind: The kind, from :mod:`pyeye.kinds`.
        scope: ``"project"`` or ``"external"``.
        anchor: The Jedi ``Name`` (or module sentinel) for the definition.
    """

    handle: str
    kind: str
    scope: Literal["project", "external"]
    anchor: Any


@dataclass(frozen=True)
class NotFound:
    """A handle that does not resolve. Operations render it in the #545 shape."""

    reason: Literal["unresolved"]
    detail: str
    #: The definition exists but resolves into a restricted directory (#999), so
    #: it is refused. The operations then show *detail* as it is: it is the
    #: honest reason, not a guess.
    restricted: bool = False
    #: The path names several definitions of one function-local name (#1022),
    #: such as ``class Twin`` in both branches of an ``if``. No single answer is
    #: true, so a handle-taking tool says so (*detail*), ``resolve`` answers
    #: ``ambiguous`` with these, and ``resolve_at`` picks the one at its position.
    candidates: tuple[Resolved, ...] = ()

    @property
    def honest_detail(self) -> str | None:
        """*detail* when it is the honest reason to show the caller, else ``None``.

        A refused restricted definition (#999) and a path naming several local
        definitions (#1022) say why; any other miss lets the operation use its
        own default detail.
        """
        return self.detail if (self.restricted or self.candidates) else None


@dataclass(frozen=True)
class _SharedLocalName:
    """The anchor of a path that names several function-local definitions (#1022).

    Python reuses one dotted name (``pkg.mod.outer.Twin``) for every ``class
    Twin`` in ``outer``. :func:`resolve_handle` turns this into a
    :class:`NotFound` carrying every definition, never one of them.
    """

    anchors: tuple[Any, ...]


@dataclass(frozen=True)
class Ambiguous:
    """A bare name with several canonical definitions, in deterministic order."""

    candidates: tuple[Resolved, ...]


#: How the not-found detail for a definition refused as restricted ends (#999).
_RESTRICTED_SUFFIX = "which pyeye doesn't read or report."

#: The not-found detail for a definition that lives in a restricted directory (#999).
RESTRICTED_DETAIL = (
    "{path!r} resolves into a restricted directory (a system directory or a "
    "credential store), " + _RESTRICTED_SUFFIX
)


def is_restricted_detail(detail: str | None) -> bool:
    """Whether *detail* is :data:`RESTRICTED_DETAIL`'s, so no other note belongs after it."""
    return detail is not None and detail.endswith(_RESTRICTED_SUFFIX)


def in_restricted_dir(name: Any) -> bool:
    """Whether Jedi *name*'s file RESOLVES into a restricted directory (#999).

    Jedi follows a symlink in the project or the venv's site-packages while it
    looks up an import, so a hit can land in ``/etc`` or a credential store
    where no input check or pruned walk applies. The file is checked on its
    resolved form with the walkers' own test, :func:`pyeye.validation.restricted_dir`.
    A name with no file (a builtin, a namespace sentinel without one) is never
    restricted.
    """
    module_path = getattr(name, "module_path", None)
    return module_path is not None and restricted_path(module_path)


#: Windows' error for a symlink chain it can't resolve, a loop included
#: (``ERROR_CANT_RESOLVE_FILENAME``).
_WINERROR_CANT_RESOLVE = 1921


def restricted_path(path: str | Path) -> bool:
    """Whether *path* RESOLVES into a restricted directory (#999).

    Fails closed: a path whose links can't be followed counts as restricted,
    so an unfollowable route never returns a result. On POSIX that is every
    error a strict resolve raises. On Windows a strict resolve also fails on
    files Jedi reads fine (access denied on a parent, a ``WindowsApps``
    app-exec link, an unusual name), so there only a loop fails closed; any
    other error falls back to a non-strict resolve, which is still checked
    (#1005). The credential stores do apply on Windows, below the server's
    own home, so the check can't simply be skipped there.
    """
    from pyeye.validation import restricted_dir

    try:
        resolved = normalize_path_strict(path)
    except RuntimeError:
        return True  # a symlink loop, before Python 3.13
    except OSError as exc:
        if not _ON_WINDOWS or _is_link_loop(exc):
            return True
        try:
            resolved = normalize_path(path)
        except (OSError, RuntimeError):
            return True
    return restricted_dir(resolved)


#: Whether the server runs on Windows: patched by tests of the Windows policy.
_ON_WINDOWS = os.name == "nt"


def _is_link_loop(exc: OSError) -> bool:
    """Whether *exc* says a symlink chain can't be followed (a loop), on any OS."""
    return exc.errno == errno.ELOOP or getattr(exc, "winerror", None) == _WINERROR_CANT_RESOLVE


def resolve_handle(path: str, analyzer: JediAnalyzer) -> Resolved | NotFound:
    """Resolve an exact dotted *path* to its definition. Never raises for a miss.

    A miss is :class:`NotFound`. An internal failure (a pyeye or Jedi bug, such
    as #684's ``KeyError``) is NOT a miss: it propagates, so the tool call is a
    loud, logged crash rather than a confident "unresolved" (#704, #626). A
    caller resolving one item of a multi-item answer uses :func:`resolve_item`.

    Args:
        path: A dotted handle, canonical or a re-export alias.
        analyzer: The project's analyzer.

    Returns:
        :class:`Resolved` with the canonical handle, or :class:`NotFound`.
    """
    found = _resolve(path, analyzer, hops=0)
    if found is None:
        return NotFound(reason="unresolved", detail=f"{path!r} did not resolve to a definition.")
    canonical, anchor = found
    if isinstance(anchor, _SharedLocalName):
        return _shared_local(canonical, anchor, analyzer)
    anchor = relocate_platform(canonical, anchor)  # os.path → its sys.platform branch (#329)
    if in_restricted_dir(anchor):
        # Refused, not returned: its symbols and location would expose the file (#999).
        return NotFound(
            reason="unresolved", detail=RESTRICTED_DETAIL.format(path=path), restricted=True
        )
    kind = normalise_kind_from_name(anchor)
    return Resolved(
        handle=canonical,
        kind=kind,
        scope=scope_for(anchor, canonical, kind, analyzer),
        anchor=anchor,
    )


def _shared_local(path: str, shared: _SharedLocalName, analyzer: JediAnalyzer) -> NotFound:
    """A :class:`NotFound` for a path naming several local definitions (#1022)."""
    if any(in_restricted_dir(a) for a in shared.anchors):
        return NotFound(
            reason="unresolved", detail=RESTRICTED_DETAIL.format(path=path), restricted=True
        )
    candidates = []
    for anchor in shared.anchors:
        kind = normalise_kind_from_name(anchor)
        candidates.append(
            Resolved(
                handle=path,
                kind=kind,
                scope=scope_for(anchor, path, kind, analyzer),
                anchor=anchor,
            )
        )
    lines = ", ".join(str(a.line) for a in shared.anchors)
    return NotFound(
        reason="unresolved",
        detail=(
            f"{path!r} names {len(shared.anchors)} definitions in one function "
            f"(lines {lines}), so no single answer is true. Use resolve_at on the "
            "one you mean."
        ),
        candidates=tuple(candidates),
    )


def resolve_item(path: str, analyzer: JediAnalyzer) -> Resolved | NotFound:
    """:func:`resolve_handle` for ONE item of a multi-item answer (#704).

    A trace node, an import target, a typeref head, a plugin record: one bad item
    mustn't sink the whole call. An internal failure on *path* is logged with its
    traceback and returned as that item's unknown, a :class:`NotFound` whose
    ``detail`` says it was an internal error, not a fact about the code. The
    caller reports it through its own honest signal (``unresolved_nodes``,
    ``unresolved_imports``, an absent typeref handle, a record's
    ``unresolved``). A single-subject caller uses :func:`resolve_handle`.
    """
    try:
        return resolve_handle(path, analyzer)
    except Exception as exc:
        logger.warning("resolver: internal error resolving %r", path, exc_info=True)
        return NotFound(
            reason="unresolved",
            detail=(
                f"pyeye hit an internal error resolving {path!r} ({type(exc).__name__}). "
                "This says nothing about whether it exists; please report it."
            ),
        )


#: The ``ScopedCache`` scope that holds :func:`resolve_external_item`'s answers.
EXTERNAL_RESOLVE_SCOPE = "resolve:external"


def resolve_external_item(path: str, analyzer: JediAnalyzer) -> Resolved | NotFound:
    """:func:`resolve_item`, memoised for an answer outside the project (#925).

    The ``imports`` edge re-resolves every external import target, and the same
    stdlib targets recur across modules and calls: each resolution builds a
    synthetic Jedi script, so a ``trace`` over ``imports`` into the stdlib paid
    for the same answers again and again.

    Only a :class:`Resolved` whose scope is ``external`` is kept: a miss (honest
    per item, #704) and a project answer are resolved every time. The entries
    live in the analyzer's ``scoped_cache``, so the file watcher clears them
    with the rest of the project's caches. That covers a project edit that
    changes an external answer, such as a new module shadowing a stdlib name.
    The epoch guard keeps an answer computed across such a change from being
    stored (#817). The scope is an LRU of ``PYEYE_RESOLVE_CACHE_MAX_ENTRIES``.
    """
    from pyeye.scope_utils import ScopedCache
    from pyeye.settings import settings

    cache = getattr(analyzer, "scoped_cache", None)
    if not isinstance(cache, ScopedCache):
        return resolve_item(path, analyzer)
    hit = cache.get_recent(path, EXTERNAL_RESOLVE_SCOPE)
    # Re-checked on a hit: a symlink can be repointed after the answer was cached (#999).
    if isinstance(hit, Resolved) and not in_restricted_dir(hit.anchor):
        return hit
    epoch = cache.epoch()
    resolved = resolve_item(path, analyzer)
    if isinstance(resolved, Resolved) and resolved.scope == "external":
        cache.set(
            path,
            resolved,
            EXTERNAL_RESOLVE_SCOPE,
            epoch=epoch,
            max_entries=settings.resolve_cache_max_entries,
        )
    return resolved


async def resolve_name(bare: str, analyzer: JediAnalyzer) -> Resolved | Ambiguous | NotFound:
    """Resolve a bare (dot-free) name: an exact top-level module wins (#623).

    The policy is :data:`BARE_NAME_POLICY`, first rule that answers wins
    (``resolver.bare_name`` docs facts, #830). Picking one of several same-named
    candidates would hide the collision, so several are always ambiguous.

    Never raises.
    """
    if "." in bare or not _is_dotted_path(bare):
        return NotFound(reason="unresolved", detail=f"{bare!r} is not a bare name.")
    for rule in BARE_NAME_POLICY:
        answer = await rule.run(bare, analyzer)
        if answer is not None:
            return answer
    # A top-level module refused as restricted (#999) answers nothing above, so
    # the miss says why instead of "check the spelling".
    exact = resolve_item(bare, analyzer)
    if isinstance(exact, NotFound) and exact.restricted:
        return exact
    return NotFound(reason="unresolved", detail=_miss_detail(bare))


@dataclass(frozen=True)
class NameRule:
    """One rule of the bare-name policy: the first rule that answers wins.

    Attributes:
        name: Short identifier (``exact_module``); the docs fact's ID segment.
        summary: What the rule decides, one sentence; the docs show it as written.
        run: Takes ``(bare, analyzer)``; returns the answer, or ``None`` to fall through.
    """

    name: str
    summary: str
    run: Callable[[str, JediAnalyzer], Awaitable[Resolved | Ambiguous | None]]


def _decide(found: dict[str, Resolved]) -> Resolved | Ambiguous | None:
    """One candidate is the answer, several are ambiguous, none falls through."""
    if not found:
        return None
    if len(found) == 1:
        return next(iter(found.values()))
    return Ambiguous(candidates=_ordered(list(found.values())))


async def _rule_shadow(bare: str, analyzer: JediAnalyzer) -> Resolved | Ambiguous | None:
    shadow = _top_level_shadow(bare, analyzer)
    return Ambiguous(candidates=_ordered(shadow)) if len(shadow) > 1 else None


async def _rule_exact_module(bare: str, analyzer: JediAnalyzer) -> Resolved | Ambiguous | None:
    exact = resolve_handle(bare, analyzer)
    if isinstance(exact, Resolved) and exact.kind == "module" and exact.handle == bare:
        return exact
    return None


async def _rule_name_index(bare: str, analyzer: JediAnalyzer) -> Resolved | Ambiguous | None:
    # An index or lookup failure propagates (#704): it isn't evidence the name is absent.
    matches = [m.get("full_name") for m in await analyzer.find_symbol(bare)]
    return _decide(_canonical_candidates(matches, analyzer))


async def _rule_members(bare: str, analyzer: JediAnalyzer) -> Resolved | Ambiguous | None:
    members = [d.full_name for d in await analyzer.find_member_definitions(bare)]
    return _decide(_canonical_candidates(members, analyzer))


#: How :func:`resolve_name` decides a bare name, in order (docs fact ``resolver.bare_name``).
BARE_NAME_POLICY: tuple[NameRule, ...] = (
    NameRule(
        "shadow",
        "a top-level package or module under more than one project root is ambiguous",
        _rule_shadow,
    ),
    NameRule(
        "exact_module",
        "a complete top-level module (the project's package, a namespace root or an "
        "external module) wins over same-named definitions",
        _rule_exact_module,
    ),
    NameRule(
        "name_index",
        "every project definition with that name, canonicalised: one is the answer, "
        "several are ambiguous",
        _rule_name_index,
    ),
    NameRule(
        "members",
        "only when nothing above matched, every method or class attribute with that "
        "name, decided the same way; dunder names never match",
        _rule_members,
    ),
)


def _canonical_candidates(
    full_names: list[str | None], analyzer: JediAnalyzer
) -> dict[str, Resolved]:
    """Re-resolve each name through :func:`resolve_handle`; aliases collapse."""
    found: dict[str, Resolved] = {}
    for full_name in full_names:
        if not full_name:
            continue
        candidate = resolve_handle(full_name, analyzer)
        if isinstance(candidate, Resolved):
            found.setdefault(candidate.handle, candidate)
    return found


def _miss_detail(bare: str) -> str:
    if bare.startswith("__") and bare.endswith("__"):
        return (
            f"{bare!r} is a special method that most classes define, so a bare name "
            "can't pick one. Use the class's dotted handle (pkg.mod.Class."
            f'{bare}), or expand(<class>, "members") to list a class\'s members.'
        )
    return f"No definition named {bare!r}."


def _top_level_shadow(bare: str, analyzer: JediAnalyzer) -> list[Resolved]:
    """Top-level modules named *bare* under DISTINCT project roots (#423 shadow).

    Each root of the ``TOP_LEVEL_PACKAGE`` boundary is checked for
    ``<root>/<bare>/__init__.py`` or ``<root>/<bare>.py``.  Fewer than two
    distinct files is no shadow.
    """
    files: dict[str, Path] = {}
    for root in project_roots(analyzer, RootsBoundary.TOP_LEVEL_PACKAGE):
        for candidate in (root / bare / "__init__.py", root / f"{bare}.py"):
            if candidate.is_file():
                # A copy that resolves into a restricted directory is no candidate (#999).
                if not restricted_path(candidate):
                    files.setdefault(path_to_key(candidate), candidate)
                break
    if len(files) < 2:
        return []
    out = []
    for path in files.values():
        anchor = ModuleSentinel(path, bare, analyzer)
        out.append(
            Resolved(
                handle=bare,
                kind="module",
                scope=scope_for(anchor, bare, "module", analyzer),
                anchor=anchor,
            )
        )
    return out


_SCOPE_ORDER = {"project": 0, "external": 1}


def _ordered(candidates: list[Resolved]) -> tuple[Resolved, ...]:
    """Deterministic order: project first, then by file and line."""

    def key(r: Resolved) -> tuple[int, str, int]:
        module_path = getattr(r.anchor, "module_path", None)
        return (
            _SCOPE_ORDER.get(r.scope, 9),
            module_path.as_posix() if module_path else "",
            getattr(r.anchor, "line", None) or 0,
        )

    return tuple(sorted(candidates, key=key))


# ---------------------------------------------------------------------------
# Strategy chain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One step of a resolution chain: the first step that answers wins.

    Attributes:
        name: Short identifier (``project_module``); the docs fact's ID segment.
        summary: What the step tries, one sentence; the docs show it as written.
        run: Takes ``(path, analyzer, hops, inference)``; returns
            ``(canonical handle, anchor)`` or ``None`` to fall through.
    """

    name: str
    summary: str
    run: Callable[[str, JediAnalyzer, int, _Inference], tuple[str, Any] | None]


class _Inference:
    """*path*'s synthetic import, run at most once and only if a step asks for it."""

    def __init__(self, path: str, analyzer: JediAnalyzer) -> None:
        self._path = path
        self._analyzer = analyzer
        self._result: tuple[list[Any], Any | None] | None = None

    def get(self) -> tuple[list[Any], Any | None]:
        if self._result is None:
            self._result = _synthetic_import(self._path, self._analyzer)
        return self._result


def _resolve(path: str, analyzer: JediAnalyzer, hops: int) -> tuple[str, Any] | None:
    """Run the strategy chain; return ``(canonical handle, anchor)`` or ``None``.

    :data:`STRATEGY` runs first. Then the path's top-level package picks one
    side (#506): :data:`PROJECT_STRATEGY` inside the project, where there is no
    fallback after a miss, else :data:`EXTERNAL_STRATEGY`, whose steps never run
    on a project path.
    """
    if not _is_dotted_path(path):
        return None
    inference = _Inference(path, analyzer)
    for step in STRATEGY:
        found = step.run(path, analyzer, hops, inference)
        if found is not None:
            return found
    # Only now, after the shared steps missed, does the side matter.
    side = PROJECT_STRATEGY if _top_level_in_project(path, analyzer) else EXTERNAL_STRATEGY
    for step in side:
        found = step.run(path, analyzer, hops, inference)
        if found is not None:
            return found
    return None


def _is_dotted_path(path: str) -> bool:
    try:
        Handle(path)
    except ValueError:
        return False
    return True


def _project_module(path: str, analyzer: JediAnalyzer) -> Any | None:
    """Step 1: a project module's ``Name``, or a sentinel anchored on its file."""
    mod_file = file_for_module(analyzer, path)
    if mod_file is None:
        return None
    try:
        script = file_artifact_cache.get_script(mod_file, analyzer.project)
        for name in script.get_names(all_scopes=False, definitions=True, references=False):
            if name.type == "module" and name.full_name == path:
                return name
    except Exception as exc:
        logger.debug("resolver: module names for %r failed: %s", path, exc)
    return ModuleSentinel(mod_file, path, analyzer)


def _top_level_in_project(path: str, analyzer: JediAnalyzer) -> bool:
    """Whether *path*'s top-level package is inside the project boundary (#506)."""
    top = path.split(".", 1)[0]
    return file_for_module(analyzer, top) is not None or bool(
        find_namespace_package_dirs(top, analyzer)
    )


def _place_definition(path: str, analyzer: JediAnalyzer, hops: int) -> tuple[str, Any] | None:
    """Step 4: place *path* in the deepest project module along it.

    Returns ``(canonical handle, definition anchor)``, or ``None`` if the deepest
    module doesn't define it.
    """
    parts = path.split(".")
    for split_at in range(len(parts) - 1, 0, -1):
        module_dotted = ".".join(parts[:split_at])
        mod_file = file_for_module(analyzer, module_dotted)
        if mod_file is None:
            continue
        rest = parts[split_at:]
        # The module file exists, so a failure reading its names is internal (#704).
        names = file_artifact_cache.get_script(mod_file, analyzer.project).get_names(
            all_scopes=True, definitions=True, references=False
        )
        # ``self.x = …`` / ``obj.x = …`` share a binding's full_name but bind
        # nothing in this scope (#567).
        matches = [
            name
            for name in names
            if _names_path(name, path, ".".join(rest), analyzer) and not is_attribute_target(name)
        ]
        if matches:
            # Several definitions of one function-local name: none is THE answer (#1022).
            shared = _shared_local_definitions(matches, path)
            if shared is not None:
                return path, shared
            anchor = _anchor_on_bindings(matches, mod_file, path)
            placed = _canonical_of(anchor, path, analyzer)
            return (placed, anchor) if placed is not None else None
        # An explicit binding first, then the module's star imports (#1007).
        return _follow_alias(module_dotted, rest, names, analyzer, hops) or _follow_star(
            module_dotted, mod_file, rest, analyzer, hops
        )
    return None


def _in_a_function(name: Any) -> bool:
    """Whether *name* is defined inside a function or method, at any depth (#1022)."""
    scope = name.parent()
    while scope is not None and scope.type != "module":
        if scope.type == "function":
            return True
        scope = scope.parent()
    return False


def _shared_local_definitions(matches: list[Any], path: str) -> _SharedLocalName | None:
    """Every distinct function-local definition *path* names, if there are several (#1022).

    ``None`` when there is one definition, or any match is not function-local:
    module-level names keep #857's binding rules.
    """
    if len(matches) < 2 or not all(_in_a_function(m) for m in matches):
        return None
    anchors: dict[tuple[Any, int, int], Any] = {}
    for match in matches:
        anchor = _anchor_on_definition(match, path)
        anchors.setdefault((anchor.module_path, anchor.line or 0, anchor.column or 0), anchor)
    if len(anchors) < 2:
        return None
    return _SharedLocalName(tuple(anchors[spot] for spot in sorted(anchors, key=lambda k: k[1:])))


#: The ``(star source module, name)`` pairs already tried in this resolution, so a
#: star cycle (``a`` star-imports ``b``, ``b`` star-imports ``a``) ends (#1007).
_STAR_SEEN: ContextVar[set[tuple[str, str]] | None] = ContextVar("_STAR_SEEN", default=None)


def _follow_star(
    module_dotted: str,
    mod_file: Path,
    rest: list[str],
    analyzer: JediAnalyzer,
    hops: int,
) -> tuple[str, Any] | None:
    """Place the head of *rest* through *module_dotted*'s ``from x import *`` (#1007).

    Each star source, in source order, that is a project module and
    star-exports the head (:func:`pyeye.star_exports.star_exported`: its static
    ``__all__``, else a public name) is tried by resolving ``<source>.<rest>``;
    the first that resolves wins. Explicit bindings were tried first, as Python
    lets them shadow a star. Bounded by the alias hop limit and a seen-set.
    """
    from pyeye.analyzers.base_resolution import build_star_sources
    from pyeye.import_analyzer import resolve_relative_import
    from pyeye.star_exports import star_exported

    if hops >= _MAX_ALIAS_HOPS:
        return None
    try:
        tree = file_artifact_cache.get_ast(mod_file)
    except (SyntaxError, ValueError):
        return None  # the server's Python can't parse it (#703): no stars to follow
    head = rest[0]
    is_package = mod_file.name == "__init__.py"
    seen = _STAR_SEEN.get()
    token = _STAR_SEEN.set(set()) if seen is None else None
    seen = _STAR_SEEN.get()
    assert seen is not None
    try:
        for source in build_star_sources(tree, module_dotted, resolve_relative_import, is_package):
            if (source, head) in seen:
                continue
            seen.add((source, head))
            source_file = file_for_module(analyzer, source)
            if source_file is None:
                continue  # not a project module: an external star isn't followed here
            try:
                exports = star_exported(file_artifact_cache.get_ast(source_file), head)
            except (SyntaxError, ValueError):
                continue
            if not exports:
                continue
            found = _resolve(".".join([source, *rest]), analyzer, hops + 1)
            if found is not None:
                return found
        return None
    finally:
        if token is not None:
            _STAR_SEEN.reset(token)


def _names_path(name: Any, path: str, qualname: str, analyzer: JediAnalyzer) -> bool:
    """Whether Jedi's *name* is the definition *path* names, in pyeye's naming (#814).

    Jedi names a file from the first sys_path root that contains it, so a
    package added inside the project (``.hidden/upstream/clonepkg``) gets a
    module part from the project root (``.hidden.upstream.clonepkg.thing.X``).
    pyeye's name comes from the one file -> module mapper (#714), through
    :func:`handle_for_anchor`. Comparing on Jedi's name missed every such package.
    The cheap checks run first, so the mapper is asked only about candidates:
    the respelling changes only the module part, so a name whose Jedi
    ``full_name`` doesn't end with *qualname* (the part of *path* after its
    module) can't match.
    """
    # ``name.name`` is cheap; ``full_name`` makes Jedi compute the scope chain.
    if name.name != path.rsplit(".", 1)[-1]:
        return False
    full_name = name.full_name
    if not full_name:
        return False
    if full_name == path:
        return True
    if not full_name.endswith(f".{qualname}"):
        return False
    return handle_for_anchor(name, full_name, analyzer) == path


def _follow_alias(
    module_dotted: str,
    rest: list[str],
    names: list[Any],
    analyzer: JediAnalyzer,
    hops: int,
) -> tuple[str, Any] | None:
    """Place the head of *rest* by NAME and follow it to its definition.

    Two cases share this path:

    * a re-export alias (``package.Thing`` → ``package._impl.Thing``, #431);
    * a definition in this module whose ``full_name`` match missed (the
      #419-class Jedi non-determinism): ``goto`` lands on the definition
      deterministically, so it is placed here rather than by falling through
      to a shallower module (#429).

    Any remaining components are then resolved under the head's canonical
    handle.
    """
    if hops >= _MAX_ALIAS_HOPS:
        return None
    head = rest[0]
    for name in names:
        if name.name != head or not _is_module_level(name) or is_attribute_target(name):
            continue
        target = _goto_definition(name)
        if target is None or not target.full_name:
            continue
        # Jedi's raw name may not be a dotted path (``.hidden.upstream.…``, #814);
        # the respelled handle must be.
        canonical_head = _canonical_of(target, target.full_name, analyzer)
        if canonical_head is None or not _is_dotted_path(canonical_head):
            continue  # a project file the mapper can't place (#714)
        if len(rest) == 1:
            return canonical_head, target
        if canonical_head == f"{module_dotted}.{head}":
            return None  # defined here; the nested path was already tried by full_name
        return _resolve(".".join([canonical_head, *rest[1:]]), analyzer, hops + 1)
    return None


def _step_project_module(
    path: str, analyzer: JediAnalyzer, _hops: int, _inference: _Inference
) -> tuple[str, Any] | None:
    module = _project_module(path, analyzer)
    return (path, module) if module is not None else None


def _step_namespace_package(
    path: str, analyzer: JediAnalyzer, _hops: int, _inference: _Inference
) -> tuple[str, Any] | None:
    ns_dirs = find_namespace_package_dirs(path, analyzer)
    return (path, ModuleSentinel(ns_dirs[0], path, analyzer)) if ns_dirs else None


def _step_place_definition(
    path: str, analyzer: JediAnalyzer, hops: int, _inference: _Inference
) -> tuple[str, Any] | None:
    return _place_definition(path, analyzer, hops)


def _step_private_stdlib(
    path: str, analyzer: JediAnalyzer, _hops: int, _inference: _Inference
) -> tuple[str, Any] | None:
    """Follow the real ``.py`` chain statically (:func:`pyeye._stdlib_static.stdlib_definition`).

    It needs no Jedi inference, so it runs before the steps that do. The
    definition is named by the public re-exporting module and anchored on
    Jedi's definition ``Name`` at that file and line (#544).
    """
    private = stdlib_definition(path)
    if private is None:
        return None
    anchor = _anchor_at_stdlib_definition(private, analyzer)
    return (private.handle, anchor) if anchor is not None else None


def _step_external_module(
    path: str, _analyzer: JediAnalyzer, _hops: int, inference: _Inference
) -> tuple[str, Any] | None:
    inferred, _target = inference.get()
    for name in inferred:
        if name.type == "module" and name.full_name == path:
            return path, name
    return None


def _step_external_definition(
    path: str, _analyzer: JediAnalyzer, _hops: int, inference: _Inference
) -> tuple[str, Any] | None:
    """Placement by definition lookup (#506), for names whose value is something else.

    ``typing.TYPE_CHECKING`` is defined in ``typing.pyi`` but infers to
    ``bool``. A target at a DIFFERENT path is refused here, so a re-export never
    becomes canonical through this step (typeshed's ``collections.abc.Mapping``
    → ``typing.Mapping``, #544; the private-stdlib step places the stdlib ABCs
    first).
    """
    if "." not in path:
        return None
    _inferred, target = inference.get()
    if (
        target is not None
        and target.full_name == path
        and getattr(target, "module_path", None) is not None
    ):
        return path, target
    return None


def _step_guarded_inference(
    path: str, _analyzer: JediAnalyzer, _hops: int, inference: _Inference
) -> tuple[str, Any] | None:
    """Accept an inferred definition only if its name equals the leaf.

    Inference can land on a different object; refusing it is an honest miss
    rather than a wrong answer. Its ``full_name`` is the canonical handle (a
    re-export under the same name: ``pathlib.Path`` → ``pathlib._local.Path``
    on 3.13).
    """
    if "." not in path:
        return None
    inferred, _target = inference.get()
    leaf = path.rsplit(".", 1)[-1]
    for name in inferred:
        if name.name == leaf and name.full_name and _is_dotted_path(name.full_name):
            return name.full_name, name
    return None


#: The steps every path runs first, in order (docs fact ``resolver.strategy``).
STRATEGY: tuple[Step, ...] = (
    Step(
        "project_module",
        "a project module, as a package or a single file",
        _step_project_module,
    ),
    Step(
        "namespace_package",
        "a PEP 420 namespace package: a directory with importable content and no init file",
        _step_namespace_package,
    ),
)

#: The steps after :data:`STRATEGY` for a path whose top-level package is in the project.
PROJECT_STRATEGY: tuple[Step, ...] = (
    Step(
        "definition_placement",
        "the definition in the deepest project module along the path, following a "
        "re-export alias to its definition (an explicit import, or a `from x import *` "
        "of a name x star-exports), with no fallback to shallower modules",
        _step_place_definition,
    ),
)

#: The steps after :data:`STRATEGY` for a path outside the project, in order.
EXTERNAL_STRATEGY: tuple[Step, ...] = (
    Step(
        "private_stdlib",
        "a stdlib definition in a private module, named by its public re-exporting module",
        _step_private_stdlib,
    ),
    Step(
        "external_module",
        "a stdlib or site-packages module, through a Jedi import",
        _step_external_module,
    ),
    Step(
        "external_definition",
        "a definition at exactly the requested path, found by goto",
        _step_external_definition,
    ),
    Step(
        "guarded_inference",
        "an inferred definition, accepted only if its name equals the last component",
        _step_guarded_inference,
    ),
)


def _anchor_at_stdlib_definition(found: StdlibDefinition, analyzer: JediAnalyzer) -> Any | None:
    """The Jedi definition ``Name`` at *found*'s file and line, or ``None``.

    Anchoring on Jedi's own definition keeps ``kind``, ``signature`` and
    ``location`` coming from the same place they do for every other symbol;
    only the handle is the public one.
    """
    names = file_artifact_cache.get_script(found.file, analyzer.project).get_names(
        all_scopes=True, definitions=True, references=False
    )
    for name in names:
        if name.name == found.name and name.line == found.line:
            return name
    return None


def _synthetic_import(path: str, analyzer: JediAnalyzer) -> tuple[list[Any], Any | None]:
    """Infer and ``goto`` *path* through a synthetic ``import <parent>``.

    The one place a file-less ``jedi.Script`` is built (#623).  Returns the
    inferred Jedi ``Name`` objects and the single ``goto`` target picked by
    :func:`pyeye._goto.goto_target` (``None`` unless exactly one).

    Inference of a name that doesn't exist returns ``[]``; it doesn't raise. A
    raise is an internal failure (#684's parso ``KeyError``) and propagates
    (#704), never an empty "unresolved".
    """
    import jedi

    module_dotted = path.rsplit(".", 1)[0] if "." in path else path
    script = jedi.Script(code=f"import {module_dotted}\n{path}", project=analyzer.project)
    inferred = list(script.infer(2, len(path)))
    return inferred, goto_target(script, 2, len(path))


# ---------------------------------------------------------------------------
# Anchoring helpers
# ---------------------------------------------------------------------------


def _is_module_level(name: Any) -> bool:
    """Whether *name* is bound at module scope (its parent is the module)."""
    try:
        parent = name.parent()
    except Exception:
        return False
    return parent is not None and getattr(parent, "type", None) == "module"


def _goto_definition(name: Any) -> Any | None:
    """Follow *name* to its definition with ``goto(follow_imports=True)``."""
    try:
        targets = name.goto(follow_imports=True)
    except Exception:
        return None
    for target in targets:
        if target.module_path is not None:
            return target
    return None


@dataclass(frozen=True)
class _Bindings:
    """What a module's AST says about the names bound on each line (#857).

    Keys are ``(line, name)``, matched against a Jedi name's ``line`` / ``name``.
    """

    imports: frozenset[tuple[int, str]]  #: a name an ``import`` alias binds
    definitions: frozenset[tuple[int, str]]  #: a name a plain definition binds
    branched: frozenset[int]  #: lines inside an if / try / loop / with / match


#: Statements whose body may or may not run: a binding inside one is conditional.
_BRANCHING = (
    ast.If,
    ast.Try,
    ast.TryStar,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)


def _definition_keys(node: ast.AST) -> list[tuple[int, str]]:
    """``(line, name)`` for each name *node* binds as a plain definition.

    Deliberately narrow (#871 review): a ``class`` / ``def`` name, a plain
    ``Name`` target of ``=`` whose value isn't that same name (``A = A`` is
    not a new definition), and an annotated assignment WITH a value. Anything
    else Jedi reports (a comprehension or lambda target, a bare annotation
    ``A: int``, ``A += 1``, ``del A``) is not one, and keeps the answer from
    before #857.
    """
    if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        return [(node.lineno, node.name)]
    if isinstance(node, ast.Assign):
        same = node.value.id if isinstance(node.value, ast.Name) else None
        return [(t.lineno, t.id) for t in node.targets if isinstance(t, ast.Name) and t.id != same]
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        target = node.target
        if isinstance(target, ast.Name):
            return [(target.lineno, target.id)]
    return []


def _bindings(mod_file: Path) -> _Bindings | None:
    """Import and definition bindings, and conditional lines, of *mod_file*.

    ``None`` when the server's Python can't parse the file (#703): Jedi's parser
    tolerates it, so resolution must too, just without telling bindings apart.
    """
    try:
        tree = file_artifact_cache.get_ast(mod_file)
    except (SyntaxError, ValueError):
        return None
    imports: set[tuple[int, str]] = set()
    definitions: set[tuple[int, str]] = set()
    branched: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                imports.add((getattr(alias, "lineno", node.lineno), bound))
        elif isinstance(node, _BRANCHING):
            branched.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        definitions.update(_definition_keys(node))
    return _Bindings(frozenset(imports), frozenset(definitions), frozenset(branched))


def _cross_file_target(name: Any) -> Any | None:
    """The definition an import binding *name* leads to in ANOTHER file, or ``None``."""
    try:
        targets = name.goto(follow_imports=True)
    except Exception:
        return None
    own_file = getattr(name, "module_path", None)
    for target in targets:
        if (
            target.module_path is not None
            and own_file is not None
            and not paths_equal(target.module_path, own_file)
            and target.full_name
        ):
            return target
    return None


def _anchor_on_bindings(matches: list[Any], mod_file: Path, handle: str) -> Any:
    """Anchor *handle* among every binding in its module that names it (#857).

    The rule is "answer as before #857, except where that answer was wrong":

    - **One binding**: if its goto leads to a definition in another file it can
      only be an import, so it collapses (a relative re-export). No AST needed,
      so a lone import under ``if TYPE_CHECKING:`` collapses too.
    - **Only imports**, all leading to ONE definition elsewhere (possibly
      repeated): collapse to it. Imports of DIFFERENT definitions keep the first
      binding, as before, whether in if/else branches or unconditional: two
      competing imports are not a case the old answer got wrong.
    - **Imports and plain definitions, all unconditional** (``from .src import
      A`` then ``class A``): the LAST binding wins, as at runtime. If the last is
      an import (``class A`` then ``from .src import A``), it collapses.
    - **Everything else keeps the first binding**, as before: no import among
      them (a property's setter, overloads, an if/else ``def``), a binding inside
      a branch (``TYPE_CHECKING``, ``try/except ImportError``), anything that
      isn't a plain definition (a comprehension or lambda target, ``A: int``,
      ``A = A``, ``A += 1``, ``del A``), or a module that won't parse.
    """
    first = matches[0]
    if len(matches) == 1:
        return _cross_file_target(first) or _anchor_on_definition(first, handle)
    found = _bindings(mod_file)
    if found is None:
        return _anchor_on_definition(first, handle)
    keys = [((m.line or 0), m.name) for m in matches]
    is_import = [k in found.imports for k in keys]
    if all(is_import):
        targets = [_cross_file_target(m) for m in matches]
        spots = {(t.module_path, t.line, t.column) for t in targets if t is not None}
        if len(spots) == 1 and all(t is not None for t in targets):
            return next(t for t in targets if t is not None)
        return _anchor_on_definition(first, handle)
    plain = all(i or k in found.definitions for i, k in zip(is_import, keys, strict=True))
    unconditional = not any(line in found.branched for line, _ in keys)
    if not (any(is_import) and plain and unconditional):
        return _anchor_on_definition(first, handle)
    last = max(matches, key=lambda m: (m.line or 0, m.column or 0))
    if ((last.line or 0), last.name) in found.imports:
        return _cross_file_target(last) or _anchor_on_definition(last, handle)
    return _anchor_on_definition(last, handle)


def _anchor_on_definition(name: Any, handle: str) -> Any:
    """Anchor a ``full_name`` match on its definition site (#429).

    A re-export binding in an ``__init__.py`` reports the same ``full_name`` as
    the class it re-exports (Jedi follows the import one hop), so a match may
    land on the import line instead of the class body. ``goto`` is idempotent
    on a true definition and follows a binding through to it; the
    ``full_name`` / ``module_path`` guard keeps a genuine definition if
    ``goto`` wanders.
    """
    try:
        targets = name.goto(follow_imports=True)
    except Exception:
        return name
    for target in targets:
        if target.full_name == handle and target.module_path is not None:
            return target
    return name


#: Jedi's module name for a file it can't place on its own roots (#714).
_JEDI_UNPLACED_MODULE = "__main__"


def handle_for_anchor(anchor: Any, full_name: str, analyzer: JediAnalyzer) -> str | None:
    """The canonical handle for *anchor*, named *full_name* by Jedi, or ``None`` (#714).

    The one project-anchor rule, shared by the resolver and every edge handle
    (``edges._handle_for_name``). A definition in a file the one file -> module
    mapper can name takes its module part from the mapper, with Jedi's qualname
    after it. Jedi's own module guess is wrong when the file's spelling differs
    from its roots (``src.pkg.mod.X``, or ``__main__.X`` for a file it can't
    place at all). Elsewhere (stdlib, site-packages) *full_name* stands. A
    ``__main__.*`` name is never a handle: such a definition is ``None``, which
    callers report as not found or skip.
    """
    module_path = getattr(anchor, "module_path", None)
    module = module_name_for_file(analyzer, Path(module_path)) if module_path else None
    if module is not None:
        if normalise_kind_from_name(anchor) == "module":
            return module
        jedi_module = getattr(anchor, "module_name", None) or ""
        if full_name.startswith(f"{module}."):
            return full_name
        if jedi_module and full_name.startswith(f"{jedi_module}."):
            return f"{module}.{full_name[len(jedi_module) + 1 :]}"
        return None
    if full_name == _JEDI_UNPLACED_MODULE or full_name.startswith(f"{_JEDI_UNPLACED_MODULE}."):
        return None
    return full_name


def _canonical_of(anchor: Any, fallback: str, analyzer: JediAnalyzer) -> str | None:
    """:func:`handle_for_anchor` of *anchor*'s ``full_name``, or of *fallback* if it has none."""
    full_name = getattr(anchor, "full_name", None)
    if full_name:
        # Respell Jedi's name first, even when it isn't itself a dotted path
        # (``.hidden.upstream.pkg.X``, #814): the respelled handle must be.
        handle = handle_for_anchor(anchor, full_name, analyzer)
        if handle is not None and _is_dotted_path(handle):
            return handle
        if _is_dotted_path(full_name):
            # A real name that names no handle stays unplaced: a __main__.*
            # name is never a handle (#714), never rescued by *fallback*.
            return None
    handle = handle_for_anchor(anchor, fallback, analyzer)
    return handle if handle is not None and _is_dotted_path(handle) else None


# ---------------------------------------------------------------------------
# Scope (the one rule, shared with edge stubs)
# ---------------------------------------------------------------------------


def scope_for(
    anchor: Any, handle: str, kind: str, analyzer: JediAnalyzer
) -> Literal["project", "external"]:
    """Classify a resolved symbol as ``"project"`` or ``"external"`` (#623).

    The one scope rule, used by :func:`resolve_handle` and by every edge stub
    (``stubs.build_stub``), so a symbol reports the same scope wherever it
    appears:

    * a symbol with a file is classified by :func:`pyeye.scope.classify_scope`,
      whose project boundary includes configured namespace roots;
    * a file-less module (a PEP 420 namespace package Jedi didn't anchor) is
      ``project`` when its directory is inside the boundary;
    * #454: an external classification is reconciled back to ``project`` when
      the canonical handle names a project module (Jedi followed an installed
      copy of a package that is also registered as a project / sibling root).
    """
    module_path: Path | None = getattr(anchor, "module_path", None)
    if module_path is None:
        if kind == "module":
            dirs = find_namespace_package_dirs(handle, analyzer)
            if dirs and classify_scope(dirs[0].as_posix(), analyzer) == "project":
                return "project"
        return "external"
    scope = classify_scope(module_path.as_posix(), analyzer)
    # Perf short-circuit (#454): the split needs the SAME package importable from
    # a registered sibling root AND an installed copy that wins Jedi's
    # precedence, which is only possible with sibling roots registered.  Without
    # them, skip the per-symbol filesystem probe, keeping stdlib-heavy edge
    # expansion free of I/O.
    if (
        scope == "external"
        and getattr(analyzer, "additional_paths", None)
        and _names_project_module(handle, kind, analyzer)
    ):
        return "project"
    return scope


def _names_project_module(handle: str, kind: str, analyzer: JediAnalyzer) -> bool:
    """Whether *handle*'s module portion is a project-boundary module file (#454).

    The module portion is the whole handle for a ``module`` kind, else the
    handle minus its trailing symbol component.  A stdlib / pure-external
    handle has no project module file, so it is never reconciled.
    """
    if kind == "module":
        module_dotted = handle
    else:
        parts = handle.split(".")
        if len(parts) < 2:
            return False
        module_dotted = ".".join(parts[:-1])
    return file_for_module(analyzer, module_dotted) is not None
