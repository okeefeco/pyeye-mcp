"""Resolver facts: the strategy chain and the bare-name policy (#830, design C15).

Read from the tables :func:`pyeye.resolver.resolve_handle` and
:func:`pyeye.resolver.resolve_name` actually run, so the docs show the order
the code follows:

- ``resolver.strategy.<step>``: one fact per step, with the side it runs on
  (``all``, ``project`` or ``external``), its position and its summary;
- ``resolver.bare_name.<rule>``: one fact per rule of the bare-name policy.

The tables' ``Step(...)`` / ``NameRule(...)`` calls are read from the
source (:mod:`..static`); the resolver is never imported (#1098, C19).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from .. import static
from ..facts import Bindable, Fact, code, text, view

PREFIXES = ("resolver",)

#: Which table each side comes from, in the order :func:`pyeye.resolver._resolve` runs them.
_SIDES: tuple[tuple[str, str, str], ...] = (
    ("all", "every path", "STRATEGY"),
    ("project", "then, inside the project", "PROJECT_STRATEGY"),
    ("external", "then, outside the project", "EXTERNAL_STRATEGY"),
)
#: A strategy step or bare-name rule, as ``(name, summary)``.
_Row = tuple[str, str]


def _numbered(lines: Iterable[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


def extract(root: Path) -> Iterator[Bindable]:
    """Yield a fact per strategy step and per bare-name rule, plus their views.

    The ``Step(name, summary, fn)`` / ``NameRule(...)`` calls are read from the
    source; the functions they name are never touched (#1098, C19).
    """

    def rows(table: str) -> list[_Row]:
        return [(n, s) for n, s in static.call_args(root, "pyeye.resolver", table, 2)]

    return _facts({t: rows(t) for _s, _h, t in _SIDES}, rows("BARE_NAME_POLICY"))


def _facts(tables: dict[str, list[_Row]], bare: list[_Row]) -> Iterator[Bindable]:
    steps: list[Fact] = []
    blocks: list[str] = []
    for side, heading, name in _SIDES:
        table = tables[name]
        side_facts = [
            Fact(
                f"resolver.strategy.{step}",
                {"side": side, "position": i, "summary": summary},
                f"{code(step)}: {text(summary)}",
            )
            for i, (step, summary) in enumerate(table, 1)
        ]
        steps.extend(side_facts)
        blocks.append(f"{heading.capitalize()}:\n\n" + _numbered(f.markdown for f in side_facts))
    yield from steps
    yield view("resolver.strategy", steps, "\n\n".join(blocks))

    rules = [
        Fact(
            f"resolver.bare_name.{rule}",
            {"position": i, "summary": summary},
            f"{code(rule)}: {text(summary)}",
        )
        for i, (rule, summary) in enumerate(bare, 1)
    ]
    yield from rules
    yield view("resolver.bare_name", rules, _numbered(f.markdown for f in rules))
