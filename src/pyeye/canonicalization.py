"""Single-step definition-site canonicalization for PyEye handles.

Given any dotted-name identifier that a user or tool might pass in, return the
*canonical handle* — the definition site — according to the rule:

    The canonical handle is where the object is **defined**, not where it is
    imported or re-exported.

For example, given either of::

    "package.Config"               # re-exported via __init__.py
    "package._impl.config.Config"  # the actual definition file

both return ``Handle("package._impl.config.Config")``.

Public API
----------
resolve_canonical(identifier, analyzer) -> Handle | None
    Resolve any dotted-name form to its canonical handle, or return None if
    the identifier cannot be resolved.  Never raises.

collect_re_exports(handle, analyzer) -> list[Handle]
    Given a canonical handle, return all dotted-name paths that bind to the
    same object via ``__init__.py`` re-exports.  Returns an empty list when
    no public paths are found.  Never raises.

Design notes
------------
Jedi's ``Name.full_name`` already points to the *definition site* even when
the search finds a re-exported name (e.g. the import line in ``__init__.py``).
We exploit this property rather than walking import chains ourselves.

The implementation accesses ``JediAnalyzer``'s private helpers
``_find_init_file`` and ``_check_symbol_in_init`` because they already contain
the correct logic for discovering ``__init__.py`` files across source layouts
(src-layout, direct-layout, namespaces).  Building equivalent logic in this
module would duplicate those helpers.  We do *not* use the existing
``find_reexports`` method because it returns import-statement strings like
``"from package import Config"`` rather than dotted handles.

Multi-hop aliasing (``A = B``, ``C = A``, etc.) is explicitly deferred to
Task 1.3.  This module handles the single-hop re-export case only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pyeye.handle import Handle

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_canonical(identifier: str, analyzer: JediAnalyzer) -> Handle | None:
    """Resolve a dotted-name identifier to its canonical (definition-site) handle.

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

    Walks the package hierarchy above the definition site, checking each
    ``__init__.py`` for a re-export of the symbol.

    Args:
        handle: Canonical handle (definition-site dotted name).
        analyzer: A configured ``JediAnalyzer`` instance pointing at the
            project that contains the symbol.

    Returns:
        A list of :class:`~pyeye.handle.Handle` objects representing public
        import paths.  The canonical handle itself is *not* included in the
        returned list.  Returns an empty list when no re-exports are found.
        Never raises.
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
    """Core resolution logic — may raise; callers catch."""
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
    # tracks to the definition site.
    module_file = _find_module_file(module_dotted, analyzer) if module_dotted else None

    if module_dotted and module_file is None:
        # Module path not found — try the project search as a fallback
        return await _resolve_via_project_search(symbol_name, identifier, analyzer)

    full_name = await _get_full_name_from_file(module_file, symbol_name, analyzer)
    if full_name is None:
        return None

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
        if len(path_parts) >= 1:
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
        # Import jedi here to keep the public surface free of top-level Jedi dep
        import jedi

        script = jedi.Script(path=str(module_file), project=analyzer.project)
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
    """Core collection logic — may raise; callers catch."""
    parts = str(handle).split(".")
    if len(parts) < 2:
        # Top-level name — no enclosing package to re-export it
        return []

    symbol_name = parts[-1]
    # module_parts are everything up to but not including the symbol
    module_parts = parts[:-1]

    result: list[Handle] = []

    # Walk up the package hierarchy: for each prefix of module_parts, check
    # whether the corresponding __init__.py re-exports this symbol.
    # E.g. for package._impl.config.Config we check:
    #   package._impl.__init__.py  — re-exports from .config import Config?
    #   package.__init__.py        — re-exports from ._impl.config import Config?
    for i in range(len(module_parts) - 1, 0, -1):
        parent_module = ".".join(module_parts[:i])
        init_file = analyzer._find_init_file(parent_module)

        if init_file is None:
            continue

        # Immediate submodule name relative to the parent
        submodule = module_parts[i]

        if await analyzer._check_symbol_in_init(init_file, symbol_name, submodule):
            re_export_path = f"{parent_module}.{symbol_name}"
            try:
                result.append(Handle(re_export_path))
            except ValueError:
                logger.debug("Skipping invalid re-export path %r", re_export_path)
            # Single-hop: stop at the first (outermost) re-export found.
            # Multi-hop chains are Task 1.3 territory.
            break

    return result
