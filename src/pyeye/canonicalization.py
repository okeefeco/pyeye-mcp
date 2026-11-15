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
**Re-export collection strategy (BFS scan):** ``_collect_re_exports_impl``
uses a breadth-first scan of all Python files in the package directory.  For
each file, Jedi's ``get_names()`` is called; any name whose ``full_name``
matches the *current* target handle is recorded as a re-export.  The newly
discovered handles then become targets for the next BFS round.  A ``visited``
set prevents revisiting handles and guarantees termination even when the
package contains self-referential re-exports.

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
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from pyeye import file_artifact_cache
from pyeye.handle import Handle
from pyeye.project_layout import (
    file_for_module,
    module_name_for_file,
)

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
        Exception: An internal failure while scanning (#704). It propagates so
            the caller can leave ``re_exports`` absent (unknown); an empty list
            would claim "measured, none".
    """
    return await _collect_re_exports_impl(handle, analyzer)


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


async def _collect_re_exports_impl(handle: Handle, analyzer: JediAnalyzer) -> list[Handle]:
    """Core collection logic — may raise; callers catch.

    Uses a BFS scan of all Python files in the package tree.

    Algorithm
    ---------
    1.  Determine the *package root directory* — the top-level directory of
        the package that owns the canonical handle.
    2.  BFS loop: start with a queue = [canonical_handle_str].  For each
        item, scan all ``.py`` files under the package root using Jedi's
        ``get_names()``.  Any name whose ``full_name`` matches the current
        queue item, and whose computed module path differs from the canonical
        handle, is a re-export.
    3.  Newly found handles are added to the queue for transitive expansion.
    4.  The ``visited`` set prevents re-processing and guarantees termination.
    5.  Results are sorted lexicographically for deterministic ordering.

    Why BFS and not the old parent-walk?
    -------------------------------------
    The parent-walk approach only checked ``__init__.py`` files that are
    direct *ancestors* of the definition site in the module hierarchy.  It
    cannot discover re-exports in sibling packages (e.g. ``package.subpkg``
    re-exporting a symbol defined in ``package._impl``), nor aliased re-exports
    in arbitrary module files (e.g. ``package.legacy``).

    The BFS scan covers all files, so it finds all of these cases.  The cost
    is higher (multiple Jedi invocations per scan round), but remains bounded
    by the package size and BFS depth.
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

    # BFS expansion
    visited: set[str] = {handle_str}
    result: list[str] = []
    queue: deque[str] = deque([handle_str])

    while queue:
        current_target = queue.popleft()
        new_handles = await _scan_package_for_handle(current_target, package_root, analyzer)
        for h in new_handles:
            if h not in visited:
                visited.add(h)
                result.append(h)
                queue.append(h)

    # Return sorted for deterministic ordering
    try:
        return sorted(Handle(h) for h in result)
    except ValueError as exc:
        logger.debug("collect_re_exports: invalid handle in results: %s", exc)
        return [Handle(h) for h in result if _is_valid_handle(h)]


async def _scan_package_for_handle(
    target_full_name: str, package_root: Path, analyzer: JediAnalyzer
) -> list[str]:
    """Scan all Python files under *package_root* for names with ``full_name == target_full_name``.

    Returns a list of module-qualified dotted names (``module_path.symbol_name``)
    for each match, excluding the target itself (the definition site).

    Args:
        target_full_name: The dotted name to search for in Jedi's ``full_name``.
        package_root: Root directory of the top-level package to scan.
        analyzer: The active ``JediAnalyzer`` instance.

    Returns:
        List of dotted handle strings for re-exporting names found.
    """
    results: list[str] = []

    # A file that can't be listed or read propagates (#704): skipping it would
    # return a re-export list that claims to be complete. ``re_exports`` has no
    # per-item incompleteness signal, so inspect leaves the field absent.
    py_files = sorted(package_root.rglob("*.py"))

    for py_file in py_files:
        script = file_artifact_cache.get_script(py_file, analyzer.project)
        names = script.get_names(all_scopes=False)

        for name in names:
            if name.full_name != target_full_name:
                continue

            # Derive the module dotted path for this file (one mapper, #625:
            # additional-package and root-package files are named too).
            mod_path = module_name_for_file(analyzer, py_file)
            if mod_path is None:
                continue

            # Build the re-export handle: module_path.symbol_name
            re_export_handle = f"{mod_path}.{name.name}"
            if re_export_handle != target_full_name:
                results.append(re_export_handle)

    return results


def _is_valid_handle(value: str) -> bool:
    """Return True if *value* is a valid dotted Python name (for Handle construction)."""
    try:
        Handle(value)
        return True
    except ValueError:
        return False
