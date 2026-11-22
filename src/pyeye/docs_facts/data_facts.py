"""Built-in fact kinds a repository configures with data (#1091, ruling C19).

A repository other than pyeye gets its facts from kinds built into the engine,
configured by data in its docs-facts config. Each reads a file; none imports
or runs one. This module holds the data-file kinds:

- ``toml``, ``json``, ``yaml``: the value at a dotted key path in a data file,
  read through :mod:`pyeye._data_files` (YAML with ``safe_load`` only).

A fact's ID is the repository's choice; its first segment is its prefix, and
the prefixes of all a repository's data facts are owned by one extractor. A
value renders as inline code, a list as a list of inline code. A missing file
or key is an :class:`~.facts.ExtractionError` naming the fact, never an empty
fact.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import _data_files
from .facts import Bindable, ExtractionError, Fact, code, code_list
from .registry import Extractor

#: The data-file kinds, by the name a config's ``from`` uses.
DATA_KINDS = _data_files.FORMATS


@dataclass(frozen=True)
class DataFact:
    """One configured fact: the value at *key* in *file*, read as *kind*."""

    id: str
    kind: str
    file: str
    key: str


def _at(data: Any, fact: DataFact) -> Any:
    """The value at *fact*'s dotted key path in *data*."""
    value = data
    for part in fact.key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ExtractionError(f"{fact.id}: {fact.file} has no key {part!r} in {fact.key!r}")
    return value


def _markdown(value: Any) -> str:
    if isinstance(value, list):
        return code_list(str(v) for v in value)
    return code(str(value))


def _read(root: Path, fact: DataFact) -> Fact:
    path = root / fact.file
    if not path.is_file():
        raise ExtractionError(f"{fact.id}: {fact.file} doesn't exist")
    value = _at(_data_files.read(path, fact.kind), fact)
    return Fact(fact.id, value, _markdown(value))


def extractor(facts: tuple[DataFact, ...]) -> Extractor:
    """One :class:`~.registry.Extractor` for a repository's configured data facts."""
    prefixes = tuple(dict.fromkeys(f.id.split(".", 1)[0] for f in facts))

    def extract(root: Path) -> Iterator[Bindable]:
        for fact in facts:
            yield _read(root, fact)

    return Extractor("data", prefixes, extract)
