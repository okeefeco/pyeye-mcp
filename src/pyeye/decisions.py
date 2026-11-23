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

    python -m pyeye.decisions index [--symbol S] [--issue N] [--active] [--status STATUS]
    python -m pyeye.decisions check
    python -m pyeye.decisions check --resolve   # also resolve Anchor/Applies-to (needs pyeye)
    python -m pyeye.decisions migrate     # split entries still in DECISIONS.md into files
    python -m pyeye.decisions --decisions-dir path/to/decisions --grandfathered OLD.md check

It runs from the project root: the log defaults to ``docs/decisions`` there. It
ships in the package so every repo using the ``decision-log`` skill has it
(#1093); this repository's ``scripts/decisions.py`` wraps it with its own
grandfather list.

Stdlib only, with no relative imports: a wrapper can load this file by path
and run it with a bare ``python``, without the ``pyeye`` package's dependencies.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Where the log lives, relative to the working directory, unless the caller says.
DEFAULT_DECISIONS_DIR = Path("docs") / "decisions"
#: How the messages name the command, unless the caller says (a repo wrapper).
DEFAULT_COMMAND = "python -m pyeye.decisions"

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
LOG_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+)$", re.M)

APPLIES_TO_RE = re.compile(r"^\*\*Applies-to:\*\*[ \t]*(.*)$", re.M)
#: The start of the next bold field (``**Verify:**``), which ends a field's value.
FIELD_RE = re.compile(r"^\*\*[A-Z][\w -]*:\*\*")
#: ``none (<why>)``: the decision governs no code site (a policy decision).
APPLIES_TO_NONE_RE = re.compile(r"^none \((?P<why>[^()]*\S[^()]*)\)", re.I)
#: Placeholders that say nothing; write ``none (<why>)`` instead.
APPLIES_TO_PLACEHOLDER_RE = re.compile(r"^(?:n/?a|none|-+|tbd|todo|\.\.\.|…)\.?$", re.I)

#: No entry is grandfathered unless the caller says so (``--grandfathered``).
#: A repo that made ``Applies-to`` mandatory after writing entries passes the
#: names of those older entries; the list should only shrink.
DEFAULT_GRANDFATHERED: frozenset[str] = frozenset()

#: What ``DECISIONS.md`` holds: a static header, never an entry.
STATIC_HEADER = "# Decision Log\n\nContract- or invariant-significant, friction-driven decisions. Each one is a small, verifiable fact: **Friction · Decision · Anchor** (stable references) **· Applies-to** (every governed site, or `none (<why>)`; required since #636) **· Verify** (checkable, or honestly labelled).\n\n**One file per decision** lives in [`entries/`](entries/), named `YYYY-MM-DD-<issue>-<slug>.md`. There is no committed index (#679). List and filter the entries from their front matter instead:\n\n```bash\npython -m pyeye.decisions index                     # every entry, newest first\npython -m pyeye.decisions index --active            # hide superseded entries\npython -m pyeye.decisions index --symbol resolve_handle\npython -m pyeye.decisions index --issue 626\npython -m pyeye.decisions check                     # validate (also runs in CI)\n```\n\nRead the index first, then open the one to three entries that matter. An entry's `status` is `active`, `amended` or `superseded`. Its `amends` / `supersedes` / `amended_by` / `superseded_by` front matter links to the related entry files.\n\nNew entries are written with the `decision-log` skill, which ships in the pyeye plugin. This file is a static header and should almost never change.\n"


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


def load(directory: Path | None = None) -> tuple[list[Entry], list[str]]:
    """Read every ``*.md`` entry in *directory*; unreadable files become errors.

    *directory* defaults to ``docs/decisions/entries`` under the working
    directory. A directory that doesn't exist has no entries.
    """
    if directory is None:
        directory = DEFAULT_DECISIONS_DIR / "entries"
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


def applies_to(body: str) -> str | None:
    """The entry's ``Applies-to`` value, or None if it has no ``Applies-to`` line.

    The value runs from the label to the next ``**Field:**`` line, so a list on
    the following lines counts. It is stripped, with lines joined by spaces.
    """
    m = APPLIES_TO_RE.search(body)
    if not m:
        return None
    lines = [m.group(1)]
    for line in body[m.end() :].split("\n")[1:]:
        if FIELD_RE.match(line) or line.startswith("#"):
            break
        lines.append(line)
    return " ".join(part.strip() for part in lines if part.strip())


def _check_applies_to(e: Entry, grandfathered: frozenset[str]) -> list[str]:
    value = applies_to(e.body)
    if e.name in grandfathered:
        if value is not None:
            return [
                f"{e.name}: has Applies-to now; delete it from APPLIES_TO_GRANDFATHERED "
                "in scripts/decisions.py"
            ]
        return []
    if value is None:
        return [
            f"{e.name}: missing '**Applies-to:**' (#636). Name every site the rule "
            "governs, or write 'Applies-to: none (<why>)' for a policy decision"
        ]
    if not value or APPLIES_TO_PLACEHOLDER_RE.match(value):
        return [
            f"{e.name}: Applies-to {value!r} says nothing; name the sites or write 'none (<why>)'"
        ]
    if value.lower().startswith("none") and not APPLIES_TO_NONE_RE.match(value):
        return [f"{e.name}: an Applies-to opt-out must read 'none (<why>)', got {value!r}"]
    return []


def stale_grandfathered(
    entries: list[Entry], grandfathered: frozenset[str] = DEFAULT_GRANDFATHERED
) -> list[str]:
    """Grandfathered names with no entry file: the list must shrink with the log."""
    names = {e.name for e in entries}
    return [
        f"APPLIES_TO_GRANDFATHERED lists {name!r}, which doesn't exist; delete it"
        for name in sorted(grandfathered - names)
    ]


def check(entries: list[Entry], grandfathered: frozenset[str] = DEFAULT_GRANDFATHERED) -> list[str]:
    """Every problem with *entries*, as messages. Empty means valid.

    *grandfathered* names the entries exempt from the ``Applies-to`` rule
    (:data:`DEFAULT_GRANDFATHERED` unless given); :func:`stale_grandfathered` checks the
    list itself against the whole log.
    """
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
        problems.extend(_check_applies_to(e, grandfathered))
    return problems


def entries_in_log(text: str) -> list[tuple[str, str, str]]:
    """``(date, title, body)`` for every entry heading still in ``DECISIONS.md``."""
    starts = [m.start() for m in LOG_HEADING_RE.finditer(text)]
    if not starts:
        return []
    chunks = [text[a:b] for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]
    out = []
    for chunk in chunks:
        m = LOG_HEADING_RE.match(chunk)
        assert m is not None
        out.append((m.group(1), m.group(2), chunk.rstrip("\n") + "\n"))
    return out


def _slug(title: str) -> str:
    text = re.sub(r"\([^()]*#\d+[^()]*\)\s*$", "", title).replace("`", "")
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-").split("-")
    kept: list[str] = []
    for word in words:
        if len("-".join([*kept, word])) > 60:
            break
        kept.append(word)
    return "-".join(kept) or "entry"


def entry_from_log(date: str, title: str, body: str) -> tuple[str, dict[str, Any]]:
    """Derive the file name and front matter for an entry split out of the log."""
    trailing = re.search(r"\(([^()]*#\d+[^()]*)\)\s*$", title)
    title_issues = [int(n) for n in re.findall(r"#(\d+)", title)]
    anchor = re.search(r"^\*\*Anchor:\*\*(.*)$", body, re.M)
    anchor_text = anchor.group(1) if anchor else ""
    issues: list[int] = []
    for n in title_issues + [int(n) for n in re.findall(r"#(\d+)", anchor_text)]:
        if n not in issues:
            issues.append(n)
    trailing_issues = [int(n) for n in re.findall(r"#(\d+)", trailing.group(1))] if trailing else []
    primary: int | None = next(iter(trailing_issues or title_issues or issues), None)
    anchors: list[str] = []
    for token in re.findall(r"`([^`]+)`", anchor_text):
        token = token.strip()
        if re.fullmatch(r"[A-Za-z_][\w./:]*(?:\(\))?", token) and token not in anchors:
            anchors.append(token)
    name = f"{date}-{primary}-{_slug(title)}.md" if primary else f"{date}-{_slug(title)}.md"
    meta: dict[str, Any] = {
        "date": date,
        "title": title,
        "issues": issues,
        "anchors": anchors,
        "status": "active",
        "amends": [],
        "supersedes": [],
        "amended_by": [],
        "superseded_by": [],
    }
    return name, meta


def render(meta: dict[str, Any], body: str) -> str:
    """An entry file: front matter in :data:`KEYS` order, a blank line, the body."""
    lines = ["---", *(f"{k}: {json.dumps(meta[k], ensure_ascii=False)}" for k in KEYS), "---"]
    return "\n".join(lines) + "\n\n" + body.rstrip("\n") + "\n"


def migrate(
    log_file: Path | None = None,
    directory: Path | None = None,
    *,
    update: bool = False,
    header: str = STATIC_HEADER,
) -> list[str]:
    """Split every entry still in *log_file* into its own file (#679).

    Re-runnable and idempotent: an entry whose file already exists with the same
    body is skipped. One whose existing body differs is an error and nothing is
    changed, unless *update* is set: then the log's body replaces the file's
    (front matter kept), for a merge that brings in an edit to an existing entry. Each written body is verified on disk before *log_file* is reset to
    *header* (:data:`STATIC_HEADER` by default). Amend/supersede links aren't guessed: entries whose
    text mentions amending or superseding are reported for the author to link.

    Returns human-readable notes; raises EntryError if anything would be lost.
    """
    if log_file is None:
        log_file = DEFAULT_DECISIONS_DIR / "DECISIONS.md"
    if directory is None:
        directory = DEFAULT_DECISIONS_DIR / "entries"
    found = entries_in_log(log_file.read_text(encoding="utf-8")) if log_file.exists() else []
    existing, errors = load(directory)
    if errors:
        raise EntryError("; ".join(errors))
    by_key = {(e.date, e.title): e for e in existing}
    plan: list[tuple[str, dict[str, Any], str]] = []
    updates: list[tuple[Entry, str]] = []
    notes: list[str] = []
    for date, title, body in found:
        have = by_key.get((date, title))
        if have is not None:
            if have.body.rstrip("\n") != body.rstrip("\n"):
                if not update:
                    raise EntryError(
                        f"{have.name}: already exists with a different body than the "
                        f"DECISIONS.md entry '{date} — {title}'; check the difference, then "
                        "rerun with --update to take the DECISIONS.md text"
                    )
                updates.append((have, body))
                continue
            notes.append(f"unchanged: {have.name}")
            continue
        name, meta = entry_from_log(date, title, body)
        if (directory / name).exists() or any(name == p[0] for p in plan):
            raise EntryError(f"{name}: name collision; rename one entry's slug")
        plan.append((name, meta, body))
    directory.mkdir(parents=True, exist_ok=True)
    for have, body in updates:
        (directory / have.name).write_text(render(have.meta, body), encoding="utf-8", newline="\n")
        written = parse(have.name, (directory / have.name).read_text(encoding="utf-8"))
        if written.body.rstrip("\n") != body.rstrip("\n"):
            raise EntryError(f"{have.name}: body changed on the round trip")
        notes.append(f"updated body: {have.name}")
    for name, meta, body in plan:
        (directory / name).write_text(render(meta, body), encoding="utf-8", newline="\n")
        written = parse(name, (directory / name).read_text(encoding="utf-8"))
        if written.body.rstrip("\n") != body.rstrip("\n"):
            raise EntryError(f"{name}: body changed on the round trip")
        notes.append(f"created: {name}")
        if re.search(r"\b(amend|supersed)", body, re.I):
            notes.append(f"  link it: {name} mentions amending/superseding another entry")
    if log_file.exists() and log_file.read_text(encoding="utf-8") != header:
        log_file.write_text(header, encoding="utf-8", newline="\n")
        notes.append(f"reset {log_file.name} to the static header")
    notes.append(
        f"{len(found)} entr{'y' if len(found) == 1 else 'ies'} in DECISIONS.md, "
        f"{len(plan)} split out"
    )
    return notes


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


def _resolve(
    entries: list[Entry], entries_dir: Path, root: Path, short_forms_fail_from: str | None
) -> list[str]:
    """``check --resolve``'s problems; its counts and externals are printed (#1182).

    pyeye is imported by name, so this module stays standard-library only and
    a bare-Python ``check`` never needs it. Without pyeye, ``--resolve`` is a
    problem: an unchecked reference must never read as a passing one.
    """
    try:
        decision_check = importlib.import_module("pyeye.decision_check")
    except ImportError as exc:
        return [f"--resolve needs pyeye importable (run it under `uv run`): {exc}"]
    report = decision_check.resolve_check(entries, entries_dir, root, short_forms_fail_from)
    before = f"before {short_forms_fail_from}" if short_forms_fail_from else "(no gate date)"
    print(
        f"decisions: resolved the references of {report.checked_entries} active entries; "
        f"{report.grandfathered_short_forms} short form(s) in entries {before} not checked"
    )
    for external in report.unresolved_externals:
        print(f"decisions: external reference not resolved (not a failure): {external}")
    return list(report.problems)


def main(
    argv: list[str] | None = None,
    *,
    decisions_dir: Path | None = None,
    grandfathered: frozenset[str] = DEFAULT_GRANDFATHERED,
    header: str = STATIC_HEADER,
    command: str = DEFAULT_COMMAND,
    short_forms_fail_from: str | None = None,
    project_root: Path | None = None,
) -> int:
    """Command-line entry point (``python -m pyeye.decisions``).

    The keyword arguments are a repo's own settings, for a wrapper such as this
    repository's ``scripts/decisions.py`` (#1093): where the log lives (default
    ``docs/decisions`` under the working directory), which old entries are
    grandfathered from the ``Applies-to`` rule, the header ``migrate`` writes,
    and how messages name the command. ``--decisions-dir`` and
    ``--grandfathered`` set the first two from the command line.

    ``check --resolve`` also resolves every Anchor and Applies-to reference
    of the active entries with pyeye (:mod:`pyeye.decision_check`, #1182),
    in *project_root* (``--project-root``, default the working directory). A
    short form fails in entries dated on or after *short_forms_fail_from*.
    It needs pyeye importable: without it the check fails, never passes.
    """
    # Titles carry non-ASCII (—, ·, ↔). A Windows console defaults to cp1252.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog=command, description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--decisions-dir",
        type=Path,
        default=decisions_dir if decisions_dir is not None else DEFAULT_DECISIONS_DIR,
        help="the decision log's directory, holding entries/ (default: docs/decisions)",
    )
    parser.add_argument(
        "--grandfathered",
        action="append",
        default=[],
        metavar="NAME",
        help="an entry file exempt from the Applies-to rule (repeatable)",
    )
    parser.add_argument("--dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--log", type=Path, default=None, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index", help="list entries, newest first")
    index.add_argument("--symbol", help="only entries whose anchors contain this text")
    index.add_argument("--issue", type=int, help="only entries for this issue number")
    index.add_argument("--active", action="store_true", help="hide superseded entries")
    index.add_argument("--status", choices=STATUSES, help="only entries with this status")
    check_parser = sub.add_parser("check", help="validate every entry (run in CI)")
    check_parser.add_argument(
        "--resolve",
        action="store_true",
        help="also resolve every Anchor and Applies-to reference with pyeye (#1182)",
    )
    check_parser.add_argument(
        "--project-root",
        type=Path,
        default=project_root if project_root is not None else Path("."),
        help="the project --resolve resolves references in (default: the working directory)",
    )
    migrate_parser = sub.add_parser(
        "migrate", help="split entries still in DECISIONS.md into files"
    )
    migrate_parser.add_argument(
        "--update",
        action="store_true",
        help="replace an existing entry's body when the DECISIONS.md text differs",
    )
    args = parser.parse_args(argv)
    entries_dir: Path = args.dir if args.dir is not None else args.decisions_dir / "entries"
    log_file: Path = args.log if args.log is not None else args.decisions_dir / "DECISIONS.md"
    exempt = grandfathered | frozenset(args.grandfathered)

    if args.command == "migrate":
        try:
            for note in migrate(log_file, entries_dir, update=args.update, header=header):
                print(note)
        except EntryError as exc:
            print(f"decisions: {exc}", file=sys.stderr)
            return 1
        return 0

    entries, errors = load(entries_dir)
    if (
        not entries
        and not errors
        and not (log_file.exists() and entries_in_log(log_file.read_text(encoding="utf-8")))
    ):
        where = entries_dir.as_posix()
        print(
            f"decisions: no entries ({where} {'is empty' if entries_dir.is_dir() else 'does not exist'})"
        )
        return 0
    if args.command == "check":
        problems = errors + check(entries, exempt) + stale_grandfathered(entries, exempt)
        if args.resolve:
            problems += _resolve(entries, entries_dir, args.project_root, short_forms_fail_from)
        if log_file.exists():
            left = entries_in_log(log_file.read_text(encoding="utf-8"))
            if left:
                problems.append(
                    f"{log_file.name}: found {len(left)} entr{'y' if len(left) == 1 else 'ies'} "
                    "in DECISIONS.md; decisions are one file each now (#679). "
                    f"Run `{command} migrate`."
                )
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
