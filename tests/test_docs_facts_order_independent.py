"""``generate``'s ledger and removed names don't depend on the order of local runs (#1112).

Both records used to be derived from the WORKING-TREE copy: an intermediate
``generate`` on a branch where a fact was briefly covered or absent dropped it
from the ledger's ``baseline`` for good (it came back as ``new``), and added a
permanent ``removed.json`` entry for a fact that later came back.  ``generate``
now derives both from the copy at the merge base with the default branch, and
keeps from the working tree only what a person or a release wrote: an entry's
hand-edited fields, and a ``first_seen`` stamped by ``changelog.py prepare``.
``check`` still compares the files with themselves, which the merge-base result
is a fixed point of.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 — runs git with fixed arguments
from pathlib import Path

import pytest

from pyeye.docs_facts import cli, ledger, removed
from pyeye.docs_facts.facts import Fact, index
from pyeye.docs_facts.ledger import Ledger
from pyeye.docs_facts.removed import Removed

FACTS = index([Fact("x.a", 1, "1"), Fact("x.b", 2, "2"), Fact("tool.t", "t", "t")])


class TestLedgerAgainstABase:
    def test_a_transient_cover_does_not_move_a_baseline_fact_to_new(self) -> None:
        base = Ledger(("x.a",), {})
        transient = ledger.updated(base, FACTS, {"x.a", "x.b", "tool.t"})  # briefly covered
        assert transient.baseline == ()
        again = ledger.updated(base, FACTS, {"x.b", "tool.t"}, current=transient)
        assert again == Ledger(("x.a",), {})

    def test_a_stamped_first_seen_in_the_working_tree_is_kept(self) -> None:
        # `changelog.py prepare` stamps "unreleased" on the release branch.
        base = Ledger((), {"x.a": "unreleased"})
        current = Ledger((), {"x.a": "2.3.0"})
        result = ledger.updated(base, FACTS, {"x.b", "tool.t"}, current=current)
        assert result.new == {"x.a": "2.3.0"}

    def test_the_base_first_seen_beats_an_unstamped_working_tree(self) -> None:
        base = Ledger((), {"x.a": "2.2.0"})
        current = Ledger((), {})  # a transient run had dropped it
        result = ledger.updated(base, FACTS, {"x.b", "tool.t"}, current=current)
        assert result.new == {"x.a": "2.2.0"}

    def test_the_result_is_a_fixed_point_of_check(self) -> None:
        base = Ledger(("x.a",), {"x.b": "2.2.0"})
        result = ledger.updated(base, FACTS, {"tool.t"}, current=Ledger((), {}))
        assert ledger.updated(result, FACTS, {"tool.t"}) == result


GONE = {"tool.t": "t", "x.a": 1}  # a base snapshot: tool.t existed


class TestRemovedAgainstABase:
    def test_a_name_gone_then_back_leaves_no_entry(self) -> None:
        transient = removed.updated([], GONE, index([Fact("x.a", 1, "1")]))
        assert [e.fact_id for e in transient] == ["tool.t"]
        again = removed.updated([], GONE, FACTS, current=transient)
        assert again == []

    def test_a_name_removed_on_the_branch_keeps_its_hand_edits(self) -> None:
        edited = Removed("tool.t", "heading", "unreleased", note="lives on internally")
        result = removed.updated([], GONE, index([Fact("x.a", 1, "1")]), current=[edited])
        assert result == [edited]

    def test_base_entries_are_never_dropped_and_take_working_tree_edits(self) -> None:
        old = Removed("tool.old", "word", "2.0.0")
        edited = Removed("tool.old", "heading", "2.0.0", note="now a method")
        assert removed.updated([old], GONE, FACTS, current=[]) == [old]
        assert removed.updated([old], GONE, FACTS, current=[edited]) == [edited]

    def test_a_hand_written_historical_entry_is_kept(self) -> None:
        # Recorded by hand for a removal long before the snapshot (D12).
        historical = Removed("tool.ancient", "word", "1.4.0", approx=True)
        assert removed.updated([], GONE, FACTS, current=[historical]) == [historical]

    def test_a_generated_entry_for_a_fact_born_on_the_branch_is_dropped(self) -> None:
        # Added on the branch, then renamed: relative to the base it never existed.
        transient = Removed("tool.born", "word", "unreleased")
        assert removed.updated([], GONE, FACTS, current=[transient]) == []

    def test_the_result_is_a_fixed_point_of_check(self) -> None:
        old = Removed("tool.old", "word", "2.0.0")
        facts = index([Fact("x.a", 1, "1")])
        result = removed.updated([old], GONE, facts, current=[])
        snapshot_now = {"x.a": 1}  # the snapshot generate writes alongside
        assert removed.updated(result, snapshot_now, facts) == result


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # nosec B603 B607 — fixed git command
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


class TestGenerateIsOrderIndependent:
    """End to end: a transient ``generate`` on a branch leaves no trace."""

    @pytest.fixture
    def repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        _git(tmp_path, "init", "-q", "-b", "main")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pyeye.docs_facts]\nchangelog = "CHANGELOG.md"\n', encoding="utf-8"
        )
        self.facts = FACTS
        monkeypatch.setattr(cli.registry, "build", lambda _root, *_e: self.facts)
        assert cli.main(["generate"], root=tmp_path) == 0
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-qm", "base")
        _git(tmp_path, "checkout", "-qb", "feature")
        return tmp_path

    @staticmethod
    def _records(repo: Path) -> tuple[dict, dict]:
        return (
            json.loads((repo / ledger.UNCOVERED).read_text(encoding="utf-8")),
            json.loads((repo / removed.REMOVED).read_text(encoding="utf-8")),
        )

    def test_a_transient_absence_leaves_no_trace(self, repo: Path) -> None:
        before = self._records(repo)
        assert "tool.t" in before[0]["baseline"]

        self.facts = index([Fact("x.a", 1, "1"), Fact("x.b", 2, "2")])  # tool.t gone
        assert cli.main(["generate", "--base", "main"], root=repo) == 0
        transient = self._records(repo)
        assert [e["fact_id"] for e in transient[1]["removed"]] == ["tool.t"]

        self.facts = FACTS  # and back
        assert cli.main(["generate", "--base", "main"], root=repo) == 0
        assert self._records(repo) == before
        assert cli.main(["check"], root=repo) == 0

    def test_without_a_usable_base_it_uses_the_working_tree(self, repo: Path) -> None:
        assert cli.main(["generate", "--base", "no-such-ref"], root=repo) == 0
        assert cli.main(["check"], root=repo) == 0

    def test_the_default_base_is_the_merge_base_with_origin_main(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        origin = tmp_path_factory.mktemp("origin")
        _git(origin, "init", "-q", "--bare")
        _git(repo, "remote", "add", "origin", str(origin))
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")
        assert cli.merge_base(repo, "origin/main") == _git(repo, "rev-parse", "main")
        assert cli.merge_base(repo, "no-such-ref") is None
