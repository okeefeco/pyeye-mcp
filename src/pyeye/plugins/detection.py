"""How a framework plugin decides its framework is used (#1143).

Detection gates whether a plugin's tools are LISTED (the tools themselves run
against any ``project_path``). It runs in two steps, cheapest first:

1. **Declared dependencies** (:func:`declared_dependencies`): the names in the
   project root's ``pyproject.toml`` (PEP 621 dependencies and optional
   groups, PEP 735 dependency groups, uv dev-dependencies, Poetry
   dependencies and groups), ``requirements*.txt`` and ``requirements/*.txt``,
   ``Pipfile``, and the ``uv.lock`` / ``poetry.lock`` package lists. A handful
   of files, read once.
2. **A bounded import scan** (:func:`scan_for_imports`): the project tree is
   walked for a file that imports the framework, through the same exclusions
   as every project scan. The walk stops after :data:`SCAN_ENTRY_LIMIT`
   directory entries. Stopping there proves nothing either way, so it reports
   ``"not_determined"``, never ``"not_detected"`` (absence vs zero).

Before #1143 the scan ran first and was unbounded: a large tree with no early
import (``$HOME``, a monorepo) was walked in full before the server read stdin.
"""

from __future__ import annotations

import logging
import re
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

from ..async_utils import filtered_walk

logger = logging.getLogger(__name__)

#: The outcome of detecting a framework. ``not_determined``: the scan stopped at
#: its bound before it found an import, so the framework may still be used.
Detection = Literal["detected", "not_detected", "not_determined"]

#: How many directory entries (files and subdirectories) the import scan lists
#: before it gives up with ``not_determined``.
SCAN_ENTRY_LIMIT = 20_000

#: A source file larger than this is not read by the import scan.
SCAN_MAX_FILE_BYTES = 1_000_000

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize_name(name: str) -> str:
    """A distribution name in its PEP 503 normal form (``Flask_Login`` -> ``flask-login``)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str | None:
    """The distribution a PEP 508 requirement string names, or ``None`` for an option line."""
    match = _NAME.match(requirement)
    return normalize_name(match.group(1)) if match else None


def _requirement_names(requirements: Iterable[Any]) -> set[str]:
    """The names of the string entries of *requirements* (PEP 735 includes are dicts)."""
    names = set()
    for requirement in requirements:
        if isinstance(requirement, str):
            name = _requirement_name(requirement)
            if name:
                names.add(name)
    return names


def _table(data: Any, *keys: str) -> dict[str, Any]:
    """``data[k1][k2]...`` when every step is a table, else ``{}``."""
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    return data if isinstance(data, dict) else {}


def _list(data: Any, *keys: str) -> list[Any]:
    """``data[k1][k2]...`` when it is a list, else ``[]``."""
    *head, last = keys
    value = _table(data, *head).get(last)
    return value if isinstance(value, list) else []


def _read_toml(path: Path) -> dict[str, Any] | None:
    """*path* parsed as TOML, or ``None`` (logged) when it can't be read or parsed."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        logger.warning(f"Plugin detection: cannot read {path.as_posix()}: {error}")
        return None


def _pyproject_names(data: dict[str, Any]) -> set[str]:
    names = _requirement_names(_list(data, "project", "dependencies"))
    for extra in _table(data, "project", "optional-dependencies").values():
        names |= _requirement_names(extra if isinstance(extra, list) else [])
    for group in _table(data, "dependency-groups").values():
        names |= _requirement_names(group if isinstance(group, list) else [])
    names |= _requirement_names(_list(data, "tool", "uv", "dev-dependencies"))
    poetry = _table(data, "tool", "poetry")
    tables = [_table(poetry, "dependencies"), _table(poetry, "dev-dependencies")]
    tables += [_table(group, "dependencies") for group in _table(poetry, "group").values()]
    for table in tables:
        names |= {normalize_name(name) for name in table}
    return names


def _requirements_txt_names(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        logger.warning(f"Plugin detection: cannot read {path.as_posix()}: {error}")
        return set()
    names = set()
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):  # -r, -e, --index-url: not a name
            name = _requirement_name(line)
            if name:
                names.add(name)
    return names


def _lock_names(data: dict[str, Any]) -> set[str]:
    packages = data.get("package")
    if not isinstance(packages, list):
        return set()
    return {
        normalize_name(package["name"])
        for package in packages
        if isinstance(package, dict) and isinstance(package.get("name"), str)
    }


def declared_dependencies(root: Path) -> set[str]:
    """Every distribution name *root*'s manifests and lock files declare, normalized."""
    names: set[str] = set()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and (data := _read_toml(pyproject)) is not None:
        names |= _pyproject_names(data)
    requirement_files = [*root.glob("requirements*.txt"), *root.glob("requirements/*.txt")]
    for path in requirement_files:
        if path.is_file():
            names |= _requirements_txt_names(path)
    pipfile = root / "Pipfile"
    if pipfile.is_file() and (data := _read_toml(pipfile)) is not None:
        for section in ("packages", "dev-packages"):
            names |= {normalize_name(name) for name in _table(data, section)}
    for lock in ("uv.lock", "poetry.lock"):
        path = root / lock
        if path.is_file() and (data := _read_toml(path)) is not None:
            names |= _lock_names(data)
    return names


def declares(root: Path, framework: str) -> bool:
    """Whether *root* declares *framework*, or one of its ``<framework>-*`` extensions."""
    prefix = f"{framework}-"
    return any(name == framework or name.startswith(prefix) for name in declared_dependencies(root))


def scan_for_imports(
    root: Path,
    markers: tuple[str, ...],
    read: Callable[[Path], str | None],
    *,
    limit: int | None = None,
) -> Detection:
    """Walk *root* for a ``.py`` file containing one of *markers*, listing at most *limit* entries.

    *read* returns a file's text, or ``None`` when it can't be read (the
    plugin's own read contract). ``detected`` on the first hit;
    ``not_detected`` when the whole tree was scanned; ``not_determined`` when
    the bound stopped the walk first. *limit* defaults to :data:`SCAN_ENTRY_LIMIT`.
    """
    limit = SCAN_ENTRY_LIMIT if limit is None else limit
    seen = 0
    for here, dirnames, filenames in filtered_walk(root):
        if seen >= limit:  # checked on entering a directory: a tree that ends here was scanned
            logger.info(
                f"Plugin detection: stopped scanning {root.as_posix()} after {seen} entries; "
                f"not determined"
            )
            return "not_determined"
        seen += len(dirnames) + len(filenames)
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = here / name
            try:
                if path.stat().st_size > SCAN_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            content = read(path)
            if content is not None and any(marker in content for marker in markers):
                return "detected"
    return "not_detected"
