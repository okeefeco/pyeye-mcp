"""Duplication-review facts: the CLI's commands, flags, defaults and vocabulary.

Read from :mod:`pyeye.duplication`: its argument parser (``python -m
pyeye.duplication`` is a documented interface), its defaults, its filter
thresholds and its closed set of dismissal reasons.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import static
from ..facts import Bindable, Fact, code, code_list, view

PREFIXES = ("duplication",)


def _share(value: float) -> str:
    """A line share the way the skill writes it: ``60 %``."""
    return f"{value:.0%}".replace("%", " %")


def _words(commands: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    """Each subcommand and long option -> the subcommands that accept it, in parser order."""
    words: dict[str, list[str]] = {}
    for command, flags in commands.items():
        words.setdefault(command, [])
        for flag in flags:
            words.setdefault(flag, []).append(command)
    return words


def extract(root: Path) -> Iterator[Bindable]:
    """Yield the CLI vocabulary, its defaults, thresholds and dismissal reasons.

    Read from the source, never imported: the vocabulary is the declared
    :data:`pyeye.duplication.COMMANDS` (#1098, C19).
    """
    source = static.Module(root, "pyeye.duplication")
    return _facts(_words(source.COMMANDS), source)


def _facts(words: dict[str, list[str]], dup: Any) -> Iterator[Bindable]:
    commands = [Fact(f"duplication.command.{w}", {}, code(w)) for w in words if not words[w]]
    flags = [
        Fact(f"duplication.flag.{w[2:]}", {"commands": words[w]}, code(w))
        for w in words
        if words[w]
    ]
    yield from commands
    yield from flags
    yield view("duplication.commands", commands, code_list(f.markdown[1:-1] for f in commands))
    yield view("duplication.flags", flags, code_list(f.markdown[1:-1] for f in flags))

    yield Fact(
        "duplication.default.min_tokens", dup.DEFAULT_MIN_TOKENS, code(str(dup.DEFAULT_MIN_TOKENS))
    )
    yield Fact(
        "duplication.default.max_occurrences",
        dup.DEFAULT_MAX_OCCURRENCES,
        code(str(dup.DEFAULT_MAX_OCCURRENCES)),
    )
    yield Fact(
        "duplication.filter.function_line_share",
        dup.FUNCTION_LINE_SHARE,
        _share(dup.FUNCTION_LINE_SHARE),
    )
    yield Fact(
        "duplication.filter.signature_line_share",
        dup.SIGNATURE_LINE_SHARE,
        _share(dup.SIGNATURE_LINE_SHARE),
    )
    reasons = [Fact(f"duplication.reason.{r}", {}, code(r)) for r in dup.DISMISSAL_REASONS]
    yield from reasons
    yield view("duplication.reasons", reasons, code_list(dup.DISMISSAL_REASONS))
