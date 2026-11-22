"""A doc registry read from a data file (#1107).

A repository can keep its doc registry in its own file instead of inline in the
config: a table whose ``doc`` key lists one entry per page, each with the same
keys as an inline ``docs`` entry (``path``, ``audience``, ``kind``, and
optionally ``allow``, ``covers`` and ``site``). TOML, JSON and YAML are read by
:mod:`pyeye._data_files`, chosen by the file's suffix; nothing is imported or
run (C19).

pyeye's own registry is ``docs/facts/docs.toml``. Until the typed
:data:`~.docs.DOCS` is deleted (#1107), a test holds the two equal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import _data_files
from ..path_utils import relative_within
from .docs import DocEntry

#: pyeye's own registry file, relative to the repository root.
PYEYE_REGISTRY = "docs/facts/docs.toml"

#: The table key that holds the entries.
KEY = "doc"

#: File suffix -> :data:`pyeye._data_files.FORMATS` name.
SUFFIXES = {".toml": "toml", ".json": "json", ".yaml": "yaml", ".yml": "yaml"}


def read(root: Path, file: str) -> tuple[DocEntry, ...]:
    """The doc entries in *file*, repo-relative under *root*, in file order.

    Raises:
        ConfigError: If *file* is outside the repository, missing, of an unknown
            format, or isn't a table whose ``doc`` key lists valid entries.
    """
    # Imported here: the config module will read a registry file through this one.
    from .config import ConfigError, _doc

    path = root / file
    if relative_within(path, root) is None:
        raise ConfigError(f"doc registry {file!r} is outside the repository")
    fmt = SUFFIXES.get(path.suffix)
    if fmt is None:
        raise ConfigError(f"doc registry {file!r}: unknown format; use one of {sorted(SUFFIXES)}")
    if not path.is_file():
        raise ConfigError(f"doc registry {file!r} doesn't exist")
    data: Any = _data_files.read(path, fmt)
    entries = data.get(KEY) if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ConfigError(f"doc registry {file!r} must be a table whose {KEY!r} key is a list")
    found = []
    for i, entry in enumerate(entries):
        try:
            # One validator for inline and file entries; its message names the
            # inline position, so this one names the file as well.
            found.append(_doc(entry, i))
        except ConfigError as err:
            raise ConfigError(f"doc registry {file!r} {KEY}[{i}]: {err}") from err
    return tuple(found)
