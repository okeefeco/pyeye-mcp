"""A repository's docs-facts setup: what to extract, check and generate (#1091).

The engine (binding, ``generate``/``check``, the snapshot, the ledger, stale
detection) is generic; what it runs is per repository. A :class:`Setup` names
it: the extractors that produce the facts, the doc registry, the prose rules
and the generated reference pages. pyeye's own is built from the in-code
constants (:func:`pyeye_setup`), and is what the CLI uses unless it is given
another.

RFC #1083 step 1. The per-repo config file that builds a :class:`Setup` for
another codebase is decided separately; this module is the seam it plugs into.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from . import docs, pages, registry, rules
from .facts import Bindable

#: A reference page builder: the facts in, the page's Markdown out.
PageBuilder = Callable[[Mapping[str, Bindable]], str]


@dataclass(frozen=True)
class Setup:
    """What docs-facts runs on one repository.

    Attributes:
        extractors: The fact extractors (``registry.build``'s input).
        docs: The doc registry: every page and how the checks treat it.
        rules: The prose rules; each runs only where its required facts exist
            (:attr:`~.rules.Rule.requires`), and is reported as skipped otherwise.
        pages: Repo-relative path -> builder of each generated reference page.
        changelog: The changelog, read for the current release (the
            removed-name sunset), or ``None`` to turn that behaviour off.
    """

    extractors: tuple[registry.Extractor, ...]
    docs: tuple[docs.DocEntry, ...]
    rules: tuple[rules.Rule, ...]
    pages: Mapping[str, PageBuilder]
    changelog: str | None = "CHANGELOG.md"


def pyeye_setup() -> Setup:
    """pyeye's own setup: its extractors, its doc registry, every rule and its pages.

    Read from the module constants at call time, so a caller that replaces one
    (a test, a spike) is seen.
    """
    return Setup(
        extractors=registry.EXTRACTORS,
        docs=docs.DOCS,
        rules=rules.RULES,
        pages=pages.PAGES,
        changelog="CHANGELOG.md",
    )
