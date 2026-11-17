"""The docs site: which registered pages it publishes, and its nav (#861).

The site is built by MkDocs from the same Markdown files, with no second copy.
What it publishes, and in what order, comes from the doc registry
(:data:`~.docs.DOCS`), never from a page list of its own, so a page can't be on
the site without being registered and checked.

- **Paths are repo paths.** Each page is served at its repo-relative path
  (``README.md`` is the site's home, ``docs/api/README.md`` is ``/docs/api/``),
  so a relative link resolves the same way on GitHub and on the site.
- **Published:** audience ``human`` or ``both``, except skills and history
  pages that still hold honest-claims seeds; an entry's ``site`` field
  overrides that (:func:`is_published`). There is no list of paths here.
- **Links to unpublished files** (a ``.claude/`` page, a source file) are
  rewritten in the *rendered* page to their GitHub URL. The source is unchanged.

This module needs no MkDocs: ``scripts/mkdocs_hooks.py`` adapts it.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..path_utils import relative_within
from . import (
    binding,
    docs as doc_registry,
)
from .docs import DocEntry

HOME = "README.md"

_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def is_published(entry: DocEntry) -> bool:
    """True if the site publishes this registered page (design C16).

    An entry's ``site`` decides when set. Otherwise a page is published when
    it is written for human readers (audience ``human`` or ``both``) and isn't
    a skill. A ``history`` page is held back while it still has honest-claims
    seeds, because those are known unbacked figures. Once #830 clears them, the
    page is published with no change here. Live pages publish with their seeds
    and are cleaned in place.
    """
    if entry.site is not None:
        return entry.site
    if entry.audience not in ("human", "both") or entry.kind == "skill":
        return False
    return not (entry.kind == "history" and entry.allow.get("honest-claims"))


def published(root: Path, docs: tuple[DocEntry, ...] | None = None) -> list[str]:
    """Every published page's repo-relative path, home first, then in path order."""
    pages = [
        path for path, entry in doc_registry.registered_files(root, docs) if is_published(entry)
    ]
    return sorted(pages, key=lambda p: (p != HOME, p.count("/"), p))


def _title(folder: str) -> str:
    """A nav section's title from its folder name: ``api`` -> ``Api``."""
    return folder.replace("-", " ").replace("_", " ").capitalize()


@dataclass
class _Section:
    pages: list[str] = field(default_factory=list)
    children: dict[str, _Section] = field(default_factory=dict)

    def as_nav(self) -> list[Any]:
        """Return the nav for this folder: its pages, then a section per subfolder."""
        nav: list[Any] = list(self.pages)
        nav.extend({_title(name): child.as_nav()} for name, child in sorted(self.children.items()))
        return nav


def nav(pages: Iterable[str]) -> list[Any]:
    """The site nav, one section per folder, as MkDocs's ``nav`` config takes it.

    Entries are bare paths, so MkDocs takes each title from the page's own
    heading. A folder's README comes first in its section.
    """
    top = _Section()
    for path in pages:
        *folders, name = path.split("/")
        section = top
        for folder in folders:
            section = section.children.setdefault(folder, _Section())
        if name == "README.md":
            section.pages.insert(0, path)
        else:
            section.pages.append(path)
    return top.as_nav()


def repository_url(root: Path) -> str:
    """The project's repository URL, from ``[project.urls]`` in ``pyproject.toml``."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return str(project["urls"]["Repository"]).rstrip("/")


def _resolve(page: str, target: str, root: Path) -> str | None:
    """*target*, a relative link on *page*, as a repo-relative path, or None."""
    folder = root / page.rsplit("/", 1)[0] if "/" in page else root
    rel = relative_within(folder / target, root)
    return rel.as_posix() if rel is not None else None


def github_link(page: str, href: str, root: Path, site: frozenset[str], repo: str) -> str | None:
    """The GitHub URL for a link to an existing repo file the site doesn't publish.

    ``None`` leaves the link alone: an external or in-page link, a published
    page, or a target that doesn't exist (``mkdocs build --strict`` reports it).
    """
    if not href or href.startswith("#") or _SCHEME.match(href) or href.startswith("/"):
        return None
    target, _, anchor = href.partition("#")
    path = _resolve(page, target, root)
    if path is None or path in site:
        return None
    full = root / path
    if not full.exists():
        return None
    kind = "tree" if full.is_dir() else "blob"
    url = f"{repo}/{kind}/main/{path.rstrip('/')}" if path not in ("", ".") else repo
    return f"{url}#{anchor}" if anchor else url


def rewrite_links(markdown: str, page: str, root: Path, site: frozenset[str], repo: str) -> str:
    """*markdown* with links to unpublished repo files pointed at GitHub.

    Links inside fenced code and inline code are left alone.
    """
    blank = markdown
    for fence in binding.fences(markdown):
        blank = (
            blank[: fence.body_start]
            + " " * (fence.body_end - fence.body_start)
            + blank[fence.body_end :]
        )
    pieces: list[str] = []
    cursor = 0
    offset = 0
    for line in blank.splitlines(keepends=True):
        spans = binding.code_spans(line)
        for match in _LINK.finditer(line):
            if any(start <= match.start() < end for start, end in spans):
                continue
            url = github_link(page, match.group(2), root, site, repo)
            if url is None:
                continue
            start = offset + match.start(2)
            pieces.append(markdown[cursor:start])
            pieces.append(url)
            cursor = offset + match.end(2)
        offset += len(line)
    pieces.append(markdown[cursor:])
    return "".join(pieces)
