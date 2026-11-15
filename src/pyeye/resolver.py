"""The one canonical handle resolver (#623).

:func:`resolve_handle` turns an exact dotted path into its definition. It is the
single implementation behind ``inspect``, ``outline``, ``expand`` and the
``trace`` roots, so those tools cannot disagree about whether a handle exists,
which definition it names, or which handle to echo back.

Strategy order (the first hit wins):

1. **Project module**: :func:`pyeye.project_layout.file_for_module` finds the
   ``__init__.py`` / ``<name>.py``; the anchor is the module ``Name`` or a
   :class:`~pyeye._module_sentinel.ModuleSentinel`.
2. **PEP 420 namespace package** (#444): a directory with importable content and
   no ``__init__.py``, anchored as a directory ``ModuleSentinel``.
3. **External module**: a stdlib / site-packages module (``logging``, ``os``,
   ``os.path``) located through a Jedi module import.
4. **Definition placement**: strip trailing components to the DEEPEST project
   module file, then match the definition whose ``full_name`` is the handle. A
   re-export alias (``package.Thing`` for ``package._impl.Thing``) is matched
   by name and followed to its definition, whose ``full_name`` becomes the
   canonical handle. There is no fallback to shallower modules after a miss.
5. **Guarded inference**, last and only for handles outside the project
   boundary (#506): infer ``module.leaf`` through a synthetic import and accept
   a result only if its name equals the leaf. Inference can land on a
   different object (``typing.TYPE_CHECKING`` infers to ``bool``); refusing it
   is an honest miss rather than a wrong answer.

Steps 3 and 5 read one :func:`_synthetic_import`, the one place a
``jedi.Script(code=...)`` is built (``tests/test_decision_invariants_fitness.py``).

This module sits below ``pyeye.mcp`` (``tests/test_import_layers_fitness.py``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pyeye import file_artifact_cache
from pyeye._goto import goto_target
from pyeye._jedi_names import is_attribute_target
from pyeye._module_sentinel import ModuleSentinel
from pyeye.handle import Handle
from pyeye.kinds import normalise_kind_from_name
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


@dataclass(frozen=True)
class Ambiguous:
    """A bare name with several canonical definitions, in deterministic order."""

    candidates: tuple[Resolved, ...]


def resolve_handle(path: str, analyzer: JediAnalyzer) -> Resolved | NotFound:
    """Resolve an exact dotted *path* to its definition. Never raises.

    Args:
        path: A dotted handle, canonical or a re-export alias.
        analyzer: The project's analyzer.

    Returns:
        :class:`Resolved` with the canonical handle, or :class:`NotFound`.
    """
    try:
        found = _resolve(path, analyzer, hops=0)
    except Exception as exc:  # never raise: an internal error is an honest miss
        logger.debug("resolve_handle(%r) failed: %s", path, exc)
        found = None
    if found is None:
        return NotFound(reason="unresolved", detail=f"{path!r} did not resolve to a definition.")
    canonical, anchor = found
    kind = normalise_kind_from_name(anchor)
    return Resolved(
        handle=canonical,
        kind=kind,
        scope=scope_for(anchor, canonical, kind, analyzer),
        anchor=anchor,
    )


async def resolve_name(bare: str, analyzer: JediAnalyzer) -> Resolved | Ambiguous | NotFound:
    """Resolve a bare (dot-free) name: an exact top-level module wins (#623).

    Policy, first rule that applies:

    1. **Shadow** (#423): the name is a top-level package or module under more
       than one project root (``<name>/`` in both the project and ``src/``).
       Picking one would hide the collision, so the result is ambiguous.
    2. **Exact top-level module**: the name is itself a complete top-level
       module (the project's own package, a PEP 420 namespace root, or an
       external module such as ``functools`` or ``inspect``).  It wins even
       when project definitions share the name; those are reachable by their
       dotted handles.
    3. **Name index**: every project definition named *bare*, each
       re-resolved through :func:`resolve_handle` so every candidate is
       canonical; duplicates (an alias and its definition) collapse.  One
       left is the answer; several are ambiguous.

    Never raises.
    """
    if "." in bare or not _is_dotted_path(bare):
        return NotFound(reason="unresolved", detail=f"{bare!r} is not a bare name.")

    shadow = _top_level_shadow(bare, analyzer)
    if len(shadow) > 1:
        return Ambiguous(candidates=_ordered(shadow))

    exact = resolve_handle(bare, analyzer)
    if isinstance(exact, Resolved) and exact.kind == "module" and exact.handle == bare:
        return exact

    try:
        matches = await analyzer.find_symbol(bare)
    except Exception as exc:  # never raise: an index failure is an honest miss
        logger.debug("resolve_name(%r): find_symbol failed: %s", bare, exc)
        matches = []
    found: dict[str, Resolved] = {}
    for match in matches:
        full_name = match.get("full_name")
        if not full_name:
            continue
        candidate = resolve_handle(full_name, analyzer)
        if isinstance(candidate, Resolved):
            found.setdefault(candidate.handle, candidate)
    if not found:
        return NotFound(reason="unresolved", detail=f"No definition named {bare!r}.")
    if len(found) == 1:
        return next(iter(found.values()))
    return Ambiguous(candidates=_ordered(list(found.values())))


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
                files.setdefault(candidate.resolve().as_posix(), candidate)
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


def _resolve(path: str, analyzer: JediAnalyzer, hops: int) -> tuple[str, Any] | None:
    """Run the strategy chain; return ``(canonical handle, anchor)`` or ``None``."""
    if not _is_dotted_path(path):
        return None

    module = _project_module(path, analyzer)  # 1
    if module is not None:
        return path, module

    ns_dirs = find_namespace_package_dirs(path, analyzer)  # 2
    if ns_dirs:
        return path, ModuleSentinel(ns_dirs[0], path, analyzer)

    # Steps 3-5.  Placement (4) needs a project module along the path, and the
    # external steps (3, 5) must never run inside the project (#506), so the
    # top-level package decides which side runs; the order is unchanged.
    if _top_level_in_project(path, analyzer):
        return _place_definition(path, analyzer, hops)  # 4
    return _external(path, analyzer)  # 3, then 5


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
        try:
            names = file_artifact_cache.get_script(mod_file, analyzer.project).get_names(
                all_scopes=True, definitions=True, references=False
            )
        except Exception as exc:
            logger.debug("resolver: names for %s failed: %s", mod_file, exc)
            return None
        for name in names:
            # ``self.x = …`` / ``obj.x = …`` share a binding's full_name but bind
            # nothing in this scope (#567).
            if name.full_name == path and not is_attribute_target(name):
                anchor = _anchor_on_definition(name, path)
                placed = _canonical_of(anchor, path, analyzer)
                return (placed, anchor) if placed is not None else None
        return _follow_alias(module_dotted, rest, names, analyzer, hops)
    return None


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
        if target is None or not target.full_name or not _is_dotted_path(target.full_name):
            continue
        canonical_head = _canonical_of(target, target.full_name, analyzer)
        if canonical_head is None:
            continue  # a project file the mapper can't place (#714)
        if len(rest) == 1:
            return canonical_head, target
        if canonical_head == f"{module_dotted}.{head}":
            return None  # defined here; the nested path was already tried by full_name
        return _resolve(".".join([canonical_head, *rest[1:]]), analyzer, hops + 1)
    return None


def _external(path: str, analyzer: JediAnalyzer) -> tuple[str, Any] | None:
    """Steps 3 and 5 for a handle outside the project, from one synthetic import.

    3. **External module**: an inferred module whose ``full_name`` is *path*.
    5. **External definition**, first rule that applies:

       a. *Definition at the requested site*: ``goto`` (through the one picker,
          :func:`pyeye._goto.goto_target`) lands on a definition whose
          ``full_name`` IS *path* and that has a file.  This is placement by
          definition lookup (#506) for names whose value is something else:
          ``typing.TYPE_CHECKING`` is defined in ``typing.pyi`` but infers to
          ``bool``.  A target at a DIFFERENT path is refused here, so a
          re-export never becomes canonical through this step
          (``collections.abc.Mapping`` → ``typing.Mapping``, #544).
       b. *Guarded inference*: an inferred definition whose name equals the
          leaf; its ``full_name`` is the canonical handle (a re-export under the
          same name, ``pathlib.Path`` → ``pathlib._local.Path`` on 3.13).
    """
    inferred, target = _synthetic_import(path, analyzer)
    for name in inferred:  # 3
        if name.type == "module" and name.full_name == path:
            return path, name
    if "." not in path:
        return None
    if (  # 5a
        target is not None
        and target.full_name == path
        and getattr(target, "module_path", None) is not None
    ):
        return path, target
    leaf = path.rsplit(".", 1)[-1]
    for name in inferred:  # 5b
        if name.name == leaf and name.full_name and _is_dotted_path(name.full_name):
            return name.full_name, name
    return None


def _synthetic_import(path: str, analyzer: JediAnalyzer) -> tuple[list[Any], Any | None]:
    """Infer and ``goto`` *path* through a synthetic ``import <parent>``.

    The one place a file-less ``jedi.Script`` is built (#623).  Returns the
    inferred Jedi ``Name`` objects and the single ``goto`` target picked by
    :func:`pyeye._goto.goto_target` (``None`` unless exactly one).  Never raises.
    """
    module_dotted = path.rsplit(".", 1)[0] if "." in path else path
    try:
        import jedi

        script = jedi.Script(code=f"import {module_dotted}\n{path}", project=analyzer.project)
        inferred = list(script.infer(2, len(path)))
    except Exception as exc:
        logger.debug("resolver: synthetic import of %r failed: %s", path, exc)
        return [], None
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


def _canonical_of(anchor: Any, fallback: str, analyzer: JediAnalyzer) -> str | None:
    """The canonical handle for *anchor*, or ``None`` if it can't be placed (#714).

    A definition in a file the one file → module mapper can name takes its
    module part from the mapper, with Jedi's qualname after it. Jedi's own
    module guess is wrong when the file's spelling differs from its roots: a
    symlinked root gives ``src.pkg.mod.X``, or ``__main__.X`` for a file it
    can't place at all. Elsewhere (stdlib, site-packages) Jedi's ``full_name``
    stands. A ``__main__.*`` name is never a handle: such a definition is
    ``None``, which the caller reports as not found.
    """
    full_name = getattr(anchor, "full_name", None)
    if not (full_name and _is_dotted_path(full_name)):
        full_name = fallback
    module_path = getattr(anchor, "module_path", None)
    module = module_name_for_file(analyzer, Path(module_path)) if module_path else None
    if module is not None:
        if normalise_kind_from_name(anchor) == "module":
            return module
        jedi_module = getattr(anchor, "module_name", None) or ""
        if jedi_module and full_name.startswith(f"{jedi_module}."):
            return f"{module}.{full_name[len(jedi_module) + 1 :]}"
        if full_name.startswith(f"{module}."):
            return full_name
        return None
    if full_name == _JEDI_UNPLACED_MODULE or full_name.startswith(f"{_JEDI_UNPLACED_MODULE}."):
        return None
    return full_name


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
