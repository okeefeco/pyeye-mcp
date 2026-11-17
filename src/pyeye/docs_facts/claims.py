"""The honest-claims rule: docs make only claims the code or a record backs (D12).

One unbacked "40% faster" undermines every fact the docs state, so a number or
a volatile status in prose must come from somewhere checkable:

- **a fact block**, whose content the code generates (it is blanked before this
  rule reads the page);
- **a registered record**, a page of kind ``record`` whose front matter gives the
  ``date``, the ``command`` that produced it and the ``commit`` it ran on, linked
  from the same line;
- **a primary source**, for a fact that isn't pyeye's (a filesystem's timestamp
  resolution, a spec), linked from the same line as an ``http(s)`` URL.

Anything else is deleted or bound, not reworded (design D12, C10). Projections
and targets aren't allowed in live docs at all, and unenforced policy numbers
are removed rather than bound.

**What's matched** (C10): percentages, multipliers (``2.5x``), durations, sizes,
"as of …", "currently N", "N+ things" and token-savings phrasing. Bare counts
("18 variables") are left to review.

**What's skipped** (C10, Q4), so only prose is read: fenced blocks other than
plain-text ones (no info string, or ``text``), inline code,
URLs and link targets, badges, HTML comments and version strings.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..path_utils import relative_within
from . import binding

#: The front-matter keys a ``record`` page must give (C10, Q5).
RECORD_KEYS: tuple[str, ...] = ("date", "command", "commit")

#: Fence info strings whose body the rule still reads: plain text, such as a
#: file tree with comments. A ``markdown`` fence shows syntax, so it's skipped.
_PROSE_FENCES = frozenset({"", "text"})

_NUM = r"\d+(?:[.,]\d+)?"
#: Label -> pattern. Labels name the kind of claim in a finding.
PATTERNS: dict[str, re.Pattern[str]] = {
    "percentage": re.compile(rf"{_NUM}\s?%"),
    "multiplier": re.compile(
        rf"\b{_NUM}\s?(?:[xX×](?![\w-])|-?fold\b"
        r"|\s*times\s+(?:faster|slower|more|less|fewer|smaller|larger|bigger|cheaper))"
    ),
    "duration": re.compile(
        rf"\b{_NUM}\s?(?:[µμ]s|ns|ms|milliseconds?|s|secs?|seconds?|mins?|minutes?"
        r"|hours?|days?|weeks?)\b"
    ),
    "size": re.compile(rf"\b{_NUM}\s?(?:[KMGT]i?B|bytes)\b"),
    "as-of": re.compile(r"\bas of\b[^.;,)]{0,30}", re.IGNORECASE),
    "currently-N": re.compile(
        r"\bcurrently\b[^.;:\d]{0,20}\d[\d,.]*\+?(?:\s+[A-Za-z][\w-]*)?", re.IGNORECASE
    ),
    "N-plus": re.compile(r"(?<![\d.,])\b\d[\d,]*\+\s+[A-Za-z][\w-]*"),
    "token-savings": re.compile(
        r"\btokens?\b[^.;]{0,30}\b(?:sav|reduc|fewer|less)"
        r"|\b(?:sav|reduc)\w*[^.;]{0,30}\btokens?\b",
        re.IGNORECASE,
    ),
}

_MD_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]*)(?:\s+\"[^\"]*\")?\)")
_BARE_URL = re.compile(r"<?https?://[^\s)>]+>?")
_HTML_COMMENT = re.compile(r"<!--.*?-->")
#: ``v2.1.0``, ``Python 3.11+``, ``3.11.4``: versions, not claims.
_VERSION = re.compile(r"(?i)\b(?:python|v)\s?\d+(?:\.\d+)+\+?|\b\d+\.\d+\.\d+\b")
_EXTERNAL = re.compile(r"https?://")
#: The longest line excerpt a finding quotes.
_EXCERPT = 100


@dataclass(frozen=True)
class Claim:
    """One unbacked claim: its 1-based line, kind and the matched text."""

    line: int
    label: str
    text: str
    excerpt: str

    @property
    def message(self) -> str:
        """The claim and the prose line it's on, with no line number.

        It is also what an allowance names (design C12: keyed on the exact
        finding message), so a seed covers that claim in that sentence and
        nothing else: a new "as of …" or another "79%" on the same page is a
        new finding.
        """
        return f"unbacked {self.label} {self.text!r}: {self.excerpt}"


def front_matter(text: str) -> dict[str, str]:
    """A page's ``key: value`` front matter between leading ``---`` lines."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def record_problems(path: str, text: str) -> list[str]:
    """What a ``record`` page lacks: each missing or empty front-matter key."""
    fields = front_matter(text)
    return [
        f"{path}: a record must give `{key}` in its front matter"
        for key in RECORD_KEYS
        if not fields.get(key)
    ]


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]


def code_free(text: str) -> str:
    """*text* with non-prose fenced blocks blanked, line numbers kept."""
    for fence in reversed(binding.fences(text)):
        if fence.info.split(" ", 1)[0].lower() not in _PROSE_FENCES:
            text = _blank(text, fence.body_start, fence.body_end)
    return text


def _prose_line(line: str) -> str:
    """*line* without inline code, HTML comments, link targets, URLs and versions."""
    for start, end in reversed(binding.code_spans(line)):
        line = line[:start] + " " * (end - start) + line[end:]
    line = _HTML_COMMENT.sub(lambda m: " " * len(m.group()), line)
    line = _MD_LINK.sub(lambda m: m.group(1), line)
    line = _BARE_URL.sub(" ", line)
    return _VERSION.sub(" ", line)


_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
#: Hosts that serve only the reader's own machine, so a link to one cites nothing.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _visible(line: str) -> str:
    """*line* as a reader sees its links: no code spans, comments or images.

    A link inside inline code or a comment isn't a citation, and a badge is an
    image, not a source. A badge's outer link is left with no text, so it
    doesn't count either.
    """
    for start, end in reversed(binding.code_spans(line)):
        line = line[:start] + " " * (end - start) + line[end:]
    line = _HTML_COMMENT.sub(" ", line)
    while _IMAGE.search(line):
        line = _IMAGE.sub(" ", line)
    return line


def _visible_links(line: str) -> Iterator[str]:
    """The targets of the links a reader can follow from *line*."""
    visible = _visible(line)
    for match in _MD_LINK.finditer(visible):
        if match.group(1).strip():
            yield match.group(2)
    for match in _BARE_URL.finditer(_MD_LINK.sub(" ", visible)):
        yield match.group().strip("<>")


def _is_external(target: str) -> bool:
    """An ``http(s)`` URL on a public host: a citable source, not a local server."""
    if not _EXTERNAL.match(target):
        return False
    host = urlparse(target).hostname or ""
    return bool(host) and host not in _LOCAL_HOSTS


def links_a_source(line: str) -> bool:
    """True if *line* visibly links an external source.

    Whether that source is *primary* is a judgment, left to review (#829).
    """
    return any(_is_external(t) for t in _visible_links(line))


def _link_targets(line: str) -> Iterator[str]:
    for target in _visible_links(line):
        if not _EXTERNAL.match(target):
            yield target.split("#", 1)[0]


def links_a_record(line: str, page: str, root: Path, records: frozenset[str]) -> bool:
    """True if *line* links a registered record (relative to *page*'s folder)."""
    folder = root / page.rsplit("/", 1)[0] if "/" in page else root
    for target in _link_targets(line):
        if not target or _EXTERNAL.match(target):
            continue
        rel = relative_within(folder / target, root)
        if rel is not None and rel.as_posix() in records:
            return True
    return False


def claims(
    text: str,
    page: str = "",
    root: Path | None = None,
    records: frozenset[str] = frozenset(),
) -> list[Claim]:
    """Every unbacked claim in *text* (fact blocks already blanked).

    Args:
        text: The page's prose.
        page: Its repo-relative path, for resolving record links.
        root: The repository root (``None``: no link is a record).
        records: Repo-relative paths of the registered ``record`` pages.
    """
    found: list[Claim] = []
    for number, raw in enumerate(code_free(text).splitlines(), 1):
        prose = _prose_line(raw)
        hits = [
            (label, m.group().strip())
            for label, pattern in PATTERNS.items()
            for m in pattern.finditer(prose)
        ]
        if not hits:
            continue
        if links_a_source(raw):
            continue
        if root is not None and links_a_record(raw, page, root, records):
            continue
        excerpt = " ".join(prose.split())
        excerpt = excerpt if len(excerpt) <= _EXCERPT else excerpt[: _EXCERPT - 3] + "..."
        found.extend(Claim(number, label, hit, excerpt) for label, hit in hits)
    return found


def record_paths(entries: Mapping[str, str]) -> frozenset[str]:
    """The registered paths whose kind is ``record`` (path -> kind)."""
    return frozenset(path for path, kind in entries.items() if kind == "record")
