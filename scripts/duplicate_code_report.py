#!/usr/bin/env python3
"""Duplicate-code ratchet over normalised AST tokens (#616, blocking since #636).

A crude first pass toward #495. Each target file is flattened into a stream of
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
``src/pyeye/canonicalization.py``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    "src/pyeye/mcp/operations",
    "src/pyeye/canonicalization.py",
)
DEFAULT_MIN_TOKENS = 35

#: Known clone sites -> the issue expected to remove them. Keys are the sorted
#: pair of ``file::qualname`` for the innermost function/class enclosing each
#: region (see :func:`site`). Shrinks to empty as #629 Phase 2 lands; delete an
#: entry when its copy goes, or the ratchet fails.
BASELINE: dict[tuple[str, str], str] = {
    # The same skip-seen / build-full-name / _try_handle / append loop.
    (
        "src/pyeye/mcp/operations/edges.py::_class_members",
        "src/pyeye/mcp/operations/edges.py::_module_members",
    ): "#686",
    # The per-edge kind gate and jedi_name getattr preamble, one copy per
    # resolver; one edge-applicability table replaces them.
    (
        "src/pyeye/mcp/operations/edges.py::resolve_imported_by",
        "src/pyeye/mcp/operations/edges.py::superclass_bases",
    ): "#626",
}

_SKIP = (ast.expr_context, ast.Load, ast.Store, ast.Del)


@dataclass(frozen=True)
class Token:
    """One normalised AST token and where it came from."""

    file: str
    lineno: int
    text: str


@dataclass(frozen=True)
class Clone:
    """Two source regions with the same normalised token run."""

    a_file: str
    a_start: int
    a_end: int
    b_file: str
    b_start: int
    b_end: int
    tokens: int


def _is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def tokenize(source: str, file: str) -> list[Token]:
    """Flatten *source* into normalised tokens in source order.

    Imports and docstrings are skipped: shared import blocks are not logic.
    """
    tokens: list[Token] = []

    def visit(node: ast.AST, lineno: int) -> None:
        if isinstance(node, _SKIP):
            return
        lineno = getattr(node, "lineno", lineno)
        text = type(node).__name__
        if isinstance(node, ast.Attribute):
            text = f"{text}.{node.attr}"
        elif isinstance(node, ast.Constant):
            text = f"{text}:{type(node.value).__name__}"
        tokens.append(Token(file, lineno, text))
        for child in ast.iter_child_nodes(node):
            if _is_docstring(child) or isinstance(child, (ast.Import, ast.ImportFrom)):
                continue
            visit(child, lineno)

    tree = ast.parse(source, filename=file)
    for stmt in tree.body:
        if not (_is_docstring(stmt) or isinstance(stmt, (ast.Import, ast.ImportFrom))):
            visit(stmt, 1)
    return tokens


def collect(paths: list[Path], root: Path = REPO_ROOT) -> list[list[Token]]:
    """Tokenise every ``.py`` file under *paths*; one token stream per file."""
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    streams: list[list[Token]] = []
    for file in files:
        try:
            display = file.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            display = file.as_posix()
        streams.append(tokenize(file.read_text(encoding="utf-8"), display))
    return streams


def find_clones(streams: list[list[Token]], min_tokens: int = DEFAULT_MIN_TOKENS) -> list[Clone]:
    """Return maximal token runs of length >= *min_tokens* that occur twice.

    Classic shingling: index every window of *min_tokens* tokens, then extend
    each match forward as far as the streams keep agreeing. Overlapping or
    self-overlapping matches are dropped.
    """
    index: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    for s, stream in enumerate(streams):
        texts = [t.text for t in stream]
        for i in range(len(texts) - min_tokens + 1):
            index[tuple(texts[i : i + min_tokens])].append((s, i))

    covered: set[tuple[int, int, int, int]] = set()
    clones: list[Clone] = []
    for positions in index.values():
        for x in range(len(positions)):
            for y in range(x + 1, len(positions)):
                (sa, ia), (sb, ib) = positions[x], positions[y]
                if (sa, ia, sb, ib) in covered:
                    continue  # interior of a run already reported
                if sa == sb and ib < ia + min_tokens:
                    continue  # overlaps itself
                a, b = streams[sa], streams[sb]
                n = min_tokens
                while (
                    ia + n < len(a)
                    and ib + n < len(b)
                    and a[ia + n].text == b[ib + n].text
                    and not (sa == sb and ia + n >= ib)
                ):
                    n += 1
                for k in range(n - min_tokens + 1):
                    covered.add((sa, ia + k, sb, ib + k))
                clones.append(
                    Clone(
                        a[ia].file,
                        a[ia].lineno,
                        max(t.lineno for t in a[ia : ia + n]),
                        b[ib].file,
                        b[ib].lineno,
                        max(t.lineno for t in b[ib : ib + n]),
                        n,
                    )
                )
    clones.sort(key=lambda c: (-c.tokens, c.a_file, c.a_start))
    return _drop_nested(clones)


def _contains(outer: Clone, inner: Clone) -> bool:
    return (
        outer.a_file == inner.a_file
        and outer.b_file == inner.b_file
        and outer.a_start <= inner.a_start
        and inner.a_end <= outer.a_end
        and outer.b_start <= inner.b_start
        and inner.b_end <= outer.b_end
    )


def _drop_nested(clones: list[Clone]) -> list[Clone]:
    """Drop a clone whose two regions both sit inside a longer reported clone.

    The same copy can match at two token alignments (repeated token runs), which
    would otherwise print it twice. *clones* must be sorted longest first.
    """
    kept: list[Clone] = []
    for clone in clones:
        if not any(_contains(k, clone) for k in kept):
            kept.append(clone)
    return kept


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def enclosing(file: str, line: int, root: Path = REPO_ROOT) -> str:
    """Qualified name of the innermost function/class around *line* in *file*.

    *file* is the display path :func:`collect` produced, relative to *root*.
    ``"<module>"`` when the line is at module level.
    """
    tree = ast.parse((root / file).read_text(encoding="utf-8"), filename=file)
    best = "<module>"

    def visit(node: ast.AST, prefix: str) -> None:
        nonlocal best
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPES):
                qual = f"{prefix}{child.name}"
                end = child.end_lineno or child.lineno
                if child.lineno <= line <= end:
                    best = qual
                    visit(child, qual + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return best


def site(clone: Clone, root: Path = REPO_ROOT) -> tuple[str, str]:
    """A clone's stable key: the sorted pair of ``file::qualname`` around each region."""
    a = f"{clone.a_file}::{enclosing(clone.a_file, clone.a_start, root)}"
    b = f"{clone.b_file}::{enclosing(clone.b_file, clone.b_start, root)}"
    return (a, b) if a <= b else (b, a)


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
    streams = collect(paths, root=args.root)
    clones = find_clones(streams, args.min_tokens)
    print(format_report(clones, len(streams), args.min_tokens))
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
