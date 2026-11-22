"""The one place pyeye reads a TOML, JSON or YAML data file (#1091).

ProjectConfig and the docs-facts data kinds both read data files; they share
these readers so a format is parsed one way everywhere. YAML is read with
``yaml.safe_load`` only, never a loader that can build objects (the
maintainer's ruling via designer, 2026-11-22; PyYAML is a runtime dependency,
#1094). Reading never runs code.

This is a lower layer: it must not import ``pyeye.mcp``.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

#: The formats :func:`read` knows, by name.
FORMATS = ("toml", "json", "yaml")


def read_toml(path: Path) -> dict[str, Any]:
    """*path* parsed as TOML (stdlib ``tomllib``)."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def read_json(path: Path) -> Any:
    """*path* parsed as JSON."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_yaml(path: Path) -> Any:
    """*path* parsed as YAML with ``yaml.safe_load``: plain data only."""
    import yaml

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read(path: Path, fmt: str) -> Any:
    """*path* parsed as *fmt*, one of :data:`FORMATS`."""
    readers = {"toml": read_toml, "json": read_json, "yaml": read_yaml}
    if fmt not in readers:
        raise ValueError(f"unknown data format {fmt!r}; expected one of {FORMATS}")
    return readers[fmt](path)
