"""Deterministic ranking for architecture-review findings.

Findings are ranked **bucketed-lexicographically within each grade tier**: a
discrete *stakes bucket* (read from the EXPLICIT :data:`AXIS_STAKES_BUCKET` map)
is the primary key, *blast-radius magnitude* is the secondary key that orders
findings only **within** a bucket, and the (now-secondary) *stakes prior* is the
final within-bucket tiebreaker.  The rank function is a *pure ordering*: it
returns every input finding exactly once (a permutation) — it never drops,
filters, or truncates.

Why bucketed-lexicographic, not a product (spec §11, bet-3)
-----------------------------------------------------------
Bet-3 is a **dominance** requirement: *the axis carries the stakes; blast only
the reach* — a high-stakes finding must outrank a low-stakes finding **regardless
of blast**.  A ``prior * blast`` PRODUCT cannot guarantee this: a large enough
blast on a low-stakes item always overtakes a high-stakes low-blast item, and in
the degenerate case ``blast == 0`` the product is ``0`` for ANY prior — so a
high-stakes finding on a leaf collapses to the bottom and prior recalibration is
structurally inert.  Using a discrete stakes bucket as the PRIMARY sort key,
with blast ordering only WITHIN the bucket, delivers dominance by construction:
every ``high`` finding precedes every ``med`` then ``low`` finding regardless of
blast.

Why an EXPLICIT bucket map, not thresholded priors (#492)
---------------------------------------------------------
"Dominance by construction" means the buckets are an **explicit construct** —
the :data:`AXIS_STAKES_BUCKET` map in :mod:`pyeye.architecture_review.taxonomy`
is the SOURCE OF TRUTH for tier.  The buckets are **deliberately not** derived
by thresholding :data:`AXIS_STAKES_PRIOR`: thresholding would make the dominance
guarantee depend on the third decimal of a value §15 explicitly labels
uncalibrated, so a routine prior nudge (``0.9 → 0.79``) could silently re-tier a
high-stakes axis and break dominance with nothing failing loudly.  There are
therefore **NO threshold constants** here.  Re-tiering an axis requires an
explicit, reviewable edit to the bucket map — never a prior tweak.

Role of the prior now: within-bucket tiebreaker ONLY
----------------------------------------------------
:data:`AXIS_STAKES_PRIOR` is demoted to the **final** ranking key — it breaks
blast ties among findings that already share a stakes bucket.  It NEVER
determines tier and CANNOT cross a bucket boundary, so a §15 prior recalibration
can only reorder findings *inside* a bucket: it is structurally incapable of
violating dominance.

Tradeoff (this inverts the earlier product framing)
---------------------------------------------------
Lexicographic ordering **fully trusts the bucket assignment** — blast can no
longer rescue a mis-bucketed finding.  So the explicit per-axis bucket map is
**load-bearing**, and getting it right (spec §15 calibration of the *bucket
map*, not the prior) is a hard dependency of trusting queue position, NOT
optional polish.  Calibrating the *prior* now only affects within-bucket
tiebreaking, never tier.

Grade vocabulary
----------------
``"mechanical_fact" | "deterministic_single" | "ambiguous" | "no_signal"``

Tier ordering (top-level split, three tiers, top to bottom)
-----------------------------------------------------------
1. ``ambiguous`` — unconfirmed; escalate first.
2. ``deterministic_single``, ``mechanical_fact`` — confident findings.
3. ``no_signal`` — last.

The grade tier is the TOP-LEVEL split; bucketed-lexicographic is the WITHIN-tier
ordering.

Unknown-axis handling
---------------------
If an axis is not present in *buckets* (e.g. an open, non-seed axis the auditor
surfaced), it degrades to the ``low`` bucket (ordinal ``0``) — never raises.
This is explicit honest degradation: the axis is not silently escalated.  Its
prior tiebreak similarly falls to the floor ``min(priors.values())``.

Blast caveat
------------
``finding_blast`` returns the **max** of ``blast_fn(handle)`` over all handles.
This can over-rank a finding that merely *references* a high-fanout hub.  Blast
is a proxy for *reach*, not ground truth and not correctness; it only orders
findings WITHIN a stakes bucket and can never cross a bucket boundary.
"""

from collections.abc import Callable
from typing import Any

from pyeye.architecture_review.taxonomy import (
    _BUCKET_ORDER,
    AXIS_STAKES_BUCKET,
    AXIS_STAKES_PRIOR,
)

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

# Lowest bucket ordinal — the honest-degradation floor for an axis absent from
# the explicit bucket map.
_BUCKET_LOW = _BUCKET_ORDER["low"]


def stakes_bucket(axis: str, buckets: dict[str, str] = AXIS_STAKES_BUCKET) -> int:
    """Return the discrete stakes-bucket ordinal for *axis*.

    The bucket is read from the EXPLICIT :data:`AXIS_STAKES_BUCKET` map (the
    source of truth for ranking tier) and mapped to an ordinal:

    - ``high`` → ``2``
    - ``med`` → ``1``
    - ``low`` → ``0``

    There is **no thresholding of the prior** — re-tiering an axis is an explicit
    edit to the bucket map, never a prior tweak (#492).

    Unknown-axis handling:
        If *axis* is absent from *buckets* (e.g. an open, non-seed axis the
        auditor surfaced), it degrades to the ``low`` bucket (``0``) rather than
        raising.  Honest degradation: the axis is never silently escalated.

    Args:
        axis: The finding's architectural axis key.
        buckets: Axis → bucket (``"high" | "med" | "low"``) mapping.  Defaults
            to :data:`AXIS_STAKES_BUCKET`.  Pass a custom dict to re-tier
            per-project (e.g. to lift ``naming_api_shape`` into ``"high"`` for
            an API-name-driven library — a one-line override, not a fork).

    Returns:
        The bucket ordinal: ``2`` (high), ``1`` (med), or ``0`` (low).  Higher
        ordinals are higher stakes.
    """
    label = buckets.get(axis)
    if label is None:
        return _BUCKET_LOW
    return _BUCKET_ORDER.get(label, _BUCKET_LOW)


def finding_blast(finding: Finding, blast_fn: Callable[[str], float]) -> float:
    """Return the blast-radius magnitude for *finding*.

    The magnitude is the **maximum** of ``blast_fn(handle)`` over all handles
    listed in ``finding["handles"]``.  For a finding with an empty handle list,
    returns ``0.0``.

    Note:
        Using the max can over-rank a finding that merely *references* a
        high-fanout hub rather than defining or owning it.  This is a known
        proxy limitation; blast is the SECONDARY sort key only and orders
        findings WITHIN a stakes bucket — it can never cross a bucket boundary
        (spec §11), so this distortion is bounded to within-bucket order.

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
    buckets: dict[str, str] = AXIS_STAKES_BUCKET,
    priors: dict[str, float] = AXIS_STAKES_PRIOR,
) -> list[Finding]:
    """Return a stable, deterministic permutation of *findings*, bucketed-lexicographically.

    **Ordering guarantee**: every input finding appears in the output exactly
    once.  A low-stakes axis can never remove a finding from view (ordering-only;
    spec §11 constraint 2).

    **Tier split** (top-level, highest priority first):

    1. ``ambiguous`` — unconfirmed findings escalate first (most need attention).
    2. ``deterministic_single``, ``mechanical_fact`` — confident findings.
    3. ``no_signal`` — last (no actionable signal).

    **Within each tier — bucketed-lexicographic**: ordered by
    ``(stakes_bucket(axis, buckets), finding_blast(finding, blast_fn),
    prior_tiebreak)`` DESCENDING.  The stakes bucket (from the EXPLICIT
    :data:`AXIS_STAKES_BUCKET` map) is the PRIMARY key, so every ``high``-bucket
    finding precedes every ``med`` then ``low`` finding REGARDLESS of blast
    (dominance by construction, spec §11 bet-3).  Blast is the SECONDARY key —
    it orders findings only WITHIN a bucket.  The stakes prior
    (``prior_tiebreak``) is the FINAL key — it breaks blast ties INSIDE a bucket
    and can NEVER cross a bucket boundary.  There is no ``prior * blast``
    product and no threshold constant anywhere.

    **Unknown-axis handling**: if *finding["axis"]* is absent from *buckets*, it
    degrades to the ``low`` bucket (and its prior tiebreak to the floor
    ``min(priors.values())``), so the finding is not silently escalated, and
    never raises.

    **Tie behaviour**: Python's ``sorted`` is stable, so findings with identical
    ``(tier, bucket, blast, prior)`` preserve their input order.

    Honesty note:
        Ranking is **not** correctness — it is attention-order only and fully
        reversible.  The bucket map is the explicit, per-project-overridable
        SOURCE OF TRUTH for tier; the prior is a within-bucket tiebreaker only.
        Both are provisional (spec §15).  Under bucketed-lexicographic ordering
        the bucket map is load-bearing (blast cannot rescue a mis-bucketed
        finding), so calibrating IT is a hard dependency of trusting queue
        position; a §15 prior recalibration, by contrast, can NEVER re-tier an
        axis (re-tiering = editing the bucket map).

    Args:
        findings: List of finding dicts to rank.  Not mutated.
        blast_fn: Pure function mapping a handle string → blast-radius magnitude.
            Injected so this function stays pure and testable without pyeye calls.
        buckets: Axis → bucket (``"high" | "med" | "low"``) mapping.  Defaults to
            :data:`AXIS_STAKES_BUCKET`.  Pass a custom dict to re-tier an axis
            per-project — this is the overridable SOURCE OF TRUTH for tier.
        priors: Axis-stakes prior mapping.  Defaults to :data:`AXIS_STAKES_PRIOR`.
            A within-bucket tiebreaker only; overriding it cannot change tier.

    Returns:
        A new list that is a permutation of *findings* in ranked order.
    """
    if not findings:
        return []

    prior_floor = min(priors.values()) if priors else 0.0

    def _key(finding: Finding) -> tuple[int, int, float, float]:
        axis = str(finding.get("axis", ""))
        grade = str(finding.get("grade", ""))
        tier = _TIER.get(grade, _TIER_FALLBACK)
        bucket = stakes_bucket(axis, buckets)
        blast = finding_blast(finding, blast_fn)
        prior_tiebreak = priors.get(axis, prior_floor)
        # Ascending tier (lower = higher priority first); negated bucket, blast,
        # and prior so higher stakes-bucket sorts first, then higher blast
        # WITHIN the bucket, then higher prior as the final within-bucket tie
        # breaker.  Bucket is primary; blast strictly secondary; prior strictly
        # tertiary — neither blast nor prior can cross a bucket boundary.
        return (tier, -bucket, -blast, -prior_tiebreak)

    return sorted(findings, key=_key)
