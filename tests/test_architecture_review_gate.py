"""Tests for architecture_review.gate — reproduction gate (spec §10).

Covers:
- Stable candidate (all N runs produce equivalent) keeps grade deterministic_single
- Unstable candidate (>=1 run lacks equivalent) gets grade rewritten to ambiguous
- Non-candidates (ambiguous/mechanical_fact/no_signal) are untouched and not re-dispatched
- Output order is preserved (gate is order-preserving)
- runs parameter is configurable; runs < 1 raises ValueError
- Equivalence uses handle-set + grade + normalized-claim (via state.findings_equivalent)
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from pyeye.architecture_review.gate import DEFAULT_GATE_RUNS, apply_reproduction_gate
from pyeye.architecture_review.state import findings_equivalent

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _ds(handles: list[str], claim: str = "Claim X") -> dict[str, Any]:
    return {"handles": handles, "grade": "deterministic_single", "claim": claim, "axis": "layering"}


def _amb(handles: list[str], claim: str = "Claim A") -> dict[str, Any]:
    return {"handles": handles, "grade": "ambiguous", "claim": claim, "axis": "layering"}


def _mf(handles: list[str], claim: str = "Claim M") -> dict[str, Any]:
    return {"handles": handles, "grade": "mechanical_fact", "claim": claim, "axis": "layering"}


def _ns(handles: list[str], claim: str = "Claim N") -> dict[str, Any]:
    return {"handles": handles, "grade": "no_signal", "claim": claim, "axis": "layering"}


# ---------------------------------------------------------------------------
# Test 1: Stable candidate stays deterministic_single
# ---------------------------------------------------------------------------


class TestStableCandidateStaysConfident:
    def test_all_runs_reproduce_equivalent(self) -> None:
        candidate = _ds(["a.b", "c.d"], "Some claim")
        rerun_finding = _ds(["a.b", "c.d"], "Some claim")

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return [rerun_finding]

        result = apply_reproduction_gate([candidate], redispatch, runs=3)

        assert len(result) == 1
        assert result[0]["grade"] == "deterministic_single"

    def test_multiple_equivalent_in_run_any_one_suffices(self) -> None:
        """If a run returns several findings, any one equivalent is enough."""
        candidate = _ds(["a.b"], "Some claim")
        rerun_equiv = _ds(["a.b"], "Some claim")
        rerun_other = _ds(["x.y"], "Unrelated")

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return [rerun_other, rerun_equiv]

        result = apply_reproduction_gate([candidate], redispatch, runs=2)
        assert result[0]["grade"] == "deterministic_single"


# ---------------------------------------------------------------------------
# Test 2: Unstable candidate downgraded to ambiguous
# ---------------------------------------------------------------------------


class TestUnstableCandidateDowngraded:
    def test_one_run_lacks_equivalent(self) -> None:
        candidate = _ds(["a.b"], "Some claim")
        different_finding = _ds(["x.y"], "Totally different claim")
        equivalent_finding = _ds(["a.b"], "Some claim")

        def redispatch(_finding: dict[str, Any], i: int) -> list[dict[str, Any]]:
            if i == 1:
                return [different_finding]  # No equivalent here
            return [equivalent_finding]

        result = apply_reproduction_gate([candidate], redispatch, runs=3)

        assert len(result) == 1
        assert result[0]["grade"] == "ambiguous"

    def test_all_runs_lack_equivalent(self) -> None:
        candidate = _ds(["a.b"], "Some claim")

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return []  # Empty — no equivalent

        result = apply_reproduction_gate([candidate], redispatch, runs=2)

        assert len(result) == 1
        assert result[0]["grade"] == "ambiguous"

    def test_short_circuits_on_first_unstable_run(self) -> None:
        """First run lacking an equivalent stops re-dispatch early (cost control, §10)."""
        candidate = _ds(["a.b"], "Some claim")
        spy: MagicMock = MagicMock(return_value=[])  # run 0 already has no equivalent

        result = apply_reproduction_gate([candidate], spy, runs=3)

        # Despite runs=3, the loop must break after the first non-reproducing run.
        assert spy.call_count == 1
        assert result[0]["grade"] == "ambiguous"

    def test_short_circuits_on_middle_unstable_run(self) -> None:
        """A failure on run 1 stops before run 2 (only runs up to the failure execute)."""
        candidate = _ds(["a.b"], "Some claim")
        equivalent_finding = _ds(["a.b"], "Some claim")

        def redispatch(_finding: dict[str, Any], i: int) -> list[dict[str, Any]]:
            if i == 1:
                return []  # No equivalent on the second run
            return [equivalent_finding]

        spy = MagicMock(side_effect=redispatch)

        result = apply_reproduction_gate([candidate], spy, runs=3)

        # Runs 0 and 1 execute; run 2 is skipped by the short-circuit.
        assert spy.call_count == 2
        assert result[0]["grade"] == "ambiguous"

    def test_downgrade_preserves_other_keys(self) -> None:
        candidate: dict[str, Any] = {
            "handles": ["a.b"],
            "grade": "deterministic_single",
            "claim": "Some claim",
            "axis": "layering",
            "evidence": "Some evidence",
            "recommendation": "Do this",
        }

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return []  # No equivalent

        result = apply_reproduction_gate([candidate], redispatch, runs=1)

        assert result[0]["grade"] == "ambiguous"
        assert result[0]["claim"] == "Some claim"
        assert result[0]["axis"] == "layering"
        assert result[0]["evidence"] == "Some evidence"
        assert result[0]["recommendation"] == "Do this"

    def test_downgrade_does_not_mutate_input(self) -> None:
        candidate = _ds(["a.b"], "Some claim")

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return []

        result = apply_reproduction_gate([candidate], redispatch, runs=1)

        assert result[0]["grade"] == "ambiguous"
        assert candidate["grade"] == "deterministic_single"  # original unchanged

    def test_downgrade_returns_new_dict_not_same_object(self) -> None:
        candidate = _ds(["a.b"], "Some claim")

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return []

        result = apply_reproduction_gate([candidate], redispatch, runs=1)

        assert result[0] is not candidate


# ---------------------------------------------------------------------------
# Test 3: Non-candidates untouched AND not re-dispatched
# ---------------------------------------------------------------------------


class TestNonCandidatesUntouched:
    def test_non_candidates_not_redispatched_spy(self) -> None:
        spy: MagicMock = MagicMock(return_value=[_ds(["g.h"], "Candidate claim")])

        ambiguous = _amb(["a.b"])
        mechanical = _mf(["c.d"])
        no_signal = _ns(["e.f"])
        candidate = _ds(["g.h"], "Candidate claim")

        findings = [ambiguous, mechanical, no_signal, candidate]
        apply_reproduction_gate(findings, spy, runs=2)

        # spy should only be called with the deterministic_single candidate
        # runs=2, 1 candidate → exactly 2 calls total
        assert spy.call_count == 2

        # Verify every call was for the candidate, not any non-candidate
        for call in spy.call_args_list:
            called_finding = call.args[0]
            assert (
                called_finding["grade"] == "deterministic_single"
            ), f"redispatch called for non-candidate: {called_finding!r}"

    def test_non_candidates_grade_unchanged(self) -> None:
        ambiguous = _amb(["a.b"])
        mechanical = _mf(["c.d"])
        no_signal = _ns(["e.f"])

        never_called = [False]

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            never_called[0] = True
            return []

        result = apply_reproduction_gate([ambiguous, mechanical, no_signal], redispatch, runs=3)

        assert not never_called[0], "redispatch should not be called for non-candidates"
        assert result[0]["grade"] == "ambiguous"
        assert result[1]["grade"] == "mechanical_fact"
        assert result[2]["grade"] == "no_signal"

    def test_non_candidates_same_object_in_output(self) -> None:
        """Non-candidates are passed through by identity (not copied)."""
        ambiguous = _amb(["a.b"])

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return []

        result = apply_reproduction_gate([ambiguous], redispatch, runs=1)

        assert result[0] is ambiguous


# ---------------------------------------------------------------------------
# Test 4: Order preserved
# ---------------------------------------------------------------------------


class TestOrderPreserved:
    def test_output_same_order_and_length(self) -> None:
        c1 = _ds(["c.d"], "Candidate 1")
        c2 = _ds(["g.h"], "Candidate 2")
        findings = [
            _amb(["a.b"]),
            c1,
            _mf(["e.f"]),
            c2,
            _ns(["i.j"]),
        ]
        equiv_c1 = _ds(["c.d"], "Candidate 1")
        equiv_c2 = _ds(["g.h"], "Candidate 2")

        def redispatch(finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            if finding["claim"] == "Candidate 1":
                return [equiv_c1]
            return [equiv_c2]

        result = apply_reproduction_gate(findings, redispatch, runs=DEFAULT_GATE_RUNS)

        assert len(result) == 5
        assert result[0]["grade"] == "ambiguous"
        assert result[1]["grade"] == "deterministic_single"
        assert result[2]["grade"] == "mechanical_fact"
        assert result[3]["grade"] == "deterministic_single"
        assert result[4]["grade"] == "no_signal"

    def test_mixed_stable_and_unstable_order(self) -> None:
        """Stable and unstable candidates interleaved with non-candidates keep order."""
        stable = _ds(["a.b"], "Stable claim")
        unstable = _ds(["c.d"], "Unstable claim")
        non_cand = _mf(["e.f"])

        findings = [unstable, non_cand, stable]

        def redispatch(finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            if finding["claim"] == "Stable claim":
                return [_ds(["a.b"], "Stable claim")]
            return []  # No equivalent for unstable

        result = apply_reproduction_gate(findings, redispatch, runs=2)

        assert len(result) == 3
        assert result[0]["grade"] == "ambiguous"  # unstable → downgraded
        assert result[1]["grade"] == "mechanical_fact"  # untouched
        assert result[2]["grade"] == "deterministic_single"  # stable → kept


# ---------------------------------------------------------------------------
# Test 5: runs is configurable
# ---------------------------------------------------------------------------


class TestRunsConfigurable:
    def test_runs_2_calls_per_candidate(self) -> None:
        candidate = _ds(["a.b"], "Some claim")
        call_indices: list[int] = []

        def redispatch(_finding: dict[str, Any], i: int) -> list[dict[str, Any]]:
            call_indices.append(i)
            return [_ds(["a.b"], "Some claim")]

        apply_reproduction_gate([candidate], redispatch, runs=2)

        assert len(call_indices) == 2
        assert call_indices == [0, 1]

    def test_runs_3_calls_per_candidate(self) -> None:
        candidate = _ds(["a.b"], "Some claim")
        call_count = [0]

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            call_count[0] += 1
            return [_ds(["a.b"], "Some claim")]

        apply_reproduction_gate([candidate], redispatch, runs=3)

        assert call_count[0] == 3

    def test_runs_0_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            apply_reproduction_gate([], lambda _f, _i: [], runs=0)

    def test_runs_negative_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            apply_reproduction_gate([], lambda _f, _i: [], runs=-1)

    def test_default_gate_runs_is_3(self) -> None:
        assert DEFAULT_GATE_RUNS == 3

    def test_multiple_candidates_each_called_n_times(self) -> None:
        c1 = _ds(["a.b"], "Claim 1")
        c2 = _ds(["c.d"], "Claim 2")
        calls_by_claim: dict[str, list[int]] = {}

        def redispatch(finding: dict[str, Any], i: int) -> list[dict[str, Any]]:
            claim = finding["claim"]
            calls_by_claim.setdefault(claim, []).append(i)
            return [finding]

        apply_reproduction_gate([c1, c2], redispatch, runs=2)

        assert calls_by_claim == {"Claim 1": [0, 1], "Claim 2": [0, 1]}

    def test_runs_1_single_call_per_candidate(self) -> None:
        candidate = _ds(["a.b"], "Some claim")
        call_count = [0]

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            call_count[0] += 1
            return []  # No equivalent → downgrade

        result = apply_reproduction_gate([candidate], redispatch, runs=1)

        assert call_count[0] == 1
        assert result[0]["grade"] == "ambiguous"


# ---------------------------------------------------------------------------
# Test 6: Equivalence is the real predicate (handle-set + grade + norm-claim)
# ---------------------------------------------------------------------------


class TestEquivalenceIsRealPredicate:
    def test_handle_reorder_is_equivalent_stays_confident(self) -> None:
        """Handle ORDER doesn't matter; set-equality makes findings equivalent."""
        candidate = _ds(["a.b", "c.d"], "Some claim")
        # Re-run returns handles in reversed order — still equivalent per findings_equivalent
        rerun_reordered = _ds(["c.d", "a.b"], "Some claim")

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return [rerun_reordered]

        result = apply_reproduction_gate([candidate], redispatch, runs=2)

        assert result[0]["grade"] == "deterministic_single"

    def test_handle_set_difference_is_not_equivalent_downgrades(self) -> None:
        """Different handle SETS → not equivalent → candidate downgraded."""
        candidate = _ds(["a.b", "c.d"], "Some claim")
        # Re-run returns a different handle set (c.d replaced with e.f)
        rerun_different_handles = _ds(["a.b", "e.f"], "Some claim")

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return [rerun_different_handles]

        result = apply_reproduction_gate([candidate], redispatch, runs=2)

        assert result[0]["grade"] == "ambiguous"

    def test_case_insensitive_claim_is_equivalent(self) -> None:
        """Claim normalisation (case-fold + whitespace collapse) is inherited from findings_equivalent."""
        f1: dict[str, Any] = {
            "handles": ["a.b"],
            "grade": "deterministic_single",
            "claim": "Some Claim",
        }
        # Lowercase claim — findings_equivalent says these are equivalent
        f2: dict[str, Any] = {
            "handles": ["a.b"],
            "grade": "deterministic_single",
            "claim": "some claim",
        }

        # Sanity: state.findings_equivalent agrees
        assert findings_equivalent(f1, f2)

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return [f2]  # Re-run returns differently-cased claim

        result = apply_reproduction_gate([f1], redispatch, runs=2)
        assert result[0]["grade"] == "deterministic_single"

    def test_custom_equivalent_overrides_default(self) -> None:
        """Caller can inject a stricter equivalence; gate uses it, not the default."""
        candidate = _ds(["a.b", "c.d"], "Some claim")
        # Reordered handles — equivalent under state.findings_equivalent but NOT under strict list eq
        rerun_reordered = _ds(["c.d", "a.b"], "Some claim")

        def strict_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
            """Stricter: requires list equality on handles (order-sensitive)."""
            return (
                a.get("handles") == b.get("handles")
                and a.get("grade") == b.get("grade")
                and a.get("claim") == b.get("claim")
            )

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return [rerun_reordered]

        result = apply_reproduction_gate(
            [candidate], redispatch, runs=2, equivalent=strict_equivalent
        )

        # strict_equivalent rejects reordered handles → downgraded
        assert result[0]["grade"] == "ambiguous"

    def test_grade_difference_is_not_equivalent(self) -> None:
        """Grade is part of equivalence; a re-run returning a different grade downgrades."""
        candidate = _ds(["a.b"], "Some claim")
        # Re-run returns ambiguous — different grade → not equivalent
        rerun_ambiguous: dict[str, Any] = {
            "handles": ["a.b"],
            "grade": "ambiguous",
            "claim": "Some claim",
        }

        def redispatch(_finding: dict[str, Any], _i: int) -> list[dict[str, Any]]:
            return [rerun_ambiguous]

        result = apply_reproduction_gate([candidate], redispatch, runs=2)

        assert result[0]["grade"] == "ambiguous"
