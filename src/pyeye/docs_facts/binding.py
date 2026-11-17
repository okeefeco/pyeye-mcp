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
#: A fence opener (CommonMark): a run of 3+ backticks or tildes, then an info
#: string. A backtick fence's info string can't contain a backtick (so a line
#: starting with inline ```code``` is not a fence). Any indent is accepted, since
#: a fence nested in a list item is indented.
_FENCE_OPEN = re.compile(r"^[ \t]*(?P<run>`{3,}|~{3,})(?P<info>[^\n]*)$")
_BACKTICKS = re.compile(r"`+")

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


def _code_spans(line: str) -> list[tuple[int, int]]:
    """Inline code spans in *line* (CommonMark): a run of N backticks to the next run of N.

    A run with no matching run after it is literal backticks, not a span.
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


def _fence_opener(line: str) -> tuple[str, int] | None:
    """``(character, length)`` if *line* opens a fenced code block."""
    m = _FENCE_OPEN.match(line.rstrip("\r\n"))
    if m is None:
        return None
    run = m.group("run")
    if run[0] == "`" and "`" in m.group("info"):
        return None
    return run[0], len(run)


def _closes(line: str, fence: tuple[str, int]) -> bool:
    """True if *line* closes *fence*: the same character, at least as long, nothing after."""
    stripped = line.strip()
    char, length = fence
    return len(stripped) >= length and stripped == char * len(stripped)


def _line_markers(line: str, number: int, offset: int, problems: list[Problem]) -> list[Marker]:
    spans = _code_spans(line)

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
    found: list[Marker] = []
    offset = 0
    fence: tuple[str, int] | None = None
    fence_line = 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if fence is not None:
            if _closes(line, fence):
                fence = None
        elif (opener := _fence_opener(line)) is not None:
            fence, fence_line = opener, number
        else:
            found.extend(_line_markers(line, number, offset, problems))
        offset += len(line)
    if fence is not None:
        problems.append(
            Problem(fence_line, "unclosed code fence: every marker after it would be ignored")
        )
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
