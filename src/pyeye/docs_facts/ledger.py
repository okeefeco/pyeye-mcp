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

A fact in a reference-only family (:attr:`~.setup.Setup.reference_only`, #1108)
is reference data, not a claim prose should make, and is never an entry.

An entry leaves the ledger when its fact is covered or no longer exists, or when
``/docs-review`` records it as deliberately not covered (C13). That dismissal is
stored once, in the review state (:mod:`.review`, ``docs/facts/review-state.json``),
and copied into the ledger's read-only ``dismissed`` section
(``{fact_id: {reason, date}}``) so every dismissal shows in the diff. Hand edits
to that section are overwritten, like a fact block's. A dismissal lapses when its
fact's value changes, and the fact returns to the uncovered entries.

The ledger never blocks a PR: a new entry is a line in the diff for the reviewer
and for ``/docs-review`` to work down.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .facts import Bindable, Fact, family

UNCOVERED = "docs/facts/uncovered.json"
UNRELEASED = "unreleased"


@dataclass(frozen=True)
class Ledger:
    """The ledger's content.

    Attributes:
        baseline: Fact IDs uncovered when the ledger was created, still uncovered.
        new: Fact ID -> ``first_seen`` release, for facts uncovered later.
        dismissed: Fact ID -> ``{reason, date}``, for facts deliberately not
            covered, copied from the review state (C13); read-only here.
    """

    baseline: tuple[str, ...]
    new: Mapping[str, str]
    dismissed: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


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


def load(root: Path, record: str = UNCOVERED) -> Ledger | None:
    """The committed ledger, or None before it's first created."""
    path = root / record
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    new = {row["fact_id"]: str(row["first_seen"]) for row in data["new"]}
    dismissed = {i: dict(v) for i, v in data.get("dismissed", {}).items()}
    return Ledger(tuple(data["baseline"]), new, dismissed)


def updated(
    old: Ledger | None,
    facts: Mapping[str, Bindable],
    covered: set[str],
    dismissed: Mapping[str, Mapping[str, str]] | None = None,
    *,
    reference_only: frozenset[str] = frozenset(),
) -> Ledger:
    """The ledger for today's facts and coverage, given the committed one.

    *dismissed* is :func:`.review.dismissed_uncovered`: the facts a human recorded
    as deliberately not covered, whose dismissal still holds. They leave the
    uncovered entries and are listed in ``dismissed`` instead.

    A fact in a *reference_only* family (#1108) is reference data, not a claim
    prose should make, so it is never an entry.
    """
    held = dict(sorted((dismissed or {}).items()))
    uncovered = {
        i for i, f in facts.items() if isinstance(f, Fact) and family(i) not in reference_only
    }
    uncovered -= covered | set(held)
    if old is None:
        return Ledger(tuple(sorted(uncovered)), {}, held)
    baseline = tuple(sorted(set(old.baseline) & uncovered))
    new = {i: old.new.get(i, UNRELEASED) for i in uncovered if i not in baseline}
    return Ledger(baseline, dict(sorted(new.items())), held)


def render(ledger: Ledger) -> str:
    """The file's text, sorted and stable."""
    data: dict[str, Any] = {
        "baseline": sorted(ledger.baseline),
        "new": [{"fact_id": i, "first_seen": s} for i, s in sorted(ledger.new.items())],
        "dismissed": {i: dict(v) for i, v in sorted(ledger.dismissed.items())},
    }
    return json.dumps(data, indent=2, sort_keys=True) + "\n"
