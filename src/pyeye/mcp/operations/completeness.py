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
- **unmeasured** — pyeye could not measure it at all: ``unparseable``, a file the
  server's Python can't parse (#703). Recovery: read the source, or change the
  environment. No count: nothing was measured.

All fields here are additive in 2.x: shapes keep their existing names
(``trace``'s result-level ``truncation_reasons`` list, ``outline``'s per-node
``truncation_reason`` string).

**Leave out, never false** (the user's call on #435): a result-level summary
added in or after #435 is absent when nothing was cut and fully present when a
cap cut — ``truncation_reasons`` on ``outline``; ``truncated: true`` +
``truncation_reasons`` + ``total`` on the capped ``expand`` / ``resolve``
results.  ``truncated: false`` never appears on them.  The one exception is
``trace``, whose result-level ``truncated`` (always present, a bool) and
``truncation_reasons`` (always present, possibly ``[]``) shipped before #435;
removing a key is barred in 2.x, so ``trace`` keeps them as they are.
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
        _reason(
            "unparseable",
            UNMEASURED,
            "Read the file, or run pyeye on a newer Python; the server's interpreter "
            "can't parse it (#703).",
            "outline",
        ),
    )
}

MAX_DEPTH = TRUNCATION_REASONS["max_depth"].name
MAX_NODES = TRUNCATION_REASONS["max_nodes"].name
EXTERNAL = TRUNCATION_REASONS["external"].name
SURVEY_LEAF = TRUNCATION_REASONS["survey_leaf"].name
UNPARSEABLE = TRUNCATION_REASONS["unparseable"].name


def reasons_emitted_by(tool: str) -> frozenset[str]:
    """The truncation reasons *tool* (``"outline"``, ``"trace"`` …) may emit."""
    return frozenset(name for name, r in TRUNCATION_REASONS.items() if tool in r.emitted_by)


def reasons_of_class(cls: str) -> frozenset[str]:
    """The truncation reasons in class *cls* (:data:`BUDGET`, :data:`BOUNDARY`, …)."""
    return frozenset(name for name, r in TRUNCATION_REASONS.items() if r.cls == cls)
