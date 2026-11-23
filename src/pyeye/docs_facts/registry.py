"""The fact registry: :data:`EXTRACTORS` is the one list of extractors.

Every fact the docs may show comes from exactly one extractor listed here, and
each extractor owns the ID prefixes it declares, so two extractors can never
produce the same fact. Adding a fact family means adding an extractor to this
list; nothing else reads code to produce documentation facts.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .extractors import (
    ci,
    cli,
    duplication,
    edges,
    env,
    mcp_surface,
    repo_config,
    resolver,
    review,
    scopes,
    security,
)
from .facts import Advisory, Bindable, index

if TYPE_CHECKING:
    from .rules import Rule


@dataclass(frozen=True)
class Extractor:
    """One fact family.

    Attributes:
        name: Short name, for error messages.
        prefixes: The first ID segments this extractor owns.
        extract: Yields the family's facts and views, and any
            :class:`~.facts.Advisory` pages; takes the repo root.
        rules: The rules that read this extractor's facts (#1092). They join
            the repository's rules, so a rule follows the extractor's options
            (its fact prefix) instead of assuming a default.
    """

    name: str
    prefixes: tuple[str, ...]
    extract: Callable[[Path], Iterable[Bindable | Advisory]]
    rules: tuple[Rule, ...] = field(default=())


EXTRACTORS: tuple[Extractor, ...] = (
    Extractor("mcp_surface", mcp_surface.PREFIXES, mcp_surface.extract),
    Extractor("edges", edges.PREFIXES, edges.extract),
    Extractor("env", env.PREFIXES, env.extract),
    Extractor("cli", cli.PREFIXES, cli.extract),
    Extractor("ci", ci.PREFIXES, ci.extract),
    Extractor("review", review.PREFIXES, review.extract),
    Extractor("duplication", duplication.PREFIXES, duplication.extract),
    Extractor("scopes", scopes.PREFIXES, scopes.extract),
    Extractor("security", security.PREFIXES, security.extract),
    Extractor("resolver", resolver.PREFIXES, resolver.extract),
    Extractor("repo_config", repo_config.PREFIXES, repo_config.extract),
)


def build(
    root: Path,
    extractors: Iterable[Extractor] = EXTRACTORS,
    advisory: dict[str, str] | None = None,
) -> dict[str, Bindable]:
    """Run every extractor and index its facts by ID.

    Args:
        root: The repository root.
        extractors: The extractors to run.
        advisory: Filled with each :class:`~.facts.Advisory` page, path -> text
            (#1092); without it they are dropped.

    Raises:
        ValueError: If two extractors claim a prefix, an extractor yields an ID
            outside its prefixes, an ID is malformed or produced twice, a view
            names a fact that doesn't exist, or two advisory pages share a path.
    """
    owners: dict[str, str] = {}
    items: list[Bindable] = []
    pages: dict[str, str] = {}
    for extractor in extractors:
        for prefix in extractor.prefixes:
            if prefix in owners:
                raise ValueError(
                    f"prefix {prefix!r} is claimed by {owners[prefix]} and {extractor.name}"
                )
            owners[prefix] = extractor.name
        for item in extractor.extract(root):
            if isinstance(item, Advisory):
                if item.path in pages:
                    raise ValueError(f"advisory page {item.path!r} is produced twice")
                pages[item.path] = item.text
                continue
            if item.id.split(".", 1)[0] not in extractor.prefixes:
                raise ValueError(
                    f"{extractor.name} yielded {item.id!r}, outside its prefixes "
                    f"{extractor.prefixes}"
                )
            items.append(item)
    by_id = index(items)
    for item in by_id.values():
        missing = [m for m in getattr(item, "members", ()) if m not in by_id]
        if missing:
            raise ValueError(f"view {item.id!r} names unknown facts {missing}")
    if advisory is not None:
        advisory.update(pages)
    return by_id
