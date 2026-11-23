"""The ``structure`` kind's options, as a repository's docs-facts config gives them (#1092).

The config names a built-in kind and its options as data (ruling C19)::

    [[tool.pyeye.docs_facts.extractors]]
    kind = "structure"
    prefix = "arch"
    include = ["src/*"]
    exclude = ["*/tests/*"]
    min_score = 0.9
    candidates_page = "docs/facts/arch.candidates.md"
    pairs = "docs/architecture/pairs.toml"     # or inline: [["pkg.a.load", "pkg.b.read"]]
    areas = "docs/architecture/areas.toml"     # or an inline table: area id = patterns

``areas`` and ``pairs`` may each be a committed data file (#1175), so the
planner's curation arrives as a reviewable diff. :func:`load` reads them, as
TOML, JSON or YAML by suffix (:mod:`pyeye._data_files`, never run)::

    # areas.toml                       # pairs.toml
    [areas]                            [[pair]]
    console = ["poetry.console*"]      a = "pkg.a.load"
    storage = ["poetry.store*"]        b = "pkg.b.read"

                                       [[pair]]          # never labelled or listed again
                                       a = "pkg.c.x"
                                       b = "pkg.d.y"
                                       rejected = "different jobs: one parses, one prints"

:func:`parse` validates the table and raises :class:`ValueError` (the loader's
``KindOptionsError`` is one) on any key or value it doesn't accept, naming it.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
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
#: The registered pages the ``architecture-handles`` rule scans, by default (#1176):
#: the area docs and top map live under ``docs/architecture/`` (ruling 1 on #1173).
ARCHITECTURE_PAGES: tuple[str, ...] = ("docs/architecture/**",)

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
        architecture_pages: :mod:`fnmatch` globs over registered page paths: the
            pages whose handles must resolve (``architecture-handles``, #1176).
        pairs: Handle pairs a planner curated (RFC #1083 step 4.2), labelled
            from pyeye's facts like scored candidates, whatever their score.
        rejected: ``(a, b, reason)`` pairs the user rejected (#1175): never
            labelled, and never listed as a candidate again.
        areas_file: The data file :attr:`areas` comes from, or ``None`` if inline.
        pairs_file: The data file :attr:`pairs` and :attr:`rejected` come from.
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
    rejected: tuple[tuple[str, str, str], ...] = ()
    areas_file: str | None = None
    pairs_file: str | None = None
    architecture_pages: tuple[str, ...] = ARCHITECTURE_PAGES


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
        "architecture_pages",
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
    areas = table.get("areas", {})
    pairs = table.get("pairs", [])
    accepted, rejected = ((), ()) if isinstance(pairs, str) else _pairs(pairs, "pairs")
    return Options(
        prefix=prefix,
        include=include,
        exclude=_patterns("exclude", table["exclude"]) if "exclude" in table else (),
        strict_source=_flag("strict_source", table.get("strict_source", False)),
        within_areas=_flag("within_areas", table.get("within_areas", False)),
        areas=() if isinstance(areas, str) else _areas(areas, "areas"),
        min_score=_score(table.get("min_score", MIN_SCORE)),
        candidates_page=_path("candidates_page", table.get("candidates_page")),
        pairs=accepted,
        rejected=rejected,
        areas_file=_path("areas", areas) if isinstance(areas, str) else None,
        pairs_file=_path("pairs", pairs) if isinstance(pairs, str) else None,
        architecture_pages=(
            _patterns("architecture_pages", table["architecture_pages"])
            if "architecture_pages" in table
            else ARCHITECTURE_PAGES
        ),
    )


def _pairs(
    value: Any, where: str
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str, str], ...]]:
    """The accepted and the rejected pairs: ``[a, b]`` or ``{a, b, rejected?}`` each."""
    if not isinstance(value, list):
        raise ValueError(f"structure: {where!r} must be a list of pairs")
    accepted: list[tuple[str, str]] = []
    rejected: list[tuple[str, str, str]] = []
    seen: set[frozenset[str]] = set()
    for i, entry in enumerate(value):
        a, b, reason = _pair(entry, f"{where}[{i}]")
        key = frozenset((a, b))
        if key in seen:
            raise ValueError(f"structure: {where}[{i}] repeats the pair {a!r} / {b!r}")
        seen.add(key)
        if reason is None:
            accepted.append((a, b))
        else:
            rejected.append((a, b, reason))
    return tuple(accepted), tuple(rejected)


def _pair(entry: Any, where: str) -> tuple[str, str, str | None]:
    reason: Any = None
    if isinstance(entry, Mapping):
        unknown = sorted(set(entry) - {"a", "b", "rejected"})
        if unknown:
            raise ValueError(f"structure: {where} has unknown key(s) {unknown}")
        reason = entry.get("rejected")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError(f"structure: {where}: 'rejected' must be a non-empty reason")
        entry = [entry.get("a"), entry.get("b")]
    if (
        not isinstance(entry, list)
        or len(entry) != PAIR_SIZE
        or not all(isinstance(h, str) and h for h in entry)
    ):
        raise ValueError(f"structure: {where} must be two non-empty handles, not {entry!r}")
    a, b = entry
    if a == b:
        raise ValueError(f"structure: {where} pairs {a!r} with itself")
    return a, b, reason


def _areas(value: Any, where: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, Mapping):
        raise ValueError(
            f"structure: {where!r} must be a table of area ID = module patterns, "
            "or a data file's path"
        )
    out = []
    for area, patterns in value.items():
        if not isinstance(area, str) or not AREA.fullmatch(area):
            raise ValueError(
                f"structure: {where}: area {area!r} must be letters, digits, '_' and '-', "
                "not starting with '-'"
            )
        found = _patterns(f"{where}.{area}", patterns)
        if not found:
            raise ValueError(f"structure: '{where}.{area}' is empty, so it holds no module")
        out.append((area, found))
    return tuple(out)


def _score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError("structure: 'min_score' must be a number, 0 or more")
    return float(value)


def _path(key: str, value: Any) -> str | None:
    """A repo-relative file path option, or ``None`` when absent."""
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value.startswith(("/", "\\"))
        or ":" in value
        or ".." in value.replace("\\", "/").split("/")
    ):
        raise ValueError(
            f"structure: {key!r} must be a path inside the repository, relative to its root"
        )
    return value


#: Data file suffix -> :data:`pyeye._data_files.FORMATS` name.
SUFFIXES = {".toml": "toml", ".json": "json", ".yaml": "yaml", ".yml": "yaml"}

#: The key that holds a data file's content.
AREAS_KEY = "areas"
PAIRS_KEY = "pair"


def _read(root: Path, file: str, key: str) -> Any:
    from ... import _data_files
    from ...path_utils import relative_within

    path = root / file
    if relative_within(path, root) is None:
        raise ValueError(f"structure: {file!r} is outside the repository")
    fmt = SUFFIXES.get(path.suffix)
    if fmt is None:
        raise ValueError(f"structure: {file!r}: unknown format; use one of {sorted(SUFFIXES)}")
    if not path.is_file():
        raise ValueError(f"structure: {file!r} doesn't exist")
    data = _data_files.read(path, fmt)
    if not isinstance(data, dict) or key not in data:
        raise ValueError(f"structure: {file!r} must be a table with a {key!r} key")
    return data[key]


def load(opts: Options, root: Path) -> Options:
    """*opts* with its ``areas`` and ``pairs`` data files read from *root* (#1175).

    Raises:
        ValueError: If a file is outside the repository, missing, of an unknown
            format, or doesn't hold valid areas or pairs. The message names it.
    """
    changes: dict[str, Any] = {}
    if opts.areas_file is not None:
        raw = _read(root, opts.areas_file, AREAS_KEY)
        changes["areas"] = _areas(raw, f"{opts.areas_file} {AREAS_KEY}")
    if opts.pairs_file is not None:
        raw = _read(root, opts.pairs_file, PAIRS_KEY)
        changes["pairs"], changes["rejected"] = _pairs(raw, f"{opts.pairs_file} {PAIRS_KEY}")
    return dataclasses.replace(opts, **changes) if changes else opts
