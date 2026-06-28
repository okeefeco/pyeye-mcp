"""Tests for pyeye.architecture_review.ranking — deterministic ranking substrate.

Covers:
- Proxy-inversion fix (prior × blast beats blast-alone)
- Ordering-only invariant (rank is a permutation, never drops findings)
- Tier precedence (ambiguous before deterministic_single/mechanical_fact before no_signal)
- Per-project override (custom priors flip ordering)
- Unknown-axis floor behavior (unlisted axes use min-prior floor, never raise)
- Stable tie-breaking (equal scores preserve input order)
"""

from collections.abc import Callable

from pyeye.architecture_review.ranking import finding_blast, rank
from pyeye.architecture_review.taxonomy import AXIS_STAKES_PRIOR

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
# Proxy-inversion fix: prior × blast beats blast-alone
# ---------------------------------------------------------------------------


class TestProxyInversion:
    """Blast-alone ranking inverts stakes.  prior × blast ranking fixes it."""

    def test_high_stakes_beats_high_blast(self) -> None:
        """validation_placement (prior=0.9, blast=2.0) must rank above
        naming_api_shape (prior=0.3, blast=4.0).

        Score math:
          prior × blast for validation_placement = 0.9 * 2.0 = 1.8
          prior × blast for naming_api_shape     = 0.3 * 4.0 = 1.2
          → validation_placement wins.

        Blast-alone would invert: 4.0 > 2.0 → naming_api_shape first (the bug).
        Both findings are in the same tier (deterministic_single) so the test
        isolates the prior × blast effect, not the tier split.
        """
        low_stakes = _finding(
            "naming_api_shape",  # prior = 0.3
            "deterministic_single",
            handles=["big_hub"],  # blast = 4.0
        )
        high_stakes = _finding(
            "validation_placement",  # prior = 0.9
            "deterministic_single",
            handles=["small_node"],  # blast = 2.0
        )
        blast_fn = _blast_map({"big_hub": 4.0, "small_node": 2.0})

        # Confirm blast-alone would invert
        assert blast_fn("big_hub") > blast_fn("small_node")

        result = rank([low_stakes, high_stakes], blast_fn)
        # prior × blast: 0.9*2.0=1.8 > 0.3*4.0=1.2 → validation_placement first
        assert result[0]["axis"] == "validation_placement"
        assert result[1]["axis"] == "naming_api_shape"

    def test_blast_alone_inversion_documented(self) -> None:
        """Documents the bug that prior × blast fixes.

        Without the prior, naming_api_shape (blast=4.0) would beat
        validation_placement (blast=2.0) — blast-alone inverts stakes.
        """
        blast_fn = _blast_map({"big_hub": 4.0, "small_node": 2.0})
        assert blast_fn("big_hub") > blast_fn(
            "small_node"
        ), "blast-alone puts naming_api_shape first (the bug prior × blast fixes)"


# ---------------------------------------------------------------------------
# Tier precedence
# ---------------------------------------------------------------------------


class TestTierPrecedence:
    def test_ambiguous_before_deterministic_single_regardless_of_score(self) -> None:
        """ambiguous tier always sorts above deterministic_single/mechanical_fact,
        even when the confident finding has much higher prior × blast."""
        # Give the confident finding a huge score advantage
        confident = _finding("error_handling", "deterministic_single", handles=["hub"])
        uncertain = _finding("naming_api_shape", "ambiguous", handles=["leaf"])

        # error_handling prior=0.9; hub blast=100.0 → score=90.0
        # naming_api_shape prior=0.3; leaf blast=1.0 → score=0.3
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

    def test_within_tier_score_order(self) -> None:
        """Within the confident tier, higher prior × blast ranks first."""
        high_score = _finding("error_handling", "deterministic_single", handles=["a"])
        low_score = _finding("naming_api_shape", "deterministic_single", handles=["b"])
        # error_handling prior=0.9, blast=10 → score=9.0
        # naming_api_shape prior=0.3, blast=10 → score=3.0
        blast_fn = _blast_map({"a": 10.0, "b": 10.0})
        result = rank([low_score, high_score], blast_fn)
        assert result[0]["axis"] == "error_handling"
        assert result[1]["axis"] == "naming_api_shape"


# ---------------------------------------------------------------------------
# Per-project override (custom priors)
# ---------------------------------------------------------------------------


class TestCustomPriorsOverride:
    def test_raising_naming_api_shape_flips_ordering(self) -> None:
        """Custom priors that raise naming_api_shape above validation_placement
        must flip the default ordering — proves per-project overridability."""
        low_stakes = _finding(
            "naming_api_shape",
            "deterministic_single",
            handles=["big_hub"],
        )
        high_stakes = _finding(
            "validation_placement",
            "deterministic_single",
            handles=["small_node"],
        )
        blast_fn = _blast_map({"big_hub": 4.0, "small_node": 2.0})

        # Default: validation_placement wins (prior × blast: 1.8 > 1.2)
        default_result = rank([low_stakes, high_stakes], blast_fn)
        assert default_result[0]["axis"] == "validation_placement"

        # Custom priors: raise naming_api_shape so its score dominates
        # naming_api_shape: 1.0 * 4.0 = 4.0 vs validation_placement: 0.1 * 2.0 = 0.2
        custom_priors = {
            **AXIS_STAKES_PRIOR,
            "naming_api_shape": 1.0,
            "validation_placement": 0.1,
        }
        custom_result = rank([low_stakes, high_stakes], blast_fn, priors=custom_priors)
        assert custom_result[0]["axis"] == "naming_api_shape"

    def test_custom_priors_still_permutation(self) -> None:
        """Custom priors must not cause drops."""
        findings = [
            _finding("layering", "ambiguous"),
            _finding("naming_api_shape", "deterministic_single"),
        ]
        blast_fn = _blast_map({})
        custom: dict[str, float] = {"layering": 0.1, "naming_api_shape": 0.9}
        result = rank(findings, blast_fn, priors=custom)
        assert len(result) == 2
        assert {id(r) for r in result} == {id(f) for f in findings}


# ---------------------------------------------------------------------------
# Unknown-axis floor behavior
# ---------------------------------------------------------------------------


class TestUnknownAxisFloor:
    def test_unknown_axis_does_not_raise(self) -> None:
        """An axis not in priors must not raise KeyError."""
        finding = _finding("totally_unknown_axis", "deterministic_single", handles=["h"])
        blast_fn = _blast_map({"h": 5.0})
        result = rank([finding], blast_fn)
        assert len(result) == 1
        assert result[0] is finding

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

    def test_unknown_axis_floor_equals_min_prior(self) -> None:
        """Unknown axis floor = min(priors.values()), NOT raised.

        Stable sort: unknown_axis and naming_api_shape both get the same score
        (floor = min(AXIS_STAKES_PRIOR) = 0.3 = naming_api_shape prior).
        Input order is preserved on ties.
        """
        unknown = _finding("mystery_axis", "deterministic_single", handles=["h"], claim="unknown")
        known_low = _finding(
            "naming_api_shape", "deterministic_single", handles=["h"], claim="known"
        )
        blast_fn = _blast_map({"h": 5.0})
        # Both findings get score = 0.3 * 5.0 = 1.5 (tied)
        # Stable sort → input order preserved
        result = rank([unknown, known_low], blast_fn)
        assert result[0]["claim"] == "unknown"
        assert result[1]["claim"] == "known"


# ---------------------------------------------------------------------------
# Tie-breaking: stable sort preserves input order
# ---------------------------------------------------------------------------


class TestStableSort:
    def test_equal_score_preserves_input_order(self) -> None:
        """When two findings have identical tier and score, input order is preserved (stable)."""
        f1 = _finding("layering", "deterministic_single", handles=["h"], claim="first")
        f2 = _finding("layering", "deterministic_single", handles=["h"], claim="second")
        blast_fn = _blast_map({"h": 3.0})
        result = rank([f1, f2], blast_fn)
        assert result[0] is f1
        assert result[1] is f2
