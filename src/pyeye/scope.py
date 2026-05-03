"""Project-vs-external scope classification for the PyEye resolve/inspect API.

Every node and stub in the API carries a binary ``scope`` field:

- ``"project"`` -- the symbol is defined in *this* project (within a configured
  package path).  All operations return rich, full-graph data.
- ``"external"`` -- the symbol is defined outside the project (third-party
  package, stdlib, or build artifact).  Operations still work, but with
  project-scoped semantics.

**Why binary and not ``stdlib | third_party | vendored``?**
A binary distinction is what governs operation behaviour: project = full-graph,
external = project-scoped.  The ``location`` field already exposes where the
symbol lives, which is enough information for the caller.

Classification rule order (first match wins)
--------------------------------------------
1. **Build artifacts** -- if any path segment is a build directory
   (``build``, ``dist``, ``.tox``, ``__pycache__``, ``*.egg-info``) →
   ``"external"``.  These paths should ideally never reach here due to
   project-aware scoping, but the classifier handles them defensively.
2. **site-packages** -- if any path segment is ``site-packages`` or
   ``dist-packages`` → ``"external"``.
3. **Stdlib** -- if the path is a descendant of ``sysconfig.get_paths()["stdlib"]``
   or ``["platstdlib"]`` → ``"external"``.
4. **Project source roots** -- if the path is a descendant of the project root
   or any configured source root / additional path → ``"project"``.
5. **Default** -- anything else (unknown external location) → ``"external"``.

**Vendored directories** (e.g. ``_vendor/``, ``third_party/``) that live *inside*
the project root fall through to rule 4 and classify as ``"project"``.  This is
the safe default: vendored code lives inside the project boundary.  A future
``vendored`` config field in ``.pyeye.json`` (e.g. ``"vendored": ["_vendor"]``)
could force such paths to ``"external"``; that option is not yet implemented.

Public API
----------
.. code-block:: python

    from pathlib import Path
    from pyeye.scope import classify_scope, Scope

    scope: Scope = classify_scope(
        "/project/src/mypackage/core.py",
        analyzer,          # JediAnalyzer
    )
    # → "project"

The function is *pure path comparison* — no Jedi calls are made.  It accepts
either a :class:`pathlib.Path` or a plain :class:`str`.

The ``JediAnalyzer`` parameter was chosen over ``ProjectManager`` or
``ProjectConfig`` because downstream callers in Phase 2 (``resolve``) and
Phase 3 (``inspect``) already have an ``analyzer`` in scope.  The analyzer
exposes the three boundaries we need: ``project_path``, ``source_roots``, and
``additional_paths``.
"""

from __future__ import annotations

import re
import sysconfig
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .analyzers.jedi_analyzer import JediAnalyzer

# ---------------------------------------------------------------------------
# Public type alias
# ---------------------------------------------------------------------------

Scope = Literal["project", "external"]

# ---------------------------------------------------------------------------
# Pre-computed stdlib roots (evaluated once at import time)
# ---------------------------------------------------------------------------

_STDLIB_ROOTS: frozenset[Path] = frozenset(
    Path(p).resolve()
    for p in (sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["platstdlib"])
)

# ---------------------------------------------------------------------------
# Segment-name sets for fast O(1) per-segment checks
# ---------------------------------------------------------------------------

_SITE_PACKAGES_NAMES: frozenset[str] = frozenset(
    ("site-packages", "dist-packages", "site_packages")
)

# Build artifact segment patterns: exact names or glob suffixes
_BUILD_ARTIFACT_NAMES: frozenset[str] = frozenset(("build", "dist", ".tox", "__pycache__"))
_BUILD_ARTIFACT_SUFFIX_RE = re.compile(r"^.+\.egg-info$")


def _has_build_artifact_segment(path: Path) -> bool:
    """Return True if any segment of *path* is a recognised build artefact name."""
    for part in path.parts:
        if part in _BUILD_ARTIFACT_NAMES:
            return True
        if _BUILD_ARTIFACT_SUFFIX_RE.match(part):
            return True
    return False


def _has_site_packages_segment(path: Path) -> bool:
    """Return True if any segment of *path* is a site-packages variant."""
    return any(part in _SITE_PACKAGES_NAMES for part in path.parts)


def _is_under_stdlib(path: Path) -> bool:
    """Return True if *path* is a descendant of any known stdlib root."""
    resolved = path.resolve()
    return any(_is_subpath(resolved, root) for root in _STDLIB_ROOTS)


def _is_subpath(path: Path, parent: Path) -> bool:
    """Return True if *path* is at or below *parent*.

    Works for both absolute and relative paths; uses pure ``Path.relative_to``
    which is safe and platform-aware without requiring the paths to exist.
    """
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _project_roots(analyzer: JediAnalyzer) -> list[Path]:
    """Collect all source roots from the analyzer, resolved to absolute paths.

    Includes:
    - ``analyzer.project_path``
    - ``analyzer.source_roots`` (e.g. the ``src/`` directory in a src-layout)
    - ``analyzer.additional_paths`` (sibling packages added via config)
    """
    roots: list[Path] = [analyzer.project_path.resolve()]
    for p in analyzer.source_roots:
        resolved = p.resolve()
        if resolved not in roots:
            roots.append(resolved)
    for p in analyzer.additional_paths:
        resolved = p.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_scope(file_path: Path | str, analyzer: JediAnalyzer) -> Scope:
    """Classify *file_path* as ``"project"`` or ``"external"``.

    Parameters
    ----------
    file_path:
        The path to the file whose scope is being classified.  Need not exist
        on disk — classification is purely structural.
    analyzer:
        A configured :class:`~pyeye.analyzers.jedi_analyzer.JediAnalyzer` for
        the project.  Provides the project boundary (project root, source roots,
        additional paths).

    Returns
    -------
    ``"project"`` if the file lives inside the project boundary; ``"external"``
    otherwise.
    """
    path = Path(file_path)

    # Rule 1: Build artifacts — even if inside the project, classify external
    if _has_build_artifact_segment(path):
        return "external"

    # Rule 2: site-packages / dist-packages
    if _has_site_packages_segment(path):
        return "external"

    # Rule 3: Stdlib — resolve first for accurate prefix comparison
    if _is_under_stdlib(path):
        return "external"

    # Rule 4: Project source roots
    resolved = path.resolve()
    for root in _project_roots(analyzer):
        if _is_subpath(resolved, root):
            return "project"

    # Rule 5: Default — unknown external location
    return "external"
