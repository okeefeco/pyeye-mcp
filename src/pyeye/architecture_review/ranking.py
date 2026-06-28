"""Deterministic ranking for architecture-review findings.

Findings are ranked by **post-gate grade tier × (axis-stakes prior × blast-radius)**
so that high-stakes axes are never buried by findings that merely reference a
high-fanout hub.  The rank function is a *pure ordering*: it returns every input
finding exactly once (a permutation) — it never drops, filters, or truncates.

Grade vocabulary
----------------
``"mechanical_fact" | "deterministic_single" | "ambiguous" | "no_signal"``

Tier ordering (three tiers, top to bottom)
------------------------------------------
1. ``ambiguous`` — unconfirmed; escalate first.
2. ``deterministic_single``, ``mechanical_fact`` — confident findings.
3. ``no_signal`` — last.

Within each tier, findings are ordered by ``priors[axis] * finding_blast``
descending.  Ties preserve input order (Python's ``sorted`` is stable).

Unknown-axis handling
---------------------
If an axis is not present in *priors*, the floor value ``min(priors.values())``
is used.  This is explicit honest degradation — the axis is not silently treated
as zero (which would incorrectly bury it) nor as the maximum (which would
incorrectly escalate it).

Blast caveat
------------
``finding_blast`` returns the **max** of ``blast_fn(handle)`` over all handles.
This can over-rank a finding that merely *references* a high-fanout hub.
Blast is a proxy, not ground truth; combine with the stakes prior to mitigate.
"""

from collections.abc import Callable
from typing import Any

from pyeye.architecture_review.taxonomy import AXIS_STAKES_PRIOR

# Type alias for a single finding dict.  Fields:
#   axis: str, claim: str, grade: str, handles: list[str],
#   evidence: str, recommendation: str | None
Finding = dict[str, Any]

# Tier assignments: lower number = higher priority (sorts first).
_TIER: dict[str, int] = {
    "ambiguous": 0,
    "deterministic_single": 1,
    "mechanical_fact": 1,
    "no_signal": 2,
}

# Fallback tier for grades not in the vocabulary (treated as no_signal).
_TIER_FALLBACK = 2


def finding_blast(finding: Finding, blast_fn: Callable[[str], float]) -> float:
    """Return the blast-radius magnitude for *finding*.

    The magnitude is the **maximum** of ``blast_fn(handle)`` over all handles
    listed in ``finding["handles"]``.  For a finding with an empty handle list,
    returns ``0.0``.

    Note:
        Using the max can over-rank a finding that merely *references* a
        high-fanout hub rather than defining or owning it.  This is a known
        proxy limitation; the caller should combine blast with the axis-stakes
        prior to mitigate distortion.

    Args:
        finding: A finding dict with at least a ``"handles"`` key mapping to
            a list of canonical handle strings.
        blast_fn: A pure function mapping a handle string to its blast-radius
            magnitude (a non-negative float).

    Returns:
        The maximum blast magnitude across all handles, or ``0.0`` if the
        handle list is empty.
    """
    handles = finding.get("handles")
    if not handles:
        return 0.0
    return max(blast_fn(h) for h in handles)


def rank(
    findings: list[Finding],
    blast_fn: Callable[[str], float],
    priors: dict[str, float] = AXIS_STAKES_PRIOR,
) -> list[Finding]:
    """Return a stable, deterministic permutation of *findings* sorted by grade tier and score.

    **Ordering guarantee**: every input finding appears in the output exactly
    once.  A low-stakes axis can never remove a finding from view.

    **Tier split** (highest priority first):

    1. ``ambiguous`` — unconfirmed findings escalate first (most need attention).
    2. ``deterministic_single``, ``mechanical_fact`` — confident findings.
    3. ``no_signal`` — last (no actionable signal).

    **Within each tier**: ordered by ``priors[axis] * finding_blast(finding,
    blast_fn)`` descending.

    **Unknown-axis handling**: if *finding["axis"]* is absent from *priors*, the
    floor ``min(priors.values())`` is used so the finding is not silently buried
    (zero) nor incorrectly escalated (maximum).

    **Tie behaviour**: Python's ``sorted`` is stable, so findings with identical
    ``(tier, score)`` preserve their input order.

    Args:
        findings: List of finding dicts to rank.  Not mutated.
        blast_fn: Pure function mapping a handle string → blast-radius magnitude.
            Injected so this function stays pure and testable without pyeye calls.
        priors: Axis-stakes prior mapping.  Defaults to ``AXIS_STAKES_PRIOR``.
            Pass a custom dict to override per-project.

    Returns:
        A new list that is a permutation of *findings* in ranked order.
    """
    if not findings:
        return []

    floor = min(priors.values()) if priors else 0.0

    def _key(finding: Finding) -> tuple[int, float]:
        axis = finding.get("axis", "")
        grade = finding.get("grade", "")
        tier = _TIER.get(str(grade), _TIER_FALLBACK)
        prior = priors.get(str(axis), floor)
        score = prior * finding_blast(finding, blast_fn)
        # Return (tier_rank, -score): ascending tier_rank = highest priority first;
        # negated score so higher scores sort first within a tier.
        return (tier, -score)

    return sorted(findings, key=_key)
