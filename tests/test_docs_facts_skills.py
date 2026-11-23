"""The shipped skills are bound to the code's facts (#825, design #818 §1).

Replaces ``test_python_explore_skill_conformance`` (#374),
``test_architecture_review_skill_conformance`` and
``test_duplication_review_skill_conformance`` (#495). Their exact-list anchors
(``<!-- pyeye-supported-edges: … -->`` and the like) are now fact blocks that
``docs_facts generate`` writes and ``check`` verifies: ``edges.implemented`` and
the ``duplication.*`` facts. What's left here can't be a block: that each fact is
*explained* in the prose, that the skill is still bound at all, and the skills'
frontmatter. ``architecture-review`` reviews an area against its recorded
architecture (#1179): its conformance is that it explains the engine's four
outcomes, and that its reviewer's example findings pass the engine's validator.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pyeye.architecture_review import taxonomy
from pyeye.docs_facts import architecture, binding, registry, review
from pyeye.docs_facts.facts import Bindable, Fact, View

ROOT = Path(__file__).parent.parent
PYTHON_EXPLORE = ".claude/skills/python-explore/SKILL.md"
ARCH_SKILL = ".claude/skills/architecture-review/SKILL.md"
ARCH_REVIEWER = ".claude/skills/architecture-review/reviewer.md"
DUP_SKILL = ".claude/skills/duplication-review/SKILL.md"


@pytest.fixture(scope="module")
def facts() -> dict[str, Bindable]:
    return registry.build(ROOT)


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _bound(path: str) -> set[str]:
    blocks, problems = binding.parse(_text(path))
    assert problems == [], problems
    return {b.fact_id for b in blocks}


def _members(facts: dict[str, Bindable], view_id: str) -> list[str]:
    group = facts[view_id]
    assert isinstance(group, View)
    return [m.rsplit(".", 1)[1] for m in group.members]


@pytest.mark.parametrize(
    ("path", "fact_ids"),
    [
        (PYTHON_EXPLORE, {"edges.implemented"}),
        (
            DUP_SKILL,
            {
                "duplication.commands",
                "duplication.flags",
                "duplication.default.min_tokens",
                "duplication.default.max_occurrences",
                "duplication.reasons",
                "duplication.filter.function_line_share",
                "duplication.filter.signature_line_share",
            },
        ),
    ],
)
def test_skill_binds_its_facts(path: str, fact_ids: set[str]) -> None:
    """Removing a block would silently unbind the skill from the code."""
    assert fact_ids <= _bound(path)


@pytest.mark.parametrize(
    ("path", "name"),
    [
        (PYTHON_EXPLORE, "python-explore"),
        (ARCH_SKILL, "architecture-review"),
        (DUP_SKILL, "duplication-review"),
    ],
)
def test_frontmatter_name_and_description(path: str, name: str) -> None:
    """The plugin resolves a skill by its name; a rename would unship it."""
    text = _text(path)
    assert re.search(rf"^name:\s*{re.escape(name)}\s*$", text, re.MULTILINE)
    assert re.search(r"^description:\s*\S", text, re.MULTILINE)


class TestPythonExplore:
    def test_no_deferred_edge_is_listed_as_supported(self, facts: dict[str, Bindable]) -> None:
        """The #1 bug class: never present a reference-backend edge as available."""
        assert set(_members(facts, "edges.implemented")).isdisjoint(
            _members(facts, "edges.deferred")
        )

    def test_every_implemented_edge_has_a_table_row(self, facts: dict[str, Bindable]) -> None:
        text = _text(PYTHON_EXPLORE)
        missing = [e for e in _members(facts, "edges.implemented") if f"| `{e}` |" not in text]
        assert not missing, f"the edge table doesn't explain {missing}"

    # TEMPORARY, until #826's removed-name rule covers the skill: pure-legacy
    # tools have no reason to appear in it at all. The honest-limits section
    # names the three #505 removals on purpose, so they aren't listed here.
    _PURE_LEGACY_TOOLS = ("lookup", "find_symbol", "goto_definition", "get_type_info")

    def test_pure_legacy_tools_absent(self) -> None:
        text = _text(PYTHON_EXPLORE)
        present = [t for t in self._PURE_LEGACY_TOOLS if t in text]
        assert not present, f"pure-legacy tools must not appear in the skill: {present}"


class TestArchitectureReview:
    """The skill over the review engine (#1179): the four outcomes, no dismissals."""

    @pytest.mark.parametrize("path", [ARCH_SKILL, ARCH_REVIEWER])
    def test_every_outcome_is_explained(self, path: str) -> None:
        text = _text(path)
        missing = [o for o in review.OUTCOMES if f"**{o}**" not in text]
        assert not missing, f"{path} doesn't explain these outcomes: {missing}"

    def test_it_runs_the_engines_commands(self) -> None:
        text = _text(ARCH_SKILL)
        for command in ("plan", "validate", "report"):
            assert f"python -m pyeye.docs_facts architecture {command}" in text or (
                f"`{command} " in text
            ), command
        assert "python -m pyeye.docs_facts architecture plan AREA" in text

    def test_it_says_what_the_engine_says_without_recorded_architecture(self) -> None:
        assert architecture.NO_ARCHITECTURE in " ".join(_text(ARCH_SKILL).split())

    def test_no_dismissals(self) -> None:
        """R7: every resolution is a decision entry; a deferral is re-reported."""
        text = _text(ARCH_SKILL)
        assert "no dismissals" in text.lower()
        for gone in ("non_issue", "confirmed_non_issues", "dismiss_finding", "state.py"):
            assert gone not in text, gone

    def test_it_codifies_through_decision_log_and_a_check_line(self) -> None:
        text = _text(ARCH_SKILL)
        assert "(../decision-log/SKILL.md)" in text
        assert "CHECK no-import: A -> B" in text

    def test_the_reviewers_example_findings_pass_the_validator(self) -> None:
        """The prompt can't teach a shape the engine rejects."""
        text = _text(ARCH_REVIEWER)
        block = text.split("```json\n", 1)[1].split("```", 1)[0]
        examples = json.loads(block)
        assert {e["category"] for e in examples} == {"deviation", "decision_needed", "ambiguity"}
        for finding in examples:
            assert review.finding_problems(finding) == [], finding

    def test_every_axis_has_a_stakes_tier(self) -> None:
        """The bucket is the ranking tier (#492): explicit for each axis, never defaulted."""
        assert set(taxonomy.AXIS_STAKES_BUCKET) == set(taxonomy.SEED_AXES)
        assert set(taxonomy.AXIS_STAKES_PRIOR) == set(taxonomy.SEED_AXES)
        assert set(taxonomy.AXIS_STAKES_BUCKET.values()) <= {"high", "med", "low"}

    def test_it_points_at_the_duplication_skill(self) -> None:
        assert "duplication-review" in _text(ARCH_SKILL)


class TestDuplicationReview:
    def test_every_command_and_flag_is_explained(self, facts: dict[str, Bindable]) -> None:
        raw = _text(DUP_SKILL)
        body = binding_free(raw)
        words = _members(facts, "duplication.commands") + [
            f"--{f}" for f in _members(facts, "duplication.flags")
        ]

        def explained(word: str) -> bool:
            # Named in prose, or bound to its own fact (a table row or bullet, #830).
            kind = "flag" if word.startswith("--") else "command"
            return f"`{word}" in body or f"fact:begin duplication.{kind}.{word.lstrip('-')} " in raw

        missing = [w for w in words if not explained(w)]
        assert not missing, f"not explained in the skill body: {missing}"

    def test_no_documented_flag_is_unknown(self, facts: dict[str, Bindable]) -> None:
        known = {f"--{f}" for f in _members(facts, "duplication.flags")} | {"--help"}
        documented = set(re.findall(r"`(--[a-z][a-z-]*)", binding_free(_text(DUP_SKILL))))
        assert documented <= known, f"no such flag: {sorted(documented - known)}"

    def test_suggested_state_file_is_named(self) -> None:
        assert ".pyeye/duplication-review.json" in _text(DUP_SKILL)

    def test_shares_render_as_the_skill_writes_them(self, facts: dict[str, Bindable]) -> None:
        share = facts["duplication.filter.signature_line_share"]
        assert isinstance(share, Fact) and share.markdown == f"{round(share.value * 100)} %"


def binding_free(text: str) -> str:
    """*text* without its fact blocks, so a check sees only the hand-written prose."""
    return re.sub(r"<!-- fact:begin \S+ -->.*?<!-- fact:end -->", "", text, flags=re.DOTALL)
