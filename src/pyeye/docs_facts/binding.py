"""Named marker blocks: how prose shows a fact without restating it.

A block names a fact or view by ID; ``generate`` rewrites what's inside it from
the fact, and ``check`` fails if what's inside differs (a stale value or a hand
edit, which are the same thing) or if the ID is unknown (a removed fact, D4).

Block form, for tables and lists (the markers stand on their own lines)::

    <!-- fact:begin edges.table -->
    | Edge | Applies to | Ceiling |
    ...
    <!-- fact:end -->

Inline form, inside a sentence (begin and end on one line)::

    Coverage must stay above <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end -->.

Markers inside fenced code blocks or inline code are text, not markers, so a
page can show the syntax (as this docstring does).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .facts import Bindable

BEGIN = re.compile(r"<!-- fact:begin (\S+) -->")
END = re.compile(r"<!-- fact:end -->")
#: Anything that looks like it means to be a marker. One that isn't exactly
#: :data:`BEGIN` or :data:`END` is a problem, never silently plain text.
_NEAR_MISS = re.compile(r"<!--\s*fact\s*:", re.IGNORECASE)
#: The rest of a line after its container prefixes, tested for a fence run.
_FENCE_RUN = re.compile(r"(?P<run>`{3,}|~{3,})(?P<info>.*)")
#: Container prefixes (CommonMark): blockquote ``>`` and list markers (``-``,
#: ``*``, ``+``, ``1.``, ``1)``), each optionally indented and nested. A fence
#: can open right after one (``1. ```bash``), and its closer may carry one too.
_CONTAINER = re.compile(r"(?:[ ]{0,3}(?:>[ ]?|(?:[-*+]|\d{1,9}[.)])[ ]+))*")
_BACKTICKS = re.compile(r"`+")


@dataclass(frozen=True)
class Fence:
    """One fenced code block.

    Attributes:
        line: 1-based line of the opener.
        info: The opener's info string, stripped (``"json pyeye-example tool=inspect"``).
        char: The fence character, a backtick or ``~``.
        length: The opener's run length; the closer must be at least as long.
        body_start: Offset of the first body line (just after the opener line).
        body_end: Offset of the closer line, or the end of the text if unclosed.
        end_line: 1-based line of the closer, or ``None`` if the fence is unclosed.
    """

    line: int
    info: str
    char: str
    length: int
    body_start: int
    body_end: int
    end_line: int | None

    @property
    def closed(self) -> bool:
        """True if a closer was found."""
        return self.end_line is not None


def _split(line: str) -> tuple[int, str, int]:
    """``(prefix width, rest, column)``: container prefixes, then the rest of the line.

    *column* is where the rest's first non-space character sits; tabs are not
    expanded (the repo's Markdown is space-indented, and markdownlint keeps it so).
    """
    body = line.rstrip("\r\n")
    prefix = _CONTAINER.match(body)
    width = prefix.end() if prefix else 0
    rest = body[width:]
    return width, rest, width + len(rest) - len(rest.lstrip(" "))


Marker = tuple[str, int, int, int, str | None]


@dataclass(frozen=True)
class Block:
    """One marker block in a page.

    Attributes:
        fact_id: The ID the begin marker names.
        line: 1-based line of the begin marker.
        start: Offset of the block's content (just after the begin marker).
        end: Offset just past the content (the end marker's start).
        inline: True when begin and end share a line.
        indent: Leading whitespace of the begin marker's line.
    """

    fact_id: str
    line: int
    start: int
    end: int
    inline: bool
    indent: str


@dataclass(frozen=True)
class Problem:
    """A marker that can't be bound: malformed, or naming an unknown fact."""

    line: int
    message: str


def code_spans(line: str) -> list[tuple[int, int]]:
    """Inline code spans in *line* (CommonMark), as half-open ``(start, end)`` ranges.

    A run of N backticks opens a span that the next run of exactly N closes. A
    run with no matching run after it is literal backticks, not a span.
    """
    spans: list[tuple[int, int]] = []
    runs = list(_BACKTICKS.finditer(line))
    i = 0
    while i < len(runs):
        opener = runs[i]
        width = len(opener.group())
        closer = next((j for j in range(i + 1, len(runs)) if len(runs[j].group()) == width), None)
        if closer is None:
            i += 1
            continue
        spans.append((opener.start(), runs[closer].end()))
        i = closer + 1
    return spans


def fences(text: str) -> list[Fence]:
    """Every fenced code block in *text* (CommonMark rules, container-aware).

    - An opener is a run of 3+ backticks or tildes after any container prefixes
      (``>``, list markers). A backtick opener's info string can't contain a
      backtick, so a line starting with inline ```code``` is not a fence.
    - Indentation counts from the enclosing content column (the last non-blank
      line's content, or a list item's text): 4+ spaces past it is indented code,
      not a fence. That is what keeps a fence inside a list item a fence, and a
      ```` line in an indented code block plain text.
    - A closer is the same character, at least as long, with nothing after it,
      indented less than 4 past the opener's content column.
    - An unclosed fence runs to the end of the text (``end_line`` is ``None``).
    """
    found: list[Fence] = []
    offset = 0
    content_col = 0
    current: tuple[int, str, str, int, int, int] | None = None  # line, info, char, len, base, start
    lines = text.splitlines(keepends=True)
    for number, line in enumerate(lines, 1):
        width, rest, col = _split(line)
        stripped = rest.strip()
        if current is not None:
            opener_line, info, char, length, base, body_start = current
            if len(stripped) >= length and stripped == char * len(stripped) and col - base < 4:
                found.append(Fence(opener_line, info, char, length, body_start, offset, number))
                current = None
                content_col = col
        else:
            run = _FENCE_RUN.match(rest.lstrip(" "))
            base = width if width else content_col
            is_opener = (
                run is not None
                and col - base < 4
                and not (run.group("run")[0] == "`" and "`" in run.group("info"))
            )
            if is_opener and run is not None:
                current = (
                    number,
                    run.group("info").strip(),
                    run.group("run")[0],
                    len(run.group("run")),
                    base,
                    offset + len(line),
                )
            # Indented code (4+ past the content column) never moves the column,
            # or its own lines would make the next ```` line look like a fence.
            if width or (stripped and col - content_col < 4):
                content_col = col
        offset += len(line)
    if current is not None:
        opener_line, info, char, length, _, body_start = current
        found.append(Fence(opener_line, info, char, length, body_start, len(text), None))
    return found


def _line_markers(line: str, number: int, offset: int, problems: list[Problem]) -> list[Marker]:
    spans = code_spans(line)

    def in_code(column: int) -> bool:
        return any(a <= column < b for a, b in spans)

    found: list[Marker] = []
    strict: set[int] = set()
    for kind, pattern in (("begin", BEGIN), ("end", END)):
        for m in pattern.finditer(line):
            if in_code(m.start()):
                continue
            strict.add(m.start())
            fact_id = m.group(1) if kind == "begin" else None
            found.append((kind, number, offset + m.start(), offset + m.end(), fact_id))
    for m in _NEAR_MISS.finditer(line):
        if m.start() not in strict and not in_code(m.start()):
            problems.append(
                Problem(
                    number,
                    "malformed fact marker: write exactly `<!-- fact:begin ID -->` "
                    "or `<!-- fact:end -->`",
                )
            )
    return found


def _markers(text: str, problems: list[Problem]) -> list[Marker]:
    """``(kind, line, start, end, fact_id)`` for each marker outside code."""
    in_fence: set[int] = set()
    for fence in fences(text):
        last = fence.end_line if fence.end_line is not None else len(text.splitlines())
        in_fence.update(range(fence.line, last + 1))
        if not fence.closed:
            problems.append(
                Problem(fence.line, "unclosed code fence: every marker after it would be ignored")
            )
    found: list[Marker] = []
    offset = 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if number not in in_fence:
            found.extend(_line_markers(line, number, offset, problems))
        offset += len(line)
    found.sort(key=lambda marker: marker[2])
    return found


def parse(text: str) -> tuple[list[Block], list[Problem]]:
    """Find the marker blocks in *text*; malformed markers are problems."""
    blocks: list[Block] = []
    problems: list[Problem] = []
    open_marker: Marker | None = None
    for marker in _markers(text, problems):
        kind, line, start, end, fact_id = marker
        if kind == "begin":
            if open_marker is not None:
                problems.append(
                    Problem(line, f"fact:begin inside the block opened on line {open_marker[1]}")
                )
            open_marker = marker
            continue
        if open_marker is None:
            problems.append(Problem(line, "fact:end without a fact:begin"))
            continue
        _, begin_line, _, begin_end, begin_id = open_marker
        open_marker = None
        line_start = text.rfind("\n", 0, begin_end) + 1
        begin_text = text[line_start:begin_end]
        newline = text.find("\n", begin_end)
        inline = text[begin_end : newline if newline != -1 else len(text)].strip() != ""
        if inline and line != begin_line:
            problems.append(Problem(begin_line, "an inline fact block must end on its own line"))
            continue
        if not inline and text[text.rfind("\n", 0, start) + 1 : start].strip():
            problems.append(Problem(line, "fact:end of a block must start its line"))
            continue
        indent = begin_text[: len(begin_text) - len(begin_text.lstrip())]
        blocks.append(Block(begin_id or "", begin_line, begin_end, start, inline, indent))
    if open_marker is not None:
        problems.append(Problem(open_marker[1], "fact:begin without a fact:end"))
    return blocks, problems


def render(text: str, facts: Mapping[str, Bindable]) -> tuple[str, list[Block], list[Problem]]:
    """Rewrite every block's content from *facts*.

    Returns:
        The rewritten text, the blocks found and the problems. A block naming an
        unknown ID, or an inline block whose fact renders on several lines, is
        left as it is and reported.
    """
    blocks, problems = parse(text)
    pieces: list[str] = []
    cursor = 0
    for block in blocks:
        fact = facts.get(block.fact_id)
        if fact is None:
            problems.append(Problem(block.line, f"unknown fact ID {block.fact_id!r}"))
            continue
        if block.inline:
            if "\n" in fact.markdown:
                problems.append(
                    Problem(block.line, f"{block.fact_id!r} renders on several lines; use a block")
                )
                continue
            content = fact.markdown
        else:
            lines = [block.indent + ln if ln else ln for ln in fact.markdown.split("\n")]
            content = "\n" + "\n".join(lines) + "\n" + block.indent
        pieces.append(text[cursor : block.start])
        pieces.append(content)
        cursor = block.end
    pieces.append(text[cursor:])
    problems.sort(key=lambda p: p.line)
    return "".join(pieces), blocks, problems
