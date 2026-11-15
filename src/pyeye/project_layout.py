"""One project-roots policy and one file↔module mapper pair (#625).

Pure path logic over an analyzer's *layout* attributes. Nothing here imports
Jedi, resolves a handle or builds a not-found shape: this is the lower-level
library that handle resolution (#623) and the edges build on.

The layout is read from the analyzer's attributes by duck typing, so a test can
pass any object carrying them:

``project_path``
    The project root.
``source_roots``
    src-layout roots inside the project (e.g. ``<project>/src``).
``added_sys_path``
    Everything handed to Jedi as extra sys.path: configured package roots plus
    namespace repo roots, in sys.path precedence order.
``additional_paths``
    Configured sibling packages (``ProjectManager``). Each is a sys.path-style
    root, so ``<shared>/utils.py`` is module ``utils``.
``namespace_paths``
    ``{namespace: [repo roots]}`` for PEP 420 namespace packages.
``_jedi_root_is_parent``
    ``True`` when ``project_path`` is itself a package (has ``__init__.py``), so
    Jedi is rooted at its parent and module names carry the package name.

Roots policy
------------
:func:`project_roots` is the single place a roots list is assembled. Each
boundary that needs one names its subset with :class:`RootsBoundary`:

=====================  ==========================================================
Boundary               Subset, in order (and why)
=====================  ==========================================================
``SCOPE``              the ``NAMESPACE_PORTIONS`` roots. "Is this file ours?"
                       for ``classify_scope``: everything the user configured,
                       packages AND namespaces, is ``project`` (#623 decision
                       7). site-packages / stdlib stay external because
                       ``classify_scope`` rules them out before any root test.
``TOP_LEVEL_PACKAGE``  project, source_roots. Only the project's *own* top-level
                       package is promoted by bare name, never a configured
                       external package root.
``MODULE_LOOKUP``      source_roots, project, additional_paths. sys.path
                       precedence for dotted-module → file lookup and for
                       file → module naming.
``NAMESPACE_PORTIONS`` source_roots, project, added_sys_path, additional_paths.
                       Every sys.path root a PEP 420 portion can live under, in
                       precedence order (first portion wins, #419/#444).
=====================  ==========================================================

Every list is deduped by resolved identity, keeping the first occurrence.

Mapper pair
-----------
:func:`module_name_for_file` and :func:`file_for_module` are inverses. Both
follow the names Jedi reports as ``full_name``, which is what every handle is
compared against.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from .path_utils import dedupe_paths


class RootsBoundary(StrEnum):
    """The named roots subsets; see the module docstring for each one's reason."""

    SCOPE = "scope"
    TOP_LEVEL_PACKAGE = "top_level_package"
    MODULE_LOOKUP = "module_lookup"
    NAMESPACE_PORTIONS = "namespace_portions"


# Each boundary's subset, in precedence order. Changing what a boundary covers
# is a one-line edit here; the module docstring records why each is what it is.
_SUBSETS: dict[RootsBoundary, tuple[str, ...]] = {
    RootsBoundary.TOP_LEVEL_PACKAGE: ("project_path", "source_roots"),
    RootsBoundary.MODULE_LOOKUP: ("source_roots", "project_path", "additional_paths"),
    RootsBoundary.NAMESPACE_PORTIONS: (
        "source_roots",
        "project_path",
        "added_sys_path",
        "additional_paths",
    ),
}
# Configured namespaces count as project (#623): SCOPE is the namespace-portion
# boundary by name, not a hand-copied list, so the two can't drift.
_SUBSETS[RootsBoundary.SCOPE] = _SUBSETS[RootsBoundary.NAMESPACE_PORTIONS]


def project_roots(analyzer: Any, boundary: RootsBoundary, *, resolved: bool = False) -> list[Path]:
    """Return the roots list for *boundary* (the single roots policy, #625).

    Args:
        analyzer: Any object carrying the layout attributes (module docstring).
            Optional list attributes that are missing count as empty.
        boundary: Which named subset to build.
        resolved: Return resolved paths (stable for ``==`` against other
            resolved paths) instead of the original ``Path`` objects.

    Returns:
        The deduped roots in the boundary's precedence order.
    """
    available: dict[str, list[Path]] = {
        "project_path": [analyzer.project_path],
        "source_roots": list(getattr(analyzer, "source_roots", None) or []),
        "added_sys_path": list(getattr(analyzer, "added_sys_path", None) or []),
        "additional_paths": list(getattr(analyzer, "additional_paths", None) or []),
    }
    ordered = [root for attr in _SUBSETS[boundary] for root in available[attr]]
    return dedupe_paths(ordered, resolve_output=resolved)


def _root_is_package(analyzer: Any) -> bool:
    flag = getattr(analyzer, "_jedi_root_is_parent", None)
    if flag is not None:
        return bool(flag)
    return (Path(analyzer.project_path) / "__init__.py").exists()


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _dotted(rel: Path, file: Path) -> str | None:
    """Module name for *file* given its path *rel* relative to a sys.path root.

    ``None`` for an ``__init__.py`` sitting directly at the root: it names no
    importable package from that root.
    """
    parts = list(rel.parts[:-1])
    if file.name != "__init__.py":
        parts.append(file.stem)
    return ".".join(parts) if parts else None


def module_name_for_file(analyzer: Any, file: Path) -> str | None:
    """Return the dotted module name for *file*, as Jedi's ``full_name`` spells it.

    The one file → module mapper (#625). Checked in this order:

    1. a file in a project that is itself a package: named from the project's
       parent, so it carries the package name (``rootpkg.b``, not ``b``);
    2. a file under an ``additional_paths`` root: named from that root;
    3. a file under a ``MODULE_LOOKUP`` source root or the project;
    4. a file under a namespace repo root, prefixed with the namespace name
       unless the repo-relative path already spells it.

    *file* is compared as given: pass a path in the same form (absolute,
    resolved or not) as the analyzer's roots.

    Returns ``None`` when the file is under none of them, is not a ``.py``
    file, or is an ``__init__.py`` directly at a root.
    """
    file = Path(file)
    if file.suffix != ".py":
        return None
    project = Path(analyzer.project_path)

    if _root_is_package(analyzer) and _is_under(file, project):
        return _dotted(file.relative_to(project.parent), file)

    for add_path in getattr(analyzer, "additional_paths", []):
        if _is_under(file, add_path):
            return _dotted(file.relative_to(add_path), file)

    for root in project_roots(analyzer, RootsBoundary.MODULE_LOOKUP):
        if _is_under(file, root):
            return _dotted(file.relative_to(root), file)

    for ns_name, ns_paths in getattr(analyzer, "namespace_paths", {}).items():
        for ns_path in ns_paths:
            if not _is_under(file, ns_path):
                continue
            name = _dotted(file.relative_to(ns_path), file)
            if name is None:
                return None
            parts = name.split(".")
            # ``ns_path`` is normally the repo root, so the repo-relative path
            # already includes the namespace dir (``company/auth/models``).
            # Prefix the namespace only when ``ns_path`` points straight at the
            # namespace dir; prefixing unconditionally double-counts it.
            ns_segments = ns_name.split(".")
            if parts[: len(ns_segments)] == ns_segments:
                return name
            return f"{ns_name}.{name}"
    return None


def file_for_module(analyzer: Any, module_dotted: str) -> Path | None:
    """Return the ``__init__.py`` or ``<name>.py`` defining *module_dotted*.

    The one module → file mapper (#625), the inverse of
    :func:`module_name_for_file`. Searches the ``MODULE_LOOKUP`` roots in
    precedence order, trying the package ``__init__.py`` before the module
    file, then the root-package case (``rootpkg.a`` inside a project that *is*
    ``rootpkg``), then a module inside a configured PEP 420 namespace package
    (``ns-repo/acme/tools.py`` for ``acme.tools``), searched under that
    package's portion directories, deepest namespace prefix first (#623).
    Without that last step a configured namespace repo's modules would have a
    module name (:func:`module_name_for_file`) but no file.  A namespace package
    itself has no file: use :func:`find_namespace_package_dirs` for its
    directories.

    Returns the path joined onto the root as given (not resolved), or ``None``.
    """
    parts = [p for p in module_dotted.split(".") if p]
    if not parts:
        return None

    bases: list[tuple[Path, list[str]]] = [
        (root, parts) for root in project_roots(analyzer, RootsBoundary.MODULE_LOOKUP)
    ]
    project = Path(analyzer.project_path)
    if _root_is_package(analyzer) and parts[0] == project.name:
        bases.append((project, parts[1:]))

    for base, rel_parts in bases:
        found = _module_file_under(base, rel_parts)
        if found is not None:
            return found
    for split_at in range(len(parts) - 1, 0, -1):
        for portion in find_namespace_package_dirs(".".join(parts[:split_at]), analyzer):
            found = _module_file_under(portion, parts[split_at:])
            if found is not None:
                return found
    return None


def _module_file_under(base: Path, rel_parts: list[str]) -> Path | None:
    """``base/<rel>/__init__.py``, else ``base/<rel>.py``, if it exists."""
    pkg_init = base.joinpath(*rel_parts) / "__init__.py"
    if pkg_init.exists():
        return pkg_init
    if rel_parts:
        mod_file = base.joinpath(*rel_parts[:-1], rel_parts[-1] + ".py")
        if mod_file.exists():
            return mod_file
    return None


def dir_shallow_qualifies(path: Path) -> bool:
    """Return whether *path* looks like an importable dir (the §3.5 filter).

    A PEP 420 namespace portion holds importable content but has no
    ``__init__.py``.  This separates such a directory from obvious junk/data dirs
    WITHOUT reading any file.  The check is deliberately **shallow and capped at
    one extra level** — it is NOT a recursive "any ``.py`` anywhere" walk (which
    would be both slow and over-eager).

    A directory qualifies iff, among its DIRECT entries, ANY of:

    - **(a)** a direct ``*.py`` file; or
    - **(b)** a direct child dir containing an ``__init__.py`` (a regular
      subpackage one level down); or
    - **(c)** a direct child dir that *itself* shallow-qualifies — checked with
      ``_recurse=False`` so the recursion stops after exactly ONE extra level
      (a namespace subpackage one level down).

    This is the **single source of truth** for the namespace-portion importable
    filter, shared by :func:`find_namespace_package_dirs` (handle anchoring, via
    ``resolve``/``inspect``) and by ``edges`` (the ``submodules`` enumerator,
    which imports this function).  Keeping one copy is what stops the anchoring
    filter and the enumeration filter from drifting apart — a namespace whose
    only content is a nested regular package (``acme/sub/deep/__init__.py``)
    qualifies under rule (c) here exactly as it does for the enumerator, so it
    can never enumerate via ``expand`` yet fail to anchor via ``resolve``.

    No file reads — ``iterdir``, ``.suffix``, ``.is_dir`` / ``.is_file`` and
    ``.exists`` only.

    Args:
        path: The candidate directory.

    Returns:
        ``True`` if *path* qualifies as an importable dir per the rules above,
        else ``False`` (including when *path* is unreadable).
    """
    return _dir_shallow_qualifies_capped(path, _recurse=True)


def _dir_shallow_qualifies_capped(path: Path, *, _recurse: bool) -> bool:
    """Back the :func:`dir_shallow_qualifies` filter with an explicit recursion cap.

    ``_recurse`` is consumed on the FIRST extra level: the rule-(c) descent calls
    this helper with ``_recurse=False``, so a grandchild dir can only satisfy
    rules (a)/(b) — never trigger a further descent.  This caps the total depth
    at one extra level (see the public wrapper's docstring for the rule list).

    Args:
        path: The candidate directory.
        _recurse: Whether a rule-(c) one-level descent is still permitted.

    Returns:
        ``True`` if *path* qualifies, else ``False`` (including on read errors).
    """
    try:
        entries = list(path.iterdir())
    except OSError:
        return False

    for entry in entries:
        name = entry.name
        if name.startswith(".") or name == "__pycache__":
            continue
        # (a) a direct .py file.
        if entry.is_file() and entry.suffix == ".py":
            return True
        if entry.is_dir():
            # (b) a direct child dir that is a regular package.
            if (entry / "__init__.py").exists():
                return True
            # (c) a direct child dir that itself shallow-qualifies — but only
            # one extra level deep (cap: _recurse=False on the descent).
            if _recurse and _dir_shallow_qualifies_capped(entry, _recurse=False):
                return True
    return False


def find_namespace_package_dirs(module_dotted: str, analyzer: Any) -> list[Path]:
    """Return the PEP 420 namespace-package portion dirs for *module_dotted* (#444).

    A namespace package has **no** ``__init__.py`` (so :func:`file_for_module`
    returns ``None`` for the package itself) and may be spread across several *portions* under
    different sys.path roots.  This returns the **union** of the matching portion
    directories in ``NAMESPACE_PORTIONS`` roots (sys.path-precedence) order — the
    anchor a top-level namespace package needs so ``resolve``/``inspect``/
    ``outline``/``expand`` can fire from the top.

    A directory qualifies as a portion iff it matches the dotted path, has **no**
    ``__init__.py`` (a regular package is handled by :func:`file_for_module`,
    not here), and :func:`dir_shallow_qualifies` (so junk/data dirs are
    excluded).

    This is the single source of truth for "where does this namespace package
    live"; ``edges`` consumes it for the ``submodules`` enumerator, and
    ``resolve``/``inspect`` consume it to anchor the handle.

    Returns:
        The portion directories, roots-ordered and de-duplicated.  ``[]`` when
        *module_dotted* is not a namespace package (e.g. a regular package, a
        plain module, or nothing on disk).
    """
    path_parts = module_dotted.split(".")
    dirs: list[Path] = []
    seen: set[str] = set()
    for base in project_roots(analyzer, RootsBoundary.NAMESPACE_PORTIONS):
        candidate = base.joinpath(*path_parts)
        try:
            if not candidate.is_dir():
                continue
            if (candidate / "__init__.py").exists():
                # A regular package portion is not a namespace portion.
                continue
        except OSError:
            continue
        if not dir_shallow_qualifies(candidate):
            continue
        key = candidate.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        dirs.append(candidate)
    return dirs


PackageKind = Literal["regular", "namespace", "module", "unknown"]


def package_kind(module_path: Any) -> PackageKind:
    """Classify a Jedi ``module_path`` by what it says about package-ness (#625).

    The one package predicate. It reads only the path:

    - ``…/__init__.py`` → ``"regular"`` (a regular package);
    - any other ``….py`` → ``"module"`` (a plain module, or a symbol defined in one);
    - an existing directory → ``"namespace"`` (a PEP 420 package, anchored on its
      directory since #444);
    - ``None``, or a non-``.py`` file such as a stub or extension module →
      ``"unknown"``.

    ``"unknown"`` is deliberately its own answer. Jedi gives a namespace package
    a ``None`` path, but it gives builtins one too, so the path alone can't
    tell. Each caller decides what unknown means for it, and says so:
    ``edges._package_dirs`` looks the handle up as a namespace package by name,
    while ``inspect``'s ``is_package`` and ``outline``'s survey mode treat it as
    not a package.
    """
    if module_path is None:
        return "unknown"
    path = Path(module_path)
    if path.name == "__init__.py":
        return "regular"
    if path.suffix == ".py":
        return "module"
    try:
        if path.is_dir():
            return "namespace"
    except OSError:
        pass
    return "unknown"


def detect_src_layout(project_path: Path | str) -> Path | None:
    """Return ``<project>/src`` when the project uses a src layout, else ``None``.

    The one src-layout rule (#625), shared by ``ProjectConfig`` auto-discovery
    and a ``JediAnalyzer`` built without a config, so the two never name the
    same files differently. A src layout is a ``src/`` directory holding at
    least one regular package (a subdirectory with ``__init__.py``).
    """
    src_dir = Path(project_path) / "src"
    try:
        if not src_dir.is_dir():
            return None
        has_package = any(
            (item / "__init__.py").exists() for item in src_dir.iterdir() if item.is_dir()
        )
    except OSError:
        return None
    return src_dir if has_package else None
