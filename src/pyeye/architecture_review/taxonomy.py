"""Seed taxonomy of architectural axes for PyEye architecture review.

This module is the single authoritative source for the 7 architectural axis
keys, their ranking **stakes bucket**, their (now-secondary) provisional stakes
prior, and their human-readable descriptions.  The skill, auditor, ranker, and
conformance tests all import from here so that axis keys never drift (the
failure mode documented in #374).

Stakes bucket (``AXIS_STAKES_BUCKET``) — the source of truth for ranking tier:
    This is an **explicit, reviewable map** from each seed axis to a discrete
    stakes tier (``"high" | "med" | "low"``).  It is the SOURCE OF TRUTH for
    ranking *dominance* (spec §11): the ranker tiers findings by this bucket
    first, so a higher-bucket finding always outranks a lower-bucket one
    REGARDLESS of blast.

    It is **deliberately NOT derived** from :data:`AXIS_STAKES_PRIOR` by
    thresholding.  Thresholding a provisional float was rejected (#492): it
    would make the dominance guarantee depend on the third decimal of a value
    §15 explicitly labels uncalibrated, so a routine prior nudge (e.g.
    ``0.9 → 0.79``) could silently re-tier a high-stakes axis to ``med`` and
    break dominance with nothing failing loudly.  Re-tiering an axis must
    therefore require an explicit edit to THIS map — a deliberate, reviewable
    design decision, NOT prior calibration.  The assignment is provisional
    (calibrate against real review data, §15), but the *act of assigning* is a
    design choice, not a derived value.

Provisional stakes priors (``AXIS_STAKES_PRIOR``) — within-bucket tiebreaker ONLY:
    These values are a **provisional default to be calibrated against real
    review data** (see spec §11 and §15).  Since #492 they are demoted to a
    **within-bucket tiebreaker only**: they give a finer ordering of findings
    that share BOTH a stakes bucket AND a blast value.  A prior NEVER determines
    tier and CANNOT affect dominance — recalibrating it can only reorder
    findings *inside* a bucket, where it is structurally incapable of crossing a
    bucket boundary.  Do not over-tune them now — wait until real audits produce
    feedback signal.

    Current provisional values (higher = higher stakes):

    - ``error_handling``: 0.9
    - ``validation_placement``: 0.9
    - ``layering``: 0.7
    - ``dependency_acquisition``: 0.6
    - ``module_boundaries``: 0.6
    - ``cross_cutting``: 0.5
    - ``naming_api_shape``: 0.3

Note:
    ``duplication`` is explicitly NOT an axis — it is tracked separately in
    issue #495.  It must never appear in this module.
"""

# ---------------------------------------------------------------------------
# Seed axes
# ---------------------------------------------------------------------------

# The 7 architectural axis keys, in canonical display order.
# All consumers (skill, auditor, conformance tests) must bind to this tuple
# rather than hard-coding the strings locally.
SEED_AXES: tuple[str, ...] = (
    "layering",
    "module_boundaries",
    "dependency_acquisition",
    "error_handling",
    "validation_placement",
    "naming_api_shape",
    "cross_cutting",
)

# ---------------------------------------------------------------------------
# Stakes bucket — the EXPLICIT source of truth for ranking tier (dominance)
# ---------------------------------------------------------------------------

# Explicit stakes bucket per axis: the SOURCE OF TRUTH for ranking dominance
# (spec §11).  The ranker tiers findings by this bucket first, so a higher
# bucket always outranks a lower one regardless of blast.
#
# This map is the thing to get right: it is NOT derived by thresholding the
# provisional AXIS_STAKES_PRIOR (that approach was rejected in #492 — see the
# module docstring — because it would let an uncalibrated float silently
# re-tier an axis and break dominance).  Editing an entry here is a DELIBERATE
# tier change, NOT calibration; re-tiering an axis must always be an explicit
# edit to this map.  The assignment is provisional (§15) but the act of
# assigning is a design decision, not a computed value.  There are NO threshold
# constants anywhere — by design.
AXIS_STAKES_BUCKET: dict[str, str] = {
    "error_handling": "high",
    "validation_placement": "high",
    "layering": "med",
    "dependency_acquisition": "med",
    "module_boundaries": "med",
    "cross_cutting": "med",
    "naming_api_shape": "low",
}

# Bucket → ordinal for the ranker to consume (higher = higher stakes, sorts
# first under descending order).  Findings whose axis is absent from
# AXIS_STAKES_BUCKET degrade honestly to "low" (see ranking.stakes_bucket).
_BUCKET_ORDER: dict[str, int] = {"high": 2, "med": 1, "low": 0}

# ---------------------------------------------------------------------------
# Provisional stakes priors — WITHIN-BUCKET TIEBREAKER ONLY (since #492)
# ---------------------------------------------------------------------------

# Provisional stakes prior for each axis, values in (0, 1].
# These are first-guess values — provisional and to be calibrated against
# real review data (spec §11/§15).  Higher values indicate higher correctness,
# security, or coupling risk.  Do not treat these as tuned constants.
#
# Demoted in #492 to a WITHIN-BUCKET TIEBREAKER ONLY: the prior is the FINAL
# ranking key, applied only to break blast ties among findings that already
# share a stakes bucket.  It NEVER determines tier and CANNOT affect dominance
# — recalibrating it can never re-tier an axis (re-tiering = editing
# AXIS_STAKES_BUCKET above).  Tier is owned solely by AXIS_STAKES_BUCKET.
AXIS_STAKES_PRIOR: dict[str, float] = {
    "layering": 0.7,
    "module_boundaries": 0.6,
    "dependency_acquisition": 0.6,
    "error_handling": 0.9,
    "validation_placement": 0.9,
    "naming_api_shape": 0.3,
    "cross_cutting": 0.5,
}

# ---------------------------------------------------------------------------
# Human descriptions
# ---------------------------------------------------------------------------

# One-line human description per axis, for the skill and human review loop.
AXIS_DESCRIPTIONS: dict[str, str] = {
    "layering": "Layering / dependency direction: which layers/packages may import which.",
    "module_boundaries": "Module & placement boundaries: where a *kind* of thing lives.",
    "dependency_acquisition": (
        "Dependency acquisition: constructor-injection vs import vs global/singleton."
    ),
    "error_handling": (
        "Error handling: raise vs return-sentinel vs result-type; exception types; where caught."
    ),
    "validation_placement": "Validation placement: at the boundary vs in core vs scattered.",
    "naming_api_shape": (
        "Naming & API shape: naming patterns, return-type conventions, sync/async split."
    ),
    "cross_cutting": "Cross-cutting access: logging, config, path handling.",
}
