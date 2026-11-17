"""Resolver facts: the strategy chain and the bare-name policy (#830, design C15).

Read from the tables :func:`pyeye.resolver.resolve_handle` and
:func:`pyeye.resolver.resolve_name` actually run, so the docs show the order
the code follows:

- ``resolver.strategy.<step>``: one fact per step, with the side it runs on
  (``all``, ``project`` or ``external``), its position and its summary;
- ``resolver.bare_name.<rule>``: one fact per rule of the bare-name policy.

It imports :mod:`pyeye.resolver` only, which sits below :mod:`pyeye.mcp`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from ... import resolver
from ..facts import Bindable, Fact, code, text, view

PREFIXES = ("resolver",)

#: Which table each side comes from, in the order :func:`pyeye.resolver._resolve` runs them.
_SIDES: tuple[tuple[str, str, tuple[resolver.Step, ...]], ...] = (
    ("all", "every path", resolver.STRATEGY),
    ("project", "then, inside the project", resolver.PROJECT_STRATEGY),
    ("external", "then, outside the project", resolver.EXTERNAL_STRATEGY),
)


def _numbered(lines: Iterable[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


def extract(root: Path) -> Iterator[Bindable]:  # noqa: ARG001 - reads the live tables
    """Yield a fact per strategy step and per bare-name rule, plus their views."""
    steps: list[Fact] = []
    blocks: list[str] = []
    for side, heading, table in _SIDES:
        side_facts = [
            Fact(
                f"resolver.strategy.{step.name}",
                {"side": side, "position": i, "summary": step.summary},
                f"{code(step.name)}: {text(step.summary)}",
            )
            for i, step in enumerate(table, 1)
        ]
        steps.extend(side_facts)
        blocks.append(f"{heading.capitalize()}:\n\n" + _numbered(f.markdown for f in side_facts))
    yield from steps
    yield view("resolver.strategy", steps, "\n\n".join(blocks))

    rules = [
        Fact(
            f"resolver.bare_name.{rule.name}",
            {"position": i, "summary": rule.summary},
            f"{code(rule.name)}: {text(rule.summary)}",
        )
        for i, rule in enumerate(resolver.BARE_NAME_POLICY, 1)
    ]
    yield from rules
    yield view("resolver.bare_name", rules, _numbered(f.markdown for f in rules))
