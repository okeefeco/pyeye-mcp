"""The uncovered-fact ledger, ``docs/facts/uncovered.json`` (D5, C3).

A fact is **covered** when a prose or skill page explains it:

- the page's registry entry names it in ``covers`` (a view stands for its members);
- or the page shows it in a marker block (a block over a view covers its members).

A link to its ``docs/reference/`` entry doesn't count: the reference pages list
every fact, so counting them would make the ledger meaningless.

The ledger has two sections:

- ``baseline``: the facts that were uncovered on the day the ledger was created.
  They're triaged once, in the sweep fix-up (#831), not left as standing noise.
- ``new``: facts that were uncovered after that, each with ``first_seen``, the
  release it first appeared uncovered in (``"unreleased"`` until
  ``scripts/changelog.py prepare`` stamps it).

An entry leaves the ledger when its fact is covered or no longer exists. The
ledger never blocks a PR: a new entry is a line in the diff for the reviewer and
for ``/docs-review`` to work down. Dismissals ("deliberately not covered") are
stored with the review's dismissal state (#829), not here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .facts import Bindable, Fact

UNCOVERED = "docs/facts/uncovered.json"
UNRELEASED = "unreleased"


@dataclass(frozen=True)
class Ledger:
    """The ledger's content.

    Attributes:
        baseline: Fact IDs uncovered when the ledger was created, still uncovered.
        new: Fact ID -> ``first_seen`` release, for facts uncovered later.
    """

    baseline: tuple[str, ...]
    new: Mapping[str, str]


def expand(ids: Iterable[str], facts: Mapping[str, Bindable]) -> set[str]:
    """Item fact IDs for *ids*: a view stands for its members; unknown IDs are dropped."""
    out: set[str] = set()
    for fact_id in ids:
        item = facts.get(fact_id)
        if isinstance(item, Fact):
            out.add(fact_id)
        elif item is not None:
            out.update(item.members)
    return out


def load(root: Path) -> Ledger | None:
    """The committed ledger, or None before it's first created."""
    path = root / UNCOVERED
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    new = {row["fact_id"]: str(row["first_seen"]) for row in data["new"]}
    return Ledger(tuple(data["baseline"]), new)


def updated(old: Ledger | None, facts: Mapping[str, Bindable], covered: set[str]) -> Ledger:
    """The ledger for today's facts and coverage, given the committed one."""
    uncovered = {i for i, f in facts.items() if isinstance(f, Fact)} - covered
    if old is None:
        return Ledger(tuple(sorted(uncovered)), {})
    baseline = tuple(sorted(set(old.baseline) & uncovered))
    new = {i: old.new.get(i, UNRELEASED) for i in uncovered if i not in baseline}
    return Ledger(baseline, dict(sorted(new.items())))


def render(ledger: Ledger) -> str:
    """The file's text, sorted and stable."""
    data: dict[str, Any] = {
        "baseline": sorted(ledger.baseline),
        "new": [{"fact_id": i, "first_seen": s} for i, s in sorted(ledger.new.items())],
    }
    return json.dumps(data, indent=2, sort_keys=True) + "\n"
