"""Per-project, non-evicting, invalidate-and-rebuild store of AST graph artifacts.

Phase A (#457) hosts the **name->definitions index** here: a whole-project map
from a simple name to *every* definition site of that name, built once by
streaming each project ``.py`` through :func:`pyeye.file_artifact_cache.get_ast`
and :func:`pyeye.analyzers.base_resolution.extract_definitions`. The index holds
only compact :class:`~pyeye._module_sentinel.DefinitionSentinel` metadata and is
kept **out** of the ``file_artifact_cache`` LRU, so completeness can never depend
on the AST cache size — an evictable index would silently drop definitions and
reincarnate #457.

The store is keyed purely by *project identity* (the project root, canonicalised
via :func:`_normalize` so build and eviction can never key it differently) and
built **whole-project** (the
union of all scope paths); scope narrowing happens at lookup time in the caller,
never at build time (baking scope into a project-keyed cache poisons it). Cache
mechanism is plain invalidate-and-rebuild: a file change or project eviction
clears the project's entry and the next lookup rebuilds. A per-project
:func:`generation` snapshot stops a build that raced an invalidation from being
cached (#617).

Phase B (#397) adds the **resolved class graph** (:func:`get_class_graph`), which
backs the ``subclasses`` edge: every class's facts plus its children bucketed
under each base's definition site. The **reverse import graph**
(:func:`get_import_graph`) backs ``imported_by`` the same way. It shares the name index's lifecycle
(:func:`invalidate`, :func:`generation`, layout keying), but its build resolves
bases with Jedi ``goto`` where the AST can't commit, so the analyzer supplies the
build and runs it on its own (Jedi worker) thread. It is keyed on scope as well,
because which modules' import tables are in the build decides which bases
resolve.

Thread-safety: a single module lock guards the cache dicts and provides
single-flight name-index builds, so concurrent first-callers (e.g. via
``asyncio.to_thread``) build the index once rather than racing. A class-graph
build is single-flight under its own per-key lock, so a long build never blocks
other projects' lookups.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pyeye import file_artifact_cache
from pyeye._module_sentinel import DefinitionSentinel
from pyeye.analyzers.base_resolution import extract_definitions
from pyeye.path_utils import path_to_key

#: A name-index: simple name -> all definition sites of that name in the project.
NameIndex = dict[str, list[DefinitionSentinel]]

# Guards _name_indices and serialises builds (single-flight). Module-global: the
# store is process-wide, mirroring file_artifact_cache's default singleton.
_lock = threading.Lock()
#: root -> layout key -> index. Keyed on the layout too (#618): module names are
#: baked in at build time and depend on the analyzer's source roots, sys.path,
#: packages and namespaces, so analyzers with different layouts on one root
#: must not share an index. Invalidating a root drops every layout under it.
_name_indices: dict[str, dict[str, NameIndex]] = {}
#: Same keys as ``_name_indices``: methods and class-body attributes by simple
#: name (#508).  Built in the same pass and dropped together, so the two never
#: disagree about which files they cover.
_member_indices: dict[str, dict[str, NameIndex]] = {}
#: Same keys again: the files the index build couldn't parse, POSIX-sorted (#729).
#: A definition there is invisible to bare-name ``resolve``, so a miss says so.
_index_unparseable: dict[str, dict[str, tuple[str, ...]]] = {}

#: What one index build produces: names, members, unparseable files.
_Indices = tuple[NameIndex, NameIndex, tuple[str, ...]]

#: A project's invalidation count, plus a store-wide epoch bumped by a full clear.
#: ``get_name_index`` stores a build only if neither moved since the caller read
#: its file list: invalidation runs on the watcher thread (#617), so a change can
#: land between listing the files and storing the index built from them.
Generation = tuple[int, int]
_generations: dict[str, int] = {}
_epoch = 0


@dataclass(frozen=True)
class ClassFact:
    """Where one project class is defined: the facts a ``subclasses`` stub needs."""

    name: str
    file: Path
    line: int
    end_line: int
    column: int


@dataclass(frozen=True)
class ClassGraph:
    """A project's resolved class graph for one layout and scope (#397).

    Only strings and ints, never AST nodes or Jedi/parso objects, so a cached
    graph pins neither the AST LRU nor parso's parse cache (#713). Treat every
    field as read-only: the graph is shared by every query in its generation.

    Attributes:
        classes: Every class's dotted name -> its :class:`ClassFact`.
        children_by_key: A base's definition-site key -> the classes that
            directly subclass it.
        import_tables: Per-module AST import tables, used to key a query target
            the same way bases were keyed (:func:`base_resolution.resolve_base`).
        module_defines: Per-module top-level definitions, for the same.
        star_sources: Per-module ``import *`` sources, for the same.
    """

    classes: dict[str, ClassFact]
    children_by_key: dict[str, frozenset[str]]
    import_tables: dict[str, dict[str, str]]
    module_defines: dict[str, dict[str, str]]
    star_sources: dict[str, list[str]]
    #: Files in scope the server's interpreter couldn't parse, POSIX-sorted (#729).
    #: A subclass defined there is unknown, never silently absent.
    unparseable: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportGraph:
    """A project's reverse import graph for one layout and scope (#397).

    The inversion of ``JediAnalyzer.find_importers``' AST match: a module ``T``
    is imported by a file when the file has ``import T`` / ``import T.x`` (every
    dotted prefix of an ``import`` is registered), a ``from`` clause resolving
    to ``T`` or below it (every prefix of the resolved clause), or
    ``from <pkg> import <name>`` with ``<pkg>.<name> == T`` (#436). Imports
    anywhere in the file count, function bodies included (#619).

    Attributes:
        importers: A dotted module name -> its importers as ``(importer module
            or None, importer file)``, one entry per file, in POSIX-sorted file
            order. ``None`` is an importer with no module name (#668); only its
            absolute imports are registered.
    """

    importers: dict[str, tuple[tuple[str | None, Path], ...]]
    #: Files in scope the server's interpreter couldn't parse, POSIX-sorted (#729).
    #: An importer there is unknown, never silently absent.
    unparseable: tuple[str, ...] = ()


#: The cached graphs: root -> (graph kind, layout key, scope key) -> graph.
_graphs: dict[str, dict[tuple[str, str, str], object]] = {}
#: (root, graph kind, layout key, scope key) -> the lock that makes that build single-flight.
_graph_locks: dict[tuple[str, str, str, str], threading.Lock] = {}


def _normalize(project_key: str) -> str:
    """Canonical store key for a project root: resolved, then posix.

    The store is reached from two layers that spell the same root differently:
    the analyzer **builds** under its *unresolved* ``project_path`` while the
    project manager **evicts** under the ``.resolve()``d path it keys its own
    caches by. Canonicalising here, in one place, makes those agree by
    construction — otherwise a symlinked or relative root (e.g. macOS
    ``/var`` -> ``/private/var``) builds under one key and is evicted under
    another, so the non-evicting index silently leaks (#457).

    Args:
        project_key: A project root path in any spelling.

    Returns:
        The resolved, posix-form key (lexical posix form if resolution fails).
    """
    try:
        return path_to_key(project_key)
    except OSError:
        return Path(project_key).as_posix()


def _should_index(
    definition: DefinitionSentinel,
    kindmap: dict[str, str],
    module_name: str | None,
) -> bool:
    """Return True if *definition* belongs in the name index.

    Indexed: direct module members (top-level classes, functions, statements)
    plus **nested classes** (a class enclosed directly by another class) so
    dotted paths like ``Outer.Inner.method`` can resolve their parent. Excluded:
    methods, class attributes, and anything inside a function — these are reached
    via the parent at lookup time, not by bare name.

    Args:
        definition: The candidate definition.
        kindmap: ``full_name -> type`` for every definition in the same module.
        module_name: The module's dotted name, or ``None``.

    Returns:
        True if the definition should be a name-index entry.
    """
    full = definition.full_name
    if "." not in full:
        return True  # bare top-level name (module_name unknown)
    parent_full = full.rsplit(".", 1)[0]
    if parent_full == module_name:
        return True  # direct module member
    # Nested: keep only classes enclosed directly by another class.
    return definition.type == "class" and kindmap.get(parent_full) == "class"


def _is_bare_name_member(
    definition: DefinitionSentinel,
    kindmap: dict[str, str],
    module_name: str | None,
) -> bool:
    """Whether *definition* is a method or class-body attribute for rule 4 (#508).

    These are what :func:`_should_index` leaves out of the name index although
    they are addressable (``Class.method``): definitions directly in a class
    body.  Nested classes are already indexed; function locals are never
    offered.  Dunder names (``__init__``, ``__eq__``) are excluded: every class
    defines them, so a bare dunder never names one thing.
    """
    if _should_index(definition, kindmap, module_name):
        return False
    name = definition.name
    if name.startswith("__") and name.endswith("__"):
        return False
    parent_full = definition.full_name.rsplit(".", 1)[0]
    return kindmap.get(parent_full) == "class"


def build_name_index(py_files: list[Path], file_to_module: dict[Path, str | None]) -> NameIndex:
    """Build a name->definitions index from *py_files* (pure, uncached).

    Streams each file's AST via ``file_artifact_cache.get_ast`` and extracts its
    definition sites; a file that cannot be read or parsed is skipped rather than
    failing the whole build. Definitions for each name are sorted by
    ``(posix path, line, column)`` for deterministic ordering.

    Args:
        py_files: The whole-project set of ``.py`` files to index.
        file_to_module: Map from each file to its dotted module name (the
            namespace-prefixed name where applicable); a missing/``None`` entry
            yields bare ``full_name``s.

    Returns:
        The freshly built :data:`NameIndex`.
    """
    return _build_indices(py_files, file_to_module)[0]


def _build_indices(py_files: list[Path], file_to_module: dict[Path, str | None]) -> _Indices:
    """Build the name index, the member index (#508) and the unparseable list (#729) in one pass."""
    index: NameIndex = {}
    members: NameIndex = {}
    unparseable: list[str] = []
    for path in py_files:
        try:
            tree = file_artifact_cache.get_ast(path)
        except SyntaxError:
            unparseable.append(path_to_key(path))  # disclosed, never silently dropped
            continue
        except (OSError, ValueError):
            continue
        module_name = file_to_module.get(path)
        # One module entry per file; for an __init__.py this is the regular
        # package itself (module_name is the package's dotted name).
        if module_name:
            index.setdefault(module_name.rsplit(".", 1)[-1], []).append(
                DefinitionSentinel(
                    module_path=path,
                    full_name=module_name,
                    kind="module",
                    line=1,
                    column=0,
                )
            )
        # Index modules, top-level defs, and nested classes; methods, class
        # attributes, and locals are excluded (reached via the parent at lookup).
        defs = extract_definitions(tree, module_name, path)
        kindmap = {d.full_name: d.type for d in defs}
        for definition in defs:
            if _should_index(definition, kindmap, module_name):
                index.setdefault(definition.name, []).append(definition)
            elif _is_bare_name_member(definition, kindmap, module_name):
                members.setdefault(definition.name, []).append(definition)

    for definitions in (*index.values(), *members.values()):
        definitions.sort(
            key=lambda d: (
                d.module_path.as_posix() if d.module_path else "",
                d.line,
                d.column,
            )
        )
    return index, members, tuple(sorted(unparseable))


def generation(project_key: str) -> Generation:
    """Snapshot *project_key*'s invalidation generation, to pass to :func:`get_name_index`.

    Take it **before** listing the files the index will be built from.
    """
    key = _normalize(project_key)
    with _lock:
        return (_epoch, _generations.get(key, 0))


def get_name_index(
    project_key: str,
    py_files: list[Path],
    file_to_module: dict[Path, str | None],
    generation: Generation | None = None,
    *,
    layout_key: str = "",
) -> NameIndex:
    """Return the cached whole-project name-index, building it on first use.

    Build-once per project: subsequent calls return the same cached object until
    :func:`invalidate` drops it. Building is single-flight under the module lock,
    so concurrent first-callers do not double-build.

    Args:
        project_key: Stable identity for the project (its root path in any
            spelling; canonicalised via :func:`_normalize`). The cache key —
            must NOT encode scope.
        py_files: The whole-project set of ``.py`` files (union of all scope
            paths); used only when a build is needed.
        file_to_module: Map from each file to its dotted module name.
        generation: The :func:`generation` taken before *py_files* was read. If
            the project was invalidated since, the index is built and returned
            but not cached, because it may predate the change.
        layout_key: The analyzer's :func:`pyeye.project_layout.layout_key`.
            Analyzers with different layouts on one root get separate indices.

    Returns:
        The cached :data:`NameIndex` for *project_key*.
    """
    return _get_indices(project_key, py_files, file_to_module, generation, layout_key)[0]


def get_member_index(
    project_key: str,
    py_files: list[Path],
    file_to_module: dict[Path, str | None],
    generation: Generation | None = None,
    *,
    layout_key: str = "",
) -> NameIndex:
    """Return the cached member index (#508): methods and class attributes by name.

    Same arguments, caching and invalidation as :func:`get_name_index`; both
    are built in one pass.  Dunder names are not in it.
    """
    return _get_indices(project_key, py_files, file_to_module, generation, layout_key)[1]


def get_index_unparseable(
    project_key: str,
    py_files: list[Path],
    file_to_module: dict[Path, str | None],
    generation: Generation | None = None,
    *,
    layout_key: str = "",
) -> tuple[str, ...]:
    """The files the index build couldn't parse, POSIX-sorted (#729).

    Same arguments, caching and invalidation as :func:`get_name_index`; built
    in the same pass.
    """
    return _get_indices(project_key, py_files, file_to_module, generation, layout_key)[2]


def _get_indices(
    project_key: str,
    py_files: list[Path],
    file_to_module: dict[Path, str | None],
    generation: Generation | None,
    layout_key: str,
) -> _Indices:
    key = _normalize(project_key)
    cached = _cached(key, layout_key)
    if cached is not None:
        return cached
    with _lock:
        cached = _cached(key, layout_key)  # double-checked under lock
        if cached is not None:
            return cached
        built = _build_indices(py_files, file_to_module)
        if generation is None or generation == (_epoch, _generations.get(key, 0)):
            _name_indices.setdefault(key, {})[layout_key] = built[0]
            _member_indices.setdefault(key, {})[layout_key] = built[1]
            _index_unparseable.setdefault(key, {})[layout_key] = built[2]
        return built


def _cached(key: str, layout_key: str) -> _Indices | None:
    index = _name_indices.get(key, {}).get(layout_key)
    members = _member_indices.get(key, {}).get(layout_key)
    unparseable = _index_unparseable.get(key, {}).get(layout_key)
    if index is None or members is None or unparseable is None:
        return None
    return index, members, unparseable


def _get_graph(
    kind: str,
    project_key: str,
    build: Callable[[], object],
    generation: Generation | None,
    layout_key: str,
    scope_key: str,
) -> object:
    """Return the cached *kind* graph, building it with *build* on first use.

    The shared lifecycle of every project graph (#397): one build per project,
    layout and scope per generation; dropped by :func:`invalidate` and then
    rebuilt, never reported empty; single-flight under a per-key lock rather
    than the store lock, so a long build never blocks other lookups; a build
    that raced an invalidation is returned but not cached (#617).
    """
    key = _normalize(project_key)
    sub = (kind, layout_key, scope_key)
    cached = _graphs.get(key, {}).get(sub)
    if cached is not None:
        return cached
    with _lock:
        build_lock = _graph_locks.setdefault((key, *sub), threading.Lock())
    with build_lock:
        cached = _graphs.get(key, {}).get(sub)  # built while we waited
        if cached is not None:
            return cached
        graph = build()
        with _lock:
            if generation is None or generation == (_epoch, _generations.get(key, 0)):
                _graphs.setdefault(key, {})[sub] = graph
        return graph


def get_class_graph(
    project_key: str,
    build: Callable[[], ClassGraph],
    generation: Generation | None = None,
    *,
    layout_key: str = "",
    scope_key: str = "",
) -> ClassGraph:
    """Return the cached class graph, building it with *build* on first use (#397).

    *build* runs on the calling thread: it may call Jedi, which must stay on the
    Jedi worker.

    Args:
        project_key: The project root, in any spelling (see :func:`_normalize`).
        build: Builds the graph from the project's current files.
        generation: The :func:`generation` taken before *build*'s files were
            listed. If the project was invalidated since, the graph is returned
            but not cached, because it may predate the change (#617).
        layout_key: The analyzer's :func:`pyeye.project_layout.layout_key` (#618).
        scope_key: The search scope the graph was built over.

    Returns:
        The class graph for that project, layout and scope.
    """
    graph = _get_graph("class", project_key, build, generation, layout_key, scope_key)
    return cast(ClassGraph, graph)


def get_import_graph(
    project_key: str,
    build: Callable[[], ImportGraph],
    generation: Generation | None = None,
    *,
    layout_key: str = "",
    scope_key: str = "",
) -> ImportGraph:
    """Return the cached reverse import graph, building it on first use (#397).

    Same key and lifecycle as :func:`get_class_graph`; see it for the arguments.

    Returns:
        The import graph for that project, layout and scope.
    """
    graph = _get_graph("import", project_key, build, generation, layout_key, scope_key)
    return cast(ImportGraph, graph)


def invalidate(project_key: str | None = None) -> None:
    """Drop cached graph artifacts so the next lookup rebuilds.

    Wired into the file-change watcher path and project eviction. Whole-index
    invalidation is intentional: rebuilds are parse-bound and cheap relative to
    the correctness cost of a stale or partial index. It drops the name and
    member indices and every class and import graph (#397) of the project.

    Args:
        project_key: The project to drop; ``None`` clears all projects.
    """
    global _epoch
    with _lock:
        if project_key is None:
            _name_indices.clear()
            _member_indices.clear()
            _index_unparseable.clear()
            _graphs.clear()
            _epoch += 1
        else:
            key = _normalize(project_key)
            _name_indices.pop(key, None)
            _member_indices.pop(key, None)
            _index_unparseable.pop(key, None)
            _graphs.pop(key, None)
            _generations[key] = _generations.get(key, 0) + 1
