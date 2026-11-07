#!/usr/bin/env python3
"""Release tooling for the hand-curated CHANGELOG.md (#583).

Versions come from git tags (setuptools_scm, #210); the CHANGELOG is written by
hand. This script connects the two without generating any prose:

* ``prepare X.Y.Z``: turn ``[Unreleased]`` into ``[X.Y.Z] - <today>`` for a
  release PR, checking the bump level against the content.
* ``notes X.Y.Z``: print one version's section (the GitHub Release body).
* ``latest``: print the newest released version.
* ``pending-release``: print the version ``tag-release.yml`` should tag after a
  merge, or nothing.
* ``check``: validate structure and tag consistency (CI).

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


def prepare(text: str, version: str, tags: list[str], today: str) -> str:
    """Return *text* with ``[Unreleased]`` promoted to ``[version] - today``."""
    sections = parse(text)
    unreleased = [s for s in sections if not s.released]
    if len(unreleased) != 1:
        raise ChangelogError("expected exactly one '## [Unreleased]' section")
    body = unreleased[0].body
    if not body:
        raise ChangelogError("[Unreleased] is empty; nothing to release")

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
                f"{previous} -> {version} is a {got} bump, but [Unreleased] has "
                f"'{reason}', which needs at least a {need} bump"
            )

    lines = text.splitlines(keepends=True)
    idx = unreleased[0].line - 1
    lines[idx] = f"## [{UNRELEASED}]\n\n## [{version}] - {today}\n"
    return "".join(lines)


def notes(text: str, version: str) -> str:
    """Return the body of the ``[version]`` section, for use as release notes."""
    for s in parse(text):
        if s.name == version:
            if not s.body:
                raise ChangelogError(f"[{version}] has no content")
            return s.body
    raise ChangelogError(f"no '## [{version}]' section in CHANGELOG.md")


_PR_MERGE_SUBJECT = re.compile(r"^Merge pull request #\d+ from \S+$")


def pr_title(head_message: str) -> str:
    """The PR title a merge to ``main`` came from, given its commit message.

    A squash merge's subject *is* the title (``release: v2.0.0 (#600)``). A merge
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
    came from a release PR (title ``release: vX.Y.Z``), so a stray heading can't
    publish. Squash and merge-commit merges are both recognised.
    """
    version = latest_version(parse(text))
    if version is None or version in tags:
        return None
    if not re.match(rf"^release: v{re.escape(version)}\b", pr_title(head_message)):
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
    p_check = sub.add_parser("check", help="validate CHANGELOG.md (CI)")
    p_check.add_argument("--no-tags", action="store_true", help="skip tag consistency")
    args = parser.parse_args(argv)

    path: Path = args.changelog
    text = path.read_text(encoding="utf-8")
    repo = path.resolve().parent
    try:
        if args.command == "prepare":
            version_key(args.version)
            today = args.date or _dt.datetime.now(_dt.UTC).date().isoformat()
            path.write_text(
                prepare(text, args.version, git_tag_versions(repo), today), encoding="utf-8"
            )
            print(f"Promoted [Unreleased] to [{args.version}] - {today} in {path.name}.")
            print(
                f"Next: open a PR titled 'release: v{args.version}'. Merging it tags and publishes."
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
            problems = check(text, tags)
            for problem in problems:
                print(f"CHANGELOG.md: {problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"CHANGELOG.md OK ({len(released(parse(text)))} released versions)")
    except ChangelogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
