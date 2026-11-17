"""MkDocs hooks: publish the doc registry's pages at their repo paths (#861).

A thin adapter over :mod:`pyeye.docs_facts.site`, which decides what's
published and builds the nav; ``mkdocs.yml`` lists no pages. Loaded through
``hooks:`` in ``mkdocs.yml``, so it needs no plugin package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import File, Files
from mkdocs.structure.pages import Page

from pyeye.docs_facts import site
from pyeye.path_utils import relative_within

ROOT = Path(__file__).resolve().parent.parent
_STATE: dict[str, Any] = {}


def on_config(config: MkDocsConfig) -> MkDocsConfig:
    """Set the nav from the registry, and remember what's published."""
    pages = site.published(ROOT)
    _STATE["pages"] = frozenset(pages)
    _STATE["repo"] = site.repository_url(ROOT)
    config.nav = site.nav(pages)
    return config


def on_files(files: Files, config: MkDocsConfig) -> Files:
    """Replace the docs folder's files with the published pages, at repo paths."""
    # Theme assets stay; everything MkDocs collected from docs_dir goes, so
    # only registry pages (and nothing else in docs/, such as docs/facts/*.json)
    # are published.
    kept = [
        f
        for f in files
        if f.abs_src_path is None or relative_within(f.abs_src_path, config.docs_dir) is None
    ]
    out = Files(kept)
    for path in sorted(_STATE["pages"]):
        out.append(File(path, ROOT.as_posix(), config.site_dir, config.use_directory_urls))
    return out


def on_page_markdown(markdown: str, *, page: Page, **_: Any) -> str:
    """Point links to unpublished repo files at GitHub, in the rendered page only."""
    return site.rewrite_links(markdown, page.file.src_uri, ROOT, _STATE["pages"], _STATE["repo"])
