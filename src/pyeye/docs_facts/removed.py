"""Removed names: ``docs/facts/removed.json`` and the rule that keeps them out of live docs.

A fact that disappears from the code (a tool, a parameter, an env var, an entry
point, an edge) can't fail a marker block once nothing binds it, but prose can
still name it. So every removal is recorded here (D4, C2), and a live page that
names a removed name fails ``check`` (C8).

Each entry is keyed by the fact ID the name had, and records:

- ``match``: how prose is scanned for it, and the only field edited by hand.

  - ``word``: any mention fails (the default for tools, env vars and entry points);
  - ``heading``: only an API heading fails, for a name that lives on as an
    internal method (``find_symbol``);
  - ``code``: only a mention inside inline code fails (`` `callers` ``), the default
    for edges, whose names are common words but which skills name in backticks;
  - ``none``: recorded, not scanned (the default for parameters; #828's runnable
    examples catch those).

- ``removed_in``: the first release without it. ``generate`` writes
  ``"unreleased"`` and ``scripts/changelog.py prepare`` stamps the version
  (``stamp_unreleased``; that script is stdlib-only, so the stamp lives there).
- ``removed_in_approx`` (optional): the release couldn't be pinned exactly (D12).
- ``note`` (optional): why the entry looks the way it does.

Entries are never deleted. A name that comes back (a live fact again) is simply
not scanned while it's live. ``generate`` derives the record from the copy at the
merge base with the default branch (#1112), so a name that went and came back on
a branch, between two local runs, leaves no entry.

The rule, for registered ``prose`` and ``skill`` pages (history pages may name
anything, and reference pages are generated from live facts):

- a matching line passes only if it also says "removed";
- each passing mention must be in the page's allow-list,
  ``DocEntry.allow["removed-name"]``, by its exact :func:`allowance` message;
  the list only shrinks (``rules.ratchet`` compares them as multisets);
- from the next major release after ``removed_in``, any match fails. The current
  release is the newest one in ``CHANGELOG.md``, so the release PR that writes
  ``## [3.0.0]`` is the one that fails, not ``main`` after the tag.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .facts import Bindable, Fact

REMOVED = "docs/facts/removed.json"
UNRELEASED = "unreleased"
RULE_ID = "removed-name"

Match = Literal["word", "heading", "code", "none"]
MATCHES: tuple[Match, ...] = ("word", "heading", "code", "none")

_SAYS_REMOVED = re.compile(r"\bremoved\b", re.IGNORECASE)
_RELEASE = re.compile(r"^## \[(\d+)\.(\d+)\.(\d+)[^\]]*\]", re.MULTILINE)
_SEMVER = re.compile(r"^(\d+)\.\d+\.\d+$")


@dataclass(frozen=True)
class Removed:
    """One removed name.

    Attributes:
        fact_id: The ID the fact had while it existed.
        match: How prose is scanned for it.
        removed_in: The first release without it, or ``"unreleased"``.
        approx: True when ``removed_in`` couldn't be pinned exactly.
        note: Free text explaining the entry.
    """

    fact_id: str
    match: Match
    removed_in: str
    approx: bool = False
    note: str = ""

    @property
    def name(self) -> str:
        """The name prose would use: the tool, parameter, variable or command."""
        return name_of(self.fact_id)


def name_of(fact_id: str) -> str:
    """The prose name for a fact ID (``tool.trace.param.depth`` -> ``depth``)."""
    if fact_id.startswith("cli.module."):
        return f"python -m {fact_id[len('cli.module.'):]}"
    if fact_id.startswith("cli.script."):
        return fact_id[len("cli.script.") :]
    return fact_id.rsplit(".", 1)[1]


def default_match(fact_id: str) -> Match | None:
    """The ``match`` a newly removed fact gets, or None if it isn't a name at all.

    Value facts (``ci.*``, ``ceiling.*``, ``project.*``) have no name to scan for,
    so their disappearance isn't recorded.
    """
    if fact_id.startswith("tool."):
        return "none" if ".param." in fact_id else "word"
    if fact_id.startswith(("env.", "cli.")):
        return "word"
    if fact_id.startswith("edge."):
        return "code"
    return None


def _entry(raw: Mapping[str, Any]) -> Removed:
    match = raw.get("match")
    if match not in MATCHES:
        raise ValueError(f"{REMOVED}: {raw.get('fact_id')!r} has match {match!r}, not {MATCHES}")
    return Removed(
        fact_id=str(raw["fact_id"]),
        match=match,
        removed_in=str(raw["removed_in"]),
        approx=bool(raw.get("removed_in_approx", False)),
        note=str(raw.get("note", "")),
    )


def load(root: Path, record: str = REMOVED) -> list[Removed]:
    """The working-tree entries (none if the file doesn't exist yet)."""
    path = root / record
    if not path.is_file():
        return []
    return parse(path.read_text(encoding="utf-8"))


def parse(text: str) -> list[Removed]:
    """The entries in the file's text (the working tree's, or a revision's)."""
    return [_entry(raw) for raw in json.loads(text)["removed"]]


def updated(
    entries: Iterable[Removed],
    old_snapshot: Mapping[str, Any],
    facts: Mapping[str, Bindable],
    *,
    current: Iterable[Removed] | None = None,
) -> list[Removed]:
    """*entries* plus a new entry for each name fact in *old_snapshot* that's gone.

    Never drops one of *entries*, and never adds a second entry for a fact ID.

    *entries* and *old_snapshot* are the merge base's when ``generate`` has one
    (#1112). *current* is then the working-tree record: its version of an entry
    wins (``match`` and ``note`` are edited by hand), and it keeps an entry the
    base doesn't have unless that entry was generated by an earlier run for a
    name that, against the base, never went: one that's live again, or one that
    was never in the base snapshot and carries only generated defaults. Without
    a base, *entries* is the working-tree record and *current* is None.
    """
    by_id = {e.fact_id: e for e in entries}
    if current is not None:
        for e in current:
            if e.fact_id in by_id or not _transient(e, old_snapshot, facts):
                by_id[e.fact_id] = e
    for fact_id in old_snapshot:
        if fact_id in facts or fact_id in by_id:
            continue
        match = default_match(fact_id)
        if match is not None:
            by_id[fact_id] = Removed(fact_id, match, UNRELEASED)
    return sorted(by_id.values(), key=lambda e: e.fact_id)


def _transient(
    entry: Removed, old_snapshot: Mapping[str, Any], facts: Mapping[str, Bindable]
) -> bool:
    """True if a working-tree *entry* the base lacks records no removal from the base."""
    if entry.fact_id in old_snapshot:
        return entry.fact_id in facts  # it went, and came back
    generated = Removed(entry.fact_id, default_match(entry.fact_id) or "none", UNRELEASED)
    return entry == generated  # born and gone on the branch; a hand entry differs


def render(entries: Iterable[Removed]) -> str:
    """The file's text: entries sorted by fact ID, optional fields only when set."""
    rows = []
    for e in sorted(entries, key=lambda e: e.fact_id):
        row: dict[str, Any] = {"fact_id": e.fact_id, "match": e.match, "removed_in": e.removed_in}
        if e.approx:
            row["removed_in_approx"] = True
        if e.note:
            row["note"] = e.note
        rows.append(row)
    # Sorted keys, as pre-commit's pretty-format-json writes them.
    return json.dumps({"removed": rows}, indent=2, sort_keys=True) + "\n"


def current_major(changelog: str) -> int | None:
    """The major version of the newest release in *changelog*, or None."""
    m = _RELEASE.search(changelog)
    return int(m.group(1)) if m else None


def sunset_passed(entry: Removed, major: int | None) -> bool:
    """True once a release of a later major than ``removed_in`` exists."""
    m = _SEMVER.match(entry.removed_in)
    if m is None or major is None:  # unreleased: removed in the current major
        return False
    return major > int(m.group(1))


def live_names(facts: Mapping[str, Bindable]) -> set[str]:
    """Names that are facts today, so a returned name is never flagged."""
    return {name_of(i) for i, f in facts.items() if isinstance(f, Fact) and default_match(i)}


def _matcher(entry: Removed) -> Callable[[str], bool]:
    """Whether a line names *entry*, by its ``match`` mode."""
    name = re.escape(entry.name)
    # Letters and digits bound a name on the left, not underscores, so the
    # ``mcp__pyeye__<name>`` form still names it; on the right an underscore
    # continues the identifier (``<name>_v2`` is another word).
    word = re.compile(rf"(?<![A-Za-z0-9]){name}(?![A-Za-z0-9_])")
    if entry.match == "heading":
        heading = re.compile(rf"^#{{1,6}}\s+[`(]*{name}(?![A-Za-z0-9_])")
        return lambda line: bool(heading.search(line))
    if entry.match == "code":
        # The odd segments between backticks are inline code.
        return lambda line: any(word.search(seg) for seg in line.split("`")[1::2])
    return lambda line: bool(word.search(line))


@dataclass(frozen=True)
class Mention:
    """A line of a live page that names a removed name.

    Attributes:
        path: The page, repo-relative.
        line: 1-based line number.
        name: The removed name.
        kind: What it was (tool, parameter, env var, command, edge).
        marked: The line says "removed", so it passes (and counts for the ratchet).
        sunset: The name's sunset has passed, so it fails even when marked.
    """

    path: str
    line: int
    name: str
    marked: bool
    sunset: bool
    kind: str = "name"

    @property
    def fails(self) -> bool:
        """True if this mention fails on its own, before the ratchet."""
        return self.sunset or not self.marked


def mentions(
    path: str,
    text: str,
    entries: Iterable[Removed],
    live: set[str],
    major: int | None,
) -> list[Mention]:
    """Every line of *text* naming a scanned removed name, one mention per line and name."""
    scanned = [(e, _matcher(e)) for e in entries if e.match != "none" and e.name not in live]
    found: list[Mention] = []
    for number, line in enumerate(text.splitlines(), 1):
        for entry, names in scanned:
            if names(line):
                found.append(
                    Mention(
                        path,
                        number,
                        entry.name,
                        marked=bool(_SAYS_REMOVED.search(line)),
                        sunset=sunset_passed(entry, major),
                        kind=kind_of(entry.fact_id),
                    )
                )
    return found


_KINDS = {
    "tool.": "tool",
    "env.": "env var",
    "cli.": "command",
    "edge.": "edge",
}


def kind_of(fact_id: str) -> str:
    """What kind of name a removed fact was, for messages."""
    if ".param." in fact_id:
        return "parameter"
    return next((k for p, k in _KINDS.items() if fact_id.startswith(p)), "name")


def allowance(m: Mention) -> str:
    """The stable message for a marked mention: what a page's allow-list names.

    No line number, so an allowance names exactly the mention it covers and
    survives edits elsewhere on the page.
    """
    return f"names removed {m.kind} {m.name!r} beside 'removed'"


def problem(m: Mention) -> str:
    """The ``path:line: message`` for a failing mention."""
    if m.sunset:
        return (
            f"{m.path}:{m.line}: names {m.name!r}, removed before this major release; "
            "only history pages may name it now"
        )
    return (
        f"{m.path}:{m.line}: names {m.name!r}, which was removed. Point readers at what "
        "replaced it, or say on the line that it was removed"
    )
