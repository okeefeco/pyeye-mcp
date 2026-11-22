"""Pairs of callables that may do the same job: candidates, never findings (#1092).

Ported from the RFC #1083 trial's ``scripts/candidates_v2.py`` (2026-11-22),
scoring unchanged, so the trial's Scrapy and Poetry results can be reproduced:

* the items are the module-level functions and classes, plus each class's
  methods (name only, as in the trial; dunders, ``__init__`` included, are left out);
* tokens: snake and camel case split, lower-cased, a plural ``s`` stripped,
  stop words and one-letter tokens dropped;
* IDF over every item's name, docstring and parameter tokens, so a rare word
  counts more than ``get``;
* ``score = name + 0.5 * docstring + 0.25 * parameters``, where the name term is
  the IDF-weighted overlap relative to the SHORTER name (:func:`overlap`), and
  the other two are weighted Jaccard (:func:`jaccard`);
* a pair needs a shared name token; a leaf name that 3+ owners define is an
  interface hook (``process_request``), not a copy, and is skipped.

Pairs are formed across areas. With no area map every module is its own area.
``within_areas`` also forms pairs inside an area, never inside one owner (the
open extension in RFC #1083). A similarity score is a tunable judgement, not a
fact, so a pair is only ever a candidate.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .dump import Dump

#: Words too common in code to say what a callable does (the trial's list).
STOP = frozenset(
    {
        "the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "is", "it", "be",
        "self", "cls", "args", "kwargs", "return", "returns", "with", "by", "from", "as",
        "this", "that", "if", "not", "no", "init", "new", "none", "str", "int", "bool",
        "any", "object", "type", "default", "true", "false",
    }
)  # fmt: skip

#: Owners that define one leaf name before it counts as an interface hook.
HOOK_OWNERS = 3

#: Weights of the docstring and parameter terms (the name term weighs 1).
DOC_WEIGHT = 0.5
PARAM_WEIGHT = 0.25


@dataclass(frozen=True)
class Item:
    """One callable as the scorer sees it."""

    handle: str
    area: str
    name: tuple[str, ...]
    doc: tuple[str, ...]
    params: tuple[str, ...]

    @property
    def owner(self) -> str:
        """The module or class that defines it."""
        return self.handle.rsplit(".", 1)[0]

    @property
    def leaf(self) -> str:
        """Its own name."""
        return self.handle.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Candidate:
    """A pair worth a look, ``a`` before ``b`` in item order."""

    score: float
    a: str
    a_area: str
    b: str
    b_area: str


def tokens(text: str) -> tuple[str, ...]:
    """The words of *text*: case-split, lower-cased, de-pluralised, stop words dropped."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    out = []
    for word in re.split(r"[^A-Za-z0-9]+", text.lower()):
        if len(word) < 2 or word in STOP or word.isdigit():
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return tuple(out)


def parameters(signature: str | None) -> str:
    """The parameter names in a one-line signature, space-separated."""
    found = re.search(r"\((.*)\)", signature or "")
    if not found:
        return ""
    return " ".join(p.split(":")[0].split("=")[0] for p in found.group(1).split(","))


def _dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def items(dump: Dump, areas: Mapping[str, str] | None = None) -> list[Item]:
    """The scorer's items, in dump order.

    Args:
        dump: The collected structure.
        areas: Module -> area. A module not in it is its own area.
    """
    area_of: dict[str, str] = dict(areas or {})
    out: list[Item] = []
    for d in dump.definitions:
        area = area_of.get(d.module, d.module)
        if d.owner == d.module and d.kind in ("function", "class"):
            out.append(
                Item(
                    d.handle,
                    area,
                    tokens(d.handle.rsplit(".", 1)[-1]),
                    tokens(d.summary),
                    tokens(parameters(d.signature)),
                )
            )
        elif d.kind == "method" and not _dunder(d.handle.rsplit(".", 1)[-1]):
            out.append(Item(d.handle, area, tokens(d.handle.rsplit(".", 1)[-1]), (), ()))
    return out


def hook_names(found: Iterable[Item]) -> frozenset[str]:
    """Leaf names that :data:`HOOK_OWNERS` or more owners define."""
    owners: defaultdict[str, set[str]] = defaultdict(set)
    for item in found:
        owners[item.leaf].add(item.owner)
    return frozenset(leaf for leaf, o in owners.items() if len(o) >= HOOK_OWNERS)


def idf(found: Iterable[Item]) -> dict[str, float]:
    """Each token's inverse document frequency over the items."""
    listed = list(found)
    df: Counter[str] = Counter()
    for item in listed:
        df.update(set(item.name) | set(item.doc) | set(item.params))
    return {t: math.log(len(listed) / c) for t, c in df.items()}


def overlap(a: Iterable[str], b: Iterable[str], weights: Mapping[str, float]) -> float:
    """Shared weight relative to the lighter side, damped when little is shared."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    shared = sum(weights[t] for t in sa & sb)
    smaller = min(sum(weights[t] for t in sa), sum(weights[t] for t in sb))
    if not smaller:
        return 0.0
    return (shared / smaller) * (1 - math.exp(-shared / 3))


def jaccard(a: Iterable[str], b: Iterable[str], weights: Mapping[str, float]) -> float:
    """Weighted Jaccard similarity."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    union = sum(weights[t] for t in sa | sb)
    return sum(weights[t] for t in sa & sb) / union if union else 0.0


def score(
    dump: Dump,
    areas: Mapping[str, str] | None = None,
    *,
    within_areas: bool = False,
) -> list[Candidate]:
    """Every candidate pair, best first (ties by handle).

    Args:
        dump: The collected structure.
        areas: Module -> area; a module not in it is its own area.
        within_areas: Also pair items in the same area (never in the same owner).
    """
    found = items(dump, areas)
    weights = idf(found)
    hooks = hook_names(found)
    pairs: list[Candidate] = []
    for i, a in enumerate(found):
        if not a.name:
            continue
        for b in found[i + 1 :]:
            if not b.name:
                continue
            if a.area == b.area and (not within_areas or a.owner == b.owner):
                continue
            if a.leaf == b.leaf and a.leaf in hooks:
                continue  # an interface hook many owners implement, not a copy
            name = overlap(a.name, b.name, weights)
            if name == 0.0:
                continue  # at least one shared name word
            total = (
                name
                + DOC_WEIGHT * jaccard(a.doc, b.doc, weights)
                + PARAM_WEIGHT * jaccard(a.params, b.params, weights)
            )
            pairs.append(Candidate(round(total, 4), a.handle, a.area, b.handle, b.area))
    pairs.sort(key=lambda c: (-c.score, c.a, c.b))
    return pairs
