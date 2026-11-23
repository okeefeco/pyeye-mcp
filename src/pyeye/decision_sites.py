"""A decision's sites, resolved through pyeye (#1178; shared with #1182).

A decision entry names the sites its rule governs (``Applies-to``) and what it
touched (``Anchor``) as backticked stable references: ``pkg.mod.func``,
``pkg.mod.Cls.method``, ``tests/test_mod.py``. This module turns such text into
records:

- :func:`refs` picks out the code references, each with its kind (``handle``,
  a dotted name; ``path``, a ``.py`` file, a pytest node ID trimmed to its
  file) and its line. Not references: a config file (``pyproject.toml``), a
  version pin, prose (``every edge in REGISTRY``), ``none (<why>)``, and a
  single bare word, which would resolve by guesswork to any same-named
  definition.
- :func:`resolve_sites` resolves each through a :class:`Resolver`. The default,
  :func:`pyeye_resolver`, is pyeye's own resolver (the user's ruling,
  2026-11-23): a re-exported path gives its definition site's canonical handle,
  and a file path its module. A site that doesn't resolve to exactly one
  project definition keeps its ``reason``, so a caller reports it rather than
  silently treating it as unmatched.

Static only (C19): nothing of the analysed project is imported or run.
:mod:`pyeye.decisions` stays standard-library only, so this lives beside it.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

#: A backticked span on one line.
_SPAN = re.compile(r"`([^`\n]+)`")

#: A dotted name of at least two parts.
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")

#: A Python file path, repo-relative.
_PY_PATH = re.compile(r"[\w.-]+(?:/[\w.-]+)*\.pyi?")

#: Last segments that make a dotted-looking span a file, not a code reference.
_NOT_CODE = frozenset(
    {"toml", "json", "yml", "yaml", "md", "txt", "cfg", "ini", "lock", "rst", "html", "csv"}
)

RefKind = Literal["handle", "path"]


@dataclass(frozen=True)
class Ref:
    """One code reference in a decision's text.

    Attributes:
        text: The reference, trimmed (``()`` and a pytest ``::node`` removed).
        kind: ``handle`` (a dotted name) or ``path`` (a ``.py``/``.pyi`` file).
        line: Its line: 1-based within the text, plus the caller's offset.
    """

    text: str
    kind: RefKind
    line: int


@dataclass(frozen=True)
class Site:
    """One reference and what it resolved to.

    Attributes:
        ref: The reference.
        handle: Its canonical project handle, or ``None`` when it didn't resolve.
        reason: Why it didn't resolve (``unresolved``, ``ambiguous``,
            ``external``, ``file_not_found``, ...), or ``None`` when it did.
    """

    ref: Ref
    handle: str | None
    reason: str | None


class Resolver(Protocol):
    """Resolves one reference to a canonical project handle."""

    def canonical(self, identifier: str) -> tuple[str | None, str | None]:
        """``(handle, None)`` for one project definition, else ``(None, reason)``."""
        ...


def _ref(span: str, line: int) -> Ref | None:
    """The code reference *span* is, trimmed, or ``None`` when it isn't one."""
    text = span.strip().split("::", 1)[0].removesuffix("()")
    if _PY_PATH.fullmatch(text):
        return Ref(text, "path", line)
    if _DOTTED.fullmatch(text) and text.rsplit(".", 1)[1] not in _NOT_CODE:
        return Ref(text, "handle", line)
    return None


def refs(text: str | None, first_line: int = 1) -> list[Ref]:
    """The code references in *text*, each once at its first line, in order.

    *first_line* is the line *text* starts on, so a caller passing one field of
    an entry gets the entry's line numbers.
    """
    out: list[Ref] = []
    seen: set[str] = set()
    for number, line in enumerate((text or "").splitlines(), first_line):
        for span in _SPAN.findall(line):
            ref = _ref(span, number)
            if ref is not None and ref.text not in seen:
                seen.add(ref.text)
                out.append(ref)
    return out


def resolve_sites(text: str | None, resolver: Resolver, first_line: int = 1) -> list[Site]:
    """Every code reference in *text*, resolved through *resolver*."""
    return [Site(ref, *resolver.canonical(ref.text)) for ref in refs(text, first_line)]


class _PyeyeResolver:
    """:class:`Resolver` over one project, with pyeye's ``resolve``.

    The analyzer is built on the first question, so a run with no reference
    never pays for it.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._analyzer: Any = None

    def _jedi(self) -> Any:
        if self._analyzer is None:
            from .analyzers.jedi_analyzer import JediAnalyzer

            self._analyzer = JediAnalyzer(self._root.as_posix())
        return self._analyzer

    def canonical(self, identifier: str) -> tuple[str | None, str | None]:
        """Resolve *identifier* as pyeye's ``resolve`` tool does."""
        from .mcp.operations.resolve import resolve

        found: dict[str, Any] = dict(asyncio.run(resolve(identifier, self._jedi())))
        if not found.get("found"):
            return None, str(found.get("reason") or "unresolved")
        if found.get("ambiguous"):
            return None, "ambiguous"
        if found.get("scope") != "project":
            return None, "external"
        return str(found["handle"]), None


def pyeye_resolver(root: Path) -> Resolver:
    """The default :class:`Resolver`: pyeye's resolver over the project at *root*."""
    return _PyeyeResolver(root)
