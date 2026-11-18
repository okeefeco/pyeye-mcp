"""Exact-match duplicate-code detection over normalised AST tokens (#616, #495).

Two consumers share this core:

* the repository's **ratchet** (``scripts/duplicate_code_report.py``), which uses
  only :func:`collect`, :func:`find_clones` and :func:`site`; and
* **duplication review** (``python -m pyeye.duplication``, the
  ``duplication-review`` skill), which adds the guards, families and
  dismissal state below.

Detection
---------
Each file is flattened into a stream of AST tokens: the node type, plus
attribute names (``.infer``) and constant *types*. Local names, literal values,
docstrings, comments and imports are dropped, so a copy whose locals were
renamed still matches. Any run of at least ``min_tokens`` identical tokens at
two places is a clone. A token window seen more than ``max_occurrences`` times
is not paired all-against-all (#495): each occurrence is paired with the next
one only, so the work stays linear in the number of copies and a heavily copied
block still connects into one family. All-pairs work on repeated data tables
ran a real run out of memory. A file that can't be read or parsed is skipped
and named in ``unparseable``; its source is never printed.

Review (judgment, not fact)
---------------------------
A similarity threshold is a tunable judgment, not a Tier-1 fact (#495), so the
review labels every result as one and states the thresholds and filters used.
It never returns source content: only file paths, line ranges, qualified names
and token counts.

* **Function filter.** A clone is kept only if more than half the lines of at
  least one of its regions are inside a ``def``. Module-level and class-body
  data (literal tables, class attributes) drops out.
* **Signature/stub guard.** A clone is dropped when at least 60 % of the lines of
  *both* regions are decorator or signature lines, or lie in a stub: an
  ``@overload`` or ``@abstractmethod`` def, or a def whose body is only ``...``,
  ``pass``, a docstring or ``raise NotImplementedError``. A concrete method of an
  ABC or ``Protocol`` is not a stub.
* **Naming.** A region is named after the scope that holds most of its AST
  tokens, not the scope where its first token falls (a copy often starts in the
  tail of the previous function). Comments and blank lines carry no tokens, so a
  comment-only edit can't rename a location and re-surface a dismissal.
* **Families.** Sites are grouped into connected components over their
  ``file::qualname`` endpoints. For a pair between two different classes, each
  end is folded into its class, so the copies between two classes form one
  family; a pair inside one class keeps its method endpoints unless one of them
  is also part of a cross-class pair. Module-level regions are never merged by
  their shared ``<module>`` name.

Dismissals
----------
A confirmed non-issue reuses :mod:`pyeye.architecture_review.state`: it is keyed
on the family's sorted member locations plus the ``"duplication"`` fact. A
family whose locations are a subset of a dismissal stays suppressed, whatever
happens inside the dismissed code (cosmetic edits, drift between members, a
member removed). A family with a site that no single dismissal covers (a new
member, a rename, a move, or a new copy bridging two dismissed families)
re-surfaces, showing only those sites. A
dismissal with ``review_after`` re-surfaces once the caller's ``today`` reaches
it. Dates are caller-supplied: nothing here reads a clock.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from pyeye.architecture_review import state as review_state
from pyeye.async_utils import filtered_rglob
from pyeye.path_utils import relative_within

DEFAULT_MIN_TOKENS = 35
#: A token window seen more often than this is skipped, bounding the pair loop.
DEFAULT_MAX_OCCURRENCES = 50
#: Function filter: a region is "in a function" when more than this share of its
#: lines are inside a ``def``.
FUNCTION_LINE_SHARE = 0.5
#: Signature/stub guard: drop a clone when both regions reach this share.
SIGNATURE_LINE_SHARE = 0.6
#: The structural fact behind every duplication dismissal key.
DISMISSAL_FACT = "duplication"
#: Why a family was dismissed (closed vocabulary).
DISMISSAL_REASONS = ("benign-idiom", "deliberate-twin", "vendored", "generated", "other")

_SKIP = (ast.expr_context, ast.Load, ast.Store, ast.Del)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_STUB_DECORATORS = frozenset({"overload", "abstractmethod", "abstractproperty"})
_MODULE = "<module>"


# ---------------------------------------------------------------------------
# Detection (shared with the ratchet)
# ---------------------------------------------------------------------------


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

    def children(node: ast.AST, lineno: int) -> None:
        for child in ast.iter_child_nodes(node):
            if not (_is_docstring(child) or isinstance(child, (ast.Import, ast.ImportFrom))):
                visit(child, lineno)

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
        children(node, lineno)

    children(ast.parse(source, filename=file), 1)
    return tokens


def display_path(file: Path, root: Path) -> str:
    """*file* relative to *root* in POSIX form, or as given when outside it."""
    rel = relative_within(file, root)
    return (rel if rel is not None else file).as_posix()


def collect(
    paths: Iterable[Path], root: Path, unparseable: list[str] | None = None
) -> list[list[Token]]:
    """Tokenise every ``.py`` file under *paths*; one token stream per file.

    Files are named relative to *root* (see :func:`display_path`). Directories
    are walked with :func:`pyeye.async_utils.filtered_rglob`, so virtual
    environments, caches and nested checkouts are skipped like every other
    project scan. A file that can't be read, decoded or parsed is skipped and
    its display path appended to *unparseable* (the error, which can quote the
    source, is never re-raised or printed).
    """
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(filtered_rglob("*.py", path)) if path.is_dir() else [path])
    streams: list[list[Token]] = []
    for f in files:
        name = display_path(f, root)
        try:
            streams.append(tokenize(f.read_text(encoding="utf-8"), name))
        except (SyntaxError, ValueError, OSError):  # UnicodeDecodeError is a ValueError
            if unparseable is not None:
                unparseable.append(name)
    return streams


@dataclass
class FindStats:
    """Work done by :func:`find_clones`, for callers that want to bound it."""

    windows: int = 0
    capped_windows: int = 0
    pairs_examined: int = 0
    #: Coverage lookups: one O(log n) bisect per examined pair, never a scan.
    coverage_steps: int = 0
    #: The most disjoint covered runs held for one (stream pair, offset).
    max_intervals: int = 0


def find_clones(
    streams: Sequence[Sequence[Token]],
    min_tokens: int = DEFAULT_MIN_TOKENS,
    max_occurrences: int = DEFAULT_MAX_OCCURRENCES,
    stats: FindStats | None = None,
) -> list[Clone]:
    """Return maximal token runs of length >= *min_tokens* that occur twice.

    Classic shingling: index every window of *min_tokens* tokens, then extend
    each match forward as far as the streams keep agreeing. Overlapping or
    self-overlapping matches are dropped.

    A window that occurs more than *max_occurrences* times is *capped*: each
    occurrence is paired only with the next one (``k - 1`` pairs, not
    ``k * (k - 1) / 2``), so the work stays linear while every copy is still
    reported and connects into one family. At or below the cap, every pair is
    examined, as before.
    """
    if min_tokens < 1:
        raise ValueError(f"min_tokens must be at least 1, got {min_tokens}")
    if max_occurrences < 2:
        raise ValueError(f"max_occurrences must be at least 2, got {max_occurrences}")
    stats = stats if stats is not None else FindStats()
    index: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    for s, stream in enumerate(streams):
        texts = [t.text for t in stream]
        for i in range(len(texts) - min_tokens + 1):
            index[tuple(texts[i : i + min_tokens])].append((s, i))
    stats.windows = len(index)

    # Runs already reported, as intervals of ``ia`` per (stream a, stream b,
    # offset): the same positions the per-token set used to hold, in O(runs).
    covered: dict[tuple[int, int, int], _Intervals] = defaultdict(_Intervals)
    clones: list[Clone] = []
    for positions in index.values():
        if len(positions) < 2:
            continue
        if len(positions) > max_occurrences:
            stats.capped_windows += 1
            pairs: Iterable[tuple[tuple[int, int], tuple[int, int]]] = zip(
                positions, positions[1:], strict=False
            )
        else:
            pairs = combinations(positions, 2)
        for (sa, ia), (sb, ib) in pairs:
            stats.pairs_examined += 1
            runs = covered[(sa, sb, ib - ia)]
            stats.coverage_steps += 1
            if ia in runs:
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
            runs.add(ia, ia + n - min_tokens)
            stats.max_intervals = max(stats.max_intervals, len(runs))
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


class _Intervals:
    """Disjoint, sorted closed intervals of ints: O(log n) membership."""

    def __init__(self) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []

    def __len__(self) -> int:
        return len(self._starts)

    def __contains__(self, value: object) -> bool:
        if not isinstance(value, int):
            return False
        i = bisect_right(self._starts, value) - 1
        return i >= 0 and value <= self._ends[i]

    def add(self, lo: int, hi: int) -> None:
        """Add ``lo..hi``, merging it with any interval it overlaps or touches."""
        i = bisect_left(self._ends, lo - 1)
        j = i
        while j < len(self._starts) and self._starts[j] <= hi + 1:
            lo, hi = min(lo, self._starts[j]), max(hi, self._ends[j])
            j += 1
        self._starts[i:j] = [lo]
        self._ends[i:j] = [hi]


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
    by_files: dict[tuple[str, str], list[Clone]] = defaultdict(list)
    for clone in clones:
        same_files = by_files[(clone.a_file, clone.b_file)]
        if not any(_contains(k, clone) for k in same_files):
            kept.append(clone)
            same_files.append(clone)
    return kept


def enclosing(file: str, line: int, root: Path) -> str:
    """Qualified name of the innermost function/class around *line* in *file*.

    *file* is the display path :func:`collect` produced, relative to *root*.
    ``"<module>"`` when the line is at module level.
    """
    return _FileFacts.load(root / file).innermost(line)


def site(clone: Clone, root: Path) -> tuple[str, str]:
    """A clone's stable key: the sorted pair of ``file::qualname`` around each region."""
    a = f"{clone.a_file}::{enclosing(clone.a_file, clone.a_start, root)}"
    b = f"{clone.b_file}::{enclosing(clone.b_file, clone.b_start, root)}"
    return (a, b) if a <= b else (b, a)


# ---------------------------------------------------------------------------
# Per-file structural facts (one parse per file)
# ---------------------------------------------------------------------------


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    return target.id if isinstance(target, ast.Name) else ""


def _is_stub_body(body: list[ast.stmt]) -> bool:
    rest = [s for s in body if not _is_docstring(s)]
    if not rest:
        return True
    if len(rest) != 1:
        return False
    stmt = rest[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
        return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"
    return False


@dataclass
class _FileFacts:
    """Scopes, function lines and signature/stub lines of one file."""

    scopes: list[tuple[int, int, str, bool]] = field(default_factory=list)
    classes: set[str] = field(default_factory=set)
    function_lines: set[int] = field(default_factory=set)
    signature_lines: set[int] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> _FileFacts:
        facts = cls()
        facts._visit(ast.parse(path.read_text(encoding="utf-8"), filename=path.name), "")
        return facts

    def _visit(self, node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, _SCOPES):
                self._visit(child, prefix)
                continue
            qualname = f"{prefix}{child.name}"
            end = child.end_lineno or child.lineno
            if isinstance(child, ast.ClassDef):
                self.scopes.append((child.lineno, end, qualname, False))
                self.classes.add(qualname)
            else:
                self.scopes.append((child.lineno, end, qualname, True))
                self._record_function(child, end)
            self._visit(child, qualname + ".")

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, end: int) -> None:
        self.function_lines.update(range(node.lineno, end + 1))
        first = min([d.lineno for d in node.decorator_list] + [node.lineno])
        body_start = node.body[0].lineno if node.body else end + 1
        self.signature_lines.update(range(first, body_start))
        # A stub by its own body or decorator only: a concrete method of an ABC
        # or Protocol is real code (template-method helpers live there).
        if _is_stub_body(node.body) or any(
            _decorator_name(d) in _STUB_DECORATORS for d in node.decorator_list
        ):
            self.signature_lines.update(range(first, end + 1))

    def innermost(self, line: int) -> str:
        best, span = _MODULE, -1
        for start, end, qualname, _ in self.scopes:
            if start <= line <= end and (span < 0 or end - start <= span):
                best, span = qualname, end - start
        return best

    def majority_scope(self, start: int, end: int, weights: dict[int, int] | None = None) -> str:
        """The innermost scope holding the most of ``start..end``, weighted by tokens.

        *weights* maps a line to its number of AST tokens, so comment and blank
        lines weigh nothing and a comment-only edit can't change the name. Without
        it every line weighs 1. Ties go to the scope reached last, so a region that
        starts in the tail of one function and covers as much of the next is
        named after the next.
        """
        counts: dict[str, int] = defaultdict(int)
        for line in range(start, end + 1):
            weight = 1 if weights is None else weights.get(line, 0)
            if weight:
                counts[self.innermost(line)] += weight
        if not counts:
            return self.innermost(start)
        best = max(counts.values())
        return [q for q in counts if counts[q] == best][-1]

    def owning_class(self, qualname: str) -> str | None:
        """The innermost class whose qualname is a proper prefix of *qualname*."""
        parts = qualname.split(".")
        for n in range(len(parts) - 1, 0, -1):
            prefix = ".".join(parts[:n])
            if prefix in self.classes:
                return prefix
        return None

    def share(self, start: int, end: int, lines: set[int]) -> float:
        return sum(1 for n in range(start, end + 1) if n in lines) / (end - start + 1)


class _Facts:
    """Per-run cache of :class:`_FileFacts`, so each file is parsed once."""

    def __init__(self, root: Path, streams: Iterable[Sequence[Token]] = ()) -> None:
        self._root = root
        self._files: dict[str, _FileFacts] = {}
        #: Tokens per line, per file: the naming weights.
        self.weights: dict[str, dict[int, int]] = {}
        for stream in streams:
            for tok in stream:
                per_line = self.weights.setdefault(tok.file, {})
                per_line[tok.lineno] = per_line.get(tok.lineno, 0) + 1

    def __call__(self, file: str) -> _FileFacts:
        if file not in self._files:
            self._files[file] = _FileFacts.load(self._root / file)
        return self._files[file]


# ---------------------------------------------------------------------------
# Review: guards, sites, families, dismissals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Region:
    """One side of a clone: a pointer, never content."""

    file: str
    start: int
    end: int
    qualname: str

    @property
    def location(self) -> str:
        """``file::qualname``."""
        return f"{self.file}::{self.qualname}"

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {"file": self.file, "start": self.start, "end": self.end, "qualname": self.qualname}


@dataclass
class Site:
    """The surviving clones between two locations; the longest one represents it."""

    a: Region
    b: Region
    tokens: int
    clones: int

    @property
    def locations(self) -> tuple[str, str]:
        """The two ``file::qualname`` endpoints."""
        return (self.a.location, self.b.location)

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "a": self.a.as_dict(),
            "b": self.b.as_dict(),
            "tokens": self.tokens,
            "clones": self.clones,
        }


@dataclass
class Family:
    """Sites whose endpoints connect (see :func:`build_families`)."""

    sites: list[Site]
    status: str = "new"
    new_locations: list[str] = field(default_factory=list)
    new_sites: list[Site] = field(default_factory=list)
    dismissal: dict[str, Any] | None = None

    @property
    def locations(self) -> list[str]:
        """Every member location, sorted: the family's identity."""
        return sorted({loc for s in self.sites for loc in s.locations})

    @property
    def tokens(self) -> int:
        """The longest clone's token count."""
        return max(s.tokens for s in self.sites)

    @property
    def key(self) -> str:
        """The dismissal key, built by ``state.non_issue_key`` over the locations."""
        return review_state.non_issue_key(self.locations, DISMISSAL_FACT)

    @property
    def id(self) -> str:
        """A short id for the CLI: the start of the dismissal key's digest."""
        return self.key.removeprefix("ni:")[:12]

    def as_dict(self) -> dict[str, Any]:
        """JSON form; a re-surfaced family shows only its new sites."""
        shown = self.new_sites if self.status == "resurfaced" else self.sites
        return {
            "id": self.id,
            "status": self.status,
            "tokens": self.tokens,
            "site_count": len(self.sites),
            "locations": self.locations,
            "new_locations": self.new_locations,
            "new_site_count": len(self.new_sites),
            "dismissal": self.dismissal,
            "sites": [s.as_dict() for s in shown],
        }


def _region(facts: _Facts, file: str, start: int, end: int) -> Region:
    weights = facts.weights.get(file)
    return Region(file, start, end, facts(file).majority_scope(start, end, weights))


def _keeps(facts: _Facts, a: Region, b: Region) -> bool:
    """The function filter and the signature/stub guard, for one clone."""
    fa, fb = facts(a.file), facts(b.file)
    in_function = (
        fa.share(a.start, a.end, fa.function_lines) > FUNCTION_LINE_SHARE
        or fb.share(b.start, b.end, fb.function_lines) > FUNCTION_LINE_SHARE
    )
    signature_only = (
        fa.share(a.start, a.end, fa.signature_lines) >= SIGNATURE_LINE_SHARE
        and fb.share(b.start, b.end, fb.signature_lines) >= SIGNATURE_LINE_SHARE
    )
    return in_function and not signature_only


def build_sites(clones: Iterable[Clone], root: Path, facts: _Facts | None = None) -> list[Site]:
    """Group the clones that pass the guards into sites, longest first."""
    facts = facts if facts is not None else _Facts(root)
    grouped: dict[tuple[str, str], list[tuple[Region, Region, int]]] = defaultdict(list)
    for c in clones:
        a = _region(facts, c.a_file, c.a_start, c.a_end)
        b = _region(facts, c.b_file, c.b_start, c.b_end)
        if not _keeps(facts, a, b):
            continue
        if b.location < a.location:
            a, b = b, a
        grouped[(a.location, b.location)].append((a, b, c.tokens))
    sites = []
    for members in grouped.values():
        a, b, tokens = max(members, key=lambda m: m[2])
        sites.append(Site(a, b, tokens, len(members)))
    sites.sort(key=lambda s: (-s.tokens, s.locations))
    return sites


def build_families(sites: Sequence[Site], root: Path, facts: _Facts | None = None) -> list[Family]:
    """Connected components over site endpoints, longest family first.

    For a site between two *different classes*, each end is folded into its
    class, so all the copies between two classes are one family. Any other
    site keeps its endpoints, with one exception: a method end that is also in
    a cross-class site is folded into its class, so a location is only ever in
    one family. That holds whatever the site's other end is, a method in the
    same class, a function or module-level code. A function or module-level
    end is itself never folded. Module-level ends are keyed by their start
    line, so two unrelated module-level regions of one file are not merged by
    their shared ``<module>`` name.
    """
    facts = facts if facts is not None else _Facts(root)
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def plain(region: Region) -> str:
        if region.qualname == _MODULE:
            return f"{region.location}@{region.start}"
        return region.location

    def klass(region: Region) -> str | None:
        file_facts = facts(region.file)
        if region.qualname in file_facts.classes:
            return f"{region.file}::{region.qualname}"
        owner = file_facts.owning_class(region.qualname)
        return f"{region.file}::{owner}" if owner is not None else None

    classes = [(klass(s.a), klass(s.b)) for s in sites]
    # Methods that take part in a pair between two classes belong to their class node.
    cross_members = {
        loc
        for s, (ca, cb) in zip(sites, classes, strict=True)
        if ca is not None and cb is not None and ca != cb
        for loc in s.locations
    }
    ends: list[tuple[str, str]] = []
    for s, (ca, cb) in zip(sites, classes, strict=True):
        if ca is not None and cb is not None and ca != cb:
            na, nb = ca, cb
        else:
            # A location that is part of a cross-class pair is always its class
            # node, whatever this site's other end is, so it is in one family.
            na = ca if ca is not None and s.a.location in cross_members else plain(s.a)
            nb = cb if cb is not None and s.b.location in cross_members else plain(s.b)
            if ca is not None and ca == cb and cross_members & set(s.locations):
                na = nb = ca
        ends.append((na, nb))
        parent[find(na)] = find(nb)
    grouped: dict[str, list[Site]] = defaultdict(list)
    for s, (na, _) in zip(sites, ends, strict=True):
        grouped[find(na)].append(s)
    families = [Family(members) for members in grouped.values()]
    families.sort(key=lambda f: (-f.tokens, f.locations))
    return families


def _due(dismissal: dict[str, Any], today: str | None) -> bool:
    review_after = dismissal.get("review_after")
    return bool(review_after and today and today >= review_after)


def apply_dismissals(
    families: Iterable[Family], dismissals: Iterable[dict[str, Any]], today: str | None = None
) -> tuple[list[Family], list[Family]]:
    """Split *families* into ``(shown, suppressed)`` against *dismissals*.

    Newness is decided per site: a site is *covered* when both its locations lie
    in one dismissal.

    * Every site covered: the family is suppressed, unless a covering
      dismissal's ``review_after`` has been reached (status ``review-due``).
    * Some sites uncovered, and the family touches a dismissal: it re-surfaces
      (status ``resurfaced``). ``new_sites`` are the uncovered sites (only they
      are shown) and ``new_locations`` the locations no dismissal names, which
      is empty for a new copy bridging two dismissed families.
    * No dismissal touched: status ``new``.
    """
    known = [d for d in dismissals if d.get("structural_fact") == DISMISSAL_FACT]
    shown: list[Family] = []
    suppressed: list[Family] = []
    for fam in families:
        locs = set(fam.locations)
        # ``file::<module>`` is shared by unrelated module-level code, so it never
        # links a family to a dismissal by itself; a covered site still does.
        named = {loc for loc in locs if not loc.endswith(f"::{_MODULE}")}
        touching = [
            d
            for d in known
            if named & set(d["handles"])
            or any(set(site.locations) <= set(d["handles"]) for site in fam.sites)
        ]
        if not touching:
            shown.append(fam)
            continue
        covering: list[dict[str, Any]] = []
        fresh: list[Site] = []
        for s in fam.sites:
            holders = [d for d in touching if set(s.locations) <= set(d["handles"])]
            covering.extend(d for d in holders if d not in covering)
            if not holders:
                fresh.append(s)
        if fresh:
            dismissed = set().union(*(set(d["handles"]) for d in touching))
            fam.status, fam.dismissal = "resurfaced", _public(touching[0])
            fam.new_sites = fresh
            fam.new_locations = sorted(locs - dismissed)
        elif any(_due(d, today) for d in covering):
            fam.status = "review-due"
            fam.dismissal = _public(next(d for d in covering if _due(d, today)))
        else:
            suppressed.append(fam)
            continue
        shown.append(fam)
    return shown, suppressed


def _public(dismissal: dict[str, Any]) -> dict[str, Any]:
    return {k: dismissal.get(k) for k in ("reason", "dismissed_on", "review_after")}


def _check_date(value: str, flag: str) -> str:
    try:
        _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{flag} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc
    return value


def dismiss(
    state: dict[str, Any],
    family: Family,
    reason: str,
    dismissed_on: str,
    review_after: str | None = None,
) -> dict[str, Any]:
    """Record *family* as a confirmed non-issue in *state* and return the entry.

    Earlier duplication dismissals whose locations are a subset of this family's
    are replaced, so re-dismissing a re-surfaced family leaves one entry.
    """
    if reason not in DISMISSAL_REASONS:
        raise ValueError(f"reason must be one of {list(DISMISSAL_REASONS)}, got {reason!r}")
    _check_date(dismissed_on, "--date")
    if review_after is not None:
        _check_date(review_after, "--review-after")
    locs = family.locations
    entry: dict[str, Any] = {
        "handles": locs,
        "structural_fact": DISMISSAL_FACT,
        "key": review_state.non_issue_key(locs, DISMISSAL_FACT),
        "reason": reason,
        "dismissed_on": dismissed_on,
        "review_after": review_after,
    }
    kept = [
        d
        for d in state.get("confirmed_non_issues", [])
        if not (d.get("structural_fact") == DISMISSAL_FACT and set(d["handles"]) <= set(locs))
    ]
    state["confirmed_non_issues"] = [*kept, entry]
    return entry


@dataclass
class Review:
    """A duplication review of one scope: families shown, families suppressed."""

    min_tokens: int
    max_occurrences: int
    scope: list[str]
    files: int
    stats: FindStats
    families: list[Family]
    suppressed: list[Family]
    unparseable: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "judgment": True,
            "note": JUDGMENT_NOTE,
            "min_tokens": self.min_tokens,
            "max_occurrences": self.max_occurrences,
            "filters": list(FILTERS),
            "scope": self.scope,
            "files": self.files,
            "unparseable_files": self.unparseable,
            "capped_windows": self.stats.capped_windows,
            "families": [f.as_dict() for f in self.families],
            "suppressed": len(self.suppressed),
        }


JUDGMENT_NOTE = (
    "Judgment, not fact: exact-match clones over normalised AST tokens. The threshold and "
    "filters below decide what counts; read both regions before acting."
)
FILTERS = (
    f"function filter: >{FUNCTION_LINE_SHARE:.0%} of one region's lines inside a def",
    f"signature/stub guard: drop when >={SIGNATURE_LINE_SHARE:.0%} of both regions' lines are "
    "decorators, signatures or stub defs",
    "families: connected components; pairs between two classes fold methods into their class",
)


def review(
    paths: Sequence[Path],
    root: Path,
    *,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    max_occurrences: int = DEFAULT_MAX_OCCURRENCES,
    dismissals: Iterable[dict[str, Any]] = (),
    today: str | None = None,
) -> Review:
    """Review *paths* for duplication.

    Scope is required: *paths* can't be empty, and each path must lie inside
    *root*, which every reported location (and so every dismissal key) is
    relative to.
    """
    check_arguments(paths, root, min_tokens, max_occurrences)
    stats = FindStats()
    unparseable: list[str] = []
    streams = collect(paths, root, unparseable)
    clones = find_clones(streams, min_tokens, max_occurrences, stats)
    facts = _Facts(root, streams)
    families = build_families(build_sites(clones, root, facts), root, facts)
    shown, suppressed = apply_dismissals(families, dismissals, today)
    scope = [display_path(p, root) for p in paths]
    return Review(
        min_tokens, max_occurrences, scope, len(streams), stats, shown, suppressed, unparseable
    )


def check_arguments(
    paths: Sequence[Path], root: Path, min_tokens: int, max_occurrences: int
) -> None:
    """Raise ``ValueError`` for a bad scope or threshold, before any scanning."""
    if not paths:
        raise ValueError("a scope is required: pass one or more files or directories")
    for path in paths:
        if relative_within(path, root) is None:
            raise ValueError(
                f"scope {path.as_posix()!r} is outside --root {root.as_posix()!r}; "
                "locations (and dismissal keys) are relative to --root"
            )
        if not path.exists():
            raise ValueError(f"scope {path.as_posix()!r} does not exist")
    if min_tokens < 1:
        raise ValueError(f"--min-tokens must be at least 1, got {min_tokens}")
    if max_occurrences < 2:
        raise ValueError(f"--max-occurrences must be at least 2, got {max_occurrences}")


def format_review(result: Review) -> str:
    """Render *result* as text: pointers and counts only, never source."""
    lines = [
        f"duplication review (#495): {len(result.families)} famil"
        f"{'y' if len(result.families) == 1 else 'ies'} across {result.files} file(s); "
        f"{len(result.suppressed)} dismissed and suppressed",
        result.as_dict()["note"],
        f"threshold: >= {result.min_tokens} tokens; windows seen > {result.max_occurrences} "
        f"times are paired with the next occurrence only ({result.stats.capped_windows} capped)",
        *(f"filter: {f}" for f in FILTERS),
    ]
    if result.unparseable:
        lines.append("unparseable (skipped): " + "; ".join(result.unparseable))
    for n, fam in enumerate(result.families, 1):
        data = fam.as_dict()
        head = f"{n}. [{fam.status}] family {fam.id}: {len(fam.sites)} site(s), longest {fam.tokens} tokens"
        if fam.status == "resurfaced":
            head += (
                f"; {len(fam.new_sites)} new site(s), {len(fam.new_locations)} new member(s) "
                "of a dismissed family"
            )
        if fam.dismissal:
            head += f" (dismissed {fam.dismissal['dismissed_on']}: {fam.dismissal['reason']})"
        lines.append(head)
        for s in data["sites"]:
            a, b = s["a"], s["b"]
            lines.append(
                f"   {s['tokens']:4d} tokens  {a['file']}:{a['start']}-{a['end']} ({a['qualname']})"
                f"  <->  {b['file']}:{b['start']}-{b['end']} ({b['qualname']})"
            )
        if fam.new_locations:
            lines.append("   new: " + "; ".join(fam.new_locations))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI: python -m pyeye.duplication {review,dismiss}
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pyeye.duplication",
        description="Duplication review: exact-match clone families, labelled as judgments.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "dismiss"):
        p = sub.add_parser(name)
        p.add_argument("scope", nargs="+", type=Path, help="files or directories (required)")
        p.add_argument("--root", type=Path, default=Path("."), help="locations are relative to it")
        p.add_argument("--min-tokens", type=int, default=DEFAULT_MIN_TOKENS)
        p.add_argument("--max-occurrences", type=int, default=DEFAULT_MAX_OCCURRENCES)
        p.add_argument("--state", type=Path, help="dismissal state file (JSON)")
        if name == "review":
            p.add_argument("--today", help="ISO date; re-surfaces dismissals due for review")
            p.add_argument("--json", action="store_true", help="machine-readable output")
        else:
            p.add_argument("--family", required=True, help="family id from a review")
            p.add_argument("--reason", required=True, choices=DISMISSAL_REASONS)
            p.add_argument("--date", required=True, help="ISO date of the dismissal")
            p.add_argument("--review-after", help="ISO date to re-surface it for review")
    return parser


def load_dismissal_state(path: Path) -> dict[str, Any]:
    """Load and validate a dismissal state file; ``ValueError`` names what's wrong."""
    try:
        state = review_state.load_state(path)
    except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
        raise ValueError(f"state file {path.as_posix()!r} is not readable JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise ValueError(f"state file {path.as_posix()!r} must hold a JSON object")
    entries = state.setdefault("confirmed_non_issues", [])
    if not isinstance(entries, list):
        raise ValueError(f"state file {path.as_posix()!r}: confirmed_non_issues must be a list")
    for n, entry in enumerate(entries):
        handles = entry.get("handles") if isinstance(entry, dict) else None
        if not isinstance(handles, list) or not all(isinstance(h, str) for h in handles):
            raise ValueError(f"state file {path.as_posix()!r}: entry {n} has no list of handles")
        if entry.get("structural_fact") != DISMISSAL_FACT:
            continue
        for key in ("dismissed_on", "review_after"):
            value = entry.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(
                    f"state file {path.as_posix()!r}: entry {n} {key} must be a string"
                )
            _check_date(value, f"entry {n} {key}")
    return state


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m pyeye.duplication``.

    Bad arguments or a bad state file exit 2 with a one-line message, before any
    scanning. ``dismiss`` exits 1 when ``--family`` names no family in the
    scope: family ids come from the scan, so that is known only after it.
    Nothing prints a traceback or source text.
    """
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    check_arguments(args.scope, args.root, args.min_tokens, args.max_occurrences)
    today = _check_date(args.today, "--today") if getattr(args, "today", None) else None
    if args.command == "dismiss":
        if args.state is None:
            raise ValueError("dismiss needs --state")
        _check_date(args.date, "--date")
        if args.review_after is not None:
            _check_date(args.review_after, "--review-after")
    state = load_dismissal_state(args.state) if args.state else {"confirmed_non_issues": []}
    result = review(
        args.scope,
        args.root,
        min_tokens=args.min_tokens,
        max_occurrences=args.max_occurrences,
        dismissals=state["confirmed_non_issues"] if args.command == "review" else (),
        today=today,
    )
    if args.command == "review":
        print(json.dumps(result.as_dict(), indent=2) if args.json else format_review(result))
        return 0
    matches = [f for f in result.families if f.id == args.family]
    if not matches:
        print(f"no family with id {args.family!r} in this scope", file=sys.stderr)
        return 1
    entry = dismiss(state, matches[0], args.reason, args.date, args.review_after)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    review_state.save_state(args.state, state)
    print(f"dismissed family {args.family}: {len(entry['handles'])} location(s), {args.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
