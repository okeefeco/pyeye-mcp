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
The input path is resolved (``Path.resolve()``) once up front and **every** rule
is applied against that resolved path, so the result never depends on which path
form the caller supplied (e.g. a ``site-packages`` symlink vs the real
editable-install target — see #338).

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

import sysconfig
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pyeye.path_utils import normalize_path, relative_within
from pyeye.project_layout import RootsBoundary, dir_name_matches, is_package_dir, project_roots

if TYPE_CHECKING:
    from .analyzers.jedi_analyzer import JediAnalyzer

# ---------------------------------------------------------------------------
# Public type alias
# ---------------------------------------------------------------------------

Scope = Literal["project", "external"]

# ---------------------------------------------------------------------------
# Pre-computed stdlib roots (evaluated once at import time)
# ---------------------------------------------------------------------------

# NOTE: _STDLIB_ROOTS is frozen at module import time via sysconfig.get_paths().
# Patching sysconfig after import has no effect on this set.  To override in
# tests, monkeypatch the module-level name directly:
#   monkeypatch.setattr("pyeye.scope._STDLIB_ROOTS", frozenset({Path("/fake")}))
_STDLIB_ROOTS: frozenset[Path] = frozenset(
    normalize_path(p)
    for p in (sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["platstdlib"])
)

# ---------------------------------------------------------------------------
# Segment-name sets for fast O(1) per-segment checks
# ---------------------------------------------------------------------------

_SITE_PACKAGES_NAMES: frozenset[str] = frozenset(("site-packages", "dist-packages"))

# Build artifact segment patterns
# ``_BUILD_ARTIFACT_TOPLEVEL`` names are only matched when the segment is the
# immediate child of the project root.  ``build/`` and ``dist/`` are common
# project subdirectory names in other contexts (e.g. ``src/dist_helpers/``
# would never collide since that segment is ``dist_helpers``, not ``dist``),
# but a directory literally named ``dist`` or ``build`` at the top of a project
# is unambiguously a build artefact.  Matching them anywhere in the path would
# misclassify files in e.g. ``some_ns/dist/helper.py`` (a legitimately-named
# sub-package) when that path happens to appear under a project root.
_BUILD_ARTIFACT_TOPLEVEL: frozenset[str] = frozenset(("build", "dist"))

# ``_BUILD_ARTIFACT_ANYWHERE`` names are semantically unambiguous regardless of
# depth: no real source file lives inside ``.tox/`` or ``__pycache__/``.
_BUILD_ARTIFACT_ANYWHERE: frozenset[str] = frozenset((".tox", "__pycache__", "*.egg-info"))


def _has_build_artifact_segment(path: Path, project_root: Path | None = None) -> bool:
    """Return True if *path* contains a recognised build-artefact segment.

    ``build`` and ``dist`` are only treated as build artifacts when the segment
    is the *immediate* child of *project_root* (i.e. at the top level of the
    project).  This prevents false positives for paths like
    ``project/src/dist_helpers/foo.py`` — but note that ``dist_helpers`` would
    never match anyway since it is not the same string; the risk is a real
    ``project/some_ns/dist/`` sub-directory being misclassified.

    ``.tox``, ``__pycache__``, and ``*.egg-info`` match at *any* depth because
    they are semantically unambiguous.

    When *path* is under *project_root*, only the segments **below** the root are
    tested: a project that lives under e.g. ``/ci/.tox/`` is not a build
    artifact (#515). A path outside the root, or a call without a root, tests
    every segment.

    Comparisons are case-folded so ``Build/`` and ``DIST/`` match on
    case-insensitive filesystems (Windows, macOS default).
    """
    parts = path.parts

    # Determine the index of the segment immediately after the project root, if
    # the project root is known and the path is actually under it.
    toplevel_idx: int | None = None
    if project_root is not None:
        root_parts = project_root.parts
        if len(parts) > len(root_parts) and parts[: len(root_parts)] == root_parts:
            toplevel_idx = len(root_parts)  # index of the first child segment

    # Under the root, skip the root's own segments and its ancestors (#515).
    start = toplevel_idx if toplevel_idx is not None else 0
    for i, part in enumerate(parts[start:], start):
        # Top-level-only names, matched by the scan's own name predicate (#1116).
        if dir_name_matches(part, _BUILD_ARTIFACT_TOPLEVEL):
            # #1104: the scan's package rule — a ``build``/``dist`` PACKAGE is source.
            if is_package_dir(Path(*parts[: i + 1])):
                continue
            if toplevel_idx is not None and i == toplevel_idx:
                return True
            elif toplevel_idx is None:
                # No project root context — fall back to matching anywhere
                # (preserves behaviour for callers that do not pass a root)
                return True
        # Anywhere names
        if dir_name_matches(part, _BUILD_ARTIFACT_ANYWHERE):
            return True
    return False


def _has_site_packages_segment(path: Path) -> bool:
    """Return True if any segment of *path* is a site-packages variant."""
    return any(part.casefold() in _SITE_PACKAGES_NAMES for part in path.parts)


def _is_under_stdlib(path: Path) -> bool:
    """Return True if *path* is a descendant of any known stdlib root."""
    return any(relative_within(path, root) is not None for root in _STDLIB_ROOTS)


def is_stdlib_source(file_path: Path | str) -> bool:
    """Whether *file_path* is a standard-library ``.py`` source file (#544).

    Rule 3 of :func:`classify_scope` (under a stdlib root), excluding anything
    in ``site-packages`` / ``dist-packages`` and typeshed ``.pyi`` stubs. Used
    to decide where the running interpreter is the authority on a name.
    """
    path = Path(file_path)
    if path.suffix != ".py":
        return False
    try:
        resolved = normalize_path(path)
    except OSError:
        return False
    return _is_under_stdlib(resolved) and not _has_site_packages_segment(resolved)


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
    # Resolve the input ONCE and apply every rule against the resolved path.
    # Mixing resolved and raw paths across rules made the result depend on which
    # path form the caller happened to supply — e.g. an editable install where
    # ``site-packages/<pkg>`` symlinks to the real project package classified as
    # "external" via the symlink path but "project" via the real path (#338).
    # Resolving first is the symlink/editable-install-correct choice: the symlink
    # collapses to its real location before any segment/prefix test runs.
    resolved = normalize_path(file_path)

    # Rule 1: Build artifacts — even if inside the project, classify external.
    # Pass the resolved project root so that ``build`` and ``dist`` are only
    # matched at the immediate top level of the project (preventing false
    # positives for legitimately-named nested sub-directories).
    project_root = normalize_path(analyzer.project_path)
    if _has_build_artifact_segment(resolved, project_root):
        return "external"

    # Rule 2: site-packages / dist-packages
    if _has_site_packages_segment(resolved):
        return "external"

    # Rule 3: Stdlib (descendant of a stdlib root)
    if _is_under_stdlib(resolved):
        return "external"

    # Rule 4: Project source roots
    for root in project_roots(analyzer, RootsBoundary.SCOPE, resolved=True):
        if relative_within(resolved, root) is not None:
            return "project"

    # Rule 5: Default — unknown external location
    return "external"
