"""Facts and views: what a marker block or a generated page can show.

A :class:`Fact` is one item (one tool parameter, one edge, one env var) with a
stable dotted ID and a JSON-serialisable value. It is what the snapshot
(``docs/facts/facts.json``) records and what change detection compares.

A :class:`View` is a group ID over item facts (``tool.trace.params``,
``edges.implemented``). It has no value of its own: it exists to be rendered in
a marker block. Both carry their Markdown rendering, so a fact has exactly one
way to appear in the docs and the comparison is a plain string comparison.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: A fact or view ID: lowercase dotted segments; env var names keep their case
#: (``env.PYEYE_CACHE_TTL``) and CLI names keep their dashes (``cli.script.pyeye-mcp``).
FACT_ID = re.compile(r"[a-z][a-z0-9_]*(\.[A-Za-z0-9_][A-Za-z0-9_-]*)+")


#: A fact family: a fact ID's first segment (``tool``, ``precommit``, ``arch``).
FAMILY = re.compile(r"[a-z][a-z0-9_]*")


def family(fact_id: str) -> str:
    """The family a fact ID belongs to: its first segment."""
    return fact_id.split(".", 1)[0]


def check_families(names: Iterable[str], where: str) -> None:
    """Refuse a name that isn't a fact family.

    Raises:
        ValueError: Naming the first bad one.
    """
    for name in names:
        if not isinstance(name, str) or not FAMILY.fullmatch(name):
            raise ValueError(
                f"{where}: {name!r} isn't a fact family (a fact ID's first segment: "
                "lower-case letters, digits and '_')"
            )


class ExtractionError(ValueError):
    """A source no longer has the shape its extractor reads, or two sources disagree.

    Extractors raise it instead of yielding a wrong or missing fact.
    """


class KindOptionsError(ValueError):
    """A kind's options aren't valid: unknown, missing or of the wrong type.

    Defined here, in a module that imports nothing of docs-facts, so a kind's
    factory can import it at the top whatever is imported first (#1163);
    :mod:`.kinds` re-exports it.
    """


@dataclass(frozen=True)
class Fact:
    """One documented item, extracted from the code.

    Attributes:
        id: Stable dotted ID, e.g. ``tool.trace.param.max_depth``.
        value: JSON-serialisable value; the snapshot records it.
        markdown: How the fact reads in the docs.
    """

    id: str
    value: Any
    markdown: str


@dataclass(frozen=True)
class View:
    """A group ID over item facts, rendered as one block.

    Attributes:
        id: Stable dotted ID, e.g. ``tool.trace.params``.
        members: IDs of the item facts it shows, in display order.
        markdown: How the group reads in the docs.
    """

    id: str
    members: tuple[str, ...]
    markdown: str


Bindable = Fact | View


def code(name: str) -> str:
    """Render *name* as inline code."""
    return f"`{name}`"


def code_list(names: Iterable[str]) -> str:
    """Render names as a comma-separated list of inline code."""
    return ", ".join(code(n) for n in names)


def text(plain: str) -> str:
    """Render plain text from the code so Markdown shows it as written.

    ``__getattr__`` would otherwise render as a bold ``getattr``.
    """
    return re.sub(r"([\\*_])", r"\\\1", plain)


def literal(value: Any) -> str:
    """Render a default or limit the way the docs write it."""
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    """Render a Markdown table; ``|`` inside a cell is escaped."""
    head = list(headers)
    lines = [
        "| " + " | ".join(head) + " |",
        "|" + "|".join("---" for _ in head) + "|",
    ]
    lines.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
    return "\n".join(lines)


def view(view_id: str, members: Iterable[Fact], markdown: str) -> View:
    """Build a :class:`View` over *members*."""
    return View(view_id, tuple(f.id for f in members), markdown)


def index(items: Iterable[Bindable]) -> dict[str, Bindable]:
    """Map ID to fact or view, rejecting a malformed or duplicate ID.

    Raises:
        ValueError: If an ID is malformed or produced twice.
    """
    by_id: dict[str, Bindable] = {}
    for item in items:
        if not FACT_ID.fullmatch(item.id):
            raise ValueError(f"malformed fact ID {item.id!r}")
        if item.id in by_id:
            raise ValueError(f"fact ID {item.id!r} is produced twice")
        by_id[item.id] = item
    return by_id


def snapshot(items: Mapping[str, Bindable]) -> dict[str, Any]:
    """The value of every item fact, by ID (views have no value of their own)."""
    return {i: f.value for i, f in sorted(items.items()) if isinstance(f, Fact)}


def memberships(items: Mapping[str, Bindable]) -> dict[str, list[str]]:
    """Each view's members, by view ID, in display order (#1114).

    The snapshot records them so a later diff knows which views held a fact
    that has since gone.
    """
    return {i: list(v.members) for i, v in sorted(items.items()) if isinstance(v, View)}
