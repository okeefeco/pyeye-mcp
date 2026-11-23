"""The architecture-review skill's loop, end to end on the engine's fixture (#1179).

Acceptance for #1132's sub-issue 2: codifying an item yields a decision entry,
and the next run reports adherence to it instead of asking again (R7: no
dismissals). A decision an existing rule kind can express is drafted as a
``CHECK`` line, which the next plan runs mechanically. A deferred item, with
nothing recorded, is simply reported again. The reviewer is played by the test;
every finding goes through the engine's own validator and report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.docs_facts import architecture, cli, config, review
from pyeye.docs_facts.extractors import structure as kind
from pyeye.docs_facts.facts import Fact
from tests.test_architecture_review_engine import _entry, _repo

ENTRIES = Path("docs") / "decisions" / "entries"

#: What the reviewer finds in area ``core`` with no record covering it.
NEEDED: dict[str, Any] = {
    "review": "architecture",
    "area": "core",
    "category": "decision_needed",
    "anchor": {"kind": "fact", "id": "arch.members.pkg.paths"},
    "problem": "The area's path functions take the path as a plain str.",
    "evidence": ["pkg.paths.helper"],
    "question": "Do core's path functions take paths as str?",
    "proposal": "Core's path functions take paths as str and convert at the boundary.",
}

CODIFIED = "2026-01-02-paths-are-str.md"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The engine's fixture repository, with its real facts in the snapshot."""
    root = _repo(tmp_path)
    opts = architecture.structure_options(root)
    assert opts is not None
    facts = {i.id: i for i in kind.extract(root, opts) if isinstance(i, Fact)}
    for rel, text in cli.snapshot_texts(facts, config.load(root).paths).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _codify(root: Path, finding: dict[str, Any]) -> None:
    """What the decision-log flow writes for the user's answer: Applies-to names the sites."""
    sites = " and ".join(f"`{h}`" for h in finding["evidence"])
    name, text = _entry(CODIFIED, "active", sites)
    (root / ENTRIES / name).write_text(text, encoding="utf-8")


def _candidates(packet: dict[str, Any]) -> list[str]:
    return [d["decision"] for d in packet["decisions"]]


class TestTheLoop:
    def test_a_codified_item_is_reported_as_adherence_next_run(self, repo: Path) -> None:
        first = architecture.plan(repo, "core")
        assert architecture.problems(NEEDED, first) == []
        assert CODIFIED not in _candidates(first)

        _codify(repo, NEEDED)
        second = architecture.plan(repo, "core")

        assert CODIFIED in _candidates(second)
        confirmed = {
            **{k: NEEDED[k] for k in ("review", "area", "problem", "evidence")},
            "category": "adherence",
            "anchor": {"kind": "decision", "id": CODIFIED},
        }
        out = architecture.report(second, [confirmed])
        assert out["rejected"] == []
        assert confirmed in out["adherence"]["findings"]

    def test_once_recorded_the_question_is_a_deviation_or_adherence_not_a_decision(
        self, repo: Path
    ) -> None:
        """The recorded decision now covers the sites: a contrary finding is a deviation from it."""
        _codify(repo, NEEDED)
        packet = architecture.plan(repo, "core")
        deviation = {
            **{k: NEEDED[k] for k in ("review", "area", "problem", "evidence")},
            "category": "deviation",
            "anchor": {"kind": "decision", "id": CODIFIED},
            "recommendation": "Take the path as str.",
        }

        assert architecture.problems(deviation, packet) == []

    def test_a_deferred_item_is_simply_reported_again(self, repo: Path) -> None:
        """Nothing records a deferral: the next run has no record, so it asks again."""
        first = architecture.plan(repo, "core")
        second = architecture.plan(repo, "core")

        assert _candidates(first) == _candidates(second)
        assert architecture.report(second, [NEEDED])["decisions_needed"] == [NEEDED]


class TestCodifyingACheckLine:
    def test_a_drafted_check_line_is_run_mechanically_next_time(self, repo: Path) -> None:
        page = repo / "docs" / "architecture.md"
        before = architecture.plan(repo, "core")
        line = "CHECK no-import: pkg.paths -> pkg.cfg"
        assert line.removeprefix("CHECK ") not in {r["id"] for r in before["rules"]}

        page.write_text(page.read_text(encoding="utf-8") + f"{line}\n", encoding="utf-8")
        after = architecture.plan(repo, "core")

        [finding] = [
            f
            for f in after["findings"]
            if f["anchor"] == {"kind": "rule", "id": line.removeprefix("CHECK ")}
        ]
        assert finding["category"] == "adherence"
        assert review.finding_problems(finding) == []
