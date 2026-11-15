"""Finding identity rests on a closed-vocabulary facet, not claim prose (#498).

The approved design on #498 lists required tests; each class below is one of
them. Identity is ``observation_key = (axis, facet, sorted handles)``, used by all
three sites that used to key on the volatile ``claim`` string: the reproduction
gate, ``merge_findings`` and the non-issue key.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from pyeye.architecture_review.gate import apply_reproduction_gate
from pyeye.architecture_review.state import (
    build_non_issue,
    finding_problems,
    findings_equivalent,
    merge_findings,
    observation_key,
)
from pyeye.architecture_review.taxonomy import AXIS_FACETS, FACET_OTHER, SEED_AXES

_AUDITOR = Path(__file__).resolve().parent.parent / "skills" / "architecture-review" / "auditor.md"


def _f(
    handles: list[str],
    *,
    axis: str = "naming_api_shape",
    facet: str | None = "name_pattern",
    grade: str = "deterministic_single",
    claim: str = "handlers are named handle_*",
) -> dict[str, Any]:
    finding: dict[str, Any] = {"axis": axis, "grade": grade, "handles": handles, "claim": claim}
    if facet is not None:
        finding["facet"] = facet
    return finding


_HANDLERS = [f"app.handlers.handle_{n}" for n in ("a", "b", "c", "d", "e", "f")]


class TestOverMergeRegression:
    def test_same_location_different_facet_is_not_equivalent(self) -> None:
        """Same axis, handles and grade; a different observation (facet)."""
        names = _f(_HANDLERS, facet="name_pattern", claim="all named handle_*")
        sync = _f(_HANDLERS, facet="sync_async", claim="all named handle_*")

        assert not findings_equivalent(names, sync)
        assert merge_findings([names], [sync]) == [names, sync]

    def test_same_handles_different_axis_is_not_equivalent(self) -> None:
        a = _f(_HANDLERS, axis="layering", facet="import_direction")
        b = _f(_HANDLERS, axis="module_boundaries", facet="placement")

        assert not findings_equivalent(a, b)
        assert merge_findings([a], [b]) == [a, b]

    def test_handle_order_is_ignored(self) -> None:
        a = _f(_HANDLERS)
        b = _f(list(reversed(_HANDLERS)))

        assert observation_key(a) == observation_key(b)
        assert findings_equivalent(a, b)

    def test_grade_still_matters(self) -> None:
        assert not findings_equivalent(_f(_HANDLERS), _f(_HANDLERS, grade="ambiguous"))


class TestThreeBlindRerunDogfood:
    """#492 dogfood: three blind auditor runs agree on handles, grade, axis and
    facet; only the claim wording differs. Before #498 the gate downgraded it."""

    RUNS = [
        _f(_HANDLERS, claim="All six handlers follow the handle_* naming convention"),
        _f(_HANDLERS, claim="Handler functions are uniformly prefixed with handle_ (6/6)"),
        _f(_HANDLERS, claim="every function in app.handlers is named handle_<x>"),
    ]

    def test_gate_promotes_the_stable_universal(self) -> None:
        first, *reruns = self.RUNS

        result = apply_reproduction_gate(
            [first], lambda _c, i: [reruns[i % len(reruns)]], runs=len(reruns)
        )

        assert result[0]["grade"] == "deterministic_single"

    def test_merge_dedupes_the_reworded_runs(self) -> None:
        accumulated: list[dict[str, Any]] = []
        for run in self.RUNS:
            accumulated = merge_findings(accumulated, [run])

        assert accumulated == [self.RUNS[0]]


class TestNonIssueKey:
    def test_reworded_claim_stays_suppressed(self) -> None:
        dismissed = build_non_issue(_f(_HANDLERS, claim="named handle_*"))
        reworded = build_non_issue(_f(_HANDLERS, claim="uses the handle_ prefix"))

        assert reworded["key"] == dismissed["key"]

    def test_grade_change_stays_suppressed(self) -> None:
        dismissed = build_non_issue(_f(_HANDLERS))
        regraded = build_non_issue(_f(_HANDLERS, grade="ambiguous"))

        assert regraded["key"] == dismissed["key"]

    def test_handle_change_resurfaces(self) -> None:
        dismissed = build_non_issue(_f(_HANDLERS))
        grown = build_non_issue(_f([*_HANDLERS, "app.handlers.handle_g"]))

        assert grown["key"] != dismissed["key"]

    def test_facet_change_resurfaces(self) -> None:
        dismissed = build_non_issue(_f(_HANDLERS, facet="name_pattern"))
        other = build_non_issue(_f(_HANDLERS, facet="return_shape"))

        assert other["key"] != dismissed["key"]

    def test_unkeyed_falls_back_to_the_claim(self) -> None:
        """No facet: the documented volatile fallback keys on the claim."""
        a = build_non_issue(_f(_HANDLERS, facet=None, claim="named handle_*"))
        b = build_non_issue(_f(_HANDLERS, facet=None, claim="uses the handle_ prefix"))

        assert a["structural_fact"] == "named handle_*"
        assert a["key"] != b["key"]


class TestUnkeyedFindings:
    @pytest.mark.parametrize(
        "finding",
        [
            _f(_HANDLERS, facet=None),
            _f(_HANDLERS, facet=FACET_OTHER),
            _f(_HANDLERS, facet="not_in_vocabulary"),
            _f(_HANDLERS, facet="import_direction"),  # a real facet, but of another axis
            _f(_HANDLERS, axis="testing_style", facet="name_pattern"),  # open axis
        ],
        ids=["missing", "other", "unlisted", "wrong-axis", "open-axis"],
    )
    def test_never_keyed_never_promoted(self, finding: dict[str, Any]) -> None:
        assert observation_key(finding) is None
        result = apply_reproduction_gate([finding], lambda _c, _i: [dict(finding)], runs=2)
        assert result[0]["grade"] == "ambiguous"

    def test_never_over_merged(self) -> None:
        """The unkeyed fallback is the exact normalised claim: a reworded unkeyed
        finding is kept (under-merge), never collapsed into another observation."""
        a = _f(_HANDLERS, facet=None, claim="named handle_*")
        b = _f(_HANDLERS, facet=None, claim="all of them are async")

        assert merge_findings([a], [b]) == [a, b]

    def test_fallback_still_dedupes_an_identical_claim(self) -> None:
        a = _f(_HANDLERS, facet=None, claim="Named  handle_*")
        b = _f(_HANDLERS, facet=None, claim="named handle_*")

        assert merge_findings([a], [b]) == [a]


class TestOrchestratorValidation:
    def test_seed_axis_without_facet_is_rejected(self) -> None:
        assert finding_problems(_f(_HANDLERS, facet=None))

    def test_unlisted_facet_is_rejected(self) -> None:
        assert finding_problems(_f(_HANDLERS, facet="import_direction"))

    @pytest.mark.parametrize("facet", ["name_pattern", FACET_OTHER])
    def test_listed_facet_or_other_is_accepted(self, facet: str) -> None:
        assert finding_problems(_f(_HANDLERS, facet=facet)) == []

    def test_open_axis_needs_no_facet(self) -> None:
        assert finding_problems(_f(_HANDLERS, axis="testing_style", facet=None)) == []


class TestVocabularyConformance:
    def test_every_seed_axis_has_a_vocabulary(self) -> None:
        assert set(AXIS_FACETS) == set(SEED_AXES)
        for axis, facets in AXIS_FACETS.items():
            assert facets, axis
            assert len(set(facets)) == len(facets), axis
            assert FACET_OTHER not in facets, axis

    def test_auditor_lists_exactly_the_taxonomy_vocabulary(self) -> None:
        """auditor.md's facet table lists each axis's facets verbatim (the #374 pattern)."""
        text = _AUDITOR.read_text(encoding="utf-8")
        rows = re.findall(r"^\|\s*`(\w+)`\s*\|\s*((?:`\w+`[\s,]*)+)\|\s*$", text, re.MULTILINE)
        documented = {axis: tuple(re.findall(r"`(\w+)`", cells)) for axis, cells in rows}
        assert documented == AXIS_FACETS
