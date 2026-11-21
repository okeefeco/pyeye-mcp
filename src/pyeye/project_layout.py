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
``MODULE_LOOKUP``      source_roots, project, additional_paths, standalone
                       dirs. sys.path precedence for dotted-module → file
                       lookup and for file → module naming. A standalone dir
                       comes last and names a script only when nothing else
                       owns its name (``standalone_shadow``, #1041).
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

import logging
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from .path_utils import dedupe_paths, paths_equal, relative_within

logger = logging.getLogger(__name__)


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
    # Standalone script dirs last (#1041): a script is named from its dir only
    # when nothing earlier, nor the stdlib or the environment, owns the name.
    RootsBoundary.MODULE_LOOKUP: (
        "source_roots",
        "project_path",
        "additional_paths",
        "standalone_paths",
    ),
    RootsBoundary.NAMESPACE_PORTIONS: (
        "source_roots",
        "project_path",
        "added_sys_path",
        "additional_paths",
    ),
}
# Configured namespaces count as project (#623): SCOPE is the namespace-portion
# boundary by name, not a hand-copied list, so the two can't drift. It adds the
# standalone script directories (#690): ``scope="all"`` searches them, so a file
# found there is project code, not "external".
_SUBSETS[RootsBoundary.SCOPE] = (*_SUBSETS[RootsBoundary.NAMESPACE_PORTIONS], "standalone_paths")


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
        "standalone_paths": list(getattr(analyzer, "standalone_paths", None) or []),
    }
    ordered = [root for attr in _SUBSETS[boundary] for root in available[attr]]
    return dedupe_paths(ordered, resolve_output=resolved)


def _resolved_posix(path: Any) -> str:
    try:
        return Path(path).resolve().as_posix()
    except OSError:
        return Path(path).as_posix()


def layout_key(analyzer: Any) -> str:
    """A stable identity for the analyzer's *effective layout* (#618).

    Anything that maps files to module names depends on the layout, not just on
    the project root: two analyzers on one root with different source roots name
    the same file differently (``src.pkg.mod`` vs ``pkg.mod``). Process-wide
    caches that bake module names in key on this, so analyzers with different
    layouts on the same root can't read each other's entries.

    Covers every layout attribute in the module docstring, plus standalone
    script directories. Paths are resolved. ``added_sys_path`` keeps its order
    (sys.path precedence matters); the other lists are sets; namespaces are
    sorted by name.

    Args:
        analyzer: Any object carrying the layout attributes.

    Returns:
        A string, equal for equal layouts.
    """

    def paths(attr: str) -> list[str]:
        return [_resolved_posix(p) for p in getattr(analyzer, attr, None) or []]

    namespaces = getattr(analyzer, "namespace_paths", None) or {}
    parts = [
        "root=" + _resolved_posix(analyzer.project_path),
        "pkgroot=" + str(_root_is_package(analyzer)),
        "src=" + "|".join(sorted(paths("source_roots"))),
        "syspath=" + "|".join(paths("added_sys_path")),
        "pkgs=" + "|".join(sorted(paths("additional_paths"))),
        "standalone=" + "|".join(sorted(paths("standalone_paths"))),
        # The project environment's import roots (#993): a venv that appears,
        # moves or changes packages is another layout (#618).
        "env=" + "|".join(getattr(getattr(analyzer, "environment", None), "site_paths", ())),
        "ns="
        + ";".join(
            f"{name}:" + "|".join(sorted(_resolved_posix(p) for p in namespaces[name]))
            for name in sorted(namespaces)
        ),
    ]
    return "\n".join(parts)


#: A stub file's suffix (PEP 484).
STUB_SUFFIX = ".pyi"

#: A PEP 561 stub-only distribution's directory suffix (``foo-stubs``).
STUBS_PACKAGE_SUFFIX = "-stubs"

DeclarationKind = Literal["source", "stub"]


def declaration_kind(file: str | Path) -> DeclarationKind:
    """Whether a definition in *file* is declared in a stub or in source (#933).

    The ONE predicate behind the ``declared_in`` marker, whose placement in the
    responses is pending. A ``.pyi`` (any case) is a stub: a project stub-only
    module, typeshed, a stub-only installed package. Anything else is source.
    """
    return "stub" if Path(file).suffix.lower() == STUB_SUFFIX else "source"


#: The node key that marks a definition declared in a stub (#933): ``True``
#: when present, absent for source. A documented flag, not a measurement left
#: out: whether a definition site is a ``.pyi`` is always known, so its absence
#: is a measured "no" (the maintainer's ruling, as resolve's ``truncated``).
STUB_KEY = "stub"


def mark_stub(node: dict[str, Any], file: str | Path | None) -> dict[str, Any]:
    """Set ``stub: true`` on *node* when *file*, its definition site, is a stub; else drop it.

    The one place the flag is written (#933): every node that carries
    ``scope`` passes through here with the file it is located at. Returns
    *node*, changed in place. A *file* of ``None`` (no definition file, e.g.
    a compiled builtin with no stub) is not a stub.
    """
    # A namespace portion's __init__.pyi declares the package's members, but the
    # package NODE has no single definition file: it is anchored at its
    # directory, so it is never a stub node (#1004).
    is_package_node = (
        file is not None and node.get("kind") == "module" and is_namespace_stub_init(file)
    )
    if file is not None and declaration_kind(file) == "stub" and not is_package_node:
        node[STUB_KEY] = True
    else:
        node.pop(STUB_KEY, None)
    return node


def in_stubs_package(file: str | Path, root: str | Path | None = None) -> bool:
    """Whether *file* is inside a ``foo-stubs`` directory (below *root*, when given).

    A PEP 561 stubs package is someone else's type information, vendored or
    installed: it gets no handles and is never enumerated (#933). Only the
    parts below *root* are tested, so a project that itself lives under a
    ``-stubs`` directory still scans.
    """
    path = Path(file)
    if root is not None:
        rel = relative_within(path, root)
        if rel is None:
            return False
        path = rel
    return any(part.endswith(STUBS_PACKAGE_SUFFIX) for part in path.parts[:-1])


def is_stub_only_module(file: str | Path) -> bool:
    """Whether *file* is a ``<name>.pyi`` with no ``<name>.py`` beside it (#933).

    Such a module is declared only, and gets a handle located at the stub. A
    stub beside its source is not: the ``.py`` is the module (#885). A package's
    ``__init__.pyi`` is not either: without an ``__init__.py`` its directory is
    a namespace package, and the stub is one portion's declarations of it
    (:func:`is_namespace_stub_init`, #1004).
    """
    path = Path(file)
    return (
        path.suffix == STUB_SUFFIX
        and path.name != "__init__.pyi"
        and not path.with_suffix(".py").is_file()
    )


def is_namespace_stub_init(file: str | Path) -> bool:
    """Whether *file* is an ``__init__.pyi`` with no ``__init__.py`` beside it (#1004).

    Its directory is a PEP 420 namespace package at runtime, and Jedi treats it
    as one (``type == "namespace"``), merging the stub's declarations into the
    namespace. So the stub declares the namespace's members, and names them as
    the package (``mixed/__init__.pyi`` declares ``mixed.M``), but it is not the
    package's file: the package is anchored at its directory (#444).
    """
    path = Path(file)
    return path.name == "__init__.pyi" and not (path.parent / "__init__.py").is_file()


def is_module_file(file: str | Path) -> bool:
    """Whether *file* is a module's file, for naming (#933, #1004).

    A ``.py``, a stub-only ``.pyi``, or a namespace portion's ``__init__.pyi``
    (named as its package, :func:`is_namespace_stub_init`).
    """
    path = Path(file)
    return path.suffix == ".py" or is_stub_only_module(path) or is_namespace_stub_init(path)


def iter_module_files(root: Path) -> list[Path]:
    """Every module file under *root*, sorted: ``.py`` files and stub-only ``.pyi``.

    The project-scan rule (:func:`pyeye.async_utils.filtered_rglob`) applies,
    and nothing in a ``foo-stubs`` directory below *root* is listed (#933).
    """
    from .async_utils import filtered_rglob

    files = [
        f
        for f in filtered_rglob(("*.py", f"*{STUB_SUFFIX}"), root)  # one walk (#933)
        if is_module_file(f) and not in_stubs_package(f, root)
    ]
    return sorted(files, key=lambda f: f.as_posix())


def _root_is_package(analyzer: Any) -> bool:
    flag = getattr(analyzer, "_jedi_root_is_parent", None)
    if flag is not None:
        return bool(flag)
    return (Path(analyzer.project_path) / "__init__.py").exists()


def _dotted(rel: Path, file: Path) -> str | None:
    """Module name for *file* given its path *rel* relative to a sys.path root.

    ``None`` for an ``__init__.py`` sitting directly at the root: it names no
    importable package from that root. ``None`` too when any part isn't a
    Python identifier (``my-pkg``, ``2fast``, ``mod.v2``): no ``import`` can
    reach the file under that name, so the mapper never invents one (#668).
    """
    parts = list(rel.parts[:-1])
    if file.name not in ("__init__.py", "__init__.pyi"):
        parts.append(file.stem)
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def module_name_for_file(analyzer: Any, file: Path) -> str | None:
    """Return the dotted module name for *file*, as Jedi's ``full_name`` spells it.

    The one file → module mapper (#625). Checked in this order:

    1. a file in a project that is itself a package: named from the project's
       parent, so it carries the package name (``rootpkg.b``, not ``b``);
    2. a file under an ``additional_paths`` root: named from that root;
    3. a file under a ``MODULE_LOOKUP`` source root or the project;
    4. a file under a namespace repo root, prefixed with the namespace name
       unless the repo-relative path already spells it.

    *file* may be spelled differently from the analyzer's roots (resolved or
    not, through a symlink): roots and file are compared as given and then
    resolved (:func:`pyeye.path_utils.relative_within`, #714).

    Returns ``None`` when the file is under none of them, is not a module file
    (a ``.py``, or a stub-only ``.pyi`` since #933: :func:`is_module_file`),
    is an ``__init__.py`` directly at a root, or has a path part that isn't a
    Python identifier (which also leaves out a ``foo-stubs`` directory). It
    never returns an invented name; callers must treat ``None`` as "can't be
    named", not as "not there" (#668).
    """
    file = Path(file)
    if not is_module_file(file):
        return None
    project = Path(analyzer.project_path)

    if _root_is_package(analyzer) and relative_within(file, project) is not None:
        rel = relative_within(file, project.parent)
        if rel is not None:
            return _dotted(rel, file)

    for add_path in getattr(analyzer, "additional_paths", []):
        rel = relative_within(file, add_path)
        if rel is not None:
            return _dotted(rel, file)

    for root in project_roots(analyzer, RootsBoundary.MODULE_LOOKUP):
        rel = relative_within(file, root)
        if rel is not None:
            name = _dotted(rel, file)
            if name is not None and _is_standalone_root(analyzer, root):
                # A script is named only if that name leads back to it: never a
                # handle another file, the stdlib or the environment owns (#1041).
                owner = file_for_module(analyzer, name)
                if owner is None or not paths_equal(owner, file):
                    return None
            return name

    for ns_name, ns_paths in getattr(analyzer, "namespace_paths", {}).items():
        for ns_path in ns_paths:
            rel = relative_within(file, ns_path)
            if rel is None:
                continue
            name = _dotted(rel, file)
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
    """Return the ``__init__.py``, ``<name>.py`` or stub-only ``<name>.pyi`` defining *module_dotted*.

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
            if _is_standalone_root(analyzer, base) and standalone_shadow(analyzer, parts[0]):
                continue  # the name is someone else's (#1041)
            return found
    for split_at in range(len(parts) - 1, 0, -1):
        for portion in find_namespace_package_dirs(".".join(parts[:split_at]), analyzer):
            found = _module_file_under(portion, parts[split_at:])
            if found is not None:
                return found
    return None


def _module_file_under(base: Path, rel_parts: list[str]) -> Path | None:
    """``base/<rel>/__init__.py``, else ``base/<rel>.py``, else ``base/<rel>.pyi``, if it exists.

    The stub comes last, so a ``.py`` beside it always wins (#885, #933). Every
    part below *base* must match its directory entry in exact case, as Python's
    import requires: on a case-insensitive filesystem ``pkg/Dyn.py`` "exists"
    for ``pkg/dyn.py``, and ``pkg.Dyn`` would be taken for a module (#1047).
    """
    pkg_init = base.joinpath(*rel_parts) / "__init__.py"
    if pkg_init.exists() and _exact_case(base, [*rel_parts, "__init__.py"]):
        return pkg_init
    if rel_parts:
        for suffix in (".py", STUB_SUFFIX):
            mod_file = base.joinpath(*rel_parts[:-1], rel_parts[-1] + suffix)
            if mod_file.exists() and _exact_case(base, [*rel_parts[:-1], rel_parts[-1] + suffix]):
                return mod_file
    return None


# --- exact-case matching on case-insensitive filesystems (#1047) -------------

#: A search root -> whether its filesystem is case-sensitive (probed once).
_case_sensitive: dict[str, bool] = {}
#: A directory -> ``(mtime_ns, its entry names)``, LRU, for the exact-case check.
_listings: OrderedDict[str, tuple[int, frozenset[str]]] = OrderedDict()
_LISTINGS_MAX = 4096
#: A directory whose mtime is this recent may change again within the same
#: timestamp tick (FAT has 2 s ticks), so its listing isn't cached.
_RECENT_NS = 2_000_000_000
_case_lock = threading.Lock()


def clear_case_caches() -> None:
    """Forget every case probe and directory listing (tests; a root's filesystem changed)."""
    with _case_lock:
        _case_sensitive.clear()
        _listings.clear()


def _is_case_sensitive(base: Path) -> bool:
    """Whether *base*'s filesystem tells names apart by case, probed once per root.

    The deepest part of *base* with a cased letter is respelled with its case
    swapped: if that spelling names the same directory, the filesystem ignores
    case. With no cased part there's nothing to swap, so the answer is
    ``False``: the exact check then runs, which is always correct, just slower.
    """
    key = base.as_posix()
    with _case_lock:
        if key in _case_sensitive:
            return _case_sensitive[key]
    sensitive = False
    probe = base
    while probe.name:
        if probe.name.lower() != probe.name.upper():
            swapped = probe.with_name(probe.name.swapcase())
            try:
                sensitive = not (swapped.exists() and os.path.samefile(probe, swapped))
            except OSError:
                sensitive = False
            break
        probe = probe.parent
    with _case_lock:
        _case_sensitive[key] = sensitive
    return sensitive


def _entries(directory: Path) -> frozenset[str] | None:
    """The names in *directory*, cached while its mtime holds; ``None`` if unreadable.

    A rename or a new entry changes the directory's mtime, so the cached
    listing is dropped. A directory changed within :data:`_RECENT_NS` isn't
    cached: a further change in the same timestamp tick wouldn't move it.
    """
    key = directory.as_posix()
    try:
        mtime = os.stat(directory).st_mtime_ns
    except OSError:
        return None
    with _case_lock:
        hit = _listings.get(key)
        if hit is not None and hit[0] == mtime:
            _listings.move_to_end(key)
            return hit[1]
    try:
        names = frozenset(os.listdir(directory))
    except OSError:
        return None
    if time.time_ns() - mtime >= _RECENT_NS:
        with _case_lock:
            _listings[key] = (mtime, names)
            _listings.move_to_end(key)
            while len(_listings) > _LISTINGS_MAX:
                _listings.popitem(last=False)
    return names


def _exact_case(base: Path, rel: list[str]) -> bool:
    """Whether each name in *rel*, below *base*, is a directory entry in exact case.

    Free on a case-sensitive filesystem, where ``exists()`` already matched
    case: there it is ``True`` without listing anything.
    """
    if _is_case_sensitive(base):
        return True
    directory = base
    for name in rel:
        names = _entries(directory)
        if names is None or name not in names:
            return False
        directory = directory / name
    return True


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
        # (a) a direct .py file, or a stub that declares a module or this
        # package (a stub-only package is a namespace, #1004).
        if entry.is_file() and (
            entry.suffix == ".py" or is_stub_only_module(entry) or is_namespace_stub_init(entry)
        ):
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


def _is_standalone_root(analyzer: Any, root: Path) -> bool:
    """Whether *root* is one of the analyzer's standalone script directories (#1041)."""
    return any(
        paths_equal(root, standalone)
        for standalone in getattr(analyzer, "standalone_paths", None) or []
    )


#: The suffixes of a compiled module (``json.cpython-312-x86_64-linux-gnu.so``).
_EXTENSION_SUFFIXES = (".so", ".pyd")


def standalone_shadow(analyzer: Any, top: str) -> str | None:
    """What owns the top-level name *top* ahead of any standalone dir, or ``None`` (#1041).

    A standalone script is named from its directory only when nothing else
    already answers to that name, as Python would import it: the standard
    library, a non-standalone root (source root, project, package), a
    configured or discovered namespace package, or a module in the project's
    environment (its ``site-packages`` and ``.pth`` roots, read statically,
    #993). The answer says what, for the honest miss that names the shadow.
    An earlier standalone dir is not covered here: ``file_for_module``'s
    root order picks it, and ``module_name_for_file`` checks the round trip.
    """
    if top in sys.stdlib_module_names:
        return f"the standard library module {top}"
    standalone = getattr(analyzer, "standalone_paths", None) or []
    for root in project_roots(analyzer, RootsBoundary.MODULE_LOOKUP):
        if any(paths_equal(root, s) for s in standalone):
            continue
        found = _module_file_under(root, [top])
        if found is not None:
            return found.as_posix()
    if find_namespace_package_dirs(top, analyzer):
        return f"the namespace package {top}"
    environment = getattr(analyzer, "environment", None)
    for site in getattr(environment, "site_paths", ()) or ():
        if top in _site_tops(Path(site)):
            return f"the module {top} in the project's environment ({Path(site).as_posix()})"
    return None


#: ``site dir -> (its mtime_ns, its top-level module names)`` (#1041).
_site_tops_cache: dict[str, tuple[int, frozenset[str]]] = {}
_site_tops_lock = threading.Lock()


def _site_tops(site: Path) -> frozenset[str]:
    """The top-level module names *site* provides: packages, modules, stubs, extensions.

    A site-packages dir can hold thousands of entries, and a standalone file's
    name is checked often, so the listing is cached by the directory's mtime:
    installing or removing a top-level package changes it (#1041).
    """
    key = site.as_posix()
    try:
        mtime = site.stat().st_mtime_ns
    except OSError:
        return frozenset()
    with _site_tops_lock:
        cached = _site_tops_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    tops: set[str] = set()
    try:
        for entry in site.iterdir():
            name = entry.name
            if entry.is_dir():
                if name.isidentifier():
                    tops.add(name)
            elif name.endswith((".py", ".pyi")):
                tops.add(name.rsplit(".", 1)[0])
            elif name.endswith(_EXTENSION_SUFFIXES):
                tops.add(name.split(".", 1)[0])
    except OSError:
        return frozenset()
    result = frozenset(tops)
    with _site_tops_lock:
        _site_tops_cache[key] = (mtime, result)
    return result


def namespace_stub_inits(module_dotted: str, analyzer: Any) -> list[Path]:
    """Each portion's ``__init__.pyi`` of the namespace *module_dotted*, in portion order (#1004).

    What declares the namespace's own members, as Jedi merges them: the first
    portion (sys.path order) that declares a name is the one that counts.
    """
    inits = []
    for portion in find_namespace_package_dirs(module_dotted, analyzer):
        init = portion / "__init__.pyi"
        if init.is_file():
            inits.append(init)
    return inits


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


def read_pyproject(project_root: Path | str) -> dict[str, Any]:
    """The project's ``pyproject.toml``, parsed statically; ``{}`` if absent or unreadable."""
    path = Path(project_root) / "pyproject.toml"
    if not path.is_file():
        return {}
    import tomllib

    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        logger.debug(f"Not reading {path.as_posix()}: {error}")
        return {}


def _normalised_name(name: Any) -> str | None:
    """*name* as a distribution's import directory: lowercase, runs of ``-_.`` as ``_`` (PEP 503)."""
    if not isinstance(name, str) or not name.strip():
        return None
    return re.sub(r"[-_.]+", "_", name.strip()).lower()


def _project_names(project_root: Path) -> list[str]:
    """The project's own normalised names: ``[project].name`` and ``[tool.poetry].name``."""
    data = read_pyproject(project_root)

    def table(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    candidates = [
        table(data.get("project")).get("name"),
        table(table(data.get("tool")).get("poetry")).get("name"),
    ]
    return list(dict.fromkeys(n for n in map(_normalised_name, candidates) if n))


def detect_src_layout(project_path: Path | str) -> Path | None:
    """Return ``<project>/src`` when the project uses a src layout, else ``None``.

    The one src-layout rule (#625), shared by ``ProjectConfig`` auto-discovery
    and a ``JediAnalyzer`` built without a config, so the two never name the
    same files differently. A src layout is a ``src/`` directory holding:

    - a regular package (a subdirectory with ``__init__.py``); or
    - the project's OWN package, by its declared name (#1078): ``src/<name>``,
      where ``<name>`` is ``[project].name`` or ``[tool.poetry].name``
      normalised (PEP 503), as a package or a PEP 420 directory
      (:func:`dir_shallow_qualifies`, #444). That is where poetry-core,
      hatchling, uv_build, pdm-backend and setuptools' src-layout discovery
      look by default, so it is a declaration in effect (#1035), not a guess:
      no other directory under ``src/`` counts. Poetry's own ``src/poetry``
      is a namespace shared with poetry-core.

    A declared ``from`` / ``where`` is read by ``ProjectConfig`` first and
    wins: auto-discovery runs only when no packages were declared.
    """
    root = Path(project_path)
    src_dir = root / "src"
    try:
        if not src_dir.is_dir():
            return None
        if any((item / "__init__.py").exists() for item in src_dir.iterdir() if item.is_dir()):
            return src_dir
    except OSError:
        return None
    for name in _project_names(root):
        own = src_dir / name
        if own.is_dir() and dir_shallow_qualifies(own):
            return src_dir
    return None
