"""The shared completeness vocabulary: every truncation reason, its class and its recovery (#435).

Every primitive that can return a bounded answer says so with a truncation
reason. Before #435 each primitive kept its own list (``trace``'s, ``outline``'s,
the linter's copy of each), so a new reason could ship in one place and not the
others. :data:`TRUNCATION_REASONS` is now the one table: the code reads its
names from it, the conformance linter derives its closed sets from it, and a
conformance test checks the tool descriptions and the ``python-explore`` skill
list exactly its reasons.

Each reason belongs to one class, which tells an agent how to recover:

- **budget** — a cap the caller set (or its default) was hit. Recovery: raise the
  limit. A per-node budget truncation carries the edge-named count of what it
  withheld (``member_count`` / ``submodule_count``), so the agent knows how much.
- **boundary** — outside this view by design, not a lost result. Recovery: call
  again on that node. No count: one would cost a walk per node.
- **unmeasured** — pyeye could not measure it at all (e.g. a file the server's
  Python can't parse). Recovery: read the source, or change the environment.

All fields here are additive in 2.x: shapes keep their existing names
(``trace``'s result-level ``truncation_reasons`` list, ``outline``'s per-node
``truncation_reason`` string).
"""

from __future__ import annotations

from dataclasses import dataclass

BUDGET = "budget"
BOUNDARY = "boundary"
UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class TruncationReason:
    """One truncation reason: its class, how to recover, and which tools emit it."""

    name: str
    cls: str
    recovery: str
    emitted_by: frozenset[str]


def _reason(name: str, cls: str, recovery: str, *emitted_by: str) -> TruncationReason:
    return TruncationReason(name, cls, recovery, frozenset(emitted_by))


#: Every truncation reason any primitive emits, by name.
TRUNCATION_REASONS: dict[str, TruncationReason] = {
    r.name: r
    for r in (
        _reason(
            "max_depth",
            BUDGET,
            "Raise max_depth, or outline/trace from that node.",
            "outline",
            "trace",
        ),
        _reason(
            "max_nodes",
            BUDGET,
            "Raise max_nodes, or start from a narrower handle.",
            "outline",
            "trace",
        ),
        _reason(
            "external",
            BOUNDARY,
            "Outline that external node directly; pyeye walks one level into external code.",
            "outline",
        ),
        _reason(
            "survey_leaf",
            BOUNDARY,
            "Outline that module to see its members; a package survey lists modules only.",
            "outline",
        ),
    )
}

MAX_DEPTH = TRUNCATION_REASONS["max_depth"].name
MAX_NODES = TRUNCATION_REASONS["max_nodes"].name
EXTERNAL = TRUNCATION_REASONS["external"].name
SURVEY_LEAF = TRUNCATION_REASONS["survey_leaf"].name


def reasons_emitted_by(tool: str) -> frozenset[str]:
    """The truncation reasons *tool* (``"outline"``, ``"trace"`` …) may emit."""
    return frozenset(name for name, r in TRUNCATION_REASONS.items() if tool in r.emitted_by)


def reasons_of_class(cls: str) -> frozenset[str]:
    """The truncation reasons in class *cls* (:data:`BUDGET`, :data:`BOUNDARY`, …)."""
    return frozenset(name for name, r in TRUNCATION_REASONS.items() if r.cls == cls)
