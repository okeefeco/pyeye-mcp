"""Per-project, non-evicting, invalidate-and-rebuild store of AST graph artifacts.

Phase A (#457) hosts the **name->definitions index** here: a whole-project map
from a simple name to *every* definition site of that name, built once by
streaming each project ``.py`` through :func:`pyeye.file_artifact_cache.get_ast`
and :func:`pyeye.analyzers.base_resolution.extract_definitions`. The index holds
only compact :class:`~pyeye._module_sentinel.DefinitionSentinel` metadata and is
kept **out** of the ``file_artifact_cache`` LRU, so completeness can never depend
on the AST cache size — an evictable index would silently drop definitions and
reincarnate #457.

The store is keyed purely by *project identity* and built **whole-project** (the
union of all scope paths); scope narrowing happens at lookup time in the caller,
never at build time (baking scope into a project-keyed cache poisons it). Cache
mechanism is plain invalidate-and-rebuild (no generation counter): a file change
or project eviction clears the project's entry and the next lookup rebuilds.

Phase B (#397) will add ``get_class_graph`` / ``get_import_graph`` to this same
store and build pass; that work ships separately.

Thread-safety: a single module lock guards the cache dict and provides
single-flight builds, so concurrent first-callers (e.g. via
``asyncio.to_thread``) build the index once rather than racing.
"""

from __future__ import annotations

import threading
from pathlib import Path

from pyeye import file_artifact_cache
from pyeye._module_sentinel import DefinitionSentinel
from pyeye.analyzers.base_resolution import extract_definitions

#: A name-index: simple name -> all definition sites of that name in the project.
NameIndex = dict[str, list[DefinitionSentinel]]

# Guards _name_indices and serialises builds (single-flight). Module-global: the
# store is process-wide, mirroring file_artifact_cache's default singleton.
_lock = threading.Lock()
_name_indices: dict[str, NameIndex] = {}


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
    index: NameIndex = {}
    for path in py_files:
        try:
            tree = file_artifact_cache.get_ast(path)
        except (OSError, SyntaxError, ValueError):
            continue
        for definition in extract_definitions(tree, file_to_module.get(path), path):
            index.setdefault(definition.name, []).append(definition)

    for definitions in index.values():
        definitions.sort(
            key=lambda d: (
                d.module_path.as_posix() if d.module_path else "",
                d.line,
                d.column,
            )
        )
    return index


def get_name_index(
    project_key: str,
    py_files: list[Path],
    file_to_module: dict[Path, str | None],
) -> NameIndex:
    """Return the cached whole-project name-index, building it on first use.

    Build-once per project: subsequent calls return the same cached object until
    :func:`invalidate` drops it. Building is single-flight under the module lock,
    so concurrent first-callers do not double-build.

    Args:
        project_key: Stable identity for the project (e.g. its root path as a
            string). The cache key — must NOT encode scope.
        py_files: The whole-project set of ``.py`` files (union of all scope
            paths); used only when a build is needed.
        file_to_module: Map from each file to its dotted module name.

    Returns:
        The cached :data:`NameIndex` for *project_key*.
    """
    cached = _name_indices.get(project_key)
    if cached is not None:
        return cached
    with _lock:
        cached = _name_indices.get(project_key)  # double-checked under lock
        if cached is not None:
            return cached
        index = build_name_index(py_files, file_to_module)
        _name_indices[project_key] = index
        return index


def invalidate(project_key: str | None = None) -> None:
    """Drop cached graph artifacts so the next lookup rebuilds.

    Wired into the file-change watcher path and project eviction. Whole-index
    invalidation is intentional: rebuilds are parse-bound and cheap relative to
    the correctness cost of a stale or partial index.

    Args:
        project_key: The project to drop; ``None`` clears all projects.
    """
    with _lock:
        if project_key is None:
            _name_indices.clear()
        else:
            _name_indices.pop(project_key, None)
