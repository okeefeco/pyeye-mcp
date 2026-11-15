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

import ast
import logging
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from pyeye import file_artifact_cache
from pyeye._module_scope import build_import_table
from pyeye.async_utils import filtered_rglob
from pyeye.handle import Handle
from pyeye.import_analyzer import resolve_relative_import
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

    # The walk follows EVERY binding, but only public ones are reported (#712):
    # a public re-export can be reached through an internal hop
    # (pkg/b.py defines X; pkg/a.py: from .b import X; pkg/__init__.py:
    # from .a import X -> pkg.X), so filtering the walk would lose it.
    while queue:
        current_target = queue.popleft()
        new_handles = await _scan_package_for_handle(current_target, package_root, analyzer)
        for h, public in new_handles:
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


async def _scan_package_for_handle(
    target_full_name: str, package_root: Path, analyzer: JediAnalyzer
) -> list[tuple[str, bool]]:
    """Scan all Python files under *package_root* for names with ``full_name == target_full_name``.

    Returns ``(module_path.symbol_name, is_public)`` for each match, excluding
    the target itself (the definition site). *is_public* is
    :func:`_is_public_binding`: only those are re-exports (#712), but the
    caller walks all of them.

    Args:
        target_full_name: The dotted name to search for in Jedi's ``full_name``.
        package_root: Root directory of the top-level package to scan.
        analyzer: The active ``JediAnalyzer`` instance.

    Returns:
        ``(dotted handle, is_public)`` pairs for every binding found.
    """
    results: list[tuple[str, bool]] = []

    # A file that can't be listed or read propagates (#704): skipping it would
    # return a re-export list that claims to be complete. ``re_exports`` has no
    # per-item incompleteness signal, so inspect leaves the field absent.
    # The shared project-scan rule (#517): a project that is itself a package
    # has its root here, which may hold nested worktrees or a .venv.
    py_files = sorted(filtered_rglob("*.py", package_root))

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
        tree = file_artifact_cache.get_ast(py_file)
        is_package = py_file.name == "__init__.py"
        table = build_import_table(tree, mod_path, resolve_relative_import, is_package)

        for surface, source in table.items():
            if source != target_full_name:
                continue
            re_export_handle = f"{mod_path}.{surface}"
            if re_export_handle != target_full_name:
                public = _is_public_binding(py_file, mod_path, surface, tree, table)
                results.append((re_export_handle, public))

    return results


def _is_private_module(module: str) -> bool:
    """Whether a dotted module name has a ``_``-prefixed part (dunders aren't private)."""
    return any(
        part.startswith("_") and not (part.startswith("__") and part.endswith("__"))
        for part in module.split(".")
    )


def _static_all(tree: ast.Module) -> set[str]:
    """The names in a module's ``__all__``, read statically (``=`` and ``+=`` of a literal).

    A dynamic ``__all__`` contributes nothing: it can't be read without running
    the module, so its names aren't claimed.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        value = node.value
        if isinstance(value, ast.List | ast.Tuple):
            names.update(
                e.value
                for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            )
    return names


def _is_public_binding(
    py_file: Path, module: str, binding: str, tree: ast.Module, table: dict[str, str]
) -> bool:
    """Whether binding *binding* in *module* (file *py_file*) is a re-export (#712).

    The user's definition, one of:

    1. *py_file* is a package ``__init__.py``;
    2. *binding* is listed in the module's ``__all__``;
    3. *module* is public (no ``_``-prefixed part) and imports *binding* from a
       module that is private (``pkg/api.py``: ``from ._impl import X``).

    A plain internal import between public modules is not a re-export: the
    ``imported_by`` edge reports it.
    """
    if py_file.name == "__init__.py":
        return True
    if binding in _static_all(tree):
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
