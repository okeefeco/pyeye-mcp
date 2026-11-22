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
from dataclasses import dataclass, field
from types import MappingProxyType

from . import docs, ledger, pages, registry, removed, review, rules
from .facts import Bindable, check_families

#: A reference page builder: the facts in, the page's Markdown out.
PageBuilder = Callable[[Mapping[str, Bindable]], str]


@dataclass(frozen=True)
class Paths:
    """Where docs-facts keeps its records, relative to the repository root (#1091).

    Attributes:
        snapshot: The facts snapshot ``check`` compares against.
        removed: The record of removed names.
        uncovered: The ledger of facts no page explains.
        review_state: The ``/docs-review`` state.
        snapshots: Fact family -> its own snapshot file (#1108). The family's
            facts leave :attr:`snapshot` for that file, so a large family (the
            architecture facts, #1092) doesn't swamp its diffs.

    Raises:
        ValueError: If a key isn't a fact family, a file is one of the other
            records, or two families share a file.
    """

    snapshot: str = "docs/facts/facts.json"
    removed: str = removed.REMOVED
    uncovered: str = ledger.UNCOVERED
    review_state: str = review.STATE_PATH
    snapshots: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        """Validate :attr:`snapshots` and freeze it."""
        check_families(self.snapshots, "snapshots")
        records = {
            self.snapshot: "is the main snapshot",
            self.removed: "is the removed-name record",
            self.uncovered: "is the uncovered-fact ledger",
            self.review_state: "is the review state",
        }
        seen: dict[str, str] = {}
        for name, path in self.snapshots.items():
            if not isinstance(path, str) or not path:
                raise ValueError(f"snapshots: {name!r} must name a file")
            if path in records:
                raise ValueError(f"snapshots: {name!r}'s file {path!r} {records[path]}")
            if path in seen:
                raise ValueError(f"snapshots: {seen[path]!r} and {name!r} share {path!r}")
            seen[path] = name
        object.__setattr__(self, "snapshots", MappingProxyType(dict(self.snapshots)))

    def snapshot_of(self, fact_id: str) -> str:
        """The snapshot file that records *fact_id*."""
        return self.snapshots.get(fact_id.split(".", 1)[0], self.snapshot)

    def snapshot_files(self) -> tuple[str, ...]:
        """Every snapshot file: the main one, then each family's, sorted."""
        return (self.snapshot, *sorted(self.snapshots.values()))


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
        paths: Where the records live (:class:`Paths`).
        reference_only: Fact families that are reference data, not claims prose
            should make (#1108): they stay out of the uncovered-fact ledger.

    Raises:
        ValueError: If a reference-only name isn't a fact family.
    """

    extractors: tuple[registry.Extractor, ...]
    docs: tuple[docs.DocEntry, ...]
    rules: tuple[rules.Rule, ...]
    pages: Mapping[str, PageBuilder]
    changelog: str | None = "CHANGELOG.md"
    paths: Paths = field(default_factory=Paths)
    reference_only: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Validate :attr:`reference_only`."""
        check_families(self.reference_only, "reference_only")


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
