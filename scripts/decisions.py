#!/usr/bin/env python3
"""List and validate the decision log: one file per decision (#679).

Each decision is ``docs/decisions/entries/YYYY-MM-DD-<issue>-<slug>.md``
(``YYYY-MM-DD-<slug>.md`` when it has no issue). The file starts with front
matter, one ``key: <JSON value>`` per line between ``---`` lines, then the
entry itself (``## YYYY-MM-DD — title`` and its Friction / Decision / Anchor /
Applies-to / Verify fields)::

    ---
    date: "2026-11-15"
    title: "One canonical handle resolver (#623)"
    issues: [623]
    anchors: ["pyeye.resolver.resolve_handle"]
    status: "active"
    amends: []
    supersedes: []
    amended_by: []
    superseded_by: []
    ---

There is no committed index. ``index`` builds one from the front matter at run
time, so nothing shared is edited per PR and nothing can go stale.

Usage::

    decisions.py index [--symbol S] [--issue N] [--active] [--status STATUS]
    decisions.py check

Stdlib only, so CI can run it with a bare ``python``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENTRIES_DIR = Path(__file__).resolve().parents[1] / "docs" / "decisions" / "entries"

#: Front-matter keys, in the order they are written.
KEYS = (
    "date",
    "title",
    "issues",
    "anchors",
    "status",
    "amends",
    "supersedes",
    "amended_by",
    "superseded_by",
)
STATUSES = ("active", "amended", "superseded")
LINK_PAIRS = (("amends", "amended_by"), ("supersedes", "superseded_by"))

NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d+))?-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+)$")


class EntryError(ValueError):
    """A decision file that can't be read as an entry."""


@dataclass
class Entry:
    """One decision file: its front matter and body."""

    name: str
    meta: dict[str, Any]
    body: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def date(self) -> str:
        """The entry's date, ``YYYY-MM-DD``."""
        return str(self.meta.get("date", ""))

    @property
    def title(self) -> str:
        """The entry's title."""
        return str(self.meta.get("title", ""))

    @property
    def status(self) -> str:
        """``active``, ``amended`` or ``superseded``."""
        return str(self.meta.get("status", ""))


def parse(name: str, text: str) -> Entry:
    """Split *text* into front matter and body. Raises EntryError if it can't."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise EntryError(f"{name}: must start with a '---' front-matter line")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise EntryError(f"{name}: front matter is not closed with '---'") from None
    meta: dict[str, Any] = {}
    for number, line in enumerate(lines[1:end], start=2):
        key, sep, raw = line.partition(": ")
        if not sep:
            raise EntryError(f"{name}:{number}: expected 'key: <JSON value>', got {line!r}")
        if key in meta:
            raise EntryError(f"{name}:{number}: duplicate key {key!r}")
        try:
            meta[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EntryError(f"{name}:{number}: {key} is not a JSON value: {exc.msg}") from None
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return Entry(name=name, meta=meta, body=body)


def load(directory: Path = ENTRIES_DIR) -> tuple[list[Entry], list[str]]:
    """Read every ``*.md`` entry in *directory*; unreadable files become errors."""
    entries: list[Entry] = []
    errors: list[str] = []
    for path in sorted(directory.glob("*.md")):
        try:
            entries.append(parse(path.name, path.read_text(encoding="utf-8")))
        except EntryError as exc:
            errors.append(str(exc))
    return entries, errors


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def check(entries: list[Entry]) -> list[str]:
    """Every problem with *entries*, as messages. Empty means valid."""
    problems: list[str] = []
    by_name = {e.name: e for e in entries}
    for e in entries:
        p = problems.append
        missing = [k for k in KEYS if k not in e.meta]
        extra = sorted(set(e.meta) - set(KEYS))
        if missing:
            p(f"{e.name}: missing front-matter keys {missing}")
        if extra:
            p(f"{e.name}: unknown front-matter keys {extra}")
        if missing:
            continue
        m = NAME_RE.match(e.name)
        if not m:
            p(f"{e.name}: name must be YYYY-MM-DD-<issue>-<slug>.md (lowercase slug)")
        if not (isinstance(e.meta["date"], str) and DATE_RE.match(e.meta["date"])):
            p(f"{e.name}: date must be a 'YYYY-MM-DD' string")
        elif m and m.group(1) != e.meta["date"]:
            p(f"{e.name}: name's date {m.group(1)} differs from front-matter date {e.date}")
        if not (isinstance(e.meta["title"], str) and e.meta["title"].strip()):
            p(f"{e.name}: title must be a non-empty string")
        issues = e.meta["issues"]
        if not (isinstance(issues, list) and all(isinstance(n, int) and n > 0 for n in issues)):
            p(f"{e.name}: issues must be a list of positive ints")
        elif m and m.group(2) and int(m.group(2)) not in issues:
            p(f"{e.name}: name's issue #{m.group(2)} is not in issues {issues}")
        if not _is_str_list(e.meta["anchors"]):
            p(f"{e.name}: anchors must be a list of non-empty strings")
        if e.status not in STATUSES:
            p(f"{e.name}: status must be one of {list(STATUSES)}, got {e.meta['status']!r}")
        heading = HEADING_RE.match(e.body.split("\n", 1)[0])
        if not heading:
            p(f"{e.name}: body must start with '## YYYY-MM-DD — <title>'")
        elif (heading.group(1), heading.group(2)) != (e.date, e.title):
            p(f"{e.name}: body heading doesn't match the front-matter date and title")
        for forward, backward in LINK_PAIRS:
            for key in (forward, backward):
                if not _is_str_list(e.meta[key]):
                    p(f"{e.name}: {key} must be a list of entry file names")
            if not (_is_str_list(e.meta[forward]) and _is_str_list(e.meta[backward])):
                continue
            for target in e.meta[forward]:
                other = by_name.get(target)
                if other is None:
                    p(f"{e.name}: {forward} {target!r}, which doesn't exist")
                elif e.name not in (other.meta.get(backward) or []):
                    p(f"{e.name}: {forward} {target}, but its {backward} doesn't list {e.name}")
            for source in e.meta[backward]:
                other = by_name.get(source)
                if other is None:
                    p(f"{e.name}: {backward} {source!r}, which doesn't exist")
                elif e.name not in (other.meta.get(forward) or []):
                    p(f"{e.name}: {backward} {source}, but its {forward} doesn't list {e.name}")
        if _is_str_list(e.meta["superseded_by"]) and _is_str_list(e.meta["amended_by"]):
            expected = (
                "superseded"
                if e.meta["superseded_by"]
                else ("amended" if e.meta["amended_by"] else "active")
            )
            if e.status in STATUSES and e.status != expected:
                p(f"{e.name}: status is {e.status!r} but its links make it {expected!r}")
    return problems


def select(
    entries: list[Entry],
    *,
    symbol: str | None = None,
    issue: int | None = None,
    active: bool = False,
    status: str | None = None,
) -> list[Entry]:
    """Filter *entries*, newest first (by date, then name)."""
    chosen = []
    for e in entries:
        if symbol and not any(symbol in a for a in e.meta.get("anchors", [])):
            continue
        if issue is not None and issue not in e.meta.get("issues", []):
            continue
        if active and e.status == "superseded":
            continue
        if status and e.status != status:
            continue
        chosen.append(e)
    return sorted(chosen, key=lambda e: (e.date, e.name), reverse=True)


def format_index(entries: list[Entry]) -> str:
    """A newest-first Markdown table of *entries*."""
    rows = ["| Date | Title | Issues | Governs | Status | File |", "|---|---|---|---|---|---|"]
    for e in entries:
        issues = ", ".join(f"#{n}" for n in e.meta.get("issues", []))
        anchors = ", ".join(f"`{a}`" for a in e.meta.get("anchors", [])[:4])
        if len(e.meta.get("anchors", [])) > 4:
            anchors += ", …"
        title = e.title.replace("|", "\\|")
        rows.append(f"| {e.date} | {title} | {issues} | {anchors} | {e.status} | {e.name} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dir", type=Path, default=ENTRIES_DIR, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index", help="list entries, newest first")
    index.add_argument("--symbol", help="only entries whose anchors contain this text")
    index.add_argument("--issue", type=int, help="only entries for this issue number")
    index.add_argument("--active", action="store_true", help="hide superseded entries")
    index.add_argument("--status", choices=STATUSES, help="only entries with this status")
    sub.add_parser("check", help="validate every entry (run in CI)")
    args = parser.parse_args(argv)

    entries, errors = load(args.dir)
    if args.command == "check":
        problems = errors + check(entries)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print(f"decisions: {len(problems)} problem(s)", file=sys.stderr)
            return 1
        print(f"decisions: {len(entries)} entries OK")
        return 0

    for error in errors:
        print(f"warning: {error}", file=sys.stderr)
    chosen = select(
        entries, symbol=args.symbol, issue=args.issue, active=args.active, status=args.status
    )
    print(format_index(chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
