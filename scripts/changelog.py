#!/usr/bin/env python3
"""Release tooling for the hand-curated CHANGELOG.md (#583).

Versions come from git tags (setuptools_scm, #210); the CHANGELOG is written by
hand. This script connects the two without generating any prose.

PRs don't edit ``[Unreleased]``; each adds a hand-written fragment,
``changes/<issue>.<category>.md`` (``<issue>-<n>`` for a second PR on the same
issue), holding one or more ``- `` bullets (#660). Categories map to headings:
see :data:`CATEGORIES`.

* ``prepare X.Y.Z``: collect the fragments and any bullets already under
  ``[Unreleased]`` into ``[X.Y.Z] - <today>`` for a release PR, checking the
  bump level against the result, then delete the fragments. It also stamps
  ``X.Y.Z`` over every ``"unreleased"`` release in the docs-facts ledgers
  (:data:`FACT_LEDGERS`, #826), so a removal or a newly uncovered fact records
  the release it shipped in.
* ``notes X.Y.Z``: print one version's section (the GitHub Release body).
* ``latest``: print the newest released version.
* ``pending-release``: print the version ``tag-release.yml`` should tag after a
  merge, or nothing.
* ``check``: validate structure, tag consistency and fragment names (CI).
* ``no-breaking``: print how many breaking changes are pending (an
  ``[Unreleased]`` ``### BREAKING CHANGES`` heading or ``*.breaking.md``
  fragments) and fail if any are: the v2.x guard.

Stdlib only, so CI can run it with a bare ``python`` before any env is synced.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
UNRELEASED = "Unreleased"
FRAGMENTS_DIRNAME = "changes"

#: The docs-facts ledgers whose ``removed_in`` / ``first_seen`` say ``"unreleased"``
#: until a release is prepared (#826). A checkout without them is skipped.
FACT_LEDGERS = ("docs/facts/removed.json", "docs/facts/uncovered.json")
_UNRELEASED_FIELD = re.compile(r'("(?:removed_in|first_seen)": )"unreleased"')

#: Fragment category -> CHANGELOG heading, in the order a release section lists
#: them (Keep a Changelog, with breaking changes first as in 1.0.0 and 2.0.0).
CATEGORIES: dict[str, str] = {
    "breaking": "BREAKING CHANGES",
    "added": "Added",
    "changed": "Changed",
    "deprecated": "Deprecated",
    "removed": "Removed",
    "fixed": "Fixed",
    "security": "Security",
}
#: Files in ``changes/`` that aren't fragments.
_NOT_FRAGMENTS = frozenset({"README.md", ".gitkeep"})
_FRAGMENT_NAME = re.compile(r"^(?P<issue>\d+)(?:-(?P<n>\d+))?\.(?P<category>[^.]+)\.md$")
_MD_HEADING = re.compile(r"^#{1,6}\s")
_SUBHEADING = re.compile(r"^###\s+(?P<title>.+?)\s*$")

_HEADING = re.compile(r"^## (?P<rest>.*)$")
_SECTION = re.compile(
    r"^\[(?P<name>Unreleased|\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)\]"
    r"(?: - (?P<date>\d{4}-\d{2}-\d{2}))?$"
)
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")
_PRE_RANK = {"a": 0, "b": 1, "rc": 2, None: 3}
_BREAKING = re.compile(r"^###\s+BREAKING CHANGES\b", re.MULTILINE | re.IGNORECASE)
_ADDED = re.compile(r"^###\s+Added\b", re.MULTILINE | re.IGNORECASE)


class ChangelogError(Exception):
    """A CHANGELOG problem to report to the user (exit 1)."""


@dataclass(frozen=True)
class Section:
    """One ``## [...]`` section of the CHANGELOG."""

    name: str
    date: str | None
    line: int  # 1-based line number of the heading
    body: str

    @property
    def released(self) -> bool:
        """Whether this is a versioned (not Unreleased) section."""
        return self.name != UNRELEASED


@dataclass(frozen=True)
class Fragment:
    """One ``changes/<issue>[-<n>].<category>.md`` file."""

    path: Path
    issue: int
    n: int
    category: str
    text: str


def parse_fragment_name(name: str) -> tuple[int, int, str]:
    """``(issue, n, category)`` for a fragment file name; raises if it isn't one."""
    m = _FRAGMENT_NAME.match(name)
    if not m:
        raise ChangelogError(
            f"{name}: not a fragment name (expected <issue>.<category>.md or "
            "<issue>-<n>.<category>.md)"
        )
    if m["category"] not in CATEGORIES:
        raise ChangelogError(
            f"{name}: unknown category {m['category']!r} (one of: {', '.join(CATEGORIES)})"
        )
    return int(m["issue"]), int(m["n"] or 0), m["category"]


def _content_problem(text: str) -> str | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "is empty"
    if not lines[0].startswith("- "):
        return "must start with a '- ' bullet"
    if any(_MD_HEADING.match(line) for line in lines):
        return "must not contain a heading (the category is in the file name)"
    return None


def fragment_problems(directory: Path) -> list[str]:
    """Every problem with the fragments in *directory* (missing directory: none)."""
    if not directory.is_dir():
        return []
    problems = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.name in _NOT_FRAGMENTS:
            continue
        rel = f"{FRAGMENTS_DIRNAME}/{path.name}"
        if not path.is_file():
            problems.append(f"{rel}: not a file")
            continue
        try:
            parse_fragment_name(path.name)
        except ChangelogError as exc:
            problems.append(f"{FRAGMENTS_DIRNAME}/{exc}")
            continue
        problem = _content_problem(path.read_text(encoding="utf-8"))
        if problem:
            problems.append(f"{rel} {problem}")
    return problems


def read_fragments(directory: Path) -> list[Fragment]:
    """The fragments in *directory*, by issue then suffix; raises on any problem."""
    problems = fragment_problems(directory)
    if problems:
        raise ChangelogError("invalid changelog fragments:\n  " + "\n  ".join(problems))
    if not directory.is_dir():
        return []
    fragments = []
    for path in directory.iterdir():
        if path.name in _NOT_FRAGMENTS:
            continue
        issue, n, category = parse_fragment_name(path.name)
        fragments.append(Fragment(path, issue, n, category, path.read_text(encoding="utf-8")))
    return sorted(fragments, key=lambda f: (f.issue, f.n))


def assemble(body: str, fragments: list[Fragment]) -> str:
    """Merge *fragments* into an ``[Unreleased]`` *body*, ordered by :data:`CATEGORIES`.

    Existing content under a heading is kept verbatim and comes first; each
    fragment's bullets follow, in fragment order. Text before the first
    ``###`` heading stays on top, and headings that aren't a category keep
    their place after the known ones.
    """
    preamble: list[str] = []
    blocks: dict[str, list[str]] = {}  # heading title -> content parts
    current: list[str] = preamble
    by_title = {title.lower(): title for title in CATEGORIES.values()}
    for line in body.splitlines():
        m = _SUBHEADING.match(line)
        if m:
            title = by_title.get(m["title"].lower(), m["title"])
            current = blocks.setdefault(title, [])
            current.append("")  # separates content from an earlier same-titled block
            continue
        current.append(line)
    parts = {title: ["\n".join(lines).strip()] for title, lines in blocks.items()}
    for fragment in fragments:
        parts.setdefault(CATEGORIES[fragment.category], []).append(fragment.text.strip())

    known = [t for t in CATEGORIES.values() if t in parts]
    others = [t for t in parts if t not in CATEGORIES.values()]
    out = ["\n".join(preamble).strip()]
    for title in known + others:
        content = "\n".join(part for part in parts[title] if part)
        if content:
            out.append(f"### {title}\n\n{content}")
    return "\n\n".join(chunk for chunk in out if chunk)


def breaking_pending(text: str, directory: Path) -> list[str]:
    """What would make the next release breaking: the v2.x guard's findings.

    An ``[Unreleased]`` ``### BREAKING CHANGES`` heading, and every
    ``*.breaking.md`` file in *directory*, whether or not its name is otherwise
    valid.
    """
    found = []
    for section in parse(text):
        if not section.released and _BREAKING.search(section.body):
            found.append(f"[Unreleased] (line {section.line}) has '### BREAKING CHANGES'")
    if directory.is_dir():
        found += sorted(
            f"{FRAGMENTS_DIRNAME}/{path.name}"
            for path in directory.iterdir()
            if path.name.endswith(".breaking.md")
        )
    return found


def version_key(version: str) -> tuple[int, int, int, int, int]:
    """Sort key for ``X.Y.Z`` / ``X.Y.ZrcN``; raises for anything else."""
    m = _VERSION.match(version)
    if not m:
        raise ChangelogError(f"not a release version: {version!r} (expected X.Y.Z)")
    major, minor, patch, pre, num = m.groups()
    return (int(major), int(minor), int(patch), _PRE_RANK[pre], int(num or 0))


def parse(text: str) -> list[Section]:
    """Split *text* into sections; every ``## `` heading must be well-formed."""
    lines = text.splitlines()
    starts: list[tuple[int, str, str | None]] = []
    for i, line in enumerate(lines):
        h = _HEADING.match(line)
        if not h:
            continue
        m = _SECTION.match(h["rest"].strip())
        if not m:
            raise ChangelogError(
                f"line {i + 1}: malformed heading {line!r} "
                "(expected '## [Unreleased]' or '## [X.Y.Z] - YYYY-MM-DD')"
            )
        starts.append((i, m["name"], m["date"]))
    sections = []
    for n, (i, name, date) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        sections.append(Section(name, date, i + 1, "\n".join(lines[i + 1 : end]).strip()))
    return sections


def released(sections: list[Section]) -> list[Section]:
    """Return only the versioned sections, newest first."""
    return [s for s in sections if s.released]


def latest_version(sections: list[Section]) -> str | None:
    """The newest released version: the first released section in the file."""
    rel = released(sections)
    return rel[0].name if rel else None


def git_tag_versions(cwd: Path) -> list[str]:
    """Release versions that have a ``v*`` git tag (unparseable tags ignored)."""
    result = subprocess.run(  # noqa: S603 - fixed git invocation
        ["git", "tag", "--list", "v*"],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ChangelogError(
            f"could not list git tags in {cwd.as_posix()}: {result.stderr.strip()}"
        )
    out = result.stdout
    versions = []
    for tag in out.split():
        candidate = tag[1:]
        if _VERSION.match(candidate):
            versions.append(candidate)
    return versions


def required_bump(body: str, previous: str) -> str:
    """The minimum bump the release notes in *body* call for."""
    if _BREAKING.search(body):
        # SemVer: before 1.0, a minor bump may break.
        return "major" if version_key(previous)[0] >= 1 else "minor"
    if _ADDED.search(body):
        return "minor"
    return "patch"


def bump_kind(previous: str, new: str) -> str:
    """Classify the step from ``previous`` to ``new`` as major, minor or patch."""
    p, n = version_key(previous), version_key(new)
    if n[0] > p[0]:
        return "major"
    if n[0] == p[0] and n[1] > p[1]:
        return "minor"
    return "patch"


_BUMP_ORDER = {"patch": 0, "minor": 1, "major": 2}


def prepare(
    text: str,
    version: str,
    tags: list[str],
    today: str,
    fragments: list[Fragment] | None = None,
) -> str:
    """Return *text* with ``[Unreleased]`` and *fragments* released as ``[version] - today``.

    The new section is :func:`assemble`'s merge of the existing ``[Unreleased]``
    body and the fragments; ``[Unreleased]`` is left empty. Deleting the
    fragment files is the caller's job, after the result is written.
    """
    sections = parse(text)
    unreleased = [s for s in sections if not s.released]
    if len(unreleased) != 1:
        raise ChangelogError("expected exactly one '## [Unreleased]' section")
    body = assemble(unreleased[0].body, fragments or [])
    if not body:
        raise ChangelogError(
            f"[Unreleased] is empty and there are no {FRAGMENTS_DIRNAME}/ fragments; "
            "nothing to release"
        )

    known = [s.name for s in released(sections)] + tags
    if version in known:
        raise ChangelogError(f"{version} is already released (section or tag exists)")
    previous = max(known, key=version_key) if known else None
    if previous is not None:
        if version_key(version) <= version_key(previous):
            raise ChangelogError(f"{version} is not newer than the latest release {previous}")
        need, got = required_bump(body, previous), bump_kind(previous, version)
        if _BUMP_ORDER[got] < _BUMP_ORDER[need]:
            reason = "### BREAKING CHANGES" if _BREAKING.search(body) else "### Added"
            raise ChangelogError(
                f"{previous} -> {version} is a {got} bump, but the release notes have "
                f"'{reason}', which needs at least a {need} bump"
            )

    lines = text.splitlines(keepends=True)
    start = unreleased[0].line - 1
    later = [s.line - 1 for s in sections if s.line > unreleased[0].line]
    end = later[0] if later else len(lines)
    new = f"## [{UNRELEASED}]\n\n## [{version}] - {today}\n\n{body}\n"
    if later:
        new += "\n"
    return "".join(lines[:start]) + new + "".join(lines[end:])


def stamp_unreleased(text: str, version: str) -> str:
    """Replace each ``"unreleased"`` ``removed_in`` / ``first_seen`` value with *version*.

    Only those JSON values change, so a note that says "unreleased" is left alone.
    """
    return _UNRELEASED_FIELD.sub(rf'\1"{version}"', text)


def stamp_fact_ledgers(repo: Path, version: str) -> list[str]:
    """Stamp *version* into each docs-facts ledger that exists; return those changed."""
    changed = []
    for rel in FACT_LEDGERS:
        ledger = repo / rel
        if not ledger.is_file():
            continue
        text = ledger.read_text(encoding="utf-8")
        new = stamp_unreleased(text, version)
        if new != text:
            ledger.write_text(new, encoding="utf-8", newline="\n")
            changed.append(rel)
    return changed


def notes(text: str, version: str) -> str:
    """Return the body of the ``[version]`` section, for use as release notes."""
    for s in parse(text):
        if s.name == version:
            if not s.body:
                raise ChangelogError(f"[{version}] has no content")
            return s.body
    raise ChangelogError(f"no '## [{version}]' section in CHANGELOG.md")


_PR_MERGE_SUBJECT = re.compile(r"^Merge pull request #\d+ from \S+$")


def release_title(version: str) -> str:
    """The commit subject and PR title of a release (#587).

    It must be a valid conventional commit, because the commitizen
    ``commit-msg`` hook rejects anything else (``release: v…`` included). And
    commit and PR title must agree, because a single-commit squash uses the
    commit subject.
    """
    return f"chore(release): v{version}"


def pr_title(head_message: str) -> str:
    """The PR title a merge to ``main`` came from, given its commit message.

    A squash merge's subject *is* the title (``chore(release): v2.0.0 (#600)``). A merge
    commit's subject is ``Merge pull request #N from <branch>``, and GitHub puts
    the title on the next non-empty line (#585). Anything else is just the
    subject.
    """
    lines = [line.strip() for line in head_message.strip().splitlines()]
    subject = lines[0] if lines else ""
    if _PR_MERGE_SUBJECT.match(subject):
        return next((line for line in lines[1:] if line), "")
    return subject


def pending_release(text: str, tags: list[str], head_message: str) -> str | None:
    """The version to tag for a merge to ``main`` whose message is *head_message*.

    Tags only when the newest released section is untagged **and** the merge
    came from a release PR (titled :func:`release_title`), so a stray heading can't
    publish. Squash and merge-commit merges are both recognised.
    """
    version = latest_version(parse(text))
    if version is None or version in tags:
        return None
    if not re.match(rf"^{re.escape(release_title(version))}\b", pr_title(head_message)):
        return None
    return version


def check(text: str, tags: list[str] | None) -> list[str]:
    """Return every problem found (empty list == valid)."""
    try:
        sections = parse(text)
    except ChangelogError as exc:
        return [str(exc)]
    problems = []
    if not sections or sections[0].name != UNRELEASED:
        problems.append("the first section must be '## [Unreleased]'")
    if sum(not s.released for s in sections) > 1:
        problems.append("more than one '## [Unreleased]' section")

    rel = released(sections)
    seen: set[str] = set()
    for s in rel:
        if s.name in seen:
            problems.append(f"line {s.line}: duplicate section [{s.name}]")
        seen.add(s.name)
        if not s.date:
            problems.append(f"line {s.line}: [{s.name}] has no '- YYYY-MM-DD' date")
        if not s.body:
            problems.append(f"line {s.line}: [{s.name}] has no content")
    for a, b in zip(rel, rel[1:], strict=False):
        if version_key(a.name) <= version_key(b.name):
            problems.append(f"line {b.line}: [{b.name}] is out of order (newest first)")

    if tags is not None:
        for tag in sorted(set(tags) - seen, key=version_key):
            problems.append(f"tag v{tag} has no '## [{tag}]' section")
        newest_tag = max(tags, key=version_key) if tags else None
        for n, s in enumerate(rel):
            if s.name in tags:
                continue
            pending_ok = n == 0 and (
                newest_tag is None or version_key(s.name) > version_key(newest_tag)
            )
            if not pending_ok:
                problems.append(
                    f"line {s.line}: [{s.name}] has no v{s.name} tag "
                    "(only the newest section may be a pending release)"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--changelog", type=Path, default=CHANGELOG)
    sub = parser.add_subparsers(dest="command", required=True)
    p_prep = sub.add_parser("prepare", help="promote [Unreleased] for a release PR")
    p_prep.add_argument("version")
    p_prep.add_argument("--date", help="release date (default: today, UTC)")
    sub.add_parser("notes", help="print a version's section").add_argument("version")
    sub.add_parser("latest", help="print the newest released version")
    p_pend = sub.add_parser("pending-release", help="version to tag after a merge")
    p_pend.add_argument(
        "--head-message", required=True, help="full message of the merge commit on main"
    )
    p_check = sub.add_parser("check", help="validate CHANGELOG.md and fragments (CI)")
    p_check.add_argument("--no-tags", action="store_true", help="skip tag consistency")
    sub.add_parser(
        "no-breaking",
        help="print the number of pending breaking changes; fail if any (v2.x guard)",
    )
    args = parser.parse_args(argv)

    path: Path = args.changelog
    text = path.read_text(encoding="utf-8")
    repo = path.resolve().parent
    fragments_dir = repo / FRAGMENTS_DIRNAME
    try:
        if args.command == "prepare":
            version_key(args.version)
            today = args.date or _dt.datetime.now(_dt.UTC).date().isoformat()
            fragments = read_fragments(fragments_dir)
            path.write_text(
                prepare(text, args.version, git_tag_versions(repo), today, fragments),
                encoding="utf-8",
            )
            for fragment in fragments:
                fragment.path.unlink()
            stamped = stamp_fact_ledgers(repo, args.version)
            print(
                f"Released [Unreleased] and {len(fragments)} fragment(s) as "
                f"[{args.version}] - {today} in {path.name}."
            )
            print(*(f"Stamped {args.version} into {f}." for f in stamped), sep="\n")
            print(
                f"Next: commit and open a PR, both titled '{release_title(args.version)}'. "
                "Merging it tags and publishes."
            )
        elif args.command == "notes":
            print(notes(text, args.version))
        elif args.command == "latest":
            print(latest_version(parse(text)) or "")
        elif args.command == "pending-release":
            print(pending_release(text, git_tag_versions(repo), args.head_message) or "")
        elif args.command == "check":
            tags = None if args.no_tags else git_tag_versions(repo)
            if tags is not None and not tags:
                raise ChangelogError(
                    "no v* tags found; fetch tags (fetch-depth: 0) or pass --no-tags"
                )
            problems = [f"CHANGELOG.md: {p}" for p in check(text, tags)]
            problems += fragment_problems(fragments_dir)
            for problem in problems:
                print(problem, file=sys.stderr)
            if problems:
                return 1
            print(f"CHANGELOG.md OK ({len(released(parse(text)))} released versions)")
        elif args.command == "no-breaking":
            found = breaking_pending(text, fragments_dir)
            print(len(found))
            for item in found:
                print(f"breaking change pending: {item}", file=sys.stderr)
            if found:
                return 1
    except ChangelogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
