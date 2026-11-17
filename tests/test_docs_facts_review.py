"""The ``/docs-review`` substrate (#829): findings, sections and dismissals.

The review principle (D8, C13, C14) is enforced here, not left to the skill's
prose: every finding names its anchor and gives a way forward, and the tool
never decides.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from pyeye.architecture_review import state as review_state
from pyeye.docs_facts import review
from pyeye.docs_facts.facts import Fact, view

_TTL = Fact("env.PYEYE_CACHE_TTL", {"default": 300}, "")
_FACTS: dict[str, Any] = {_TTL.id: _TTL, "envs": view("envs", [_TTL], "")}


def _clear(**overrides: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "page": "README.md",
        "section": "performance-settings",
        "category": "fact_drift",
        "anchor": {"kind": "fact", "id": "env.PYEYE_CACHE_TTL"},
        "problem": "says the TTL defaults to 600",
        "replacement": "The cache TTL defaults to 300 seconds.",
    }
    finding.update(overrides)
    return finding


def _ambiguous(**overrides: Any) -> dict[str, Any]:
    finding = _clear(
        category="audience",
        anchor={"kind": "audience_rule", "id": "human-docs-explain"},
        needs_decision=True,
        question="Should the README explain the TTL, or link the reference page?",
        options=[
            {"text": "Explain it inline.", "cost": "longer README"},
            {"text": "Link the reference.", "cost": "one more click"},
        ],
        recommended=1,
        recommendation_anchor={"kind": "audience_rule", "id": "reference-lives-in-reference"},
    )
    del finding["replacement"]
    finding.update(overrides)
    return finding


def _without(finding: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in finding.items() if k not in keys}


class TestFindingProblems:
    def test_a_clear_fix_passes(self) -> None:
        assert review.finding_problems(_clear(), _FACTS) == []

    def test_a_needs_decision_finding_with_a_recommendation_passes(self) -> None:
        assert review.finding_problems(_ambiguous(), _FACTS) == []

    def test_an_unanchored_assessment_passes_in_place_of_a_recommendation(self) -> None:
        finding = _without(_ambiguous(), "recommended", "recommendation_anchor")
        finding["assessment"] = f"{review.UNANCHORED}: linking keeps one copy of the value."
        assert review.finding_problems(finding, _FACTS) == []

    @pytest.mark.parametrize(
        ("finding", "problem"),
        [
            (_without(_clear(), "replacement"), "must propose its replacement text"),
            (_clear(replacement="  "), "must propose its replacement text"),
            (_clear(options=[]), "options belong only to a needs-decision finding"),
            (_clear(needs_decision="yes"), "needs_decision must be true or false"),
            (_clear(category="tone"), "category must be one of"),
            (_clear(anchor={"kind": "vibe", "id": "x"}), "anchor.kind must be one of"),
            (_clear(anchor={"kind": "fact", "id": ""}), "anchor.id must be a non-empty string"),
            (_clear(anchor="env.X"), "anchor must be an object"),
            (_clear(anchor={"kind": "fact", "id": "env.GONE"}), "which doesn't exist"),
            (_without(_clear(), "problem"), "problem must be a non-empty string"),
            (_clear(section=""), "section must be a non-empty string"),
        ],
    )
    def test_a_clear_fix_without_a_way_forward_is_rejected(
        self, finding: dict[str, Any], problem: str
    ) -> None:
        assert any(problem in p for p in review.finding_problems(finding, _FACTS))

    @pytest.mark.parametrize(
        ("finding", "problem"),
        [
            (_ambiguous(replacement="x"), "offers options, not a replacement"),
            (_without(_ambiguous(), "question"), "must state its question"),
            (_ambiguous(options=[{"text": "a", "cost": "b"}]), "a list of 2 to 3 options"),
            (_ambiguous(options=[{"text": "a", "cost": "b"}] * 4), "a list of 2 to 3 options"),
            (_ambiguous(options=[{"text": "a"}, {"text": "b", "cost": "c"}]), "text and cost"),
            (_ambiguous(recommended=5), "index of one of the options"),
            (_ambiguous(recommended=True), "index of one of the options"),
            (_without(_ambiguous(), "recommendation_anchor"), "recommendation_anchor must be"),
            (
                _without(_ambiguous(), "recommended", "recommendation_anchor"),
                f"an assessment starting {review.UNANCHORED!r}",
            ),
            (
                {**_without(_ambiguous(), "recommended"), "assessment": "I'd link it."},
                f"an assessment starting {review.UNANCHORED!r}",
            ),
        ],
    )
    def test_a_needs_decision_finding_must_ask_and_never_settle(
        self, finding: dict[str, Any], problem: str
    ) -> None:
        assert any(problem in p for p in review.finding_problems(finding, _FACTS))

    def test_fact_anchors_are_only_checked_against_facts_when_given(self) -> None:
        assert review.finding_problems(_clear(anchor={"kind": "fact", "id": "env.GONE"})) == []


def test_identity_ignores_the_prose() -> None:
    reworded = _clear(problem="the default is wrong", replacement="Defaults to 300.")
    assert review.finding_key(reworded) == review.finding_key(_clear())
    assert review.finding_key(_clear(section="other")) != review.finding_key(_clear())


class TestSections:
    def test_split_at_headings_with_github_slugs(self) -> None:
        text = "intro\n# Title\nbody\n## Performance Settings!\nmore\n"
        found = review.sections(text)
        assert [s.slug for s in found] == ["", "title", "performance-settings"]
        assert found[2].text == "## Performance Settings!\nmore\n"

    def test_a_heading_inside_a_code_fence_is_not_one(self) -> None:
        text = "# A\n```bash\n# a comment\n```\n# B\n"
        assert [s.slug for s in review.sections(text)] == ["a", "b"]

    def test_repeated_headings_get_suffixes(self) -> None:
        assert [s.slug for s in review.sections("# Use\nx\n# Use\ny\n# Use\n")] == [
            "use",
            "use-1",
            "use-2",
        ]

    def test_an_empty_preamble_is_not_a_section(self) -> None:
        assert [s.slug for s in review.sections("\n\n# A\n")] == ["a"]


class TestFreshness:
    section = review.Section("performance-settings", "## Performance\nTTL is 300.\n")

    def test_never_reviewed_needs_review(self) -> None:
        assert review.needs_review({}, "README.md", self.section, [_TTL.id], _FACTS)

    def test_fine_until_text_or_facts_change(self) -> None:
        state: dict[str, Any] = {}
        review.mark_reviewed(state, "README.md", self.section, [_TTL.id], _FACTS, "2026-11-18")
        assert not review.needs_review(state, "README.md", self.section, [_TTL.id], _FACTS)
        respaced = review.Section(self.section.slug, "## Performance\n\nTTL  is 300.\n")
        assert not review.needs_review(state, "README.md", respaced, [_TTL.id], _FACTS)
        edited = review.Section(self.section.slug, "## Performance\nTTL is 600.\n")
        assert review.needs_review(state, "README.md", edited, [_TTL.id], _FACTS)
        changed = {_TTL.id: Fact(_TTL.id, {"default": 600}, "")}
        assert review.needs_review(state, "README.md", self.section, [_TTL.id], changed)

    def test_a_view_pins_its_members_values(self) -> None:
        changed = {**_FACTS, _TTL.id: Fact(_TTL.id, {"default": 1}, "")}
        assert review.section_hash(self.section, ["envs"], _FACTS) != review.section_hash(
            self.section, ["envs"], changed
        )


class TestDismissals:
    def test_a_dismissed_finding_is_suppressed_even_reworded(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        reworded = _clear(problem="different words")
        assert review.triage([reworded], state, _FACTS) == []

    def test_it_resurfaces_when_its_anchor_fact_changes(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        changed = {_TTL.id: Fact(_TTL.id, {"default": 600}, "")}
        assert review.triage([_clear()], state, changed) == [(_clear(), "resurfaced")]

    def test_a_new_finding_is_new(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        other = _clear(section="quick-start")
        assert review.triage([other], state, _FACTS) == [(other, "new")]

    def test_review_after_comes_due_only_with_today(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _clear(), _FACTS, "deliberate", "2026-11-18", "2026-12-01")
        assert review.triage([_clear()], state, _FACTS) == []
        assert review.triage([_clear()], state, _FACTS, today="2026-11-30") == []
        assert review.triage([_clear()], state, _FACTS, today="2026-12-01") == [
            (_clear(), "review-due")
        ]

    def test_re_dismissing_replaces_the_old_entry(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        changed = {_TTL.id: Fact(_TTL.id, {"default": 600}, "")}
        review.dismiss_finding(state, _clear(), changed, "fine", "2026-11-19")
        assert len(state["confirmed_non_issues"]) == 1
        assert state["confirmed_non_issues"][0]["date"] == "2026-11-19"

    def test_the_key_is_architecture_reviews_non_issue_key(self) -> None:
        state: dict[str, Any] = {}
        entry = review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        assert entry["key"] == review_state.non_issue_key(
            entry["handles"], entry["structural_fact"]
        )

    def test_other_reviews_entries_are_left_alone(self) -> None:
        foreign = {"handles": ["README.md#performance-settings"], "structural_fact": "facet:x/y"}
        state: dict[str, Any] = {"confirmed_non_issues": [dict(foreign)]}
        review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        assert state["confirmed_non_issues"][0] == foreign
        assert review.triage([_clear()], state, _FACTS) == []

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"reason": "meh"}, "reason must be one of"),
            ({"dismissed_on": "18/11/2026"}, "ISO date"),
            ({"review_after": "soon"}, "ISO date"),
        ],
    )
    def test_bad_reasons_and_dates_are_rejected(self, kwargs: dict[str, str], message: str) -> None:
        args = {"reason": "fine", "dismissed_on": "2026-11-18", "review_after": None, **kwargs}
        with pytest.raises(ValueError, match=message):
            review.dismiss_finding({}, _clear(), _FACTS, **args)  # type: ignore[arg-type]


class TestUncovered:
    def test_a_dismissal_holds_until_the_fact_changes(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_uncovered(state, _TTL.id, _FACTS, "internal tuning", "2026-11-18")
        assert review.dismissed_uncovered(state, _FACTS) == {
            _TTL.id: {"reason": "internal tuning", "date": "2026-11-18"}
        }
        changed = {_TTL.id: Fact(_TTL.id, {"default": 1}, "")}
        assert review.dismissed_uncovered(state, changed) == {}

    def test_it_needs_a_real_fact_and_a_reason(self) -> None:
        with pytest.raises(ValueError, match="no fact"):
            review.dismiss_uncovered({}, "env.GONE", _FACTS, "why", "2026-11-18")
        with pytest.raises(ValueError, match="needs its reason"):
            review.dismiss_uncovered({}, _TTL.id, _FACTS, " ", "2026-11-18")


class TestOrphans:
    def test_a_dismissal_whose_fact_is_gone_is_a_problem(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_uncovered(state, _TTL.id, _FACTS, "internal", "2026-11-18")
        review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        assert review.orphaned(state, _FACTS) == []
        problems = review.orphaned(state, {})
        assert len(problems) == 2
        assert all("env.PYEYE_CACHE_TTL" in p and "no longer exists" in p for p in problems)

    def test_non_fact_anchors_never_orphan(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _ambiguous(), _FACTS, "deliberate", "2026-11-18")
        assert review.orphaned(state, {}) == []


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    (tmp_path / "docs" / "facts").mkdir(parents=True)
    state = review.load(tmp_path)
    assert state["confirmed_non_issues"] == []
    review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
    review.save(tmp_path, state)
    text = (tmp_path / review.STATE_PATH).read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert review.load(tmp_path) == copy.deepcopy(state)
