"""Path dependencies a project declares in its ``pyproject.toml``, read statically (#1035).

The user's ruling (A+): packages beside the project come only from declared or
standard Python mechanisms, never from a guess at neighbouring directories.
This module is the declared half. The environment's editable installs reach
Jedi through :mod:`pyeye.environment` (#993); pyeye's own config is in
:mod:`pyeye.config`.

Formats read, each from the project's ``pyproject.toml`` only (never
``setup.py``, which is code, nor ``requirements*.txt``):

- **uv:** ``[tool.uv.sources]`` entries with a ``path`` (a table, or a list of
  tables with markers), and ``[tool.uv.workspace]`` ``members`` (globs) minus
  ``exclude``. A glob member that would match outside the workspace root is
  dropped; a literal member path is a declaration and is kept wherever it is.
- **Poetry:** ``path`` dependencies in ``[tool.poetry.dependencies]``,
  ``[tool.poetry.group.<name>.dependencies]`` and the legacy
  ``[tool.poetry.dev-dependencies]``.
- **PEP 621 / PEP 735:** ``name @ file:...`` direct references in
  ``[project] dependencies``, ``[project.optional-dependencies]`` and
  ``[dependency-groups]``. Two placeholders are expanded by plain substitution:
  PDM's ``${PROJECT_ROOT}`` and Hatch's ``{root:uri}``. An entry with any
  other placeholder is skipped (logged at debug).

Only an existing directory counts (a wheel or sdist path is skipped). Its
import root is its ``src/`` when it has a src layout, else the directory
itself. Nothing is executed. The caller path-checks every root as it does any
configured package.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

from .path_utils import absolute_path, normalize_path, relative_within
from .project_layout import detect_src_layout

logger = logging.getLogger(__name__)

#: ``reason`` values, as ``configure_packages``' ``discovered`` reports them.
REASON_UV_SOURCE = "uv_source"
REASON_UV_WORKSPACE = "uv_workspace"
REASON_POETRY_PATH = "poetry_path"
REASON_PEP621_FILE_URL = "pep621_file_url"

_GLOB_CHARS = re.compile(r"[*?\[]")
_PERCENT = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_WINDOWS_DRIVE = re.compile(r"^/[A-Za-z]:")
_PLACEHOLDER = re.compile(r"\$\{[^}]*\}|\{[^}]*\}")


def declared_path_dependencies(project_root: Path) -> list[tuple[str, str]]:
    """Every directory *project_root*'s ``pyproject.toml`` declares, as ``(import root, reason)``.

    The import root is absolute and POSIX, in the declared spelling (see
    :func:`_import_root`); the list is in declaration order, deduplicated. ``[]`` with no ``pyproject.toml``, or one that can't be read
    (the config loader reports that one when it is the config file).
    """
    data = _pyproject(project_root)
    if not data:
        return []
    found: dict[str, str] = {}
    for directory, reason in (
        *_uv_sources(data, project_root),
        *_uv_workspace(data, project_root),
        *_poetry_paths(data, project_root),
        *_pep621_file_urls(data, project_root),
    ):
        if directory.is_dir():
            found.setdefault(_import_root(directory), reason)
        else:
            logger.debug(f"Skipping declared dependency {directory.as_posix()}: not a directory")
    return list(found.items())


def _pyproject(project_root: Path) -> dict[str, Any]:
    path = project_root / "pyproject.toml"
    if not path.is_file():
        return {}
    import tomllib

    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        logger.debug(f"Not reading declared dependencies from {path.as_posix()}: {error}")
        return {}


def _import_root(directory: Path) -> str:
    """*directory*'s import root, its ``src/`` for a src layout, in the declared spelling.

    Absolute, with ``..`` collapsed lexically but no symlink resolved (#717),
    so ``rejected_paths`` reports a refused declaration as it was written
    (``/etc``, not macOS's ``/private/etc``). Path checks and ``discovered``
    resolve it themselves.
    """
    src = detect_src_layout(directory)
    return absolute_path(src if src is not None else directory).as_posix()


def _anchored(root: Path, entry: str) -> Path:
    path = Path(entry).expanduser()
    return path if path.is_absolute() else root / path


def _table(data: Any, *keys: str) -> dict[str, Any]:
    """``data[k1][k2]...`` when every step is a table, else ``{}``."""
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    return data if isinstance(data, dict) else {}


def _uv_sources(data: dict[str, Any], root: Path) -> list[tuple[Path, str]]:
    out = []
    for spec in _table(data, "tool", "uv", "sources").values():
        for entry in spec if isinstance(spec, list) else [spec]:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                out.append((_anchored(root, entry["path"]), REASON_UV_SOURCE))
    return out


def _uv_workspace(data: dict[str, Any], root: Path) -> list[tuple[Path, str]]:
    workspace = _table(data, "tool", "uv", "workspace")
    excluded = {normalize_path(p).as_posix() for p in _members(root, workspace.get("exclude"))}
    return [
        (path, REASON_UV_WORKSPACE)
        for path in _members(root, workspace.get("members"))
        if normalize_path(path).as_posix() not in excluded
    ]


def _members(root: Path, patterns: Any) -> list[Path]:
    """Workspace *patterns* expanded under *root*: a glob never reaches outside it."""
    out: list[Path] = []
    for pattern in patterns if isinstance(patterns, list) else []:
        if not isinstance(pattern, str):
            continue
        if not _GLOB_CHARS.search(pattern):
            out.append(_anchored(root, pattern))  # a literal path is a declaration
            continue
        if ".." in Path(pattern).parts:
            continue  # a glob that climbs out of the workspace matches nothing
        try:
            matches = sorted(root.glob(pattern))
        except (ValueError, NotImplementedError, OSError):
            continue  # an absolute or unsupported pattern matches nothing
        # Resolved, so a symlinked match can't lead out either.
        real_root = normalize_path(root)
        out.extend(m for m in matches if relative_within(normalize_path(m), real_root) is not None)
    return out


def _poetry_paths(data: dict[str, Any], root: Path) -> list[tuple[Path, str]]:
    poetry = _table(data, "tool", "poetry")
    tables = [_table(poetry, "dependencies"), _table(poetry, "dev-dependencies")]
    tables += [_table(group, "dependencies") for group in _table(poetry, "group").values()]
    out = []
    for table in tables:
        for spec in table.values():
            for entry in spec if isinstance(spec, list) else [spec]:
                if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                    out.append((_anchored(root, entry["path"]), REASON_POETRY_PATH))
    return out


def _pep621_file_urls(data: dict[str, Any], root: Path) -> list[tuple[Path, str]]:
    project = _table(data, "project")
    requirements: list[Any] = list(project.get("dependencies") or [])
    for extra in _table(project, "optional-dependencies").values():
        requirements.extend(extra if isinstance(extra, list) else [])
    for group in _table(data, "dependency-groups").values():
        requirements.extend(group if isinstance(group, list) else [])  # skips include-group
    out = []
    for requirement in requirements:
        path = _file_url_path(requirement, root) if isinstance(requirement, str) else None
        if path is not None:
            out.append((path, REASON_PEP621_FILE_URL))
    return out


def _file_url_path(requirement: str, root: Path) -> Path | None:
    """The directory a ``name @ file:...`` requirement names, or ``None``."""
    spec = requirement.split(";", 1)[0]
    if "@" not in spec:
        return None
    url = spec.split("@", 1)[1].strip()
    if not url.startswith(("file:", "{root:uri}")):
        return None
    url = url.replace("${PROJECT_ROOT}", root.as_posix()).replace("{root:uri}", root.as_uri())
    if _PLACEHOLDER.search(url):
        logger.debug(f"Skipping {requirement!r}: an unsupported placeholder")
        return None
    raw = _file_url_to_path(url)
    if raw is None:
        return None
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _file_url_to_path(url: str) -> str | None:
    """The local path a ``file:`` URL names, or ``None`` for another host.

    Plain string work, with no URL library (SECURITY.md: the server imports no
    networking module). It handles ``file:///abs``, ``file://localhost/abs``,
    ``file:rel`` and ``file:///C:/x`` on Windows; ``%xx`` escapes are decoded
    as UTF-8. ``file:///${PROJECT_ROOT}`` expands to ``file:////abs``, so
    extra leading slashes collapse to one.
    """
    rest = url[len("file:") :]
    if rest.startswith("//"):
        host, sep, path = rest[2:].partition("/")
        if host not in ("", "localhost"):
            return None
        rest = sep + path
    rest = _PERCENT.sub(
        lambda m: bytes.fromhex(m.group(0).replace("%", "")).decode("utf-8", "replace"), rest
    )
    if rest.startswith("/"):
        rest = "/" + rest.lstrip("/")
        if sys.platform == "win32" and _WINDOWS_DRIVE.match(rest):
            rest = rest[1:]
    return rest


#: Appended to resolve's and inspect's not-found ``detail`` for a third-party miss.
UNDECLARED_NOTE = (
    "If it is a project beside this one, declare it as a path dependency in "
    'pyproject.toml (for example [tool.uv.sources] name = {{ path = "../{top}" }}) '
    "or add it with configure_packages."
)


def not_found_note(analyzer: Any, dotted: str) -> str | None:
    """:data:`UNDECLARED_NOTE` when *dotted*'s top-level name looks third-party (#1035).

    The same test as the environment's note (:func:`pyeye.environment.third_party_top`):
    not the standard library's and not a module of the project. pyeye no
    longer guesses neighbouring directories, so a sibling it can't see must be
    declared.
    """
    from .environment import third_party_top

    top = third_party_top(analyzer, dotted)
    return UNDECLARED_NOTE.format(top=top) if top is not None else None
