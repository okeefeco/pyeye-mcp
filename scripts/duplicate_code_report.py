#!/usr/bin/env python3
"""Duplicate-code ratchet over normalised AST tokens (#616, blocking since #636).

The detector itself lives in :mod:`pyeye.duplication` (#495), shared with the
``duplication-review`` skill; this script is the repository's ratchet over it,
with no review guards: every exact-match clone counts. Each target file is flattened into a stream of
AST tokens: the node type, plus attribute names (``.infer``, ``.full_name``)
because they carry the API being used. Local identifiers, literal values,
docstrings and comments are dropped, so a **renamed copy** still matches.
Line-based tools such as pylint's ``duplicate-code`` miss those because the
text differs.

Any run of at least ``--min-tokens`` identical tokens that appears at two places
is reported as one clone region (``file:start-end <-> file:start-end``). Runs
inside one statement list and copies spanning different files are both caught.

It is a RATCHET, like the #614/#615 fitness tests. Each clone is keyed by its
*site*: the two enclosing functions (``file::qualname``), so moving code up or
down a file doesn't change it. :data:`BASELINE` lists the known sites, each with
the issue expected to remove it. The comparison is exact both ways:

* a site not in the baseline fails (a new copy: consolidate it instead);
* a baselined site that no longer occurs fails too, until its entry is deleted.

Modes:
    (default)            ratchet against BASELINE; exit 1 on a new or stale site
    --report-only        print the report, always exit 0
    --fail-on-findings   exit 1 on ANY clone, baselined or not

Usage:
    duplicate_code_report.py [--min-tokens N] [--report-only | --fail-on-findings] [paths ...]

With no paths it scans ``src/pyeye/mcp/operations`` and
``src/pyeye/canonicalization.py``. A token window seen more than
``pyeye.duplication.DEFAULT_MAX_OCCURRENCES`` times is paired with its next
occurrence only (#495): the pair loop stays linear on repeated data, and every
copy is still reported, so a 51-way copy fails the ratchet like a 2-way one.
A target file that can't be parsed fails the ratchet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyeye import duplication
from pyeye.duplication import (  # re-exported: the tests and callers use these names
    DEFAULT_MIN_TOKENS,
    Clone,
    Token,
    _drop_nested,
    find_clones,
    tokenize,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    "src/pyeye/mcp/operations",
    "src/pyeye/canonicalization.py",
)

#: Known clone sites -> the issue expected to remove them. Keys are the sorted
#: pair of ``file::qualname`` for the innermost function/class enclosing each
#: region (see :func:`site`). Shrinks to empty as #629 Phase 2 lands; delete an
#: entry when its copy goes, or the ratchet fails.
BASELINE: dict[tuple[str, str], str] = {}

__all__ = [
    "BASELINE",
    "DEFAULT_MIN_TOKENS",
    "DEFAULT_TARGETS",
    "Clone",
    "Token",
    "_drop_nested",
    "collect",
    "enclosing",
    "find_clones",
    "format_report",
    "main",
    "ratchet",
    "site",
    "tokenize",
]


def collect(
    paths: list[Path], root: Path = REPO_ROOT, unparseable: list[str] | None = None
) -> list[list[Token]]:
    """Tokenise every ``.py`` file under *paths*; one token stream per file."""
    return duplication.collect(paths, root, unparseable)


def enclosing(file: str, line: int, root: Path = REPO_ROOT) -> str:
    """Qualified name of the innermost function/class around *line* in *file*."""
    return duplication.enclosing(file, line, root)


def site(clone: Clone, root: Path = REPO_ROOT) -> tuple[str, str]:
    """A clone's stable key: the sorted pair of ``file::qualname`` around each region."""
    return duplication.site(clone, root)


def format_report(clones: list[Clone], files: int, min_tokens: int) -> str:
    """Render clones as a human-readable report."""
    lines = [
        f"duplicate-code report (#616): {len(clones)} clone region(s) "
        f"of >= {min_tokens} AST tokens across {files} file(s)"
    ]
    for c in clones:
        lines.append(
            f"  {c.tokens:4d} tokens  {c.a_file}:{c.a_start}-{c.a_end}"
            f"  <->  {c.b_file}:{c.b_start}-{c.b_end}"
        )
    return "\n".join(lines)


def ratchet(
    found: set[tuple[str, str]], baseline: dict[tuple[str, str], str]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """``(new, stale)`` sites: found but not baselined, baselined but not found."""
    return sorted(found - set(baseline)), sorted(set(baseline) - found)


def main(argv: list[str] | None = None) -> int:
    """Entry point: the ratchet by default (exit 1 on a new or stale site)."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--min-tokens", type=int, default=DEFAULT_MIN_TOKENS)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report-only", action="store_true", help="print the report; exit 0")
    mode.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="exit 1 on any clone, baselined or not",
    )
    args = parser.parse_args(argv)
    paths = args.paths or [args.root / t for t in DEFAULT_TARGETS]
    unparseable: list[str] = []
    streams = collect(paths, root=args.root, unparseable=unparseable)
    clones = find_clones(streams, args.min_tokens)
    print(format_report(clones, len(streams), args.min_tokens))
    if unparseable:
        # A file the ratchet can't read would hide its copies: never pass silently.
        print("  unparseable (not checked): " + "; ".join(unparseable))
        return 1
    if args.report_only:
        return 0
    if args.fail_on_findings:
        return 1 if clones else 0

    new, stale = ratchet({site(c, args.root) for c in clones}, BASELINE)
    for key in new:
        print(f"  NEW duplicate (not in BASELINE): {key[0]}  <->  {key[1]}")
    for key in stale:
        print(f"  baselined duplicate no longer found ({BASELINE[key]}): delete its entry: {key}")
    if new:
        print(
            "  Consolidate the copy instead of adding to BASELINE "
            "(docs/development/duplicate-code-check.md)."
        )
    return 1 if (new or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
