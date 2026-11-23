"""The ``structure`` kind's options, as a repository's docs-facts config gives them (#1092).

The config names a built-in kind and its options as data (ruling C19)::

    [[tool.pyeye.docs_facts.extractors]]
    kind = "structure"
    prefix = "arch"
    include = ["src/*"]
    exclude = ["*/tests/*"]
    min_score = 0.9
    candidates_page = "docs/facts/arch.candidates.md"
    pairs = [["pkg.a.load", "pkg.b.read"]]      # curated by a planner, as data

    [tool.pyeye.docs_facts.extractors.areas]   # area id -> module patterns
    console = ["poetry.console*"]
    installation = ["poetry.installation*"]

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

#: An area ID: one later fact ID segment (``arch.cross.<area>``).
AREA = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")

#: The lowest score a scored candidate needs to be labelled and listed, by
#: default: about the RFC #1083 trial's top-150 cut (0.91), which leaves 68
#: candidates on Poetry 2.5.2 and 165 on Scrapy 2.20.0 (#1092). The scorer alone
#: misses real duplicates (they can share no name word, or score under 0.6), so
#: a planner's curated ``pairs`` are how those are labelled.
MIN_SCORE = 0.9

#: A curated pair's length: two handles.
PAIR_SIZE = 2


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
        areas: Area ID -> :mod:`fnmatch` patterns on module names. A module no
            area matches is its own area; with no areas, every module is.
        min_score: The lowest candidate score whose pair is labelled.
        candidates_page: Where ``generate`` writes the advisory candidate page,
            or ``None`` for nowhere (the candidates are never facts).
        pairs: Handle pairs a planner curated (RFC #1083 step 4.2), labelled
            from pyeye's facts like scored candidates, whatever their score.
    """

    prefix: str = "arch"
    include: tuple[str, ...] = ("*",)
    exclude: tuple[str, ...] = ()
    strict_source: bool = False
    within_areas: bool = False
    areas: tuple[tuple[str, tuple[str, ...]], ...] = ()
    min_score: float = MIN_SCORE
    candidates_page: str | None = None
    pairs: tuple[tuple[str, str], ...] = ()


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
    known = {
        "prefix",
        "include",
        "exclude",
        "strict_source",
        "within_areas",
        "areas",
        "min_score",
        "candidates_page",
        "pairs",
    }
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
        areas=_areas(table.get("areas", {})),
        min_score=_score(table.get("min_score", MIN_SCORE)),
        candidates_page=_page(table.get("candidates_page")),
        pairs=_pairs(table.get("pairs", [])),
    )


def _pairs(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise ValueError("structure: 'pairs' must be a list of [handle, handle] pairs")
    out: list[tuple[str, str]] = []
    seen: set[frozenset[str]] = set()
    for i, pair in enumerate(value):
        if (
            not isinstance(pair, list)
            or len(pair) != PAIR_SIZE
            or not all(isinstance(h, str) and h for h in pair)
        ):
            raise ValueError(f"structure: pairs[{i}] must be two non-empty handles, not {pair!r}")
        a, b = pair
        if a == b:
            raise ValueError(f"structure: pairs[{i}] pairs {a!r} with itself")
        key = frozenset(pair)
        if key in seen:
            raise ValueError(f"structure: pairs[{i}] repeats the pair {a!r} / {b!r}")
        seen.add(key)
        out.append((a, b))
    return tuple(out)


def _areas(value: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, Mapping):
        raise ValueError("structure: 'areas' must be a table of area ID = module patterns")
    out = []
    for area, patterns in value.items():
        if not isinstance(area, str) or not AREA.fullmatch(area):
            raise ValueError(
                f"structure: area {area!r} must be letters, digits, '_' and '-', "
                "not starting with '-'"
            )
        found = _patterns(f"areas.{area}", patterns)
        if not found:
            raise ValueError(f"structure: 'areas.{area}' is empty, so it holds no module")
        out.append((area, found))
    return tuple(out)


def _score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError("structure: 'min_score' must be a number, 0 or more")
    return float(value)


def _page(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in value.split("/"):
        raise ValueError(
            "structure: 'candidates_page' must be a path inside the repository, "
            "relative to its root"
        )
    return value
