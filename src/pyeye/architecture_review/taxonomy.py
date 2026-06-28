"""Seed taxonomy of architectural axes for PyEye architecture review.

This module is the single authoritative source for the 7 architectural axis
keys, their provisional stakes priors, and their human-readable descriptions.
The skill, auditor, ranker, and conformance tests all import from here so that
axis keys never drift (the failure mode documented in #374).

Provisional stakes priors (``AXIS_STAKES_PRIOR``):
    These values are a **provisional default to be calibrated against real
    review data** (see spec §11 and §15).  They encode rough relative stakes
    (correctness / security / coupling risk) at first-guess granularity.
    Do not over-tune them now — wait until real audits produce feedback signal.

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
# Provisional stakes priors
# ---------------------------------------------------------------------------

# Provisional stakes prior for each axis, values in (0, 1].
# These are first-guess values — provisional and to be calibrated against
# real review data (spec §11/§15).  Higher values indicate higher correctness,
# security, or coupling risk.  Do not treat these as tuned constants.
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
