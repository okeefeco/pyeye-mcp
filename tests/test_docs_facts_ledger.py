"""The uncovered-fact ledger and the changed-fact list (#826, design D5, C3, C4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pyeye.docs_facts import changed, cli, docs, ledger
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.facts import Fact, View, index
from pyeye.docs_facts.ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent

FACTS = index(
    [
        Fact("x.a", 1, "1"),
        Fact("x.b", 2, "2"),
        Fact("x.c", 3, "3"),
        View("x.ab", ("x.a", "x.b"), "1, 2"),
    ]
)


class TestLedger:
    def test_expand_turns_views_into_members_and_drops_unknown_ids(self) -> None:
        assert ledger.expand(["x.ab", "x.c", "x.nope"], FACTS) == {"x.a", "x.b", "x.c"}

    def test_the_first_ledger_is_all_baseline(self) -> None:
        assert ledger.updated(None, FACTS, {"x.a"}) == Ledger(("x.b", "x.c"), {})

    def test_baseline_only_shrinks_and_new_facts_are_dated(self) -> None:
        old = Ledger(("x.a", "x.b"), {"x.gone": "2.1.1"})
        grown = index([*FACTS.values(), Fact("x.d", 4, "4")])

        result = ledger.updated(old, grown, covered={"x.a"})

        assert result.baseline == ("x.b",)  # x.a is covered now; x.c was never baseline
        assert result.new == {"x.c": "unreleased", "x.d": "unreleased"}  # x.gone left

    def test_first_seen_is_kept(self) -> None:
        old = Ledger((), {"x.c": "2.1.1"})
        assert ledger.updated(old, FACTS, {"x.a", "x.b"}).new == {"x.c": "2.1.1"}

    def test_a_baseline_fact_covered_then_uncovered_is_new(self) -> None:
        once = ledger.updated(Ledger(("x.c",), {}), FACTS, {"x.a", "x.b", "x.c"})
        again = ledger.updated(once, FACTS, {"x.a", "x.b"})
        assert again == Ledger((), {"x.c": "unreleased"})

    def test_render_and_load_round_trip(self, tmp_path: Path) -> None:
        value = Ledger(("x.b", "x.a"), {"x.c": "unreleased"})
        (tmp_path / "docs/facts").mkdir(parents=True)
        (tmp_path / ledger.UNCOVERED).write_text(ledger.render(value), encoding="utf-8")

        assert json.loads((tmp_path / ledger.UNCOVERED).read_text(encoding="utf-8")) == {
            "baseline": ["x.a", "x.b"],
            "new": [{"fact_id": "x.c", "first_seen": "unreleased"}],
            "dismissed": {},
        }
        assert ledger.load(tmp_path) == Ledger(("x.a", "x.b"), {"x.c": "unreleased"})
        assert ledger.load(tmp_path / "nowhere") is None

    def test_the_committed_ledger_lists_only_real_facts(self) -> None:
        committed = ledger.load(ROOT)
        assert committed is not None
        facts = cli.registry.build(ROOT)
        listed = [*committed.baseline, *committed.new]
        assert listed and all(isinstance(facts.get(i), Fact) for i in listed)


class TestChanged:
    def test_diff_sorts_ids_and_keeps_pages_for_changed_ones(self) -> None:
        base = {"x.a": 1, "x.b": 2, "x.gone": 0}
        head = {"x.a": 1, "x.b": 20, "x.new": 5}
        pages = {"x.b": ["a.md"], "x.a": ["b.md"], "x.gone": ["c.md"]}

        result = changed.diff(base, head, pages)

        assert (result.added, result.changed, result.removed) == (["x.new"], ["x.b"], ["x.gone"])
        assert result.pages == {"x.b": ["a.md"], "x.gone": ["c.md"]}

    def test_summary_lists_each_kind_with_its_pages(self) -> None:
        text = changed.summary(
            changed.Changes(added=["x.new"], changed=["x.b"], pages={"x.b": ["a.md"]}),
            "main",
        )
        assert "### Docs facts changed against `main`" in text
        assert "**Added** (1)" in text and "- `x.new`\n" in text
        assert "- `x.b` (bound in a.md)" in text
        assert "**Removed**" not in text

    def test_summary_says_when_nothing_changed(self) -> None:
        assert "No fact changed." in changed.summary(changed.Changes(), "main")

    def test_bound_pages_expands_views_and_keeps_removed_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.md").write_text(
            "<!-- fact:begin x.ab -->\n<!-- fact:end -->\n"
            "<!-- fact:begin x.gone -->\n<!-- fact:end -->\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(docs, "DOCS", (DocEntry("a.md", "human", "prose"),))

        assert changed.bound_pages(tmp_path, FACTS) == {
            "x.a": ["a.md"],
            "x.b": ["a.md"],
            "x.gone": ["a.md"],
        }


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603 S607


class TestReportChanged:
    @pytest.fixture
    def repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "t")
        monkeypatch.setattr(docs, "DOCS", ())
        monkeypatch.setattr(cli.registry, "build", lambda _root, *_extractors: FACTS)
        # The CLI checks only a repository that declares a config (#1091): this one
        # selects pyeye's setup, whose (patched) constants it reads at call time.
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pyeye.docs_facts]\npreset = "pyeye"\n', encoding="utf-8"
        )
        return tmp_path

    def _snapshot(self, repo: Path, facts: dict[str, int]) -> None:
        (repo / "docs/facts").mkdir(parents=True, exist_ok=True)
        (repo / cli.SNAPSHOT).write_text(json.dumps({"facts": facts}), encoding="utf-8")

    def test_it_diffs_against_the_base_revision(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._snapshot(repo, {"x.a": 1})
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        self._snapshot(repo, {"x.a": 2, "x.b": 2})

        assert cli.main(["changed", "--base", "HEAD"], root=repo) == 0
        out = capsys.readouterr().out
        assert "**Added** (1)" in out and "**Changed** (1)" in out

    def test_a_base_without_a_snapshot_is_reported_not_failed(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (repo / "f").write_text("x", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")

        assert cli.main(["changed", "--base", "HEAD"], root=repo) == 0
        assert "has no `docs/facts/facts.json`" in capsys.readouterr().out
