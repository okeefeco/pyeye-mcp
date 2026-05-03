"""Definition-site canonicalization for PyEye handles.

Given any dotted-name identifier that a user or tool might pass in, return the
*canonical handle* — the definition site — according to the rule:

    The canonical handle is where the object is **defined**, not where it is
    imported or re-exported.

For example, given any of::

    "package.Config"                    # re-exported via __init__.py (1+ hops)
    "package.subpkg.Config"             # intermediate re-export
    "package.legacy.LegacyConfig"       # aliased re-export
    "package._impl.config.Config"       # the actual definition file

all return ``Handle("package._impl.config.Config")``.

Public API
----------
resolve_canonical(identifier, analyzer) -> Handle | None
    Resolve any dotted-name form to its canonical handle, or return None if
    the identifier cannot be resolved.  Never raises.

collect_re_exports(handle, analyzer) -> list[Handle]
    Given a canonical handle, return all dotted-name paths that bind to the
    same object via re-exports in any ``__init__.py`` or module file in the
    package tree.  Returns an empty list when no public paths are found.
    Never raises.

Design notes — Jedi resolution behavior
-----------------------------------------
Jedi's ``Name.full_name`` via ``get_names()`` performs exactly ONE step of
import/alias resolution per call.  It does *not* follow multi-hop chains
automatically.  For example, ``package/__init__.py`` importing
``from package.subpkg import Config`` yields ``full_name='package.subpkg.Config'``
— not the final definition site.

**Resolution strategy (multi-hop walk):** ``_resolve_canonical_impl`` calls
``_get_full_name_from_file`` iteratively, following each ``full_name`` result
to its own module, until the result stabilises (i.e., ``full_name`` equals the
input) or the max-depth guard fires.  This is an explicit, verifiable chain walk
rather than relying on ``follow_imports=True`` in ``goto()`` (which has
inconsistent behaviour across import styles).

The chain walk is bounded by ``_MAX_RESOLUTION_DEPTH = 20`` iterations.  In
practice, real codebases rarely exceed 3–4 hops.  Cycles are detected by the
stabilisation check (``full_name == current_identifier``) — if Jedi follows a
cycle, the result will not change between iterations and the loop will exit.

**Re-export collection strategy (BFS scan):** ``_collect_re_exports_impl``
uses a breadth-first scan of all Python files in the package directory.  For
each file, Jedi's ``get_names()`` is called; any name whose ``full_name``
matches the *current* target handle is recorded as a re-export.  The newly
discovered handles then become targets for the next BFS round.  A ``visited``
set prevents revisiting handles and guarantees termination even when the
package contains self-referential re-exports.

Results are sorted lexicographically for deterministic ordering.

**Cycle detection:** The visited set in the BFS loop is the primary cycle
guard.  Because Jedi resolves ``full_name`` to the *definition* module (not to
the re-exporting __init__), the __init__.py's own binding appears as ``module.X``
not as ``package.X``, so the cycle test fires before infinite expansion.

**``__all__`` handling:** Symbols listed in ``__all__`` are "public" by
convention, but Jedi's ``get_names()`` returns all top-level names regardless.
Per the spec, re-exports NOT in ``__all__`` are still collected — a future
implementation may distinguish public vs private re-exports.

**Conditional imports (``if TYPE_CHECKING:``, ``try:/except ImportError:``):**
Jedi sees these statically and follows them like normal imports.  If a symbol
is only imported under ``TYPE_CHECKING``, Jedi may or may not include it in
``get_names()``.  Conservative behavior: return whatever Jedi sees.  See the
spec's "Edge-case handle resolution" section for details.
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from pyeye import file_artifact_cache
from pyeye.handle import Handle

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)

# Maximum number of resolution hops before giving up (cycle / deep-chain guard).
# Real codebases rarely exceed 3–4 hops; 20 is a generous safety bound.
_MAX_RESOLUTION_DEPTH: int = 20


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_canonical(identifier: str, analyzer: JediAnalyzer) -> Handle | None:
    """Resolve a dotted-name identifier to its canonical (definition-site) handle.

    Follows multi-hop import chains iteratively until the result stabilises.
    See module docstring for the Jedi behavior this relies on.

    Args:
        identifier: Any dotted Python name, e.g. ``"package.Config"`` or
            ``"package._impl.config.Config"``.
        analyzer: A configured ``JediAnalyzer`` instance pointing at the
            project that contains the identifier.

    Returns:
        The canonical :class:`~pyeye.handle.Handle` (definition site), or
        ``None`` if the identifier cannot be resolved.  Never raises.
    """
    try:
        return await _resolve_canonical_impl(identifier, analyzer)
    except Exception as exc:
        logger.debug("resolve_canonical(%r) failed: %s", identifier, exc)
        return None


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
        Returns an empty list when no re-exports are found.  Never raises.
    """
    try:
        return await _collect_re_exports_impl(handle, analyzer)
    except Exception as exc:
        logger.debug("collect_re_exports(%r) failed: %s", handle, exc)
        return []


# ---------------------------------------------------------------------------
# Implementation helpers
# ---------------------------------------------------------------------------


async def _resolve_canonical_impl(identifier: str, analyzer: JediAnalyzer) -> Handle | None:
    """Core resolution logic — may raise; callers catch.

    Implements an iterative chain walk: resolves the identifier once, then
    follows the result until it stabilises or the depth guard fires.
    """
    parts = identifier.split(".")
    if not parts:
        return None

    # The leaf component is the symbol name; everything before it is the
    # module path.
    symbol_name = parts[-1]
    module_dotted = ".".join(parts[:-1])

    if not symbol_name:
        return None

    # Convert the module dotted name to a file path, then ask Jedi for the
    # names defined in that file.  Jedi's full_name for each Name already
    # tracks to the definition site (one hop at a time).
    module_file = _find_module_file(module_dotted, analyzer) if module_dotted else None

    if module_dotted and module_file is None:
        # Module path not found — try the project search as a fallback
        return await _resolve_via_project_search(symbol_name, identifier, analyzer)

    full_name = await _get_full_name_from_file(module_file, symbol_name, analyzer)
    if full_name is None:
        return None

    # Multi-hop walk: follow full_name until it stabilises.
    # Each iteration resolves one more hop in the import chain.
    # The loop exits when:
    #   (a) full_name == current_identifier — we're at the definition site, OR
    #   (b) depth guard fires (prevents infinite loops / very deep chains).
    current_identifier = full_name
    for _ in range(_MAX_RESOLUTION_DEPTH):
        current_identifier = full_name

        # Parse current_identifier to find its module file
        hop_parts = current_identifier.split(".")
        hop_symbol = hop_parts[-1]
        hop_module = ".".join(hop_parts[:-1])

        if not hop_symbol:
            break

        hop_file = _find_module_file(hop_module, analyzer) if hop_module else None
        if hop_file is None:
            break

        next_full_name = await _get_full_name_from_file(hop_file, hop_symbol, analyzer)
        if next_full_name is None or next_full_name == current_identifier:
            # Stabilised (or definition not found in this file) — exit chain walk.
            # This is the sole stabilisation guard; no duplicate check needed.
            break

        full_name = next_full_name

    # Validate and wrap as Handle
    try:
        return Handle(full_name)
    except ValueError:
        logger.debug("Jedi returned invalid full_name %r for %r", full_name, identifier)
        return None


def _find_module_file(module_dotted: str, analyzer: JediAnalyzer) -> Path | None:
    """Convert a dotted module path to its ``__init__.py`` or ``module.py``.

    Checks source roots, project path, and any additional configured paths
    in the same order as ``JediAnalyzer._find_init_file``.

    Returns the resolved :class:`~pathlib.Path`, or ``None`` if not found.
    """
    path_parts = module_dotted.split(".")

    # Search roots in the same priority order the analyzer uses
    search_roots = list(getattr(analyzer, "source_roots", [])) + [analyzer.project_path]
    if hasattr(analyzer, "additional_paths"):
        search_roots.extend(analyzer.additional_paths)

    for base in search_roots:
        # Package: base/a/b/__init__.py
        pkg_init: Path = base.joinpath(*path_parts) / "__init__.py"
        if pkg_init.exists():
            return pkg_init

        # Module file: base/a/b.py  (last part is a .py, rest are directories)
        mod_file: Path = base.joinpath(*path_parts[:-1], path_parts[-1] + ".py")
        if mod_file.exists():
            return mod_file

    return None


async def _get_full_name_from_file(
    module_file: Path | None, symbol_name: str, analyzer: JediAnalyzer
) -> str | None:
    """Return Jedi's ``full_name`` for *symbol_name* defined or imported in *module_file*.

    Returns ``None`` when the symbol is absent or Jedi cannot resolve it.
    """
    if module_file is None:
        return None

    try:
        script = file_artifact_cache.get_script(module_file, analyzer.project)
        names = script.get_names(all_scopes=False)
        for name in names:
            if name.name == symbol_name and name.full_name:
                return str(name.full_name)
    except Exception as exc:
        logger.debug("_get_full_name_from_file(%r, %r) failed: %s", module_file, symbol_name, exc)

    return None


async def _resolve_via_project_search(
    symbol_name: str, original_identifier: str, analyzer: JediAnalyzer
) -> Handle | None:
    """Fallback: use Jedi project-level search when module file resolution fails.

    Searches for *symbol_name* and tries to find a result whose ``full_name``
    is consistent with (starts with the same root as) *original_identifier*.
    """
    try:
        results = await analyzer.find_symbol(symbol_name)
        for result in results:
            full_name = result.get("full_name")
            if not full_name:
                continue
            # Accept if full_name exactly matches or original identifier is a
            # prefix path that could lead to this definition
            if full_name == original_identifier:
                try:
                    return Handle(full_name)
                except ValueError:
                    continue
    except Exception as exc:
        logger.debug("_resolve_via_project_search(%r) failed: %s", symbol_name, exc)

    return None


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
    # _find_module_file with just that package name.
    top_package = parts[0]
    top_init = _find_module_file(top_package, analyzer)
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

    try:
        py_files = sorted(package_root.rglob("*.py"))
    except Exception as exc:
        logger.debug("_scan_package_for_handle: cannot list files under %s: %s", package_root, exc)
        return results

    # Pre-compute the project root for module path derivation
    project_path = analyzer.project_path
    source_roots = list(getattr(analyzer, "source_roots", []))
    all_roots = source_roots + [project_path]

    for py_file in py_files:
        try:
            script = file_artifact_cache.get_script(py_file, analyzer.project)
            names = script.get_names(all_scopes=False)
        except Exception as exc:
            logger.debug("_scan_package_for_handle: jedi error on %s: %s", py_file, exc)
            continue

        for name in names:
            if name.full_name != target_full_name:
                continue

            # Derive the module dotted path for this file
            mod_path = _file_to_module_path(py_file, all_roots)
            if mod_path is None:
                continue

            # Build the re-export handle: module_path.symbol_name
            re_export_handle = f"{mod_path}.{name.name}"
            if re_export_handle != target_full_name:
                results.append(re_export_handle)

    return results


def _file_to_module_path(py_file: Path, roots: list[Path]) -> str | None:
    """Derive the dotted module path for *py_file* relative to one of *roots*.

    Returns ``None`` if the file cannot be placed under any root.

    For ``__init__.py`` files, returns the package path (without ``__init__``).
    For regular ``.py`` files, returns the module path (without ``.py``).
    """
    for root in roots:
        try:
            rel = py_file.relative_to(root)
        except ValueError:
            continue

        parts = list(rel.parts)
        if not parts:
            continue

        if parts[-1] == "__init__.py":
            module_parts = parts[:-1]
        elif parts[-1].endswith(".py"):
            module_parts = parts[:-1] + [parts[-1][:-3]]
        else:
            continue

        return ".".join(module_parts) if module_parts else None

    return None


def _is_valid_handle(value: str) -> bool:
    """Return True if *value* is a valid dotted Python name (for Handle construction)."""
    try:
        Handle(value)
        return True
    except ValueError:
        return False
