"""The project's Python environment, found and read the way Python's conventions say (#993).

pyeye can run outside the project's environment (the Claude Code plugin, ``uvx``,
``uv tool``), so it can't rely on its own interpreter's ``sys.path`` for the
project's third-party packages. Before #993 it didn't: Jedi analysed with its
default environment, which under an isolated install is pyeye's own, so a
project's imports resolved against PYEYE's dependencies (or not at all).

This module finds the project's environment and reads its import roots
STATICALLY, as Python's ``site`` module would compute them, without ever running
the environment's interpreter: a repository can ship its own ``.venv``, and
pyeye never runs project code (SECURITY.md).

Precedence (the maintainer's ruling; standard conventions with one deliberate
deviation, recorded in the decision entry):

1. the config's ``environment`` (a path, or ``false`` to opt out), as pyright
   and VS Code take an explicit interpreter;
2. a venv in the project: ``.venv``, ``venv`` or ``env`` holding a
   ``pyvenv.cfg`` (one level up too, for a project that is itself a package).
   It ranks ABOVE an activated environment because one server answers for
   many projects (#665), as editors prefer the workspace's own venv;
3. the activated environment, ``VIRTUAL_ENV`` then ``CONDA_PREFIX``, unless it
   is pyeye's own (``sys.prefix``);
4. none: third-party imports don't resolve, and pyeye says why.
"""

from __future__ import annotations

import ast
import functools
import logging
import os
import re
import stat
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .path_utils import absolute_path, normalize_path, paths_equal

logger = logging.getLogger(__name__)

#: The directory names of an in-project virtual environment, in the order tried.
VENV_NAMES: tuple[str, ...] = (".venv", "venv", "env")

#: The activation variables, in the order tried.
ACTIVATION_VARS: tuple[str, ...] = ("VIRTUAL_ENV", "CONDA_PREFIX")

#: ``source`` values: where the environment came from.
SOURCE_CONFIG = "config"
SOURCE_PROJECT = "project"
SOURCE_NONE = "none"

_PTH_IMPORT = re.compile(r"^import[ \t]")
#: The one import-line shape whose module is read: ``import M`` (then
#: anything after a ``;``), with M a plain module name (#1035).
_PTH_FINDER_IMPORT = re.compile(r"import[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*")

#: Bounds on what one environment's ``.pth`` files may cost (#993 review): the
#: environment can come from the repository. Each is far above a real
#: environment's (an editable install adds one line; a large conda env, tens).
#: Hitting one logs a warning and reads no further.
MAX_PTH_BYTES = 1 << 20  # per .pth file; the rest of the file is ignored
MAX_PTH_LINES = 1000  # paths per .pth file
MAX_SITE_PATHS = 1000  # per environment: import roots that exist (junk lines can't use it up)
MAX_PTH_LOOKUPS = 20_000  # per environment: .pth paths looked up, found or not; bounds the time
#: Editable-install finder modules (#1035): real ones are a few KB.
MAX_FINDER_BYTES = 64 << 10  # per finder module; a bigger one is not read
MAX_FINDER_MODULES = 32  # per environment, far above one per editable install
#: What reading one finder module costs against MAX_PTH_LOOKUPS: one lookup
#: per KiB it may hold, so parsing is paid for like the lookups it replaces.
FINDER_LOOKUP_COST = MAX_FINDER_BYTES >> 10


@dataclass(frozen=True)
class ProjectEnvironment:
    """A project's environment: where it is, how it was found, and its import roots.

    Attributes:
        path: The environment's directory in the caller's spelling (#717): no
            symlink resolved, as configured, found under the project root as
            given, or as the activation variable names it. ``None`` when none
            was found.
        source: ``config``, ``project``, ``VIRTUAL_ENV``, ``CONDA_PREFIX`` or ``none``.
        site_paths: Its import roots, as Python's ``site`` module computes them:
            its ``site-packages`` and the plain-path lines of the ``.pth`` files
            there, resolved, POSIX, each path-checked. ``[]`` with no environment.
    """

    path: Path | None
    source: str
    site_paths: tuple[str, ...] = field(default=())

    def as_response(self) -> dict[str, Any]:
        """The always-present ``environment`` key of ``configure_packages`` (#993)."""
        return {"path": self.path.as_posix() if self.path else None, "source": self.source}


def discover(project_path: str | Path, configured: Any = None) -> ProjectEnvironment:
    """The project's environment, by the precedence in this module's docstring.

    Every candidate is path-checked on its RESOLVED form, whatever its source
    (#993 review): a refused one is skipped with a warning and discovery
    continues to the next.

    Args:
        project_path: The project root.
        configured: The config's ``environment`` value: a path (absolute, or
            relative to the project; ``~`` expanded), ``False`` to opt out, or
            ``None`` when unset. A path the path check refuses is skipped with
            a warning, like any refused config entry (#856, #909).
    """
    spelled_root = absolute_path(project_path)
    if configured is False:
        return ProjectEnvironment(None, SOURCE_CONFIG)
    if configured:
        found = _checked_config_environment(spelled_root, str(configured))
        if found is not None:
            return found
    for base in _project_bases(spelled_root):
        for name in VENV_NAMES:
            candidate = base / name
            if (candidate / "pyvenv.cfg").is_file():
                found = _environment(candidate, SOURCE_PROJECT)
                if found is not None:
                    return found
    own = normalize_path(sys.prefix)
    for var in ACTIVATION_VARS:
        value = os.environ.get(var)
        if not value:
            continue
        spelled = absolute_path(Path(value).expanduser())
        if spelled.is_dir() and not paths_equal(spelled, own):
            found = _environment(spelled, var)
            if found is not None:
                return found
    return ProjectEnvironment(None, SOURCE_NONE)


def _project_bases(root: Path) -> list[Path]:
    """Where an in-project venv may be: the root, and its parent if the root is a package.

    The parent is skipped when someone else could have planted a venv there
    (#993 review): on POSIX, a world-writable parent (the sticky ``/tmp``) or
    one the current user doesn't own.
    """
    if not (root / "__init__.py").is_file():
        return [root]
    return [root, root.parent] if _trusted_dir(root.parent) else [root]


def _trusted_dir(directory: Path) -> bool:
    """Whether only the current user can have created *directory*'s entries (POSIX).

    Not when another user owns it or can write to it: world- OR group-writable.
    """
    getuid = getattr(os, "getuid", None)
    if getuid is None:  # Windows: no owner/mode model to test
        return True
    try:
        info = directory.stat()
    except OSError:
        return False
    if info.st_mode & (stat.S_IWOTH | stat.S_IWGRP) or info.st_uid != getuid():
        logger.warning(
            f"Not looking for a venv in {directory.as_posix()}: "
            "it is group- or world-writable, or owned by another user"
        )
        return False
    return True


def _checked_config_environment(spelled_root: Path, configured: str) -> ProjectEnvironment | None:
    """The configured environment, if it exists and passes the path checks."""
    from .exceptions import ValidationError
    from .validation import PathValidator

    path = Path(configured).expanduser()
    spelled = path if path.is_absolute() else absolute_path(spelled_root / path)
    try:
        PathValidator.validate_final(spelled.as_posix(), spelled_root)
    except ValidationError as error:
        logger.warning(f"Skipping config environment {configured}: {error}")
        return None
    if not spelled.is_dir():
        logger.warning(f"Config environment {configured} does not exist; ignoring it")
        return None
    return _environment(spelled, SOURCE_CONFIG)


def _environment(spelled: Path, source: str) -> ProjectEnvironment | None:
    """The environment at *spelled*, or ``None`` when its RESOLVED form is refused.

    A venv symlinked into a credential store, or ``VIRTUAL_ENV=/etc``, is
    refused (#993 review); so is an ancestor of a restricted directory.
    """
    resolved = normalize_path(spelled)
    if not _allowed(resolved, spelled, what=f"{source} environment"):
        return None
    return ProjectEnvironment(spelled, source, tuple(site_paths(resolved)))


def site_paths(env: Path) -> list[str]:
    """*env*'s import roots, read from disk as Python's ``site`` module computes them.

    Its ``site-packages`` (``lib/pythonX.Y/site-packages`` on POSIX, preferring
    the version ``pyvenv.cfg`` names; ``Lib/site-packages`` on Windows), then,
    for each ``.pth`` file there in name order, its plain-path lines. A
    ``.pth`` line that starts with ``import`` is code that ``site`` would run:
    it is skipped, never executed. Nothing here runs the environment's
    interpreter.

    The environment can come from the repository, so every root is path-checked
    on its RESOLVED form, as the walkers prune (#856, #909): one that is, is
    inside, or is an ancestor of a restricted directory (a symlinked
    ``site-packages``, a ``.pth`` line naming ``/etc``, a home's ``.ssh``, or
    climbing to ``/``) is dropped with a warning, and a dropped
    ``site-packages``' ``.pth`` files are never read. The work is bounded:
    :data:`MAX_SITE_PATHS` roots that exist and :data:`MAX_PTH_LOOKUPS` lookups
    per environment, and per file :data:`MAX_PTH_BYTES` and :data:`MAX_PTH_LINES`.
    Only roots that exist count toward :data:`MAX_SITE_PATHS`, so a junk
    ``.pth`` can't starve a later file's real entries; the lookup ceiling,
    far higher, bounds the time a set of junk files can take.
    """
    out: dict[str, None] = {}
    lookups = MAX_PTH_LOOKUPS
    seen_finders: set[str] = set()  # each finder module read once per environment (#1035)
    for site_dir in _site_packages_dirs(env):
        if not _allowed(site_dir, site_dir, what="site-packages"):
            continue
        out[site_dir.as_posix()] = None
        for pth in sorted(site_dir.glob("*.pth")):
            if lookups <= 0:
                logger.warning(
                    f"Environment {env.as_posix()}: over {MAX_PTH_LOOKUPS} .pth paths "
                    "looked up; reading no further"
                )
                return list(out)
            entries, looked_up, finders = _cached_pth_paths(pth, lookups)
            lookups -= max(1, looked_up)
            if finders:
                found, cost = _finder_paths(site_dir, finders, seen_finders, lookups)
                lookups -= cost
                entries = (*entries, *found)
            for entry in entries:
                if entry in out:
                    continue
                if len(out) >= MAX_SITE_PATHS:
                    logger.warning(
                        f"Environment {env.as_posix()} adds over {MAX_SITE_PATHS} "
                        "import roots; reading no further"
                    )
                    return list(out)
                out[entry] = None
    return list(out)


def _site_packages_dirs(env: Path) -> list[Path]:
    windows = env / "Lib" / "site-packages"
    if windows.is_dir():
        return [normalize_path(windows)]
    candidates = sorted((env / "lib").glob("python*/site-packages"))
    version = _pyvenv_version(env)
    if version:
        preferred = [c for c in candidates if c.parent.name == f"python{version}"]
        candidates = preferred or candidates
    return list(dict.fromkeys(normalize_path(c) for c in candidates if c.is_dir()))


def _pyvenv_version(env: Path) -> str | None:
    """``X.Y`` from ``pyvenv.cfg``'s ``version`` / ``version_info``, if it says."""
    try:
        text = (env / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*version(?:_info)?\s*=\s*(\d+)\.(\d+)", text, re.MULTILINE)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def _cached_pth_paths(pth: Path, budget: int) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
    """:func:`_pth_paths`, cached while the file is unchanged (#993 review).

    Each analyzer rebuild and each ``configure_packages`` reads the environment
    again. Keyed on the file and its stat, only a changed ``.pth`` is re-read.

    A directory a ``.pth`` line names but that is created only AFTER the file
    was first read is missed until the ``.pth`` changes (#993 re-review). That
    is fine: installers write the target first (an editable install's source
    tree exists before its ``.pth`` is written), and a new analyzer for a new
    session reads it afresh. Finder modules are not read here, so a finder
    that changes on its own is never served stale (#1035 review).
    """
    try:
        info = pth.stat()
    except OSError:
        return (), 0, ()
    return _pth_paths(pth, min(budget, MAX_PTH_LINES), info.st_mtime_ns, info.st_size)


@functools.lru_cache(maxsize=512)
def _pth_paths(
    pth: Path, limit: int, _mtime_ns: int, _size: int
) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
    """The directories *pth*'s plain lines add, the paths looked up, and its finder modules.

    As ``site.addpackage`` reads a ``.pth``, minus its code lines: a code line
    is never run. ``import M[; ...]`` (M a plain name) names an editable
    install's finder module, returned deduplicated for :func:`_finder_paths`
    to read (#1035). Bounded: at most :data:`MAX_PTH_BYTES` are read and
    *limit* distinct paths looked up; lines are deduplicated first. Each
    directory is path-checked on its RESOLVED form. *_mtime_ns* and *_size*
    only key the cache.
    """
    try:
        with pth.open("rb") as handle:
            data = handle.read(MAX_PTH_BYTES + 1)
    except OSError:
        return (), 0, ()
    if len(data) > MAX_PTH_BYTES:
        logger.warning(f"{pth.as_posix()} is over {MAX_PTH_BYTES} bytes; reading only the start")
        data = data[:MAX_PTH_BYTES]
    lines: dict[str, None] = {}
    finders: dict[str, None] = {}
    for raw in data.decode("utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        if not line or line.startswith("#") or line in lines:
            continue
        if _PTH_IMPORT.match(line):
            match = _PTH_FINDER_IMPORT.fullmatch(line.split(";", 1)[0])
            if match is not None and len(finders) < MAX_FINDER_MODULES:
                finders[match.group(1)] = None
            continue
        if len(lines) >= limit:
            logger.warning(f"{pth.as_posix()}: path limit ({limit}) reached; reading no further")
            break
        lines[line] = None
    out = _checked_dirs(lines, pth)
    return tuple(out), len(lines), tuple(finders)


def _checked_dirs(entries: Iterable[str], source: Path) -> list[str]:
    """The existing directories among *entries* that pass the path check, resolved, POSIX."""
    out: dict[str, None] = {}
    for line in entries:
        entry = Path(line) if Path(line).is_absolute() else source.parent / line
        if entry.is_dir():
            resolved = normalize_path(entry)
            if _allowed(resolved, source, what=".pth path"):
                out[resolved.as_posix()] = None
    return list(out)


def _finder_paths(
    site_dir: Path, names: Iterable[str], seen: set[str], lookups: int
) -> tuple[list[str], int]:
    """The import roots *names*' finder modules give, and what reading them cost (#1035).

    Each module is read at most once per environment (*seen*), and at most
    :data:`MAX_FINDER_MODULES` per environment, whatever they contain. Each
    read is charged :data:`FINDER_LOOKUP_COST` against the lookup budget, and
    each root it gives one more. Returns the roots and the lookups charged.
    """
    roots: list[str] = []
    cost = 0
    for name in names:
        if name in seen:
            continue
        if len(seen) >= MAX_FINDER_MODULES or lookups - cost < FINDER_LOOKUP_COST:
            logger.warning(f"{site_dir.as_posix()}: finder budget reached; reading no more")
            break
        seen.add(name)
        cost += FINDER_LOOKUP_COST
        targets = _finder_module_roots(site_dir / f"{name}.py")[: max(0, lookups - cost)]
        cost += len(targets)
        roots.extend(_checked_dirs(targets, site_dir / f"{name}.py"))
    return roots, cost


#: Parsed finder modules, keyed on (path, device, inode, mtime, size): each is
#: parsed at most once while it is unchanged, across environments too.
_FINDER_CACHE: dict[tuple[str, int, int, int, int], tuple[str, ...]] = {}
_FINDER_CACHE_SIZE = 128


def _finder_module_roots(module: Path) -> tuple[str, ...]:
    """The roots an editable install's finder *module* names, read as text, never run (#1035).

    *module* is read only if it is a regular file, not a symlink, and at most
    :data:`MAX_FINDER_BYTES`. On POSIX it is opened with ``O_NOFOLLOW`` and
    checked with ``fstat`` on the same descriptor, so a swap between the check
    and the read can't redirect it. It is parsed with :mod:`ast` and never
    imported, and only the two literal shapes :func:`_finder_targets` accepts
    are read. A target's root is the directory above it, and only when the
    mapped name is the target's own name (:func:`_root_for`). A parse failure
    reads nothing.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        if not hasattr(os, "O_NOFOLLOW") and module.is_symlink():
            return ()
        fd = os.open(module, flags)
    except OSError:
        return ()  # absent, or a symlink (O_NOFOLLOW refuses it)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FINDER_BYTES:
            if stat.S_ISREG(info.st_mode):
                logger.warning(f"Not reading {module.as_posix()}: over {MAX_FINDER_BYTES} bytes")
            return ()
        key = (module.as_posix(), info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        if key in _FINDER_CACHE:
            return _FINDER_CACHE[key]
        data = os.read(fd, MAX_FINDER_BYTES + 1)
    except OSError:
        return ()
    finally:
        os.close(fd)
    roots = _parse_finder(module, data[:MAX_FINDER_BYTES])
    if len(_FINDER_CACHE) >= _FINDER_CACHE_SIZE:
        _FINDER_CACHE.pop(next(iter(_FINDER_CACHE)))
    _FINDER_CACHE[key] = roots
    return roots


def _parse_finder(module: Path, data: bytes) -> tuple[str, ...]:
    """The roots in a finder module's *data*: the two literal shapes only, at most MAX_PTH_LINES."""
    try:
        tree = ast.parse(data.decode("utf-8", errors="replace"), filename=module.as_posix())
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        logger.debug(f"Not reading {module.as_posix()}: {error}")
        return ()
    roots: dict[str, None] = {}
    for statement in tree.body:
        for name, target in _finder_targets(statement):
            root = _root_for(name, target)
            if root is not None:
                roots[root] = None
            if len(roots) >= MAX_PTH_LINES:
                logger.warning(f"{module.as_posix()}: path limit ({MAX_PTH_LINES}) reached")
                return tuple(roots)
    return tuple(roots)


def _str(node: ast.AST | None) -> str | None:
    """*node*'s value when it is a plain string literal, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _finder_targets(statement: ast.stmt) -> list[tuple[str, str]]:
    """``(mapped name, target path)`` pairs from one top-level *statement*."""
    if isinstance(statement, ast.AnnAssign | ast.Assign):
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        value = statement.value
        if len(names) != 1 or not isinstance(value, ast.Dict) or None in value.keys:
            return []
        pairs: list[tuple[str, str]] = []
        for key_node, value_node in zip(value.keys, value.values, strict=True):
            key = _str(key_node)
            if key is None:
                return []
            if names[0] == "MAPPING" and (path := _str(value_node)) is not None:
                pairs.append((key, path))
            elif names[0] == "NAMESPACES" and isinstance(value_node, ast.List):
                paths = [_str(item) for item in value_node.elts]
                if None in paths:
                    return []
                pairs.extend((key, p) for p in paths if p is not None)
            else:
                return []
        return pairs if names[0] in ("MAPPING", "NAMESPACES") else []
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        call = statement.value
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "map_module"
            and len(call.args) == 2
            and not call.keywords
        ):
            name, path = _str(call.args[0]), _str(call.args[1])
            if name is not None and path is not None:
                return [(name, path)]
    return []


def _root_for(name: str, target: str) -> str | None:
    """The sys.path root that imports *target* as *name*, or ``None``.

    *target* is a package directory, a package's ``__init__.py`` or a module
    file, given absolute. The root is the directory above it, and only when
    *name* (a plain, undotted name) is the target's own name.
    """
    from .project_layout import package_kind

    path = Path(target)
    if not name.isidentifier() or not path.is_absolute():
        return None
    # The one package predicate (#625); asked only of a .py, so a mapped
    # directory costs no stat here.
    if path.suffix == ".py" and package_kind(path) == "regular":
        path = path.parent
    own = path.stem if path.suffix == ".py" else path.name
    return path.parent.as_posix() if own == name else None


def _allowed(resolved: Path, source: Path, *, what: str) -> bool:
    """Whether the RESOLVED *resolved* passes the walkers' prune test (#856, #909, #993).

    Refused when it is, is inside, or is an ancestor of a restricted directory
    or a credential store: ``/`` on the import path would make ``/etc``'s
    modules importable as a namespace package.
    """
    from .validation import unwalkable_root

    if not unwalkable_root(resolved):
        return True
    logger.warning(
        f"Skipping {what} {resolved.as_posix()} (from {source.as_posix()}): "
        "it is, is inside, or contains a restricted directory"
    )
    return False


#: Projects already warned about having no environment (one warning each).
_WARNED: set[str] = set()


def warn_once_if_none(project_path: str | Path, env: ProjectEnvironment) -> None:
    """Log, once per project, that no environment was found (#993)."""
    if env.source != SOURCE_NONE:
        return
    key = normalize_path(project_path).as_posix()
    if key in _WARNED:
        return
    _WARNED.add(key)
    logger.warning(
        f"No Python environment found for {key}: its third-party imports won't resolve. "
        "Set `environment` in the project's pyeye config to the virtualenv's directory."
    )


#: Appended to resolve's and inspect's not-found ``detail`` (#993, #568).
NO_ENVIRONMENT_NOTE = (
    "No project environment was found, so third-party packages can't be seen: "
    "set `environment` in the project's pyeye config to its virtualenv."
)


def not_found_note(analyzer: Any, dotted: str) -> str | None:
    """:data:`NO_ENVIRONMENT_NOTE` when *dotted* looks third-party and no environment was found.

    Third-party means its top-level name is neither the standard library's nor
    a module of the project's own roots. Then "doesn't exist" and "couldn't
    see the venv" would otherwise read the same (#568).
    """
    env = getattr(analyzer, "environment", None)
    if env is None or env.source != SOURCE_NONE:
        return None
    return NO_ENVIRONMENT_NOTE if third_party_top(analyzer, dotted) is not None else None


def third_party_top(analyzer: Any, dotted: str) -> str | None:
    """*dotted*'s top-level name when it looks third-party, else ``None`` (#993, #1035).

    Third-party: an identifier that is neither a standard-library module nor a
    module of the project's own roots. The one test behind both not-found
    notes (no environment; an undeclared sibling).
    """
    top = dotted.split(".", 1)[0]
    if not top.isidentifier() or top in sys.stdlib_module_names:
        return None
    from .project_layout import file_for_module

    if file_for_module(analyzer, top) is not None:
        return None
    return top
