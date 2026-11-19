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

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .path_utils import normalize_path, paths_equal

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


@dataclass(frozen=True)
class ProjectEnvironment:
    """A project's environment: where it is, how it was found, and its import roots.

    Attributes:
        path: The environment's directory, or ``None`` when none was found.
        source: ``config``, ``project``, ``VIRTUAL_ENV``, ``CONDA_PREFIX`` or ``none``.
        site_paths: Its import roots, as Python's ``site`` module computes them:
            its ``site-packages`` and the plain-path lines of the ``.pth`` files
            there, resolved, POSIX. ``[]`` with no environment.
    """

    path: Path | None
    source: str
    site_paths: tuple[str, ...] = field(default=())

    def as_response(self) -> dict[str, Any]:
        """The always-present ``environment`` key of ``configure_packages`` (#993)."""
        return {"path": self.path.as_posix() if self.path else None, "source": self.source}


def discover(project_path: str | Path, configured: Any = None) -> ProjectEnvironment:
    """The project's environment, by the precedence in this module's docstring.

    Args:
        project_path: The project root.
        configured: The config's ``environment`` value: a path (absolute, or
            relative to the project; ``~`` expanded), ``False`` to opt out, or
            ``None`` when unset. A path the path check refuses is skipped with
            a warning, like any refused config entry (#856, #909).
    """
    root = normalize_path(project_path)
    if configured is False:
        return ProjectEnvironment(None, SOURCE_CONFIG)
    if configured:
        env = _checked_config_environment(root, str(configured))
        if env is not None:
            return _environment(env, SOURCE_CONFIG)
    for base in _project_bases(root):
        for name in VENV_NAMES:
            candidate = base / name
            if (candidate / "pyvenv.cfg").is_file():
                return _environment(normalize_path(candidate), SOURCE_PROJECT)
    own = normalize_path(sys.prefix)
    for var in ACTIVATION_VARS:
        value = os.environ.get(var)
        if not value:
            continue
        env = normalize_path(value)
        if env.is_dir() and not paths_equal(env, own):
            return _environment(env, var)
    return ProjectEnvironment(None, SOURCE_NONE)


def _project_bases(root: Path) -> list[Path]:
    """Where an in-project venv may be: the root, and its parent if the root is a package."""
    return [root, root.parent] if (root / "__init__.py").is_file() else [root]


def _checked_config_environment(root: Path, configured: str) -> Path | None:
    """The configured environment's directory, if it exists and passes the path check."""
    from .exceptions import ValidationError
    from .validation import PathValidator

    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        PathValidator.validate_final(path.as_posix(), root)
    except ValidationError as error:
        logger.warning(f"Skipping config environment {configured}: {error}")
        return None
    resolved = normalize_path(path)
    if not resolved.is_dir():
        logger.warning(f"Config environment {configured} does not exist; ignoring it")
        return None
    return resolved


def _environment(path: Path, source: str) -> ProjectEnvironment:
    return ProjectEnvironment(path, source, tuple(site_paths(path)))


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
    climbing to ``/``) is dropped with a warning, and its ``.pth`` files are
    never read.
    """
    out: list[str] = []
    for site_dir in _site_packages_dirs(env):
        if not _allowed(site_dir, env):
            continue
        out.append(site_dir.as_posix())
        for pth in sorted(site_dir.glob("*.pth")):
            out.extend(_pth_paths(site_dir, pth))
    return list(dict.fromkeys(out))


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


def _pth_paths(site_dir: Path, pth: Path) -> list[str]:
    """The directories *pth* adds, as ``site.addpackage`` reads them, minus its code lines."""
    try:
        lines = pth.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for raw in lines:
        line = raw.rstrip()
        if not line or line.startswith("#") or _PTH_IMPORT.match(line):
            continue
        entry = Path(line) if Path(line).is_absolute() else site_dir / line
        if entry.is_dir():
            resolved = normalize_path(entry)
            if _allowed(resolved, pth):
                out.append(resolved.as_posix())
    return out


def _allowed(resolved: Path, source: Path) -> bool:
    """Whether the RESOLVED import root *resolved* passes the walkers' prune test (#993)."""
    from .validation import unwalkable_root

    if not unwalkable_root(resolved):
        return True
    logger.warning(
        f"Skipping environment path {resolved.as_posix()} (from {source.as_posix()}): "
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
    top = dotted.split(".", 1)[0]
    if not top.isidentifier() or top in sys.stdlib_module_names:
        return None
    from .project_layout import file_for_module

    if file_for_module(analyzer, top) is not None:
        return None
    return NO_ENVIRONMENT_NOTE
