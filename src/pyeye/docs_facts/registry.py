"""The fact registry: :data:`EXTRACTORS` is the one list of extractors.

Every fact the docs may show comes from exactly one extractor listed here, and
each extractor owns the ID prefixes it declares, so two extractors can never
produce the same fact. Adding a fact family means adding an extractor to this
list; nothing else reads code to produce documentation facts.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .extractors import ci, cli, duplication, edges, env, mcp_surface, review, scopes, security
from .facts import Bindable, index


@dataclass(frozen=True)
class Extractor:
    """One fact family.

    Attributes:
        name: Short name, for error messages.
        prefixes: The first ID segments this extractor owns.
        extract: Yields the family's facts and views; takes the repo root.
    """

    name: str
    prefixes: tuple[str, ...]
    extract: Callable[[Path], Iterable[Bindable]]


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
)


def build(root: Path, extractors: Iterable[Extractor] = EXTRACTORS) -> dict[str, Bindable]:
    """Run every extractor and index the result by ID.

    Raises:
        ValueError: If two extractors claim a prefix, an extractor yields an ID
            outside its prefixes, an ID is malformed or produced twice, or a view
            names a fact that doesn't exist.
    """
    owners: dict[str, str] = {}
    items: list[Bindable] = []
    for extractor in extractors:
        for prefix in extractor.prefixes:
            if prefix in owners:
                raise ValueError(
                    f"prefix {prefix!r} is claimed by {owners[prefix]} and {extractor.name}"
                )
            owners[prefix] = extractor.name
        for item in extractor.extract(root):
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
    return by_id
