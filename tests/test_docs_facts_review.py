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
        "replacement": "Show the cache TTL's default through its fact block for env.PYEYE_CACHE_TTL.",
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
        subject="The cache TTL defaults to",
    )
    del finding["replacement"]
    finding.update(overrides)
    return finding


def _hashed(finding: dict[str, Any], root: Path) -> dict[str, Any]:
    """*finding* with the page_hash a scope packet gives its page (#829-3)."""
    text = (root / finding["page"]).read_text(encoding="utf-8")
    return {**finding, "page_hash": review.page_hash(text)}


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
        ok = _clear(section=_README_SECTION, anchor={"kind": "fact", "id": _TTL.id})
        assert review.finding_problems(_hashed(ok, root), _FACTS, root) == []
        assert review.finding_problems(_clear(page="NOPE.md"), _FACTS, root) == [
            "page 'NOPE.md' isn't a registered doc"
        ]
        (problem,) = review.finding_problems(_hashed(_clear(section="no-such"), root), _FACTS, root)
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


def _readme_anchor() -> tuple[str, str]:
    """A README section and a subject unique in it, read from the README as it is now.

    The section's own heading line is unique in it, so no edit to README's prose
    can break the tests that need a real registered page (the CLI tests).
    """
    text = (_ROOT / "README.md").read_text(encoding="utf-8")
    section = next(s for s in review.sections(text) if s.slug)
    return section.slug, section.text.splitlines()[0].strip()


_README_SECTION, _README_SUBJECT = _readme_anchor()


def _bound_skill_fact() -> tuple[str, str]:
    """A registered skill page and an item fact one of its blocks shows, from the docs as they are."""
    from pyeye.docs_facts import binding, docs
    from pyeye.docs_facts.registry import build

    facts = build(_ROOT)
    for path, entry in docs.registered_files(_ROOT):
        if entry.kind != "skill":
            continue
        blocks, _ = binding.parse((_ROOT / path).read_text(encoding="utf-8"))
        for block in blocks:
            if isinstance(facts.get(block.fact_id), Fact):
                return path, block.fact_id
    raise AssertionError("no skill page binds an item fact")


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
        path, fact_id = _bound_skill_fact()
        out = review.scope(_ROOT, repo_facts, pages=[path])
        (page,) = out["pages"]
        assert fact_id in page["facts"]
        assert any(fact_id in s["facts"] for s in page["sections"])

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
            snap[fact_id] = "a different value"
            return snap

        path, fact_id = _bound_skill_fact()
        monkeypatch.setattr(changed, "base_snapshot", older)
        out = review.scope(_ROOT, repo_facts, base="any")
        assert out["changed"] == [fact_id]
        paths = [p["page"] for p in out["pages"]]
        assert path in paths
        page = next(p for p in out["pages"] if p["page"] == path)
        assert page["changed"] == [fact_id]


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
    """The findings as a file, each with its page's current page_hash, as scope gives it."""
    hashed = [
        _hashed(f, _ROOT) if (_ROOT / str(f.get("page", ""))).is_file() else f for f in findings
    ]
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(hashed), encoding="utf-8")
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
            section=_README_SECTION,
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
            subject=_README_SUBJECT,
        )
        path = _write(tmp_path, [finding])
        assert review.main(["validate", str(path)], root=_ROOT) == 0
        assert json.loads(capsys.readouterr().out) == {
            "ok": True,
            "accepted": 1,
            "rejected": 0,
            "shown": [{"index": 0, "status": "new"}],
        }

    @pytest.mark.usefixtures("memory_state")
    def test_dismiss_then_validate_suppresses_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        finding = _clear(
            section=_README_SECTION,
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
            subject=_README_SUBJECT,
        )
        path = _write(tmp_path, [finding])
        args = ["dismiss", str(path), "--index", "0", "--reason", "fine", "--date", "2026-11-18"]
        assert review.main(args, root=_ROOT) == 0
        capsys.readouterr()
        assert review.main(["validate", str(path)], root=_ROOT) == 0
        assert json.loads(capsys.readouterr().out) == {
            "ok": True,
            "accepted": 1,
            "rejected": 0,
            "shown": [],
        }

    def test_dismissing_an_invalid_finding_is_refused(
        self, tmp_path: Path, memory_state: dict[str, Any]
    ) -> None:
        path = _write(tmp_path, [_without(_clear(), "replacement")])
        args = ["dismiss", str(path), "--index", "0", "--reason", "fine", "--date", "2026-11-18"]
        assert review.main(args, root=_ROOT) == 2
        assert memory_state["confirmed_non_issues"] == []

    def test_mark_fine_records_the_section(self, memory_state: dict[str, Any]) -> None:
        args = ["mark-fine", "README.md", _README_SECTION, "--date", "2026-11-18"]
        assert review.main(args, root=_ROOT) == 0
        assert f"README.md#{_README_SECTION}" in memory_state["coverage"]
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
            "'env.PYEYE_CACHE_TTL', which no longer exists: it was removed or changed in this "
            "change. The dismissal is for the uncovered-fact ledger (deliberately not covered), "
            "recorded 2026-11-18. If it was renamed or reworded, move it: `uv run python "
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
        with pytest.raises(ValueError, match="needs the repo root"):
            review.move(state, style["key"], "new words", _FACTS)

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


# --- code_contradiction: anchored on a canonical code symbol (#829-2, C15) ---


class _FakeSymbols:
    """A :class:`review.Symbols` over a fixed table, for tests."""

    def __init__(
        self,
        canonical: dict[str, str],
        surfaces: dict[str, dict[str, str]] | None = None,
        edges: dict[tuple[str, str], list[str]] | None = None,
        literals: frozenset[str] = frozenset(),
    ) -> None:
        self._literals = literals
        self._canonical = canonical
        self._surfaces = surfaces or {}
        self._edges = edges or {}

    def canonical(self, handle: str) -> str | None:
        return self._canonical.get(handle)

    def surface(self, handle: str) -> dict[str, str] | None:
        return self._surfaces.get(handle)

    def edge(self, handle: str, edge: str) -> list[str] | None:
        return self._edges.get((handle, edge))

    def has_literal(self, text: str) -> bool:
        return text in self._literals


_LOAD = "pkg._impl.load"
_SIG = "load(path: str) -> bytes"
_DOC = "Read the file. Raises FileNotFoundError when it is missing."


def _syms(**kwargs: Any) -> _FakeSymbols:
    return _FakeSymbols(
        kwargs.get("canonical", {_LOAD: _LOAD}),
        kwargs.get("surfaces", {_LOAD: {"signature": _SIG, "docstring": _DOC}}),
        kwargs.get("edges", {(_LOAD, "callees"): ["builtins.open"]}),
        kwargs.get("literals", frozenset({"Package path does not exist: {}"})),
    )


def _contradiction(**overrides: Any) -> dict[str, Any]:
    finding = _clear(
        category="code_contradiction",
        anchor={"kind": "symbol", "id": _LOAD},
        problem="Says load() returns None on a missing file; it raises FileNotFoundError.",
        replacement="load() raises FileNotFoundError when the file is missing.",
        evidence=[{"docstring": "Raises FileNotFoundError when it is missing."}],
        route="wording",
        route_reason="An error path is behaviour no extractor reads, and the example "
        "fixture has no missing file.",
    )
    finding.update(overrides)
    return finding


class TestCodeContradiction:
    def test_a_canonical_project_symbol_with_true_evidence_passes(self) -> None:
        evidence = [
            {"signature": _SIG},
            {"docstring": "Raises   FileNotFoundError when it is missing."},
            {"edge": "callees", "includes": ["builtins.open"]},
        ]
        finding = _contradiction(evidence=evidence)
        assert review.finding_problems(finding, _FACTS, None, _syms()) == []

    def test_an_unresolved_symbol_is_rejected(self) -> None:
        problems = review.finding_problems(_contradiction(), _FACTS, None, _syms(canonical={}))
        assert "anchor names symbol 'pkg._impl.load', which doesn't resolve in the project" in (
            problems
        )

    def test_a_re_export_alias_is_rejected_with_the_canonical_handle(self) -> None:
        symbols = _syms(canonical={"pkg.load": _LOAD})
        finding = _contradiction(anchor={"kind": "symbol", "id": "pkg.load"})
        assert "anchor must use the canonical handle 'pkg._impl.load', not 'pkg.load'" in (
            review.finding_problems(finding, _FACTS, None, symbols)
        )

    def test_evidence_is_required(self) -> None:
        problems = review.finding_problems(_without(_contradiction(), "evidence"), _FACTS)
        assert any(p.startswith("a code_contradiction must carry evidence") for p in problems)

    @pytest.mark.parametrize(
        ("evidence", "problem"),
        [
            ([{"signature": "load(path)"}], "evidence[0].signature isn't pyeye's"),
            (
                [{"docstring": "Returns None on a missing file"}],
                "evidence[0].docstring isn't in pkg._impl.load",
            ),
            ([{"docstring": "the"}], "evidence[0].docstring must quote at least 4 words"),
            ([{"docstring": "Read the file. Rai"}], "evidence[0].docstring isn't in"),
            (
                [{"edge": "callees", "includes": ["os.remove"]}],
                "doesn't list ['os.remove']",
            ),
            ([{"edge": "subclasses", "includes": ["x"]}], "pyeye can't expand 'subclasses'"),
            ([{"edge": "callees", "includes": []}], "includes must list the handles"),
            ([{"source": "def load"}], "evidence[0] must be one of"),
        ],
    )
    def test_evidence_must_be_what_pyeye_reports(
        self, evidence: list[dict[str, Any]], problem: str
    ) -> None:
        problems = review.finding_problems(_contradiction(evidence=evidence), _FACTS, None, _syms())
        assert any(problem in p for p in problems), problems

    def test_it_is_always_a_clear_fix(self) -> None:
        finding = _without(_contradiction(), "replacement")
        finding.update(
            needs_decision=True,
            question="Which is right?",
            options=[{"text": "a", "cost": "b"}, {"text": "c", "cost": "d"}],
            assessment=f"{review.UNANCHORED}: x",
        )
        problems = review.finding_problems(finding, _FACTS)
        assert "a code_contradiction is a clear fix: route it to a fact, an example or wording" in (
            problems
        )

    @pytest.mark.parametrize(
        ("overrides", "problem"),
        [
            (
                {"route": None},
                "must say its route, one of ['fact', 'example', 'link', 'delete', 'code_bug', "
                "'wording']",
            ),
            ({"route": "guess"}, "must say its route"),
            ({"route": "fact"}, "a fact route names its extractor"),
            ({"route": "wording", "route_reason": " "}, "a wording route must say why neither"),
        ],
    )
    def test_it_must_say_its_route(self, overrides: dict[str, Any], problem: str) -> None:
        problems = review.finding_problems(_contradiction(**overrides), _FACTS)
        assert any(problem in p for p in problems), problems

    @pytest.mark.parametrize(
        "overrides",
        [
            {"route": "fact", "extractor": "env"},
            {"route": "fact", "extractor": "new: the analyzers' hard-coded defaults"},
            {
                "route": "example",
                "replacement": '```json pyeye-example tool=resolve\n{"identifier": "load"}\n```',
            },
        ],
    )
    def test_a_fact_or_example_route_needs_no_reason(self, overrides: dict[str, Any]) -> None:
        finding = _without(_contradiction(), "route_reason")
        finding.update(overrides)
        assert review.finding_problems(finding, _FACTS, None, _syms()) == []

    def test_it_rests_on_a_symbol(self) -> None:
        finding = _contradiction(anchor={"kind": "fact", "id": _TTL.id})
        assert "a code_contradiction finding rests on a symbol or literal anchor" in (
            review.finding_problems(finding, _FACTS)
        )

    def test_project_symbols_uses_pyeye(self) -> None:
        symbols = review.project_symbols(_ROOT)
        handle = "pyeye.resolver.resolve_handle"
        assert symbols.canonical(handle) == handle
        assert symbols.canonical("pyeye.resolver.no_such_function") is None
        assert symbols.canonical("os.path.join") is None  # external: not a project symbol
        surface = symbols.surface(handle)
        assert surface is not None
        assert surface["signature"].startswith("resolve_handle(path: str")
        assert "Never raises for a miss" in surface["docstring"]
        assert "pyeye.resolver.Resolved" in (symbols.edge(handle, "callees") or [])

    @pytest.mark.usefixtures("memory_state")
    def test_validate_resolves_symbols_and_checks_evidence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        handle = "pyeye.resolver.resolve_handle"
        good = _contradiction(
            section=_README_SECTION,
            anchor={"kind": "symbol", "id": handle},
            evidence=[{"docstring": "Never raises for a miss."}],
        )
        assert review.main(["validate", str(_write(tmp_path, [good]))], root=_ROOT) == 0
        assert json.loads(capsys.readouterr().out) == {
            "ok": True,
            "accepted": 1,
            "rejected": 0,
            "shown": [{"index": 0, "status": "new"}],
        }
        bad = {**good, "anchor": {"kind": "symbol", "id": "pyeye.resolver.nope"}}
        assert review.main(["validate", str(_write(tmp_path, [bad]))], root=_ROOT) == 1
        assert "doesn't resolve in the project" in capsys.readouterr().out
        wrong = {**good, "evidence": [{"docstring": "Always raises an error here."}]}
        assert review.main(["validate", str(_write(tmp_path, [wrong]))], root=_ROOT) == 1
        assert "isn't in pyeye.resolver.resolve_handle's docstring" in capsys.readouterr().out


class TestSymbolDismissals:
    """C15: pinned to the signature and docstring; an unresolved handle is an orphan."""

    def test_a_body_edit_keeps_it_and_a_docstring_change_lapses_it(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, _contradiction(), _FACTS, "fine", "2026-11-18", None, _syms())
        assert review.triage([_contradiction()], state, _FACTS, None, _syms()) == []
        changed = _syms(surfaces={_LOAD: {"signature": _SIG, "docstring": "Read it."}})
        assert review.triage([_contradiction()], state, _FACTS, None, changed) == [
            (_contradiction(), "resurfaced")
        ]

    def test_it_needs_pyeye_to_pin(self) -> None:
        with pytest.raises(ValueError, match="needs pyeye"):
            review.dismiss_finding({}, _contradiction(), _FACTS, "fine", "2026-11-18")

    def test_an_unresolved_handle_is_an_orphan_and_moves_to_its_new_handle(self) -> None:
        state: dict[str, Any] = {}
        entry = review.dismiss_finding(
            state, _contradiction(), _FACTS, "fine", "2026-11-18", None, _syms()
        )
        renamed = "pkg._impl.read"
        after = _syms(
            canonical={renamed: renamed},
            surfaces={renamed: {"signature": _SIG, "docstring": _DOC}},
        )
        (message,) = review.orphaned(state, _FACTS, None, after)
        assert "names symbol 'pkg._impl.load', which no longer resolves in the project" in message
        assert f"move {entry['key']} <new canonical handle>" in message
        with pytest.raises(ValueError, match="isn't the canonical handle"):
            review.move(state, entry["key"], "pkg.read", _FACTS, None, after)
        review.move(state, entry["key"], renamed, _FACTS, None, after)
        assert review.orphaned(state, _FACTS, None, after) == []
        moved = _contradiction(anchor={"kind": "symbol", "id": renamed})
        assert review.triage([moved], state, _FACTS, None, after) == []

    def test_a_live_symbol_dismissal_doesnt_move(self) -> None:
        state: dict[str, Any] = {}
        entry = review.dismiss_finding(
            state, _contradiction(), _FACTS, "fine", "2026-11-18", None, _syms()
        )
        with pytest.raises(ValueError, match="still exists"):
            review.move(state, entry["key"], _LOAD, _FACTS, None, _syms())


class TestSubjects:
    """C15: a rule anchor's subject is part of the key and must stay in its section."""

    def _style(self, subject: str, **overrides: Any) -> dict[str, Any]:
        finding = _clear(
            page="page.md",
            section="links",
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
            subject=subject,
            problem="The link target is missing.",
            replacement="Link docs/testing/ instead.",
        )
        finding.update(overrides)
        return finding

    def test_a_rule_finding_must_quote_its_subject(self) -> None:
        problems = review.finding_problems(_without(self._style("x"), "subject"), _FACTS)
        assert "a finding on a rule anchor must quote its subject: the exact text it is about" in (
            problems
        )

    def test_the_subject_must_occur_in_the_section(self) -> None:
        good = _clear(
            section=_README_SECTION,
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
            subject=_README_SUBJECT.replace(" ", "   \n", 1),
        )
        assert review.finding_problems(_hashed(good, _ROOT), _FACTS, _ROOT) == []
        bad = {**good, "subject": "Not on the page"}
        assert review.finding_problems(_hashed(bad, _ROOT), _FACTS, _ROOT) == [
            f"subject 'Not on the page' doesn't occur verbatim in README.md#{_README_SECTION}"
        ]

    def test_a_different_subject_is_a_new_finding_not_a_hidden_one(self) -> None:
        state: dict[str, Any] = {}
        review.dismiss_finding(state, self._style("[a](gone.md)"), _FACTS, "fine", "2026-11-18")
        assert review.triage([self._style("[a](gone.md)")], state, _FACTS) == []
        other = self._style("[b](also-gone.md)")
        assert review.triage([other], state, _FACTS) == [(other, "new")]

    def test_a_vanished_subject_lapses_and_check_stays_green(self, tmp_path: Path) -> None:
        """C16: a prose edit never turns CI red; the next review run prunes the entry."""
        page = tmp_path / "page.md"
        page.write_text("# Links\nSee [a](gone.md).\n", encoding="utf-8")
        state: dict[str, Any] = {}
        entry = review.dismiss_finding(
            state, self._style("[a](gone.md)"), _FACTS, "fine", "2026-11-18"
        )
        assert not review.subject_lapsed(entry, tmp_path)
        page.write_text("# Links\nSee [the docs](gone.md).\n", encoding="utf-8")
        assert review.subject_lapsed(entry, tmp_path)
        assert review.orphaned(state, _FACTS, tmp_path) == []
        assert review.prune(state, tmp_path) == ["page.md#links"]
        assert state["confirmed_non_issues"] == []
        reworded = self._style("[the docs](gone.md)")
        assert review.triage([reworded], state, _FACTS) == [(reworded, "new")]

    def test_a_lapsed_subject_can_still_move_to_the_reworded_text(self, tmp_path: Path) -> None:
        page = tmp_path / "page.md"
        page.write_text("# Links\nSee [a](gone.md).\n", encoding="utf-8")
        state: dict[str, Any] = {}
        entry = review.dismiss_finding(
            state, self._style("[a](gone.md)"), _FACTS, "fine", "2026-11-18"
        )
        with pytest.raises(ValueError, match="still exists"):
            review.move(state, entry["key"], "[a](gone.md)", _FACTS, tmp_path)
        page.write_text("# Links\nSee [the docs](gone.md).\n", encoding="utf-8")
        with pytest.raises(ValueError, match="doesn't occur verbatim"):
            review.move(state, entry["key"], "[c](x.md)", _FACTS, tmp_path)
        review.move(state, entry["key"], "[the docs](gone.md)", _FACTS, tmp_path)
        assert review.prune(state, tmp_path) == []
        moved = self._style("[the docs](gone.md)")
        assert review.triage([moved], state, _FACTS) == []


class TestReviewFixes864:
    """The #864 review: real aliases, weak evidence, repeated subjects, route references."""

    @pytest.fixture
    def alias_project(self, tmp_path: Path) -> Path:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("from .core import run\n", encoding="utf-8")
        (tmp_path / "pkg" / "core.py").write_text(
            'def run():\n    """Run the job once and return nothing."""\n', encoding="utf-8"
        )
        return tmp_path

    def test_a_relative_re_export_is_an_alias_with_the_real_resolver(
        self, alias_project: Path
    ) -> None:
        symbols = review.project_symbols(alias_project)
        assert symbols.canonical("pkg.run") == "pkg.core.run"
        assert symbols.canonical("pkg.core.run") == "pkg.core.run"
        finding = _contradiction(
            anchor={"kind": "symbol", "id": "pkg.run"},
            evidence=[{"docstring": "Run the job once"}],
        )
        assert "anchor must use the canonical handle 'pkg.core.run', not 'pkg.run'" in (
            review.finding_problems(finding, _FACTS, None, symbols)
        )

    def test_the_resolver_itself_collapses_a_relative_re_export(self, alias_project: Path) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.resolver import Resolved, resolve_handle

        found = resolve_handle("pkg.run", JediAnalyzer(alias_project.as_posix()))
        assert isinstance(found, Resolved)
        assert found.handle == "pkg.core.run"

    @pytest.mark.parametrize(
        "init",
        [
            "try:\n    from .thing import Maybe\nexcept ImportError:\n    Maybe = None\n",
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
            "    from .thing import Maybe\nelse:\n    Maybe = object\n",
        ],
        ids=["try_except", "type_checking"],
    )
    def test_canonical_follows_a_branched_re_export(self, tmp_path: Path, init: str) -> None:
        """The resolver keeps the first binding here by design (#857, #871); the anchor follows it."""
        from pyeye.docs_facts.review import _ProjectSymbols

        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text(init, encoding="utf-8")
        (tmp_path / "pkg" / "thing.py").write_text("class Maybe:\n    pass\n", encoding="utf-8")

        assert _ProjectSymbols(tmp_path).canonical("pkg.Maybe") == "pkg.thing.Maybe"

    def test_a_subject_must_occur_exactly_once(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text(
            "# Features\nSee [docs](a.md) and [docs](b.md). Also [guide](c.md).\n",
            encoding="utf-8",
        )
        finding = _clear(
            section="features",
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
            subject="[docs]",
        )
        (problem,) = review.finding_problems(_hashed(finding, tmp_path), _FACTS, tmp_path)
        assert problem.startswith("subject '[docs]' occurs 2 times in README.md#features")
        unique = {**finding, "subject": "[docs](b.md)"}
        assert review.finding_problems(_hashed(unique, tmp_path), _FACTS, tmp_path) == []

    def test_a_fact_route_names_a_registered_or_new_extractor(self) -> None:
        finding = _contradiction(route="fact", extractor="the defaults one")
        (problem,) = [p for p in review.finding_problems(finding, _FACTS) if "extractor" in p]
        assert problem.startswith("a fact route names its extractor: one of [")
        assert "'new: <what it reads>'" in problem

    def test_an_example_route_needs_an_example(self, tmp_path: Path) -> None:
        bare = _contradiction(route="example")
        assert any(
            p.startswith("an example route points at a runnable example")
            for p in review.finding_problems(bare, _FACTS)
        )
        page = tmp_path / "README.md"
        page.write_text(
            '# Features\nx\n\n```json pyeye-example tool=resolve\n{"identifier": "x"}\n```\n',
            encoding="utf-8",
        )
        at = _contradiction(
            section="features", route="example", example_at={"page": "README.md", "line": 4}
        )
        assert review.finding_problems(_hashed(at, tmp_path), _FACTS, tmp_path) == []
        wrong = {**at, "example_at": {"page": "README.md", "line": 2}}
        assert "no runnable example opens at README.md:2" in (
            review.finding_problems(_hashed(wrong, tmp_path), _FACTS, tmp_path)
        )
        assert (
            "example_at must be {page, line}"
            in review.finding_problems({**at, "example_at": "README.md:4"}, _FACTS)[0]
        )


class TestProposalsMeetTheRules:
    """#829-3: a finding's own proposed wording must meet D12 and C15."""

    def test_an_unbacked_claim_in_a_replacement_is_rejected(self) -> None:
        finding = _clear(replacement="It used ~17,500 bytes, 0.03× the old size.")
        problems = review.proposal_problems(finding, _FACTS)
        assert any("replacement adds an unbacked claim (size" in p for p in problems)
        assert any("replacement adds an unbacked claim (multiplier" in p for p in problems)
        assert problems == [p for p in review.finding_problems(finding, _FACTS) if "unbacked" in p]

    def test_an_unbacked_claim_in_an_option_is_rejected(self) -> None:
        options = [
            {"text": "Keep the table; it is 2x faster.", "cost": "an unbacked claim"},
            {"text": "Link the record instead.", "cost": "one more click"},
        ]
        problems = review.proposal_problems(_ambiguous(options=options), _FACTS)
        assert len(problems) == 1
        assert problems[0].startswith("options[0].text adds an unbacked claim (multiplier")

    def test_a_replacement_cant_restate_the_anchor_fact(self) -> None:
        finding = _clear(replacement="The TTL is set by PYEYE_CACHE_TTL to 300.")
        assert review.proposal_problems(finding, _FACTS) == [
            "replacement restates the value '300' of fact env.PYEYE_CACHE_TTL: show it "
            "through a fact block for env.PYEYE_CACHE_TTL instead"
        ]

    def test_a_value_inside_a_fact_block_is_bound_not_restated(self) -> None:
        bound = "The TTL is <!-- fact:begin env.PYEYE_CACHE_TTL.default -->300<!-- fact:end -->."
        assert review.proposal_problems(_clear(replacement=bound), _FACTS) == []


class TestFeedback829_3:
    """#829-3: subject in identity, duplicates, page_hash, seeds and D12-measurement."""

    def _link(self, subject: str) -> dict[str, Any]:
        return _clear(
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
            subject=subject,
            replacement="Link docs/testing/ instead.",
        )

    @pytest.mark.parametrize(
        "finding",
        [
            _clear(),
            _contradiction(),
            _clear(
                category="style",
                anchor={"kind": "style_rule", "id": "broken-link"},
                subject="[a](gone.md)",
            ),
        ],
        ids=["fact", "symbol", "rule"],
    )
    def test_finding_identity_equals_dismissal_identity(self, finding: dict[str, Any]) -> None:
        """Two findings share a key exactly when their dismissals would share an identity."""
        other_subject = (
            {**finding, "subject": "[b](also-gone.md)"} if "subject" in finding else None
        )
        reworded = {**finding, "problem": "different words", "replacement": "Different fix."}
        assert review.finding_key(reworded) == review.finding_key(finding)
        state: dict[str, Any] = {}
        review.dismiss_finding(state, finding, _FACTS, "fine", "2026-11-18", None, _syms())
        assert review.triage([reworded], state, _FACTS, None, _syms()) == []
        if other_subject is not None:
            assert review.finding_key(other_subject) != review.finding_key(finding)
            assert review.triage([other_subject], state, _FACTS, None, _syms()) == [
                (other_subject, "new")
            ]

    def test_two_links_in_one_section_are_two_findings(self) -> None:
        assert review.batch_problems([self._link("[a](x.md)"), self._link("[b](y.md)")]) == {}

    def test_a_repeated_finding_in_a_batch_is_rejected(self) -> None:
        repeat = {**self._link("[a](x.md)"), "problem": "said again"}
        assert review.batch_problems([self._link("[a](x.md)"), repeat]) == {
            "1": [
                "repeats finding 0: one finding per page, section, category, anchor and (for a "
                "rule anchor) subject; merge them"
            ]
        }

    def test_a_finding_against_a_changed_page_is_rejected(self, tmp_path: Path) -> None:
        page = tmp_path / "README.md"
        page.write_text("# Features\nOld text.\n", encoding="utf-8")
        finding = _hashed(_clear(section="features"), tmp_path)
        assert review.finding_problems(finding, _FACTS, tmp_path) == []
        page.write_text("# Features\nNew text.\n", encoding="utf-8")
        (problem,) = review.finding_problems(finding, _FACTS, tmp_path)
        assert problem.startswith("page README.md changed since scope (page_hash")
        assert problem.endswith("re-run scope for README.md")
        unhashed = _without(finding, "page_hash")
        assert "changed since scope" in review.finding_problems(unhashed, _FACTS, tmp_path)[0]

    def test_packets_carry_the_page_hash_and_its_claim_seeds(self, repo_facts: Any) -> None:
        from pyeye.docs_facts.claim_seeds import SEEDS

        seeded = next(iter(sorted(SEEDS)))
        out = review.scope(_ROOT, repo_facts, pages=[seeded])
        (page,) = out["pages"]
        text = (_ROOT / seeded).read_text(encoding="utf-8")
        assert page["page_hash"] == review.page_hash(text)
        assert page["claim_seeds"] == list(SEEDS[seeded])

    def test_d12_measurement_is_a_claims_rule(self) -> None:
        finding = _clear(
            category="honest_claims",
            anchor={"kind": "claims_rule", "id": "D12-measurement"},
            subject="p95",
            replacement="Link the dated benchmark record, or delete the table.",
        )
        assert review.finding_problems(finding, _FACTS) == []

    def test_validate_reports_a_repeated_finding(
        self, tmp_path: Path, memory_state: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        finding = _clear(
            section=_README_SECTION,
            category="style",
            anchor={"kind": "style_rule", "id": "broken-link"},
            subject=_README_SUBJECT,
            replacement="Link docs/testing/ instead.",
        )
        path = _write(tmp_path, [finding, {**finding, "problem": "again"}])
        assert review.main(["validate", str(path)], root=_ROOT) == 1
        assert '"1": [' in capsys.readouterr().out
        assert memory_state["confirmed_non_issues"] == []


def test_packets_list_the_facts_a_page_names_without_binding(tmp_path: Path) -> None:
    """worker-4's caching.md case: an env var restated by hand is anchorable.

    Built from its own page, not a live doc: a docs PR that binds the fact
    (as #877 did for caching.md) must not break it.
    """
    ttl = Fact("env.PYEYE_CACHE_TTL", {"default": 300}, "`PYEYE_CACHE_TTL`")
    debounce = Fact("env.PYEYE_WATCHER_DEBOUNCE", {"default": 0.5}, "`PYEYE_WATCHER_DEBOUNCE`")
    facts: dict[str, Any] = {ttl.id: ttl, debounce.id: debounce}
    (tmp_path / "page.md").write_text(
        "# Caching\n"
        "The debounce is <!-- fact:begin env.PYEYE_WATCHER_DEBOUNCE -->x<!-- fact:end -->.\n"
        "Entries live `PYEYE_CACHE_TTL` seconds.\n",
        encoding="utf-8",
    )
    entry = type("E", (), {"audience": "human", "kind": "prose", "covers": ()})()
    page = review.packet(tmp_path, "page.md", entry, facts, {})
    assert list(page["facts"]) == [debounce.id]
    assert list(page["mentioned"]) == [ttl.id]


def test_mentioned_facts_match_names_not_substrings() -> None:
    ttl = Fact("env.PYEYE_CACHE_TTL", {"default": 300}, "`PYEYE_CACHE_TTL`")
    tool = Fact("tool.trace", {}, "`trace`")
    facts = {ttl.id: ttl, tool.id: tool}
    assert review.mentioned_facts("Set PYEYE_CACHE_TTL.", facts, []) == [ttl.id]
    assert review.mentioned_facts("Set PYEYE_CACHE_TTL_X.", facts, []) == []
    assert review.mentioned_facts("Call `trace` here.", facts, []) == [tool.id]
    assert review.mentioned_facts("Call `trace` here.", facts, [tool.id]) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"default": 300}, "300"),
        (0.5, "0.5"),
        ("main", "main"),
        (True, None),
        (None, None),
        (7, None),  # one digit: too common to spot as a restatement
        ("ab", None),
        (["a", "b"], None),
    ],
)
def test_restatable_values(value: Any, expected: str | None) -> None:
    """Only a distinctive scalar value counts as hand-written when it appears in prose."""
    assert review._restatable(value) == expected


def test_a_string_fact_value_restated_in_a_replacement_is_rejected() -> None:
    fallback = Fact("scope.default.plugin", "main", "`main`")
    finding = _clear(
        anchor={"kind": "fact", "id": fallback.id},
        replacement="Plugins fall back to main.",
    )
    assert review.proposal_problems(finding, {fallback.id: fallback}) == [
        "replacement restates the value 'main' of fact scope.default.plugin: show it through "
        "a fact block for scope.default.plugin instead"
    ]


def test_batch_problems_skips_a_finding_too_malformed_to_key() -> None:
    """Its own shape problems explain it; the batch check doesn't crash on it."""
    good = _clear()
    assert review.batch_problems([{"page": "README.md"}, good, {**good}]) == {
        "2": [
            "repeats finding 1: one finding per page, section, category, anchor and (for a "
            "rule anchor) subject; merge them"
        ]
    }


class TestC17:
    """#829-4: the maintainer's C17 rulings and the run feedback."""

    def test_a_page_level_finding_uses_star(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# A\nx\n# B\ny\n", encoding="utf-8")
        finding = _clear(
            section=review.PAGE,
            category="style",
            anchor={"kind": "style_rule", "id": "orphaned-text"},
            subject="# B",
            replacement="Delete the fictitious suite; link docs/testing/ instead.",
        )
        assert review.finding_problems(_hashed(finding, tmp_path), _FACTS, tmp_path) == []
        assert review.section_text(tmp_path, "README.md", "*") == "# A\nx\n# B\ny\n"

    def test_a_fact_finding_cant_be_page_level(self) -> None:
        problems = review.finding_problems(_clear(section="*"), _FACTS)
        assert (
            "a fact_drift finding is a clear fix in one section; '*' is for page-wide defects"
            in (problems)
        )

    def test_a_page_level_dismissal_survives_prune_while_the_page_exists(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "page.md").write_text("# A\n", encoding="utf-8")
        state: dict[str, Any] = {}
        finding = _clear(
            page="page.md",
            section="*",
            category="style",
            anchor={"kind": "style_rule", "id": "orphaned-text"},
            subject="# A",
        )
        review.dismiss_finding(state, finding, _FACTS, "fine", "2026-11-18")
        assert review.prune(state, tmp_path) == []
        (tmp_path / "page.md").unlink()
        assert review.prune(state, tmp_path) == ["page.md#*"]

    def _literal(self, text: str, **overrides: Any) -> dict[str, Any]:
        finding = _contradiction(anchor={"kind": "literal", "id": text}, route="wording")
        finding.pop("evidence")
        finding.update(overrides)
        return finding

    def test_a_literal_anchor_must_be_a_whole_literal_in_src(self) -> None:
        good = self._literal("Package path does not exist: {}")
        assert review.finding_problems(good, _FACTS, None, _syms()) == []
        partial = self._literal("Package path does not")
        (problem,) = review.finding_problems(partial, _FACTS, None, _syms())
        assert "isn't a whole string literal in src/" in problem

    def test_src_literals_parses_strings_and_f_string_parts(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "m.py").write_text(
            '# "a comment string"\nx = "plain"\ny = f"Missing {name}: try again"\n',
            encoding="utf-8",
        )
        found = review.src_literals(tmp_path)
        assert {"plain", "Missing ", ": try again"} <= found
        assert "a comment string" not in found

    def test_a_literal_that_left_src_is_an_orphan_and_moves(self) -> None:
        state: dict[str, Any] = {}
        finding = self._literal("Package path does not exist: {}")
        entry = review.dismiss_finding(state, finding, _FACTS, "fine", "2026-11-18", None, _syms())
        after = _syms(literals=frozenset({"Package path is missing: {}"}))
        (message,) = review.orphaned(state, _FACTS, None, after)
        assert "which is no longer a literal in src/" in message
        review.move(state, entry["key"], "Package path is missing: {}", _FACTS, None, after)
        assert review.orphaned(state, _FACTS, None, after) == []

    @pytest.mark.parametrize(
        ("overrides", "problem"),
        [
            ({"route": "link"}, "a link route names its `link`"),
            ({"route": "code_bug"}, "blocked_by: '#N'"),
            ({"route": "code_bug", "blocked_by": "851"}, "blocked_by: '#N'"),
        ],
    )
    def test_link_and_code_bug_routes_need_their_target(
        self, overrides: dict[str, Any], problem: str
    ) -> None:
        problems = review.finding_problems(_contradiction(**overrides), _FACTS)
        assert any(problem in p for p in problems), problems

    def test_link_delete_and_code_bug_routes_pass(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "perf.py").write_text("", encoding="utf-8")
        for overrides in (
            {"route": "link", "link": "tests/perf.py"},
            {"route": "delete"},
            {"route": "code_bug", "blocked_by": "#851"},
        ):
            finding = _without(_contradiction(**overrides), "route_reason")
            assert review._route_problems(finding, tmp_path) == [], overrides
        missing = _contradiction(route="link", link="tests/gone.py")
        assert review._route_problems(missing, tmp_path) == [
            "link target 'tests/gone.py' doesn't exist in the repo"
        ]

    def test_a_closed_blocking_issue_lifts_the_dismissal(self) -> None:
        state: dict[str, Any] = {}
        finding = _contradiction(route="code_bug", blocked_by="#851")
        entry = review.dismiss_finding(
            state, finding, _FACTS, "deliberate", "2026-11-18", None, _syms()
        )
        assert entry["blocked_by"] == "#851"
        assert review.lift_blocked(state, lambda _n: None) == []  # offline: left alone
        assert review.lift_blocked(state, lambda _n: False) == []  # still open
        assert [e["key"] for e in review.lift_blocked(state, lambda n: n == 851)] == [entry["key"]]
        assert state["confirmed_non_issues"] == []

    def test_a_contradictory_directive_needs_a_decision(self) -> None:
        clear = _clear(
            category="audience",
            anchor={"kind": "audience_rule", "id": "contradictory-directive"},
            subject="always run X",
        )
        assert "a contradictory-directive finding needs a decision: which directive wins" in (
            review.finding_problems(clear, _FACTS)
        )
        decided = _ambiguous(
            anchor={"kind": "audience_rule", "id": "contradictory-directive"},
            recommendation_anchor={"kind": "audience_rule", "id": "link-not-restate"},
        )
        assert review.finding_problems(decided, _FACTS) == []

    def test_new_rule_ids(self) -> None:
        assert {"D12-volatile", "D12-number"} <= set(review.RULE_IDS["claims_rule"])
        assert "duplicated-prose" in review.RULE_IDS["style_rule"]
        assert "duplication" not in review.RULE_IDS["style_rule"]

    def test_packets_list_bound_views(self, tmp_path: Path) -> None:
        ttl = Fact("env.PYEYE_CACHE_TTL", {"default": 300}, "`PYEYE_CACHE_TTL`")
        facts: dict[str, Any] = {ttl.id: ttl, "env.PYEYE_CACHE_TTL.default": view("x", [ttl], "")}
        (tmp_path / "p.md").write_text(
            "# P\n<!-- fact:begin env.PYEYE_CACHE_TTL.default -->300<!-- fact:end -->\n",
            encoding="utf-8",
        )
        entry = type("E", (), {"audience": "human", "kind": "prose", "covers": ()})()
        assert review.packet(tmp_path, "p.md", entry, facts, {})["views"] == [
            "env.PYEYE_CACHE_TTL.default"
        ]

    def test_validate_stdout_is_json_only(
        self, tmp_path: Path, memory_state: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        import logging

        logging.getLogger("pyeye").warning("a log line that must not reach stdout")
        finding = _contradiction(
            section=_README_SECTION,
            anchor={"kind": "symbol", "id": "pyeye.resolver.resolve_handle"},
            evidence=[{"docstring": "Never raises for a miss."}],
            route="wording",
        )
        assert review.main(["validate", str(_write(tmp_path, [finding]))], root=_ROOT) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True and out["accepted"] == 1
        assert memory_state["confirmed_non_issues"] == []


def test_the_reviewer_prompt_lists_exactly_the_registered_extractors() -> None:
    """The fact route's extractor list in reviewer.md can't drift from the registry."""
    from pyeye.docs_facts.registry import EXTRACTORS

    prompt = (_ROOT / ".claude/skills/docs-review/reviewer.md").read_text(encoding="utf-8")
    listed = re.search(r"extractor that would produce it \(([^)]*)\)", " ".join(prompt.split()))
    assert listed is not None
    assert re.findall(r"`(\w+)`", listed.group(1)) == [e.name for e in EXTRACTORS]


class TestC17Coverage:
    """The paths the C17 tests above don't reach: real literals, gh, move's refusals, the CLI."""

    def test_project_symbols_has_literal_and_skips_unparseable_files(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "ok.py").write_text('MSG = "Package path does not exist"\n')
        (tmp_path / "src" / "broken.py").write_text("def broken(:\n")
        symbols = review.project_symbols(tmp_path)
        assert symbols.has_literal("Package path does not exist")
        assert not symbols.has_literal("Package path")

    @pytest.mark.parametrize(
        ("returncode", "stdout", "expected"),
        [(0, "CLOSED\n", True), (0, "OPEN\n", False), (1, "", None)],
    )
    def test_gh_issue_closed_reads_gh(
        self, monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, expected: bool | None
    ) -> None:
        import subprocess  # nosec B404 - only the fake below runs

        seen: list[list[str]] = []

        def fake(args: list[str], **_kwargs: Any) -> Any:
            seen.append(args)
            return subprocess.CompletedProcess(args, returncode, stdout, "")

        monkeypatch.setattr(subprocess, "run", fake)
        assert review.gh_issue_closed(851) is expected
        assert seen == [["gh", "issue", "view", "851", "--json", "state", "-q", ".state"]]

    def test_gh_issue_closed_is_unknown_without_gh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess  # nosec B404 - only the fake below runs

        def missing(*_args: Any, **_kwargs: Any) -> Any:
            raise FileNotFoundError("gh")

        monkeypatch.setattr(subprocess, "run", missing)
        assert review.gh_issue_closed(851) is None

    def test_move_needs_pyeye_for_a_symbol_or_literal(self) -> None:
        state: dict[str, Any] = {}
        finding = TestC17()._literal("Package path does not exist: {}")
        entry = review.dismiss_finding(state, finding, _FACTS, "fine", "2026-11-18", None, _syms())
        with pytest.raises(ValueError, match="moving a literal needs pyeye"):
            review.move(state, entry["key"], "x", _FACTS, None, None)

    def test_move_refuses_a_new_string_that_isnt_a_literal(self) -> None:
        state: dict[str, Any] = {}
        finding = TestC17()._literal("Package path does not exist: {}")
        entry = review.dismiss_finding(state, finding, _FACTS, "fine", "2026-11-18", None, _syms())
        gone = _syms(literals=frozenset({"Something else"}))
        with pytest.raises(ValueError, match="isn't a whole string literal in src/"):
            review.move(state, entry["key"], "Not one either", _FACTS, None, gone)

    def test_lift_blocked_on_the_command_line(
        self,
        memory_state: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        finding = _contradiction(route="code_bug", blocked_by="#851")
        entry = review.dismiss_finding(
            memory_state, finding, _FACTS, "deliberate", "2026-11-18", None, _syms()
        )
        monkeypatch.setattr(review, "gh_issue_closed", lambda number: number == 851)
        assert review.main(["lift-blocked"], root=_ROOT) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["lifted"] == [{"key": entry["key"], "blocked_by": "#851"}]
        assert memory_state["confirmed_non_issues"] == []
