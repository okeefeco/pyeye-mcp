"""The ``structure`` kind's options, as a repository's docs-facts config gives them (#1092).

The config names a built-in kind and its options as data (ruling C19)::

    [[tool.pyeye.docs_facts.extractors]]
    kind = "structure"
    prefix = "arch"
    include = ["src/*"]
    exclude = ["*/tests/*"]

:func:`parse` validates the table and raises :class:`ValueError` (the loader's
``KindOptionsError`` is one) on any key or value it doesn't accept, naming it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: A fact ID's first segment (:data:`pyeye.docs_facts.facts.FACT_ID`).
PREFIX = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class Options:
    """What the ``structure`` kind collects, and the fact ID prefix it owns.

    Attributes:
        prefix: The first segment of every fact ID it yields.
        include: Patterns for the module files in scope (``dump.selected``).
        exclude: Patterns for module files left out.
        strict_source: Hold Jedi to source, refusing even the compiled modules
            on pyeye's own interpreter path (``dump.source_only``).
        within_areas: Also pair candidates inside one area.
    """

    prefix: str = "arch"
    include: tuple[str, ...] = ("*",)
    exclude: tuple[str, ...] = ()
    strict_source: bool = False
    within_areas: bool = False


def _patterns(key: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(p, str) and p for p in value):
        raise ValueError(f"structure: {key!r} must be a list of non-empty strings")
    return tuple(value)


def _flag(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"structure: {key!r} must be true or false")
    return value


def parse(table: Mapping[str, Any]) -> Options:
    """The options in *table* (the config entry, minus ``kind``).

    Raises:
        ValueError: On an unknown key, a value of the wrong type, a prefix that
            isn't a fact ID segment, or an ``include`` that selects nothing.
    """
    known = {"prefix", "include", "exclude", "strict_source", "within_areas"}
    unknown = sorted(set(table) - known)
    if unknown:
        raise ValueError(
            f"structure: unknown option(s) {', '.join(map(repr, unknown))}; "
            f"expected {', '.join(sorted(known))}"
        )
    defaults = Options()
    prefix = table.get("prefix", defaults.prefix)
    if not isinstance(prefix, str) or not PREFIX.fullmatch(prefix):
        raise ValueError(
            f"structure: 'prefix' must be lower-case letters, digits and '_', "
            f"starting with a letter, not {prefix!r}"
        )
    include = _patterns("include", table["include"]) if "include" in table else defaults.include
    if not include:
        raise ValueError("structure: 'include' is empty, so nothing would be collected")
    return Options(
        prefix=prefix,
        include=include,
        exclude=_patterns("exclude", table["exclude"]) if "exclude" in table else (),
        strict_source=_flag("strict_source", table.get("strict_source", False)),
        within_areas=_flag("within_areas", table.get("within_areas", False)),
    )
