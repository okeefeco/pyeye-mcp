"""The architecture finding shape, in the generalised review validator (#1178, #1132 R6).

``docs_facts/review.py`` checks both review kinds. An architecture finding says
``review: "architecture"``; its category is its outcome (adherence, deviation,
decision needed, ambiguity), and each outcome rests on its own anchor kinds. A
docs finding is unchanged, with ``review`` absent or ``"docs"``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.docs_facts import review
from pyeye.docs_facts.review import UNANCHORED, finding_key, finding_problems


def _finding(category: str, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "review": "architecture",
        "area": "pkg",
        "category": category,
        "problem": "what was found",
        "anchor": {"kind": "decision", "id": "2026-01-01-1-a-rule.md"},
        "evidence": ["pkg.mod.func"],
    }
    if category == "deviation":
        base["recommendation"] = "make it follow the decision"
    if category in ("decision_needed", "ambiguity"):
        base["anchor"] = {"kind": "symbol", "id": "pkg.mod.func"}
        base["question"] = "which pattern should this area use?"
    if category == "decision_needed":
        base["proposal"] = "every handler logs through the module logger"
    if category == "ambiguity":
        base["options"] = [{"text": "A", "cost": "x"}, {"text": "B", "cost": "y"}]
        base["assessment"] = f"{UNANCHORED}: B is more common"
    base.update(fields)
    return base


class _Symbols:
    def canonical(self, handle: str) -> str | None:
        return {"pkg.mod.func": "pkg.mod.func", "pkg.Func": "pkg.mod.func"}.get(handle)

    def surface(self, _handle: str) -> dict[str, str] | None:
        return None

    def edge(self, _handle: str, _edge: str) -> list[str] | None:
        return None

    def has_literal(self, _text: str) -> bool:
        return False


class TestEachOutcomeIsValid:
    @pytest.mark.parametrize("category", review.OUTCOMES)
    def test_the_minimal_finding_of_each_outcome_passes(self, category: str) -> None:
        assert finding_problems(_finding(category)) == []

    def test_an_adherence_needs_no_evidence(self) -> None:
        assert finding_problems(_finding("adherence", evidence=[])) == []

    def test_an_ambiguity_may_recommend_an_option_on_an_anchor(self) -> None:
        finding = _finding(
            "ambiguity",
            recommended=1,
            recommendation_anchor={"kind": "fact", "id": "arch.members.pkg.mod"},
        )
        del finding["assessment"]

        assert finding_problems(finding, facts={"arch.members.pkg.mod": object()}) == []  # type: ignore[dict-item]


class TestEachAnchorKind:
    @pytest.mark.parametrize(
        ("anchor", "fine"),
        [
            ({"kind": "rule", "id": "no-import: pkg.core -> pkg.cli"}, True),
            ({"kind": "rule", "id": "pkg.core must not import pkg.cli"}, False),
            ({"kind": "decision", "id": "2026-01-01-1-a-rule.md"}, True),
            ({"kind": "decision", "id": "docs/decisions/entries/x.md"}, False),
            ({"kind": "decision", "id": "a rule"}, False),
            ({"kind": "convention", "id": "AGENTS.md#logging"}, True),
            ({"kind": "convention", "id": "AGENTS.md"}, False),
            ({"kind": "style_rule", "id": "broken-link"}, False),
        ],
    )
    def test_record_anchors(self, anchor: dict[str, str], fine: bool) -> None:
        assert (finding_problems(_finding("deviation", anchor=anchor)) == []) is fine

    def test_a_convention_anchor_must_be_a_section_on_disk(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("# Agents\n\n## Logging\n\nUse the logger.\n")
        ok = _finding("deviation", anchor={"kind": "convention", "id": "AGENTS.md#logging"})
        gone = _finding("deviation", anchor={"kind": "convention", "id": "AGENTS.md#docstrings"})

        assert finding_problems(ok, root=tmp_path) == []
        assert any("isn't a section on disk" in p for p in finding_problems(gone, root=tmp_path))

    def test_a_fact_anchor_must_exist(self) -> None:
        finding = _finding("decision_needed", anchor={"kind": "fact", "id": "arch.members.gone"})

        problems = finding_problems(finding, facts={})

        assert any("doesn't exist" in p for p in problems)

    def test_a_symbol_anchor_must_be_canonical(self) -> None:
        finding = _finding("decision_needed", anchor={"kind": "symbol", "id": "pkg.Func"})

        problems = finding_problems(finding, symbols=_Symbols())

        assert any("canonical handle 'pkg.mod.func'" in p for p in problems)


class TestNoDeviationWithoutARecord:
    @pytest.mark.parametrize("category", ["adherence", "deviation"])
    def test_adherence_and_deviation_rest_on_a_record(self, category: str) -> None:
        finding = _finding(category, anchor={"kind": "symbol", "id": "pkg.mod.func"})

        assert "rests on a rule or decision or convention anchor" in " ".join(
            finding_problems(finding)
        )

    @pytest.mark.parametrize("category", ["decision_needed", "ambiguity"])
    def test_a_decision_needed_or_ambiguity_never_names_a_record(self, category: str) -> None:
        """By definition no record covers it."""
        finding = _finding(category, anchor={"kind": "decision", "id": "2026-01-01-1-a-rule.md"})

        assert "rests on a fact or symbol anchor" in " ".join(finding_problems(finding))


class TestTheWayForward:
    def test_a_deviation_needs_a_recommendation(self) -> None:
        finding = _finding("deviation")
        del finding["recommendation"]

        assert "a deviation must give its recommendation" in finding_problems(finding)

    def test_an_adherence_carries_no_recommendation(self) -> None:
        finding = _finding("adherence", recommendation="keep going")

        assert any("confirmation" in p for p in finding_problems(finding))

    @pytest.mark.parametrize("category", ["adherence", "deviation"])
    def test_a_settled_outcome_carries_no_decision_fields(self, category: str) -> None:
        finding = _finding(category, question="which?", options=[])

        assert any("carries no decision fields" in p for p in finding_problems(finding))

    def test_a_decision_needed_proposes_one_decision(self) -> None:
        finding = _finding("decision_needed")
        del finding["proposal"]

        assert any("propose the decision" in p for p in finding_problems(finding))

    def test_a_decision_needed_has_no_options(self) -> None:
        finding = _finding("decision_needed", options=[{"text": "A", "cost": "x"}] * 2)

        assert any("one norm, not options" in p for p in finding_problems(finding))

    def test_an_ambiguity_needs_options_and_an_assessment(self) -> None:
        finding = _finding("ambiguity", options=[{"text": "A", "cost": "x"}])
        del finding["assessment"]

        problems = " ".join(finding_problems(finding))

        assert "options" in problems
        assert UNANCHORED in problems

    @pytest.mark.parametrize("category", ["decision_needed", "ambiguity"])
    def test_a_question_is_required_and_no_recommendation(self, category: str) -> None:
        finding = _finding(category, recommendation="do X")
        del finding["question"]

        problems = " ".join(finding_problems(finding))

        assert "must state its question" in problems
        assert "carries no recommendation" in problems

    def test_needs_decision_is_a_docs_field(self) -> None:
        assert any(
            "drop needs_decision" in p
            for p in finding_problems(_finding("ambiguity", needs_decision=True))
        )


class TestEvidence:
    @pytest.mark.parametrize("category", ["deviation", "decision_needed", "ambiguity"])
    def test_a_judgment_gives_its_evidence(self, category: str) -> None:
        assert any(
            "must give its evidence" in p for p in finding_problems(_finding(category, evidence=[]))
        )

    def test_evidence_must_be_canonical_handles_that_resolve(self) -> None:
        finding = _finding("deviation", evidence=["pkg.Func", "pkg.gone"])

        problems = finding_problems(finding, symbols=_Symbols())

        assert "evidence must use the canonical handle 'pkg.mod.func', not 'pkg.Func'" in problems
        assert "evidence 'pkg.gone' doesn't resolve in the project" in problems


class TestTheReviewKind:
    def test_an_unknown_review_kind_is_rejected(self) -> None:
        assert finding_problems({"review": "code"}) == [
            "review must be one of ['docs', 'architecture'] (absent means 'docs')"
        ]

    def test_an_architecture_finding_needs_an_outcome_category(self) -> None:
        problems = finding_problems(_finding("fact_drift"))

        assert (
            "category must be one of ['adherence', 'deviation', 'decision_needed', 'ambiguity']"
            in problems
        )

    def test_review_docs_is_the_same_as_absent(self) -> None:
        """Designer's note: absent is a default, not the only spelling."""
        docs = {
            "page": "README.md",
            "section": "",
            "category": "style",
            "anchor": {"kind": "style_rule", "id": "broken-link"},
            "subject": "[x](gone.md)",
            "problem": "a broken link",
            "replacement": "[x](here.md)",
        }

        assert finding_problems({**docs, "review": "docs"}) == finding_problems(docs) == []
        assert finding_key({**docs, "review": "docs"}) == finding_key(docs)

    def test_an_architecture_key_is_area_outcome_anchor_and_evidence(self) -> None:
        one = _finding("deviation", evidence=["pkg.b", "pkg.a"])
        other = _finding("deviation", evidence=["pkg.c"])

        assert finding_key(one) == (
            "architecture",
            "pkg",
            "deviation",
            "decision",
            "2026-01-01-1-a-rule.md",
            "pkg.a",
            "pkg.b",
        )
        assert finding_key(one) != finding_key(other)
        assert review.batch_problems([one, dict(one)]) == {
            "1": review.batch_problems([one, one])["1"]
        }
