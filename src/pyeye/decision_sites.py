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
- Given the project's top-level names (:func:`top_level_names`, and
  :func:`external_top_level_names`), a dotted name is classified from the
  layout, never by resolving (#1182, #1178): rooted at a project top-level
  package or module it is a ``handle``; at a standard-library or environment
  one, an ``external``; at neither, a ``short_form``
  (``JediAnalyzer.find_importers``, ``outline._is_package``), which names
  something only a guess turns into a handle. A short form is never resolved.
  Callers report short forms, and externals that don't resolve, apart,
  counted and listed: never as stale, never silently.
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
import sys
from collections.abc import Collection
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

RefKind = Literal["handle", "path", "external", "short_form"]


@dataclass(frozen=True)
class Ref:
    """One code reference in a decision's text.

    Attributes:
        text: The reference, trimmed (``()`` and a pytest ``::node`` removed).
        kind: ``handle`` (a dotted name; with the layout, one rooted at a
            project top-level name), ``path`` (a ``.py``/``.pyi`` file),
            ``external`` (rooted at a standard-library or environment
            top-level name) or ``short_form`` (rooted at neither).
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
            ``external``, ``file_not_found``, ...; ``short_form`` for a short
            form, which is never resolved), or ``None`` when it did.
    """

    ref: Ref
    handle: str | None
    reason: str | None


class Resolver(Protocol):
    """Resolves one reference to a canonical project handle."""

    def canonical(self, identifier: str) -> tuple[str | None, str | None]:
        """``(handle, None)`` for one project definition, else ``(None, reason)``."""
        ...


def _kind(text: str, tops: Collection[str] | None, external: Collection[str]) -> RefKind:
    """A dotted name's kind: from its first segment, when the layout is given."""
    if tops is None:
        return "handle"
    first = text.split(".", 1)[0]
    if first in tops:
        return "handle"
    return "external" if first in external else "short_form"


def _ref(
    span: str, line: int, tops: Collection[str] | None, external: Collection[str]
) -> Ref | None:
    """The code reference *span* is, trimmed, or ``None`` when it isn't one."""
    text = span.strip().split("::", 1)[0].removesuffix("()")
    if _PY_PATH.fullmatch(text):
        return Ref(text, "path", line)
    if _DOTTED.fullmatch(text) and text.rsplit(".", 1)[1] not in _NOT_CODE:
        return Ref(text, _kind(text, tops, external), line)
    return None


def refs(
    text: str | None,
    first_line: int = 1,
    *,
    tops: Collection[str] | None = None,
    external: Collection[str] = (),
) -> list[Ref]:
    """The code references in *text*, each once at its first line, in order.

    *first_line* is the line *text* starts on, so a caller passing one field of
    an entry gets the entry's line numbers. With *tops* (the project's
    :func:`top_level_names`) a dotted name is a ``handle`` when rooted at one
    of them, an ``external`` when rooted at one of *external*
    (:func:`external_top_level_names`), else a ``short_form``. Without *tops*,
    every dotted name is a ``handle``.
    """
    out: list[Ref] = []
    seen: set[str] = set()
    for number, line in enumerate((text or "").splitlines(), first_line):
        for span in _SPAN.findall(line):
            ref = _ref(span, number, tops, external)
            if ref is not None and ref.text not in seen:
                seen.add(ref.text)
                out.append(ref)
    return out


def resolve_sites(
    text: str | None,
    resolver: Resolver,
    first_line: int = 1,
    *,
    tops: Collection[str] | None = None,
    external: Collection[str] = (),
) -> list[Site]:
    """Every code reference in *text*, resolved through *resolver*.

    A ``short_form`` (with *tops*, see :func:`refs`) is never resolved: its
    site has no handle and the reason ``short_form``. An ``external`` is
    resolved and keeps the resolver's answer.
    """
    return [
        (
            Site(ref, None, "short_form")
            if ref.kind == "short_form"
            else Site(ref, *resolver.canonical(ref.text))
        )
        for ref in refs(text, first_line, tops=tops, external=external)
    ]


def top_level_names(root: Path) -> frozenset[str]:
    """The project's own top-level packages and modules at *root* (#1182, #1178).

    Read from the layout, never by resolving: the entries of the project root
    and of its ``src/`` layout. A dotted name rooted at one is a ``handle``.
    """
    from .project_layout import _site_tops, detect_src_layout

    bases = [root]
    src = detect_src_layout(root)
    if src is not None:
        bases.append(src)
    return frozenset(name for base in bases for name in _site_tops(base))


def external_top_level_names(root: Path) -> frozenset[str]:
    """The standard library's top-level names, and the project environment's (#1182).

    Read from the layout, never by resolving: ``sys.stdlib_module_names`` and
    the top-level entries of the project environment's site directories. A
    dotted name rooted at one, and not at a project name, is an ``external``.
    """
    from .environment import discover
    from .project_layout import _site_tops

    names: set[str] = set(sys.stdlib_module_names)
    for site in discover(root).site_paths:
        names |= _site_tops(Path(site))
    return frozenset(names)


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
