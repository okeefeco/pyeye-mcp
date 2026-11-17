"""Fact slots in MCP tool descriptions (#827, #818 D9).

A tool docstring keeps its prose hand-written and writes each fact part as a
slot, ``<<fact:ID>>`` or ``<<fact:ID:FORM>>``. The slot is filled when the
module loads, before the MCP server reads the docstring as the tool's
description:

- core tools carry :func:`described` under ``@mcp.tool()``;
- plugin tools are filled by the server's plugin-tool wrapper.

A slot names a fact or view from :data:`LOAD_TIME_EXTRACTORS` and renders it in
the docstrings' own reStructuredText style (````name````), not as Markdown. An
unknown ID or form raises :class:`SlotError`, so a stale slot stops the server
from loading instead of shipping wrong text.

Only extractors that don't import :mod:`pyeye.mcp.server` can fill slots:
``mcp_surface`` reads the registered tools, so it can't describe them while they
register. A tool's own parameters are checked, not slotted
(``tests/test_docs_facts_describe.py``): repeating the schema in the prose would
add nothing.

The slot-free text is kept as ``__doc_template__`` on the described function, so
the hand-list rule (:func:`hand_lists`) can check exactly the hand-written part.
"""

from __future__ import annotations

import functools
import importlib
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from .facts import Bindable, Fact, View, index

#: Extractor modules (under :mod:`pyeye.docs_facts.extractors`) whose facts can
#: fill a slot. Neither reads :mod:`pyeye.mcp.server`. They are imported on the
#: first fill, not here: ``edges`` imports :mod:`pyeye.mcp`, whose package
#: ``__init__`` imports the server, which imports this module.
LOAD_TIME_EXTRACTORS = ("edges", "scopes")

#: ``<<fact:ID>>`` or ``<<fact:ID:FORM>>``. ``<<`` never occurs naturally in a
#: docstring, so, unlike ``str.format``, literal braces in JSON examples are safe.
SLOT = re.compile(r"<<fact:(?P<id>[A-Za-z0-9_.-]+?)(?::(?P<form>[a-z_]+))?>>")

#: The views :func:`hand_lists` guards: a hand-written list of their members
#: must be a slot, unless it is the complete set, each member with its own prose.
GUARDED_VIEWS = ("edges.implemented", "edges.deferred", "ceilings.table", "scopes.options")

#: A list of at least this many members of one view, outside a slot, is a hand list.
HAND_LIST_MIN = 3

F = TypeVar("F", bound=Callable[..., Any])


class SlotError(ValueError):
    """A slot names a fact, view or form that doesn't exist, or can't render."""


@functools.cache
def load_time_facts() -> Mapping[str, Bindable]:
    """Every fact and view a slot can name, indexed by ID (built once)."""
    root = Path(".")
    modules = [
        importlib.import_module(f"{__package__}.extractors.{n}") for n in LOAD_TIME_EXTRACTORS
    ]
    return index(item for module in modules for item in module.extract(root))


def _members(item: Bindable, facts: Mapping[str, Bindable]) -> list[Fact]:
    if isinstance(item, View):
        return [m for m in (facts[i] for i in item.members) if isinstance(m, Fact)]
    return [item]


def label(fact: Fact) -> str:
    """How a fact is named in prose: an edge or ceiling ID, or a scope's syntax."""
    if fact.id.startswith("scope.option."):
        return str(fact.value["syntax"])
    if fact.id == "scope.default.plugin":
        return str(fact.value["fallback"])
    return fact.id.split(".", 1)[1]


def _rst(name: str) -> str:
    return f"``{name}``"


Facts = Mapping[str, Bindable]


def _render_list(members: list[Fact], indent: str, facts: Facts) -> str:  # noqa: ARG001 - inline
    return ", ".join(_rst(label(m)) for m in members)


def _render_bullets(members: list[Fact], indent: str, facts: Facts) -> str:  # noqa: ARG001
    lines = []
    for m in members:
        meaning = m.value.get("meaning") if isinstance(m.value, dict) else None
        if meaning is None:
            raise SlotError(f"{m.id!r} has no meaning to show as a bullet")
        lines.append(f"- {_rst(label(m))}: {meaning}.")
    return ("\n" + indent).join(lines)


def _render_applies_to(members: list[Fact], indent: str, facts: Facts) -> str:  # noqa: ARG001
    parts = []
    for m in members:
        kinds = m.value.get("applies_to") if isinstance(m.value, dict) else None
        if kinds is None:
            raise SlotError(f"{m.id!r} has no applies_to to show")
        parts.append(f"{_rst(label(m))} → {', '.join(kinds)}")
    return "; ".join(parts)


def ceiling_statement(edge: Fact, facts: Facts) -> str | None:
    """How a description states *edge*'s ceiling: ````<ceiling>``: <meaning>``.

    ``None`` for an exact edge (no ceiling). The edge-ceiling rule (#827, design
    C12) looks for exactly this text, so the slot and the check can't disagree.

    Raises:
        SlotError: If *edge* isn't an edge fact, or its ceiling has no fact.
    """
    if not edge.id.startswith("edge.") or not isinstance(edge.value, dict):
        raise SlotError(f"{edge.id!r} is not an edge, so it has no ceiling")
    ceiling_id = edge.value.get("ceiling")
    if ceiling_id is None:
        return None
    ceiling = facts.get(f"ceiling.{ceiling_id}")
    if not isinstance(ceiling, Fact):
        raise SlotError(f"{edge.id!r} has ceiling {ceiling_id!r}, which has no fact")
    return f"{_rst(ceiling_id)}: {ceiling.value['meaning']}"


def _render_ceiling(members: list[Fact], indent: str, facts: Facts) -> str:  # noqa: ARG001
    parts = []
    for m in members:
        statement = ceiling_statement(m, facts)
        parts.append(statement if statement is not None else "exact (no ceiling)")
    return "; ".join(parts)


def _render_ceilings(members: list[Fact], indent: str, facts: Facts) -> str:
    lines = []
    for m in members:
        statement = ceiling_statement(m, facts)
        # "On ``edge``", not "``edge``": a bullet that starts with the edge name
        # is that edge's own entry to the #417 marker rule.
        lines.append(f"- On {_rst(label(m))}: {statement or 'exact (no ceiling)'}.")
    return ("\n" + indent).join(lines)


#: Forms that render several lines, at the slot's own indentation. A slot in one
#: of them must be on a line of its own, or :func:`fill` raises :class:`SlotError`.
BLOCK_FORMS = frozenset({"bullets", "ceilings"})

#: Slot forms. Inline: ``list`` (the default), ``applies_to``, and ``ceiling``
#: (an edge's ceiling statement). Block (one member per line, see
#: :data:`BLOCK_FORMS`): ``bullets`` (each member's meaning) and ``ceilings``
#: (each edge with its ceiling statement).
FORMS: dict[str, Callable[[list[Fact], str, Facts], str]] = {
    "list": _render_list,
    "bullets": _render_bullets,
    "applies_to": _render_applies_to,
    "ceiling": _render_ceiling,
    "ceilings": _render_ceilings,
}


def fill(doc: str, facts: Mapping[str, Bindable] | None = None) -> str:
    """Replace every slot in *doc* with its rendered fact.

    Raises:
        SlotError: If a slot names an unknown fact, view or form, or a form that
            the fact can't render.
    """
    facts = load_time_facts() if facts is None else facts

    def replace(match: re.Match[str]) -> str:
        fact_id, form = match["id"], match["form"] or "list"
        if fact_id not in facts:
            raise SlotError(f"unknown fact {fact_id!r} in slot {match[0]!r}")
        if form not in FORMS:
            raise SlotError(f"unknown form {form!r} in slot {match[0]!r}; known: {sorted(FORMS)}")
        line_start = doc.rfind("\n", 0, match.start()) + 1
        line_end = doc.find("\n", match.end())
        before = doc[line_start : match.start()]
        after = doc[match.end() : len(doc) if line_end == -1 else line_end]
        own_line = not before.strip() and not after.strip()
        if form in BLOCK_FORMS and not own_line:
            raise SlotError(f"a {form!r} slot must be on a line of its own: {match[0]!r}")
        return FORMS[form](_members(facts[fact_id], facts), before if own_line else "", facts)

    filled = SLOT.sub(replace, doc)
    leftover = unfilled(filled)
    if leftover:
        raise SlotError(f"malformed slot(s) {leftover}; write <<fact:ID>> or <<fact:ID:FORM>>")
    return filled


def described(func: F) -> F:
    """Fill *func*'s docstring slots, keeping the template as ``__doc_template__``."""
    template = func.__doc__ or ""
    func.__doc_template__ = template  # type: ignore[attr-defined]
    func.__doc__ = fill(template)
    return func


def unfilled(text: str) -> list[str]:
    """Slot tokens, whole or malformed, still in *text*; a registered description has none."""
    return re.findall(r"<<fact:[^>\n]*(?:>>)?", text)


def _paragraphs(text: str) -> Iterable[str]:
    return (p for p in re.split(r"\n[ \t]*\n", text) if p.strip())


def hand_lists(template: str, facts: Mapping[str, Bindable] | None = None) -> list[str]:
    """Paragraphs of *template* that hand-write a partial list of a guarded view.

    The slots are removed first, so only the hand-written text is checked. A
    paragraph that names at least :data:`HAND_LIST_MIN` members of a view, as
    ````name```` or ``"name"``, must name all of them: a complete list with
    prose for each member is fine, and a new member then fails it until the
    prose covers it. Naming one or two as an example is fine.

    Returns:
        ``"<view>: <names> in: <paragraph start>"`` for each offending paragraph.
    """
    facts = load_time_facts() if facts is None else facts
    problems = []
    for para in _paragraphs(SLOT.sub("", template)):
        for view_id in GUARDED_VIEWS:
            names = [label(m) for m in _members(facts[view_id], facts)]
            named = [n for n in names if _quoted(n, para)]
            if HAND_LIST_MIN <= len(named) < len(names):
                start = " ".join(para.split())[:70]
                problems.append(f"{view_id}: {', '.join(named)} in: {start!r}")
    return problems


def _quoted(name: str, text: str) -> bool:
    """Whether *name* appears as ````name```` or ``"name"`` (a parameterised scope by its prefix)."""
    stem = re.escape(name.split("<", 1)[0])
    end = r"" if "<" in name else r"(?:``|\")"
    return re.search(rf"(?:``|\"){stem}{end}", text) is not None
