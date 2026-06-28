"""Tests for pyeye.architecture_review.ranking — deterministic ranking substrate.

Covers (bucketed-lexicographic, explicit-bucket-map form — #492):
- Dominance by construction: a high-stakes leaf (blast 0) outranks a low-stakes
  hub (high blast), same grade-tier (the dogfood scenario the product failed).
- Dominance is independent of the prior VALUES: mutating priors within a bucket
  cannot re-tier — the explicit AXIS_STAKES_BUCKET map owns tier (the key new
  guarantee the threshold approach could not give).
- Bucket dominance regardless of blast (med-bucket high-blast below high-bucket
  low-blast).
- Within-bucket blast ordering (blast descending inside a bucket).
- Override via the bucket map (custom buckets re-tier an axis).
- Ordering-only invariant (rank is a permutation, never drops findings).
- Tier precedence (ambiguous before deterministic_single/mechanical_fact before
  no_signal).
- Unknown-axis floor behavior (unlisted axes → low bucket, never raise).
- Stable tie-breaking (equal keys preserve input order).
"""

from collections.abc import Callable

from pyeye.architecture_review.ranking import finding_blast, rank, stakes_bucket
from pyeye.architecture_review.taxonomy import (
    AXIS_STAKES_BUCKET,
    AXIS_STAKES_PRIOR,
    SEED_AXES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(
    axis: str,
    grade: str,
    handles: list[str] | None = None,
    claim: str = "some claim",
) -> dict[str, object]:
    """Build a minimal finding dict for test use."""
    return {
        "axis": axis,
        "claim": claim,
        "grade": grade,
        "handles": handles if handles is not None else [],
        "evidence": "test evidence",
        "recommendation": None,
    }


def _blast_map(m: dict[str, float]) -> Callable[[str], float]:
    """Return a blast_fn backed by a dict; unknown handles return 0.0."""

    def _fn(handle: str) -> float:
        return m.get(handle, 0.0)

    return _fn


# ---------------------------------------------------------------------------
# finding_blast
# ---------------------------------------------------------------------------


class TestFindingBlast:
    def test_empty_handles_returns_zero(self) -> None:
        blast_fn = _blast_map({})
        finding = _finding("layering", "deterministic_single", handles=[])
        assert finding_blast(finding, blast_fn) == 0.0

    def test_single_handle(self) -> None:
        blast_fn = _blast_map({"pyeye.server": 5.0})
        finding = _finding("layering", "deterministic_single", handles=["pyeye.server"])
        assert finding_blast(finding, blast_fn) == 5.0

    def test_max_over_handles(self) -> None:
        """finding_blast returns the max — may over-rank a finding that merely references a hub."""
        blast_fn = _blast_map({"a": 1.0, "b": 10.0, "c": 3.0})
        finding = _finding("layering", "deterministic_single", handles=["a", "b", "c"])
        assert finding_blast(finding, blast_fn) == 10.0

    def test_unknown_handles_return_zero(self) -> None:
        blast_fn = _blast_map({"known": 4.0})
        finding = _finding("layering", "deterministic_single", handles=["unknown"])
        assert finding_blast(finding, blast_fn) == 0.0


# ---------------------------------------------------------------------------
# stakes_bucket — reads the explicit map, never thresholds a prior
# ---------------------------------------------------------------------------


class TestStakesBucket:
    def test_high_axis_is_ordinal_2(self) -> None:
        assert stakes_bucket("validation_placement") == 2
        assert stakes_bucket("error_handling") == 2

    def test_med_axis_is_ordinal_1(self) -> None:
        assert stakes_bucket("layering") == 1
        assert stakes_bucket("dependency_acquisition") == 1

    def test_low_axis_is_ordinal_0(self) -> None:
        assert stakes_bucket("naming_api_shape") == 0

    def test_unknown_axis_floors_to_low(self) -> None:
        """An axis absent from the bucket map degrades to low (0), never raises."""
        assert stakes_bucket("totally_unknown_axis") == 0

    def test_custom_buckets_retier(self) -> None:
        """A custom bucket map re-tiers — the source of truth for tier is the map."""
        custom = {**AXIS_STAKES_BUCKET, "naming_api_shape": "high"}
        assert stakes_bucket("naming_api_shape", custom) == 2


# ---------------------------------------------------------------------------
# Ordering-only invariant (permutation property)
# ---------------------------------------------------------------------------


class TestOrderingOnly:
    def test_rank_returns_all_findings_empty(self) -> None:
        blast_fn = _blast_map({})
        result = rank([], blast_fn)
        assert result == []

    def test_rank_is_permutation_single(self) -> None:
        findings = [_finding("layering", "ambiguous")]
        blast_fn = _blast_map({})
        result = rank(findings, blast_fn)
        assert len(result) == 1
        assert result[0] is findings[0]

    def test_rank_is_permutation_multiple(self) -> None:
        """rank(xs) must be a permutation: same multiset by identity, no drops."""
        findings = [
            _finding("layering", "deterministic_single", handles=["h1"]),
            _finding("error_handling", "ambiguous", handles=["h2"]),
            _finding("naming_api_shape", "no_signal"),
            _finding("module_boundaries", "mechanical_fact", handles=["h3"]),
        ]
        blast_fn = _blast_map({"h1": 5.0, "h2": 3.0, "h3": 1.0})
        result = rank(findings, blast_fn)
        assert len(result) == len(findings)
        # identity membership: every input finding appears exactly once
        for f in findings:
            assert f in result
        assert {id(r) for r in result} == {id(f) for f in findings}

    def test_rank_preserves_no_signal_findings(self) -> None:
        """Even no_signal findings must appear in result (ordering-only, no drop)."""
        findings = [
            _finding("naming_api_shape", "no_signal"),
            _finding("cross_cutting", "deterministic_single"),
        ]
        blast_fn = _blast_map({})
        result = rank(findings, blast_fn)
        assert len(result) == 2
        no_signal_ids = {id(f) for f in findings if f["grade"] == "no_signal"}
        result_ids = {id(r) for r in result}
        assert no_signal_ids.issubset(result_ids)


# ---------------------------------------------------------------------------
# Dominance by construction (the dogfood scenario the product failed)
# ---------------------------------------------------------------------------


class TestDominanceByConstruction:
    """A high-stakes finding must outrank a low-stakes one REGARDLESS of blast."""

    def test_high_stakes_leaf_beats_low_stakes_hub_blast_zero(self) -> None:
        """validation_placement (high bucket) with blast 0 outranks
        naming_api_shape (low bucket) with blast 9, same grade-tier.

        This is the exact case the ``prior × blast`` PRODUCT failed: with
        blast 0 the product was 0 for ANY prior, burying the high-stakes leaf.
        Under bucketed-lexicographic the high bucket dominates by construction.
        """
        high_stakes_leaf = _finding(
            "validation_placement",  # high bucket
            "deterministic_single",
            handles=["leaf"],  # blast 0
        )
        low_stakes_hub = _finding(
            "naming_api_shape",  # low bucket
            "deterministic_single",
            handles=["hub"],  # blast 9
        )
        blast_fn = _blast_map({"leaf": 0.0, "hub": 9.0})

        # Confirm blast-alone (and the old product) would invert.
        assert finding_blast(high_stakes_leaf, blast_fn) == 0.0
        assert finding_blast(low_stakes_hub, blast_fn) == 9.0

        result = rank([low_stakes_hub, high_stakes_leaf], blast_fn)
        assert result[0]["axis"] == "validation_placement"
        assert result[1]["axis"] == "naming_api_shape"

    def test_dominance_independent_of_prior_values(self) -> None:
        """The KEY new guarantee: mutating prior VALUES cannot re-tier.

        Pass priors where validation_placement is set BELOW naming_api_shape.
        Under the rejected ``prior × blast`` product (or a thresholded-prior
        bucket) that float swing would flip the order.  Here the EXPLICIT
        AXIS_STAKES_BUCKET map still tiers validation=high, naming=low, so
        validation STILL outranks naming — the float is structurally incapable
        of crossing a bucket boundary.
        """
        high_stakes = _finding(
            "validation_placement",  # high bucket
            "deterministic_single",
            handles=["leaf"],
        )
        low_stakes = _finding(
            "naming_api_shape",  # low bucket
            "deterministic_single",
            handles=["hub"],
        )
        blast_fn = _blast_map({"leaf": 0.0, "hub": 9.0})

        # Priors INVERTED relative to stakes: validation LOWER than naming.
        inverted_priors = {
            **AXIS_STAKES_PRIOR,
            "validation_placement": 0.01,
            "naming_api_shape": 0.99,
        }
        result = rank([low_stakes, high_stakes], blast_fn, priors=inverted_priors)
        # Bucket map (not the prior) owns tier → validation still first.
        assert result[0]["axis"] == "validation_placement"
        assert result[1]["axis"] == "naming_api_shape"

    def test_med_bucket_high_blast_below_high_bucket_low_blast(self) -> None:
        """A med-bucket finding with very high blast ranks BELOW a high-bucket
        finding with low/zero blast, same grade-tier."""
        med_high_blast = _finding(
            "dependency_acquisition",  # med bucket
            "deterministic_single",
            handles=["hub"],  # blast 1000
        )
        high_low_blast = _finding(
            "error_handling",  # high bucket
            "deterministic_single",
            handles=["leaf"],  # blast 0
        )
        blast_fn = _blast_map({"hub": 1000.0, "leaf": 0.0})
        result = rank([med_high_blast, high_low_blast], blast_fn)
        assert result[0]["axis"] == "error_handling"
        assert result[1]["axis"] == "dependency_acquisition"


# ---------------------------------------------------------------------------
# Within-bucket ordering: blast descending, then prior tiebreak
# ---------------------------------------------------------------------------


class TestWithinBucketOrdering:
    def test_within_bucket_blast_descending(self) -> None:
        """Two same-bucket findings order by blast descending."""
        high_blast = _finding("error_handling", "deterministic_single", handles=["a"])
        low_blast = _finding("validation_placement", "deterministic_single", handles=["b"])
        # both high bucket; blast a=10 > b=2
        blast_fn = _blast_map({"a": 10.0, "b": 2.0})
        result = rank([low_blast, high_blast], blast_fn)
        assert result[0]["axis"] == "error_handling"
        assert result[1]["axis"] == "validation_placement"

    def test_prior_breaks_blast_ties_within_bucket(self) -> None:
        """When same bucket AND same blast, the prior is the final tiebreaker.

        error_handling (prior 0.9) and validation_placement (prior 0.9) are both
        high; give validation a higher prior so it wins the tie.
        """
        eh = _finding("error_handling", "deterministic_single", handles=["h"], claim="eh")
        vp = _finding("validation_placement", "deterministic_single", handles=["h"], claim="vp")
        blast_fn = _blast_map({"h": 5.0})  # identical blast
        priors = {**AXIS_STAKES_PRIOR, "validation_placement": 0.95, "error_handling": 0.90}
        result = rank([eh, vp], blast_fn, priors=priors)
        assert result[0]["claim"] == "vp"
        assert result[1]["claim"] == "eh"


# ---------------------------------------------------------------------------
# Tier precedence (grade-tier is the TOP-LEVEL split)
# ---------------------------------------------------------------------------


class TestTierPrecedence:
    def test_ambiguous_before_deterministic_single_regardless_of_bucket_blast(self) -> None:
        """ambiguous tier always sorts above deterministic_single/mechanical_fact,
        even when the confident finding has a higher bucket AND blast."""
        confident = _finding("error_handling", "deterministic_single", handles=["hub"])
        uncertain = _finding("naming_api_shape", "ambiguous", handles=["leaf"])
        blast_fn = _blast_map({"hub": 100.0, "leaf": 1.0})
        result = rank([confident, uncertain], blast_fn)
        assert result[0]["grade"] == "ambiguous"
        assert result[1]["grade"] == "deterministic_single"

    def test_ambiguous_before_mechanical_fact(self) -> None:
        confident = _finding("error_handling", "mechanical_fact", handles=["hub"])
        uncertain = _finding("naming_api_shape", "ambiguous", handles=["leaf"])
        blast_fn = _blast_map({"hub": 100.0, "leaf": 1.0})
        result = rank([confident, uncertain], blast_fn)
        assert result[0]["grade"] == "ambiguous"
        assert result[1]["grade"] == "mechanical_fact"

    def test_no_signal_always_last(self) -> None:
        """no_signal grade sorts below ambiguous AND deterministic_single."""
        ns = _finding("validation_placement", "no_signal", handles=["hub"])
        conf = _finding("naming_api_shape", "deterministic_single", handles=["leaf"])
        unc = _finding("layering", "ambiguous", handles=["node"])
        blast_fn = _blast_map({"hub": 1000.0, "leaf": 1.0, "node": 1.0})
        result = rank([ns, conf, unc], blast_fn)
        assert result[-1]["grade"] == "no_signal"

    def test_no_signal_last_even_alone(self) -> None:
        """Single no_signal finding is returned (permutation), just at the back."""
        ns = _finding("error_handling", "no_signal")
        blast_fn = _blast_map({})
        result = rank([ns], blast_fn)
        assert len(result) == 1
        assert result[0]["grade"] == "no_signal"


# ---------------------------------------------------------------------------
# Per-project override via the bucket map (the new tier source of truth)
# ---------------------------------------------------------------------------


class TestCustomBucketsOverride:
    def test_raising_naming_api_shape_retiers_it(self) -> None:
        """A custom bucket map that lifts naming_api_shape → high re-tiers it,
        so it now ranks among high-bucket findings — proves bucket overridability."""
        naming = _finding("naming_api_shape", "deterministic_single", handles=["leaf"])
        validation = _finding("validation_placement", "deterministic_single", handles=["hub"])
        blast_fn = _blast_map({"leaf": 1.0, "hub": 1.0})

        # Default: both differ by bucket — validation (high) above naming (low).
        default_result = rank([naming, validation], blast_fn)
        assert default_result[0]["axis"] == "validation_placement"
        assert default_result[1]["axis"] == "naming_api_shape"

        # Custom buckets: naming → high (now same bucket as validation), and a
        # higher blast on naming's leaf so it leads within the shared bucket.
        custom_buckets = {**AXIS_STAKES_BUCKET, "naming_api_shape": "high"}
        blast_fn2 = _blast_map({"leaf": 5.0, "hub": 1.0})
        custom_result = rank([validation, naming], blast_fn2, buckets=custom_buckets)
        assert custom_result[0]["axis"] == "naming_api_shape"
        assert custom_result[1]["axis"] == "validation_placement"

    def test_custom_buckets_still_permutation(self) -> None:
        """Custom buckets must not cause drops."""
        findings = [
            _finding("layering", "ambiguous"),
            _finding("naming_api_shape", "deterministic_single"),
        ]
        blast_fn = _blast_map({})
        custom = {**AXIS_STAKES_BUCKET, "naming_api_shape": "high"}
        result = rank(findings, blast_fn, buckets=custom)
        assert len(result) == 2
        assert {id(r) for r in result} == {id(f) for f in findings}


# ---------------------------------------------------------------------------
# Unknown-axis floor behavior
# ---------------------------------------------------------------------------


class TestUnknownAxisFloor:
    def test_unknown_axis_does_not_raise(self) -> None:
        """An axis not in the bucket map must not raise."""
        finding = _finding("totally_unknown_axis", "deterministic_single", handles=["h"])
        blast_fn = _blast_map({"h": 5.0})
        result = rank([finding], blast_fn)
        assert len(result) == 1
        assert result[0] is finding

    def test_every_seed_axis_is_explicitly_bucketed(self) -> None:
        """Every audited seed axis must be DELIBERATELY mapped in AXIS_STAKES_BUCKET.

        Placed right next to the unknown-axis floor test on purpose: that test
        proves graceful degradation (an unlisted axis sinks to ``low`` rather than
        raising) — which is exactly what would let a REAL seed axis that is missing
        from the bucket map silently drop to the bottom of its grade-tier with no
        error.  This coverage assertion converts that silent sink into a LOUD
        failure: an omitted seed axis fails here instead of being quietly buried.
        (Belt-and-suspenders with the conformance suite's equivalent guard.)
        """
        assert set(SEED_AXES) == set(AXIS_STAKES_BUCKET), (
            f"every seed axis must be explicitly bucketed: "
            f"SEED_AXES {sorted(SEED_AXES)} != AXIS_STAKES_BUCKET {sorted(AXIS_STAKES_BUCKET)}"
        )

    def test_unknown_axis_is_permutation(self) -> None:
        """rank with an unknown axis still returns every input finding."""
        findings = [
            _finding("mystery_axis", "deterministic_single", handles=["h"]),
            _finding("layering", "deterministic_single", handles=["h"]),
        ]
        blast_fn = _blast_map({"h": 1.0})
        result = rank(findings, blast_fn)
        assert len(result) == 2
        assert {id(r) for r in result} == {id(f) for f in findings}

    def test_unknown_axis_lands_in_low_bucket(self) -> None:
        """Unknown axis → low bucket, so it ranks below a med-bucket finding,
        same grade-tier, regardless of blast."""
        unknown = _finding("mystery_axis", "deterministic_single", handles=["h"], claim="unknown")
        med = _finding("layering", "deterministic_single", handles=["leaf"], claim="med")
        blast_fn = _blast_map({"h": 100.0, "leaf": 0.0})
        result = rank([unknown, med], blast_fn)
        # layering is med (1) > mystery_axis low (0) → med first despite lower blast
        assert result[0]["claim"] == "med"
        assert result[1]["claim"] == "unknown"


# ---------------------------------------------------------------------------
# Tie-breaking: stable sort preserves input order
# ---------------------------------------------------------------------------


class TestStableSort:
    def test_equal_key_preserves_input_order(self) -> None:
        """When two findings have identical tier/bucket/blast/prior, input order
        is preserved (stable)."""
        f1 = _finding("layering", "deterministic_single", handles=["h"], claim="first")
        f2 = _finding("layering", "deterministic_single", handles=["h"], claim="second")
        blast_fn = _blast_map({"h": 3.0})
        result = rank([f1, f2], blast_fn)
        assert result[0] is f1
        assert result[1] is f2
