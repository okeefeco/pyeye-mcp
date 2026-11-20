"""Re-export collection and module-file lookup for PyEye handles.

Resolving a handle to its definition is :mod:`pyeye.resolver`'s job (#623);
the former ``resolve_canonical`` chain walk was folded into it and deleted in
#623 slice 5.

Public API
----------
collect_re_exports(handle, analyzer) -> list[Handle]
    Given a canonical handle, return all dotted-name paths that bind to the
    same object via re-exports in any ``__init__.py`` or module file in the
    package tree.  Returns an empty list when no public paths are found.
    Never raises.

find_module_file(module_dotted, analyzer) -> Path | None
    Convert a dotted module path to its ``__init__.py`` or ``module.py``
    on disk (a delegate of :func:`pyeye.project_layout.file_for_module`).

Design notes
------------
**Re-export collection strategy (BFS over one import index):**
``_collect_re_exports_impl`` parses each Python file in the package directory
once and indexes its AST import table by source (``_build_binding_index``,
#712, #795).  A breadth-first walk over that index then records every binding
whose source is the *current* target; the newly discovered handles become
targets for the next round.  A ``visited`` set prevents revisiting handles and
guarantees termination even when the package contains self-referential
re-exports.  The cost is one parse per file per scan, whatever the depth.

Results are sorted lexicographically for deterministic ordering.

**``__all__`` handling:** Symbols listed in ``__all__`` are "public" by
convention, but Jedi's ``get_names()`` returns all top-level names regardless.
Re-exports NOT in ``__all__`` are still collected.

**Conditional imports (``if TYPE_CHECKING:``, ``try:/except ImportError:``):**
Jedi sees these statically and follows them like normal imports.
Conservative behavior: return whatever Jedi sees.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pyeye import file_artifact_cache
from pyeye._module_scope import build_import_table
from pyeye.async_utils import filtered_rglob
from pyeye.handle import Handle
from pyeye.import_analyzer import resolve_relative_import
from pyeye.path_utils import path_to_key
from pyeye.project_layout import (
    file_for_module,
    layout_key,
    module_name_for_file,
)
from pyeye.star_exports import bound_names, build_star_sources, star_exported_from, static_all

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)


async def collect_re_exports(handle: Handle, analyzer: JediAnalyzer) -> list[Handle]:
    """Return all public dotted paths that bind to the same object as *handle*.

    Uses a BFS scan of all Python files in the package hierarchy.  Follows
    transitive re-exports (e.g., if A re-exports B which re-exports the symbol,
    both A and B are included).  The canonical handle itself is not included.

    Args:
        handle: Canonical handle (definition-site dotted name).
        analyzer: A configured ``JediAnalyzer`` instance pointing at the
            project that contains the symbol.

    Returns:
        A sorted list of :class:`~pyeye.handle.Handle` objects representing
        public import paths.  The canonical handle itself is *not* included.
        Returns an empty list when no re-exports are found.

    Raises:
        Exception: An internal failure while scanning (#704), or
            :class:`UnparseableReExportScan` when a file in the package couldn't
            be parsed. Either propagates so the caller can leave ``re_exports``
            absent (unknown); an empty list would claim "measured, none". The
            ``re_exports`` edge (#393) uses :func:`re_export_scan` instead, which
            lists such files and keeps the rest.
    """
    scan = await re_export_scan(handle, analyzer)
    if scan.unparseable_files:
        raise UnparseableReExportScan(scan.unparseable_files)
    return [Handle(p) for p in scan.paths]


class UnparseableReExportScan(Exception):
    """Some files in the package couldn't be parsed, so the re-export list is incomplete."""

    def __init__(self, files: tuple[str, ...]) -> None:
        """Record the files (POSIX paths) that failed to parse."""
        super().__init__(f"re-export scan could not parse {len(files)} file(s): {list(files)}")
        self.files = files


@dataclass(frozen=True)
class ReExportScan:
    """One symbol's public re-export paths, and the files the scan couldn't parse."""

    #: Public dotted paths that bind the symbol (#712), sorted; not the handle itself.
    paths: tuple[str, ...]
    #: POSIX paths (``path_to_key``) of files that failed to parse, sorted (#729 shape).
    unparseable_files: tuple[str, ...]


# The shared re-export cache (#393): inspect's re_exports field and the
# re_exports edge read the same scan. Keyed on the project, its effective
# layout (#618: module names depend on it) and the handle. The watcher drops a
# project's entries (ProjectManager._on_files_changed), as configure_packages
# does. Locked like the TypeRef cache: the watcher thread invalidates while
# analysis reads, and the lock is never held across an await.
_ReExportKey = tuple[str, str, str]
_RE_EXPORT_CACHE_MAX = 4096
_re_export_cache: OrderedDict[_ReExportKey, ReExportScan] = OrderedDict()
_re_export_lock = threading.Lock()


def _re_export_key(handle: Handle, analyzer: JediAnalyzer) -> _ReExportKey:
    return (path_to_key(analyzer.project_path), layout_key(analyzer), str(handle))


async def re_export_scan(handle: Handle, analyzer: JediAnalyzer) -> ReExportScan:
    """The (cached) re-export scan for *handle*: public paths plus unparseable files.

    A file that fails to parse is listed and skipped, so the paths found in the
    other files are still returned. Any other failure propagates and is not
    cached (#704).
    """
    key = _re_export_key(handle, analyzer)
    with _re_export_lock:
        cached = _re_export_cache.get(key)
        if cached is not None:
            _re_export_cache.move_to_end(key)
            return cached
    unparseable: list[str] = []
    paths = await _collect_re_exports_impl(handle, analyzer, unparseable)
    scan = ReExportScan(
        paths=tuple(sorted(str(p) for p in paths)),
        unparseable_files=tuple(sorted(set(unparseable))),
    )
    with _re_export_lock:
        _re_export_cache[key] = scan
        while len(_re_export_cache) > _RE_EXPORT_CACHE_MAX:
            _re_export_cache.popitem(last=False)
    return scan


def invalidate_re_exports(root: Path | str | None = None) -> None:
    """Drop the cached re-export scans and binding indexes of the project at *root*, or all."""
    global _index_epoch
    with _re_export_lock:
        # A build that overlaps this won't be stored (#803). Per project: a
        # watcher batch for one project must not discard another's builds.
        if root is None:
            _index_epoch += 1  # stales every in-flight build, so the counters can go
            _index_generations.clear()
            _re_export_cache.clear()
            _binding_index_cache.clear()
            return
        key = path_to_key(root)
        _index_generations[key] = _index_generations.get(key, 0) + 1
        for cached in [k for k in _re_export_cache if k[0] == key]:
            del _re_export_cache[cached]
        for indexed in [k for k in _binding_index_cache if k[0] == key]:
            del _binding_index_cache[indexed]


@dataclass(frozen=True)
class _CachedIndex:
    """One package's binding index and the files it couldn't parse (#803)."""

    index: _BindingIndex
    #: POSIX paths of the files that failed to parse while building it.
    unparseable: tuple[str, ...]


# The binding index, cached per package (#803). #393's cache above is keyed by
# handle, so before this every NEW handle rebuilt its package's whole index
# (django: 907 files per inspect, 13-15 s cold). Keyed on the project, its
# layout and the package root; cleared with the scans by invalidate_re_exports
# (the watcher, configure_packages). It holds compact (source -> bindings)
# facts, never ASTs. Under _re_export_lock, never held across an await; each
# key's build is serialised by its own lock, so concurrent first calls share
# one build. A build that overlaps an invalidation of ITS project (that
# project's generation, or the global epoch, moved) is returned to its caller
# but not stored, so no pre-edit index is kept. Other projects' invalidations
# don't touch it, or steady watcher traffic elsewhere would keep it empty.
_IndexKey = tuple[str, str, str]
_BINDING_INDEX_CACHE_MAX = 32
_binding_index_cache: OrderedDict[_IndexKey, _CachedIndex] = OrderedDict()
_index_build_locks: dict[_IndexKey, threading.Lock] = {}
_index_generations: dict[str, int] = {}
_index_epoch = 0


def _package_binding_index(package_root: Path, analyzer: JediAnalyzer) -> _CachedIndex:
    """*package_root*'s binding index, built once and cached (#803).

    Synchronous on purpose: no await between the check and the store, so two
    coroutines on the worker loop can't interleave mid-build. Any failure other
    than a parse error propagates and nothing is cached (#704).
    """
    key = (path_to_key(analyzer.project_path), layout_key(analyzer), path_to_key(package_root))
    with _re_export_lock:
        cached = _binding_index_cache.get(key)
        if cached is not None:
            _binding_index_cache.move_to_end(key)
            return cached
        build_lock = _index_build_locks.setdefault(key, threading.Lock())
    with build_lock:
        with _re_export_lock:
            cached = _binding_index_cache.get(key)  # built while we waited
            if cached is not None:
                return cached
            generation = (_index_epoch, _index_generations.get(key[0], 0))
        unparseable: list[str] = []
        built = _CachedIndex(
            index=_build_binding_index(package_root, analyzer, unparseable),
            unparseable=tuple(sorted(set(unparseable))),
        )
        with _re_export_lock:
            if generation == (_index_epoch, _index_generations.get(key[0], 0)):
                _binding_index_cache[key] = built
                while len(_binding_index_cache) > _BINDING_INDEX_CACHE_MAX:
                    _binding_index_cache.popitem(last=False)
            _index_build_locks.pop(key, None)
    return built


# ---------------------------------------------------------------------------
# Implementation helpers
# ---------------------------------------------------------------------------


def find_module_file(module_dotted: str, analyzer: JediAnalyzer) -> Path | None:
    """Convert a dotted module path to its ``__init__.py`` or ``module.py``.

    Delegates to :func:`pyeye.project_layout.file_for_module`, the one
    module → file mapper (#625), which also handles a project that is itself a
    package. Returns ``None`` if not found.
    """
    return file_for_module(analyzer, module_dotted)


async def _collect_re_exports_impl(
    handle: Handle, analyzer: JediAnalyzer, unparseable: list[str] | None = None
) -> list[Handle]:
    """Core collection logic — may raise; callers catch.

    Uses a BFS scan of all Python files in the package tree.

    Algorithm
    ---------
    1.  Determine the *package root directory* — the top-level directory of
        the package that owns the canonical handle.
    2.  Index every ``.py`` file under the package root once: each
        module-scope import binding, keyed by its source (#795).
    3.  BFS loop: start with a queue = [canonical_handle_str].  For each
        item, every indexed binding whose source is the current queue item is
        a hop; the public ones are re-exports (#712).
    4.  Newly found handles are added to the queue for transitive expansion.
    5.  The ``visited`` set prevents re-processing and guarantees termination.
    6.  Results are sorted lexicographically for deterministic ordering.

    Why BFS and not the old parent-walk?
    -------------------------------------
    The parent-walk approach only checked ``__init__.py`` files that are
    direct *ancestors* of the definition site in the module hierarchy.  It
    cannot discover re-exports in sibling packages (e.g. ``package.subpkg``
    re-exporting a symbol defined in ``package._impl``), nor aliased re-exports
    in arbitrary module files (e.g. ``package.legacy``).

    The scan covers all files, so it finds all of these cases.  It parses
    each file once per scan, however many hops the walk takes (#795).
    """
    handle_str = str(handle)
    parts = handle_str.split(".")
    if len(parts) < 2:
        # Top-level name — no enclosing package to re-export it
        return []

    # Determine the package root directory to scan.
    # The top-level package name is parts[0]; its directory is found via
    # find_module_file with just that package name.
    top_package = parts[0]
    top_init = find_module_file(top_package, analyzer)
    if top_init is None:
        return []

    # The package root is the directory containing the top-level __init__.py
    package_root = top_init.parent

    # One pass over the package builds every file's import table (#795): the
    # BFS below then walks that index in memory. Scanning the package once per
    # hop cost hops x files parses (django.apps.apps: ~66 hops x 907 files).
    # Cached per package (#803): every handle in the package shares one build.
    cached = _package_binding_index(package_root, analyzer)
    if cached.unparseable:
        if unparseable is None:
            # Strict mode (#704): raise the real parse error, as the uncached
            # build did. get_ast doesn't cache a failure, so this re-raises it.
            for bad in cached.unparseable:
                file_artifact_cache.get_ast(Path(bad))
        else:
            unparseable.extend(cached.unparseable)
    index = cached.index

    # BFS expansion
    visited: set[str] = {handle_str}
    result: list[str] = []
    queue: deque[str] = deque([handle_str])

    # The walk follows EVERY binding, but only public ones are reported (#712):
    # a public re-export can be reached through an internal hop
    # (pkg/b.py defines X; pkg/a.py: from .b import X; pkg/__init__.py:
    # from .a import X -> pkg.X), so filtering the walk would lose it.
    while queue:
        current_target = queue.popleft()
        for h, public in index.get(current_target, ()):
            if h == current_target:
                continue
            if h not in visited:
                visited.add(h)
                if public:
                    result.append(h)
                queue.append(h)

    # Return sorted for deterministic ordering
    try:
        return sorted(Handle(h) for h in result)
    except ValueError as exc:
        logger.debug("collect_re_exports: invalid handle in results: %s", exc)
        return [Handle(h) for h in result if _is_valid_handle(h)]


#: source dotted name -> ``(binding handle, is_public)`` for every module-scope
#: import binding in a package, in file order then table order.
_BindingIndex = dict[str, list[tuple[str, bool]]]


@dataclass(frozen=True)
class _ModuleBindings:
    """One module's statically read bindings, for :func:`_build_binding_index`."""

    py_file: Path
    table: dict[str, str]  # explicit binding -> its source (build_import_table)
    listed: frozenset[str] | None  # static __all__ (pyeye.star_exports.static_all)
    stars: list[str]  # ``from X import *`` sources, in source order
    bound: set[str]  # names bound other than by a star (pyeye.star_exports.bound_names)


def _star_bindings(modules: dict[str, _ModuleBindings]) -> dict[str, dict[str, str]]:
    """``module -> {name: f"{source}.{name}"}`` for the names its stars bind (#1010).

    The shared rule (:mod:`pyeye.star_exports`): a source exports its static
    ``__all__``, else its names not starting with ``_``, which include what the
    source's own stars bring in. As in ``resolve``, a name the module binds
    itself beats a star, and the first star source that exports a name wins.
    Only sources in *modules* (this package) are read; a star cycle ends.
    """
    received: dict[str, dict[str, str]] = {}
    in_progress: set[str] = set()

    def exports(module_name: str) -> frozenset[str] | set[str]:
        module = modules[module_name]
        if module.listed is not None:
            return module.listed
        names = module.bound | set(receive(module_name))
        return {name for name in names if star_exported_from(None, name)}

    def receive(module_name: str) -> dict[str, str]:
        if module_name in received:
            return received[module_name]
        if module_name in in_progress:
            return {}  # a star cycle: what's received so far is all there is
        in_progress.add(module_name)
        module = modules[module_name]
        got: dict[str, str] = {}
        for source in module.stars:
            if source not in modules or source == module_name:
                continue  # outside this package, or a self-star: not read
            for name in sorted(exports(source)):
                if name not in module.bound and name not in got:
                    got[name] = f"{source}.{name}"
        in_progress.discard(module_name)
        received[module_name] = got
        return got

    return {name: got for name in modules if (got := receive(name))}


def _build_binding_index(
    package_root: Path,
    analyzer: JediAnalyzer,
    unparseable: list[str] | None = None,
) -> _BindingIndex:
    """Index every module-scope import binding under *package_root* by its source.

    Each file is parsed once and its import table built once (#795). An entry
    ``source -> [(f"{module}.{surface}", is_public), ...]`` records that
    *module* binds *surface* from *source*; *is_public* is
    :func:`_is_public_binding` (#712).

    Args:
        package_root: Root directory of the top-level package to scan.
        analyzer: The active ``JediAnalyzer`` instance.
        unparseable: When given, a file that fails to parse is appended to it
            (POSIX path) and skipped; otherwise the ``SyntaxError`` propagates.

    Returns:
        The index, possibly empty.
    """
    index: _BindingIndex = {}

    # A file that can't be listed or read propagates (#704): skipping it would
    # return a re-export list that claims to be complete. ``re_exports`` has no
    # per-item incompleteness signal, so inspect leaves the field absent.
    # The shared project-scan rule (#517): a project that is itself a package
    # has its root here, which may hold nested worktrees or a .venv.
    py_files = sorted(filtered_rglob("*.py", package_root))

    # In file order; two files can map to one module name, and both are indexed.
    modules: list[tuple[str, _ModuleBindings]] = []
    for py_file in py_files:
        # Derive the module dotted path for this file (one mapper, #625:
        # additional-package and root-package files are named too).
        mod_path = module_name_for_file(analyzer, py_file)
        if mod_path is None:
            continue
        # Each module-scope binding's immediate source, from the shared AST
        # import table (relative imports resolved, aliases under their alias).
        # Jedi's full_name followed only ABSOLUTE imports: a package __init__'s
        # ``from .core import X`` came back as ``pkg.X`` and was never matched
        # (#712).
        try:
            tree = file_artifact_cache.get_ast(py_file)
        except SyntaxError:
            # Only a parse failure is "unparseable" (#703/#729). With a list,
            # record it and keep scanning; without one it propagates (#704).
            if unparseable is None:
                raise
            unparseable.append(path_to_key(py_file))
            continue
        is_package = py_file.name == "__init__.py"
        modules.append(
            (
                mod_path,
                _ModuleBindings(
                    py_file=py_file,
                    table=build_import_table(tree, mod_path, resolve_relative_import, is_package),
                    listed=static_all(tree),  # read once per file, not once per binding
                    stars=build_star_sources(tree, mod_path, resolve_relative_import, is_package),
                    bound=bound_names(tree),
                ),
            )
        )

    # Star sources are looked up by module name; the first file of a name wins.
    by_name: dict[str, _ModuleBindings] = {}
    for mod_path, module in modules:
        by_name.setdefault(mod_path, module)
    star_tables = _star_bindings(by_name)
    for mod_path, module in modules:
        # Explicit bindings first, then star ones (#1010): ``source.N`` for each
        # name N a ``from source import *`` binds in this module. A star never
        # binds a name the module binds itself, so the two don't overlap.
        table = dict(module.table)
        if by_name[mod_path] is module:
            for surface, source in star_tables.get(mod_path, {}).items():
                table.setdefault(surface, source)
        for surface, source in table.items():
            public = _is_public_binding(
                module.py_file, mod_path, surface, table, listed=module.listed
            )
            index.setdefault(source, []).append((f"{mod_path}.{surface}", public))

    return index


async def _scan_package_for_handle(
    target_full_name: str,
    package_root: Path,
    analyzer: JediAnalyzer,
    unparseable: list[str] | None = None,
) -> list[tuple[str, bool]]:
    """Every binding under *package_root* whose immediate source is *target_full_name*.

    One hop of the re-export walk, as ``(module_path.symbol_name, is_public)``
    pairs, excluding the target itself (the definition site). *is_public* is
    :func:`_is_public_binding`: only those are re-exports (#712), but the
    walk follows all of them. :func:`_collect_re_exports_impl` builds the
    index once and walks it (#795); this reads one hop from a fresh index.

    Args:
        target_full_name: The dotted name a binding's source must equal.
        package_root: Root directory of the top-level package to scan.
        analyzer: The active ``JediAnalyzer`` instance.
        unparseable: As for :func:`_build_binding_index`.

    Returns:
        ``(dotted handle, is_public)`` pairs for every binding found.
    """
    index = _build_binding_index(package_root, analyzer, unparseable)
    return [(h, public) for h, public in index.get(target_full_name, ()) if h != target_full_name]


def _is_private_module(module: str) -> bool:
    """Whether a dotted module name has a ``_``-prefixed part (dunders aren't private)."""
    return any(
        part.startswith("_") and not (part.startswith("__") and part.endswith("__"))
        for part in module.split(".")
    )


def _is_public_binding(
    py_file: Path,
    module: str,
    binding: str,
    table: dict[str, str],
    *,
    listed: frozenset[str] | None = None,
) -> bool:
    """Whether binding *binding* in *module* (file *py_file*) is a re-export (#712).

    The user's definition, one of:

    1. *py_file* is a package ``__init__.py``;
    2. *binding* is listed in the module's ``__all__``;
    3. *module* is public (no ``_``-prefixed part) and imports *binding* from a
       module that is private (``pkg/api.py``: ``from ._impl import X``).

    A plain internal import between public modules is not a re-export: the
    ``imported_by`` edge reports it. *table* maps each binding to its source,
    star bindings included (#1010). *listed* is the module's static
    ``__all__`` (:func:`pyeye.star_exports.static_all`), already read by the
    caller; ``None`` when it has none, or a dynamic one that can't be read.
    """
    if py_file.name == "__init__.py":
        return True
    if listed is not None and binding in listed:
        return True
    if _is_private_module(module):
        return False
    source = table.get(binding)
    return source is not None and _is_private_module(source.rsplit(".", 1)[0])


def _is_valid_handle(value: str) -> bool:
    """Return True if *value* is a valid dotted Python name (for Handle construction)."""
    try:
        Handle(value)
        return True
    except ValueError:
        return False
