"""The ``/docs-review`` substrate (#829): findings, sections and dismissals.

The review principle (D8, C13, C14) is enforced here, not left to the skill's
prose: every finding names its anchor and gives a way forward, and the tool
never decides.
"""

from __future__ import annotations

import copy
import json
import re
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
        anchor={"kind": "audience_rule", "id": "human-explains"},
        needs_decision=True,
        question="Should the README explain the TTL, or link the reference page?",
        options=[
            {"text": "Explain it inline.", "cost": "longer README"},
            {"text": "Link the reference.", "cost": "one more click"},
        ],
        recommended=1,
        recommendation_anchor={"kind": "audience_rule", "id": "link-not-restate"},
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
            (_clear(options=[]), "a clear fix carries no decision fields"),
            (_clear(question="?"), "a clear fix carries no decision fields: ['question']"),
            (_clear(recommended=0), "a clear fix carries no decision fields: ['recommended']"),
            (_clear(assessment="x"), "a clear fix carries no decision fields: ['assessment']"),
            (_clear(needs_decision="yes"), "needs_decision must be true or false"),
            (_clear(category="tone"), "category must be one of"),
            (_clear(anchor={"kind": "vibe", "id": "x"}), "anchor.kind must be one of"),
            (_clear(anchor={"kind": "fact", "id": ""}), "anchor.id must be a non-empty string"),
            (_clear(anchor="env.X"), "anchor must be an object"),
            (_clear(anchor={"kind": "fact", "id": "env.GONE"}), "which doesn't exist"),
            (_without(_clear(), "problem"), "problem must be a non-empty string"),
            (_clear(section=None), "section must be a string"),
            (_clear(category="style"), "a style finding rests on a style_rule anchor"),
            (
                _clear(category="style", anchor={"kind": "style_rule", "id": "made-up"}),
                "'made-up' isn't a style_rule",
            ),
            (
                _clear(category="honest_claims", anchor={"kind": "claims_rule", "id": "D99"}),
                "'D99' isn't a claims_rule",
            ),
            (_clear(category="style", anchor={"kind": "task", "id": "t1"}), "none yet (#830)"),
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
                _ambiguous(recommendation_anchor={"kind": "fact", "id": "env.GONE"}),
                "recommendation_anchor names fact 'env.GONE'",
            ),
            (
                _ambiguous(recommendation_anchor={"kind": "audience_rule", "id": "invented"}),
                "'invented' isn't a audience_rule",
            ),
            (
                _without(_ambiguous(), "recommended", "recommendation_anchor"),
                f"an assessment starting {review.UNANCHORED!r}",
            ),
            (
                {**_without(_ambiguous(), "recommended"), "assessment": "I'd link it."},
                f"an assessment starting {review.UNANCHORED!r}",
            ),
            (
                {**_without(_ambiguous(), "recommended"), "assessment": review.UNANCHORED},
                "a recommendation_anchor needs a recommended option",
            ),
        ],
    )
    def test_a_needs_decision_finding_must_ask_and_never_settle(
        self, finding: dict[str, Any], problem: str
    ) -> None:
        assert any(problem in p for p in review.finding_problems(finding, _FACTS))

    def test_with_root_the_page_and_section_must_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ok = _clear(section="features", anchor={"kind": "fact", "id": _TTL.id})
        assert review.finding_problems(ok, _FACTS, root) == []
        assert review.finding_problems(_clear(page="NOPE.md"), _FACTS, root) == [
            "page 'NOPE.md' isn't a registered doc"
        ]
        (problem,) = review.finding_problems(_clear(section="no-such"), _FACTS, root)
        assert problem.startswith("README.md has no section 'no-such'; its sections: [")

    def test_the_text_before_the_first_heading_is_a_section(self) -> None:
        assert review.finding_problems(_clear(section=""), _FACTS) == []

    def test_the_reviewer_prompt_uses_only_known_rule_ids(self) -> None:
        prompt = (
            Path(__file__).resolve().parents[1] / ".claude/skills/docs-review/reviewer.md"
        ).read_text(encoding="utf-8")
        for kind, ids in review.RULE_IDS.items():
            for rule_id in ids:
                assert f"`{rule_id}`" in prompt, (kind, rule_id)
        quoted = set(re.findall(r'"kind": "(\w+)", "id": "([^"]+)"', prompt))
        for kind, rule_id in quoted:
            if kind in review.RULE_IDS:
                assert rule_id in review.RULE_IDS[kind], (kind, rule_id)
        assert {k for k, _ in quoted} <= set(review.ANCHOR_KINDS)

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


# --- the ledger and check (C13, C14) ------------------------------------------


class TestLedgerIntegration:
    def test_a_held_dismissal_leaves_the_uncovered_entries(self) -> None:
        from pyeye.docs_facts import ledger

        other = Fact("env.PYEYE_OTHER", {"default": 1}, "")
        facts = {_TTL.id: _TTL, other.id: other}
        state: dict[str, Any] = {}
        review.dismiss_uncovered(state, _TTL.id, facts, "tuning knob", "2026-11-18")
        held = review.dismissed_uncovered(state, facts)
        old = ledger.Ledger((), {other.id: "2.1.0", _TTL.id: "unreleased"})
        new = ledger.updated(old, facts, set(), held)
        assert new.new == {other.id: "2.1.0"}
        assert new.dismissed == {_TTL.id: {"reason": "tuning knob", "date": "2026-11-18"}}
        assert '"dismissed": {\n    "env.PYEYE_CACHE_TTL"' in ledger.render(new)

    def test_a_lapsed_dismissal_returns_the_fact(self) -> None:
        from pyeye.docs_facts import ledger

        state: dict[str, Any] = {}
        review.dismiss_uncovered(state, _TTL.id, _FACTS, "tuning knob", "2026-11-18")
        changed = {_TTL.id: Fact(_TTL.id, {"default": 600}, "")}
        held = review.dismissed_uncovered(state, changed)
        new = ledger.updated(ledger.Ledger((), {}), changed, set(), held)
        assert new.new == {_TTL.id: "unreleased"}
        assert new.dismissed == {}


def test_check_fails_on_an_orphaned_dismissal(monkeypatch: pytest.MonkeyPatch) -> None:
    """C14: the PR that removes a fact must remove or move its dismissal."""
    from pyeye.docs_facts import cli

    ghost = Fact("env.PYEYE_GHOST", {"default": 1}, "")
    state: dict[str, Any] = {}
    review.dismiss_uncovered(state, ghost.id, {ghost.id: ghost}, "gone soon", "2026-11-18")
    monkeypatch.setattr(review, "load", lambda _root: state)
    problems = cli.plan(Path(__file__).resolve().parents[1]).problems
    assert any("env.PYEYE_GHOST" in p and "no longer exists" in p for p in problems)


def test_the_committed_state_has_no_orphans() -> None:
    from pyeye.docs_facts.registry import build

    root = Path(__file__).resolve().parents[1]
    assert review.orphaned(review.load(root), build(root)) == []


# --- scope, packets and the command line -------------------------------------

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def repo_facts() -> Any:
    from pyeye.docs_facts.registry import build

    return build(_ROOT)


class TestScope:
    def test_there_is_no_default_scope(self, repo_facts: Any) -> None:
        with pytest.raises(ValueError, match="no default scope"):
            review.scope(_ROOT, repo_facts)

    def test_an_unregistered_page_is_refused(self, repo_facts: Any) -> None:
        with pytest.raises(ValueError, match="matches no registered page"):
            review.scope(_ROOT, repo_facts, pages=["nowhere/*.md"])

    def test_on_demand_pages_become_packets(self, repo_facts: Any) -> None:
        out = review.scope(_ROOT, repo_facts, pages=["README.md"])
        (page,) = out["pages"]
        assert page["page"] == "README.md"
        assert page["audience"] == "human"
        assert page["sections"][0]["line"] == 1
        assert all({"section", "line", "needs_review", "facts"} <= set(s) for s in page["sections"])

    def test_a_skill_page_carries_its_bound_facts(self, repo_facts: Any) -> None:
        out = review.scope(_ROOT, repo_facts, pages=["skills/duplication-review/SKILL.md"])
        (page,) = out["pages"]
        assert "duplication.default.min_tokens" in page["facts"]
        assert any("duplication.default.min_tokens" in s["facts"] for s in page["sections"])

    def test_an_audience_selects_its_pages_and_never_reference_pages(self, repo_facts: Any) -> None:
        out = review.scope(_ROOT, repo_facts, audience="claude")
        assert out["pages"]
        assert all(p["audience"] == "claude" and p["kind"] != "reference" for p in out["pages"])

    def test_a_bad_base_is_an_error_not_the_whole_repo(self, repo_facts: Any) -> None:
        with pytest.raises(ValueError, match="can't read docs/facts/facts.json at 'no-such-ref'"):
            review.scope(_ROOT, repo_facts, base="no-such-ref")

    def test_change_triggered_against_head_has_no_changed_facts(self, repo_facts: Any) -> None:
        out = review.scope(_ROOT, repo_facts, base="HEAD")
        assert out["changed"] == []
        assert out["pages"] == []
        assert isinstance(out["uncovered"], list)

    def test_change_triggered_picks_pages_binding_a_changed_fact(
        self, repo_facts: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye.docs_facts import changed

        def older(root: Path, _base: str, _path: str) -> dict[str, Any]:
            from pyeye.docs_facts.cli import _committed_snapshot

            snap = dict(_committed_snapshot(root))
            snap["duplication.default.min_tokens"] = 25
            return snap

        monkeypatch.setattr(changed, "base_snapshot", older)
        out = review.scope(_ROOT, repo_facts, base="any")
        assert out["changed"] == ["duplication.default.min_tokens"]
        paths = [p["page"] for p in out["pages"]]
        assert "skills/duplication-review/SKILL.md" in paths
        page = next(p for p in out["pages"] if p["page"] == "skills/duplication-review/SKILL.md")
        assert page["changed"] == ["duplication.default.min_tokens"]


@pytest.fixture
def memory_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The review state in memory, so CLI tests never write the committed file."""
    state: dict[str, Any] = {
        "version": 1,
        "coverage": {},
        "findings": [],
        "confirmed_non_issues": [],
    }
    monkeypatch.setattr(review, "load", lambda _root: state)
    monkeypatch.setattr(review, "save", lambda _root, _s: None)
    return state


def _write(tmp_path: Path, findings: list[dict[str, Any]]) -> Path:
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(findings), encoding="utf-8")
    return path


class TestCli:
    @pytest.mark.usefixtures("memory_state")
    def test_validate_reports_problems_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(tmp_path, [_without(_clear(), "replacement")])
        assert review.main(["validate", str(path)], root=_ROOT) == 1
        assert "replacement" in capsys.readouterr().out

    @pytest.mark.usefixtures("memory_state")
    def test_validate_gives_statuses(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        finding = _clear(
            section="features",
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
        )
        path = _write(tmp_path, [finding])
        assert review.main(["validate", str(path)], root=_ROOT) == 0
        assert json.loads(capsys.readouterr().out) == {"shown": [{"index": 0, "status": "new"}]}

    @pytest.mark.usefixtures("memory_state")
    def test_dismiss_then_validate_suppresses_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        finding = _clear(
            section="features",
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
        )
        path = _write(tmp_path, [finding])
        args = ["dismiss", str(path), "--index", "0", "--reason", "fine", "--date", "2026-11-18"]
        assert review.main(args, root=_ROOT) == 0
        capsys.readouterr()
        assert review.main(["validate", str(path)], root=_ROOT) == 0
        assert json.loads(capsys.readouterr().out) == {"shown": []}

    def test_dismissing_an_invalid_finding_is_refused(
        self, tmp_path: Path, memory_state: dict[str, Any]
    ) -> None:
        path = _write(tmp_path, [_without(_clear(), "replacement")])
        args = ["dismiss", str(path), "--index", "0", "--reason", "fine", "--date", "2026-11-18"]
        assert review.main(args, root=_ROOT) == 2
        assert memory_state["confirmed_non_issues"] == []

    def test_mark_fine_records_the_section(self, memory_state: dict[str, Any]) -> None:
        args = ["mark-fine", "README.md", "features", "--date", "2026-11-18"]
        assert review.main(args, root=_ROOT) == 0
        assert "README.md#features" in memory_state["coverage"]
        assert (
            review.main(["mark-fine", "README.md", "no-such", "--date", "2026-11-18"], root=_ROOT)
            == 2
        )
        assert (
            review.main(["mark-fine", "nowhere.md", "x", "--date", "2026-11-18"], root=_ROOT) == 2
        )

    def test_dismiss_uncovered(
        self, memory_state: dict[str, Any], capsys: pytest.CaptureFixture[str], repo_facts: Any
    ) -> None:
        fact_id = next(i for i in repo_facts if i.startswith("env."))
        args = ["dismiss-uncovered", fact_id, "--reason", "internal", "--date", "2026-11-18"]
        assert review.main(args, root=_ROOT) == 0
        assert "docs_facts.py generate" in capsys.readouterr().out
        assert fact_id in review.dismissed_uncovered(memory_state, repo_facts)

    def test_scope_on_the_command_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert review.main(["scope", "README.md"], root=_ROOT) == 0
        assert json.loads(capsys.readouterr().out)["pages"][0]["page"] == "README.md"
        assert review.main(["scope"], root=_ROOT) == 2


class TestOrphanFixes:
    """C14: whoever removes a fact gets a message they can act on without knowing /docs-review."""

    def test_the_message_names_the_fact_the_file_and_both_fixes(self) -> None:
        state: dict[str, Any] = {}
        entry = review.dismiss_uncovered(state, _TTL.id, _FACTS, "internal", "2026-11-18")
        (message,) = review.orphaned(state, {})
        key = entry["key"]
        assert message == (
            "docs/facts/review-state.json: a /docs-review dismissal names fact "
            "'env.PYEYE_CACHE_TTL', which no longer exists: it was removed or renamed in this "
            "change. The dismissal is for the uncovered-fact ledger (deliberately not covered), "
            "recorded 2026-11-18. If the fact was renamed, move it: `uv run python "
            f"scripts/docs_review.py move {key} <new fact ID>`. Otherwise delete it: "
            f"`uv run python scripts/docs_review.py forget {key}`."
        )

    def test_a_finding_dismissal_names_its_section(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        (message,) = review.orphaned(state, {})
        assert "The dismissal is for a finding on README.md#performance-settings" in message

    def test_forget_deletes_only_that_dismissal(self) -> None:
        state: dict[str, Any] = {}
        gone = review.dismiss_uncovered(state, _TTL.id, _FACTS, "internal", "2026-11-18")
        kept = review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        assert review.forget(state, gone["key"])["key"] == gone["key"]
        assert [e["key"] for e in state["confirmed_non_issues"]] == [kept["key"]]
        with pytest.raises(ValueError, match="no /docs-review dismissal"):
            review.forget(state, gone["key"])

    def test_move_carries_an_uncovered_dismissal_to_the_new_id(self) -> None:
        state: dict[str, Any] = {}
        old = review.dismiss_uncovered(state, _TTL.id, _FACTS, "internal", "2026-11-18")
        renamed = Fact("env.PYEYE_SCOPE_CACHE_TTL", {"default": 300}, "")
        facts = {renamed.id: renamed}
        assert review.orphaned(state, facts)
        moved = review.move(state, old["key"], renamed.id, facts)
        assert review.orphaned(state, facts) == []
        assert review.dismissed_uncovered(state, facts) == {
            renamed.id: {"reason": "internal", "date": "2026-11-18"}
        }
        assert moved["handles"] == [renamed.id]

    def test_move_keeps_a_finding_dismissal_on_its_section(self) -> None:
        state: dict[str, Any] = {}
        old = review.dismiss_finding(state, _clear(), _FACTS, "fine", "2026-11-18")
        renamed = Fact("env.PYEYE_SCOPE_CACHE_TTL", {"default": 300}, "")
        facts = {renamed.id: renamed}
        moved = review.move(state, old["key"], renamed.id, facts)
        assert moved["handles"] == ["README.md#performance-settings"]
        assert moved["category"] == "fact_drift"
        finding = _clear(anchor={"kind": "fact", "id": renamed.id})
        assert review.triage([finding], state, facts) == []

    def test_move_refuses_a_missing_target_or_a_non_fact_anchor(self) -> None:
        state: dict[str, Any] = {}
        old = review.dismiss_uncovered(state, _TTL.id, _FACTS, "internal", "2026-11-18")
        with pytest.raises(ValueError, match="no fact 'env.NOPE'"):
            review.move(state, old["key"], "env.NOPE", {})
        style = review.dismiss_finding(state, _ambiguous(), _FACTS, "deliberate", "2026-11-18")
        with pytest.raises(ValueError, match="isn't anchored on a fact"):
            review.move(state, style["key"], _TTL.id, _FACTS)

    def test_move_refuses_a_dismissal_whose_fact_still_exists(self) -> None:
        """Moving a live dismissal would re-point it at an unrelated fact."""
        other = Fact("env.PYEYE_OTHER", {"default": 300}, "")
        facts = {_TTL.id: _TTL, other.id: other}
        state: dict[str, Any] = {}
        old = review.dismiss_uncovered(state, _TTL.id, facts, "internal", "2026-11-18")
        with pytest.raises(ValueError, match="still exists"):
            review.move(state, old["key"], other.id, facts)
        assert review.dismissed_uncovered(state, facts) == {
            _TTL.id: {"reason": "internal", "date": "2026-11-18"}
        }

    def test_a_rename_that_changed_the_value_lapses(self) -> None:
        state: dict[str, Any] = {}
        old = review.dismiss_uncovered(state, _TTL.id, _FACTS, "internal", "2026-11-18")
        renamed = Fact("env.PYEYE_SCOPE_CACHE_TTL", {"default": 900}, "")
        facts = {renamed.id: renamed}
        review.move(state, old["key"], renamed.id, facts)
        assert review.orphaned(state, facts) == []
        assert review.dismissed_uncovered(state, facts) == {}

    def test_the_commands_on_the_command_line(
        self, memory_state: dict[str, Any], capsys: pytest.CaptureFixture[str], repo_facts: Any
    ) -> None:
        other = next(i for i in repo_facts if i.startswith("env."))
        ghost = Fact("env.PYEYE_GHOST", {"default": 1}, "")
        entry = review.dismiss_uncovered(
            memory_state, ghost.id, {ghost.id: ghost}, "x", "2026-11-18"
        )
        assert review.main(["move", entry["key"], other], root=_ROOT) == 0
        moved = json.loads(capsys.readouterr().out)["moved"]
        assert review.main(["forget", moved["key"]], root=_ROOT) == 0
        assert memory_state["confirmed_non_issues"] == []
        assert review.main(["forget", moved["key"]], root=_ROOT) == 2


class TestLowFixes:
    def test_a_covered_fact_dirties_only_the_sections_that_name_it(self) -> None:
        text = "# One\nThe `PYEYE_CACHE_TTL` setting.\n# Two\nUnrelated.\n"
        ttl = Fact("env.PYEYE_CACHE_TTL", {"default": 300}, "`PYEYE_CACHE_TTL`")
        facts = {ttl.id: ttl}
        entry = type("E", (), {"covers": (ttl.id,)})()
        one, two = review.sections(text)
        assert review._section_fact_ids(one, entry, facts, text) == [ttl.id]
        assert review._section_fact_ids(two, entry, facts, text) == []

    def test_a_covered_fact_no_section_names_counts_everywhere(self) -> None:
        text = "# One\nx\n# Two\ny\n"
        ttl = Fact("env.PYEYE_CACHE_TTL", {"default": 300}, "`PYEYE_CACHE_TTL`")
        entry = type("E", (), {"covers": (ttl.id,)})()
        for section in review.sections(text):
            assert review._section_fact_ids(section, entry, {ttl.id: ttl}, text) == [ttl.id]

    def test_prune_drops_entries_for_gone_sections_and_pages(self, tmp_path: Path) -> None:
        (tmp_path / "page.md").write_text("# Kept\nx\n", encoding="utf-8")
        state: dict[str, Any] = {
            "coverage": {
                "page.md#kept": {"content_hash": "h"},
                "page.md#renamed": {"content_hash": "h"},
                "gone.md#x": {"content_hash": "h"},
            },
            "confirmed_non_issues": [],
        }
        kept = review.dismiss_finding(
            state, _clear(page="page.md", section="kept"), _FACTS, "fine", "2026-11-18"
        )
        review.dismiss_finding(
            state, _clear(page="page.md", section="renamed"), _FACTS, "fine", "2026-11-18"
        )
        uncovered = review.dismiss_uncovered(state, _TTL.id, _FACTS, "x", "2026-11-18")
        foreign = {"handles": ["page.md#renamed"], "structural_fact": "facet:a/b"}
        state["confirmed_non_issues"].append(foreign)
        removed = review.prune(state, tmp_path)
        assert removed == ["gone.md#x", "page.md#renamed", "page.md#renamed"]
        assert list(state["coverage"]) == ["page.md#kept"]
        assert state["confirmed_non_issues"] == [kept, uncovered, foreign]


# --- code_contradiction: anchored on a canonical code symbol (#829-2) ----------


def _symbols(table: dict[str, str]) -> review.SymbolCheck:
    return lambda handle: table.get(handle)


def _contradiction(**overrides: Any) -> dict[str, Any]:
    finding = _clear(
        category="code_contradiction",
        anchor={"kind": "symbol", "id": "pkg._impl.load"},
        problem="Says load() returns None on a missing file; it raises FileNotFoundError.",
        replacement="load() raises FileNotFoundError when the file is missing.",
    )
    finding.update(overrides)
    return finding


class TestCodeContradiction:
    def test_a_canonical_project_symbol_passes(self) -> None:
        symbols = _symbols({"pkg._impl.load": "pkg._impl.load"})
        assert review.finding_problems(_contradiction(), _FACTS, None, symbols) == []

    def test_an_unresolved_symbol_is_rejected(self) -> None:
        (problem,) = review.finding_problems(_contradiction(), _FACTS, None, _symbols({}))
        assert (
            problem == "anchor names symbol 'pkg._impl.load', which doesn't resolve in the project"
        )

    def test_a_re_export_alias_is_rejected_with_the_canonical_handle(self) -> None:
        symbols = _symbols({"pkg.load": "pkg._impl.load"})
        finding = _contradiction(anchor={"kind": "symbol", "id": "pkg.load"})
        assert review.finding_problems(finding, _FACTS, None, symbols) == [
            "anchor must use the canonical handle 'pkg._impl.load', not 'pkg.load'"
        ]

    def test_it_is_always_a_clear_fix(self) -> None:
        finding = _without(_contradiction(), "replacement")
        finding.update(
            needs_decision=True,
            question="Which is right?",
            options=[{"text": "a", "cost": "b"}, {"text": "c", "cost": "d"}],
            assessment=f"{review.UNANCHORED}: x",
        )
        problems = review.finding_problems(finding, _FACTS)
        assert "a code_contradiction is a clear fix: state what the code does" in problems

    def test_it_rests_on_a_symbol(self) -> None:
        finding = _contradiction(anchor={"kind": "fact", "id": _TTL.id})
        assert "a code_contradiction finding rests on a symbol anchor" in (
            review.finding_problems(finding, _FACTS)
        )

    def test_project_symbols_uses_pyeyes_resolver(self) -> None:
        check = review.project_symbols(_ROOT)
        assert check("pyeye.resolver.resolve_handle") == "pyeye.resolver.resolve_handle"
        assert check("pyeye.resolver.no_such_function") is None
        assert check("os.path.join") is None  # external: not a project symbol

    def test_validate_resolves_symbols(
        self, tmp_path: Path, memory_state: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        good = _contradiction(
            section="features", anchor={"kind": "symbol", "id": "pyeye.resolver.resolve_handle"}
        )
        bad = _contradiction(
            section="features", anchor={"kind": "symbol", "id": "pyeye.resolver.nope"}
        )
        assert review.main(["validate", str(_write(tmp_path, [good]))], root=_ROOT) == 0
        assert json.loads(capsys.readouterr().out) == {"shown": [{"index": 0, "status": "new"}]}
        assert review.main(["validate", str(_write(tmp_path, [bad]))], root=_ROOT) == 1
        assert "doesn't resolve in the project" in capsys.readouterr().out
        assert memory_state["confirmed_non_issues"] == []
