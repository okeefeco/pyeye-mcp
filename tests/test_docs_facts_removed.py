"""Removed names stay out of live docs (#826, design D4, C2 and C8)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pyeye.docs_facts import cli, ledger, removed, rules
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.facts import Fact, View, index
from pyeye.docs_facts.removed import Removed
from tests.utils.docs_facts_config import write_config

ROOT = Path(__file__).resolve().parent.parent


class TestNames:
    @pytest.mark.parametrize(
        ("fact_id", "name"),
        [
            ("tool.trace", "trace"),
            ("tool.trace.param.max_depth", "max_depth"),
            ("env.PYEYE_CACHE_TTL", "PYEYE_CACHE_TTL"),
            ("cli.script.pyeye-mcp", "pyeye-mcp"),
            ("cli.module.pyeye.mcp", "python -m pyeye.mcp"),
            ("edge.callers", "callers"),
        ],
    )
    def test_name_of(self, fact_id: str, name: str) -> None:
        assert removed.name_of(fact_id) == name

    @pytest.mark.parametrize(
        ("fact_id", "match"),
        [
            ("tool.trace", "word"),
            ("tool.trace.param.max_depth", "none"),
            ("env.PYEYE_CACHE_TTL", "word"),
            ("cli.script.pyeye-mcp", "word"),
            ("edge.callers", "code"),
            ("ci.coverage_threshold", None),
            ("ceiling.static_calls", None),
            ("project.requires_python", None),
        ],
    )
    def test_default_match(self, fact_id: str, match: str | None) -> None:
        assert removed.default_match(fact_id) == match


class TestStore:
    def test_round_trip_keeps_optional_fields_only_when_set(self, tmp_path: Path) -> None:
        entries = [
            Removed("tool.b", "word", "2.0.0"),
            Removed("tool.a", "none", "2.0.0", approx=True, note="why"),
        ]
        (tmp_path / "docs/facts").mkdir(parents=True)
        (tmp_path / removed.REMOVED).write_text(removed.render(entries), encoding="utf-8")

        rows = json.loads((tmp_path / removed.REMOVED).read_text(encoding="utf-8"))["removed"]
        assert rows == [
            {
                "fact_id": "tool.a",
                "match": "none",
                "removed_in": "2.0.0",
                "removed_in_approx": True,
                "note": "why",
            },
            {"fact_id": "tool.b", "match": "word", "removed_in": "2.0.0"},
        ]
        assert removed.load(tmp_path) == sorted(entries, key=lambda e: e.fact_id)

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert removed.load(tmp_path) == []

    def test_unknown_match_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "docs/facts").mkdir(parents=True)
        (tmp_path / removed.REMOVED).write_text(
            json.dumps({"removed": [{"fact_id": "tool.a", "match": "any", "removed_in": "1"}]}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="match 'any'"):
            removed.load(tmp_path)

    def test_updated_appends_disappeared_names_only(self) -> None:
        old = {
            "tool.kept": {},
            "tool.gone": {},
            "tool.gone.param.p": {},
            "edge.gone": {},
            "ci.coverage_threshold": 85,
            "tool.known": {},
        }
        facts = index([Fact("tool.kept", {}, "`kept`")])
        known = Removed("tool.known", "heading", "1.0.0")

        result = removed.updated([known], old, facts)

        assert result == [
            Removed("edge.gone", "code", "unreleased"),
            Removed("tool.gone", "word", "unreleased"),
            Removed("tool.gone.param.p", "none", "unreleased"),
            known,  # never replaced: its hand-set match survives
        ]

    def test_updated_never_drops_an_entry(self) -> None:
        entry = Removed("tool.back", "word", "1.0.0")
        facts = index([Fact("tool.back", {}, "`back`")])  # it came back

        assert removed.updated([entry], {}, facts) == [entry]


class TestCommittedRecord:
    """The seeded ``docs/facts/removed.json`` (C2, C8)."""

    def test_it_holds_the_v1_and_v2_removals(self) -> None:
        by_name = {e.name: e for e in removed.load(ROOT)}

        for name in ("find_references", "get_call_hierarchy", "analyze_dependencies"):
            assert by_name[name].match == "word"
            assert by_name[name].removed_in == "2.0.0"
        for name in ("find_symbol_multi", "configure_namespace_package", "find_in_namespace"):
            assert by_name[name].removed_in == "1.1.2"
        assert by_name["find_symbol"].match == "heading"
        assert by_name["lookup"].match == "none"

    def test_every_release_is_a_version_or_unreleased(self) -> None:
        for e in removed.load(ROOT):
            assert e.removed_in == "unreleased" or re.fullmatch(r"\d+\.\d+\.\d+", e.removed_in)

    def test_no_entry_is_a_live_fact(self) -> None:
        """A live name must not be recorded as removed (it would be skipped, unnoticed)."""
        facts = cli.registry.build(ROOT)
        assert not [e.fact_id for e in removed.load(ROOT) if e.fact_id in facts]


class TestSunset:
    def test_current_major_is_the_newest_release_heading(self) -> None:
        text = "# Changelog\n\n## [Unreleased]\n\n## [3.0.0] - 2027-01-01\n\n## [2.1.0]\n"
        assert removed.current_major(text) == 3
        assert removed.current_major("## [Unreleased]\n") is None

    @pytest.mark.parametrize(
        ("removed_in", "major", "passed"),
        [
            ("2.0.0", 2, False),
            ("2.0.0", 3, True),
            ("1.1.2", 2, True),
            ("unreleased", 9, False),
            ("2.0.0", None, False),
        ],
    )
    def test_sunset_passed(self, removed_in: str, major: int | None, passed: bool) -> None:
        assert removed.sunset_passed(Removed("tool.x", "word", removed_in), major) is passed


class TestMentions:
    ENTRIES = [
        Removed("tool.find_references", "word", "2.0.0"),
        Removed("tool.find_symbol", "heading", "2.0.0"),
        Removed("tool.lookup", "none", "2.0.0"),
        Removed("cli.module.pyeye.old", "word", "2.0.0"),
        Removed("tool.trace", "word", "2.0.0"),  # live again
        Removed("edge.callers", "code", "2.0.0"),
    ]

    def _found(self, text: str, major: int = 2) -> list[tuple[int, str, bool, bool]]:
        return [
            (m.line, m.name, m.marked, m.sunset)
            for m in removed.mentions("p.md", text, self.ENTRIES, {"trace"}, major)
        ]

    def test_word_matches_anywhere_including_the_mcp_form(self) -> None:
        text = "use find_references\n`mcp__pyeye__find_references`\nfind_references_v2\n"
        assert self._found(text) == [
            (1, "find_references", False, False),
            (2, "find_references", False, False),
        ]

    def test_heading_matches_only_a_heading(self) -> None:
        text = "## find_symbol\n### `find_symbol()`\nJediAnalyzer.find_symbol is fine\n"
        assert [m[0] for m in self._found(text)] == [1, 2]

    def test_code_matches_only_inside_backticks(self) -> None:
        text = 'who callers are\nuse the `callers` edge\n`trace(edges=["callers"])` and `x`\n'
        assert [m[0] for m in self._found(text)] == [2, 3]
        assert self._found("`a` callers `b`\n") == []

    def test_none_and_live_names_are_not_scanned(self) -> None:
        assert self._found("lookup the trace tool\n") == []

    def test_a_command_name_matches_with_its_spaces(self) -> None:
        assert self._found("run python -m pyeye.old\n") == [
            (1, "python -m pyeye.old", False, False)
        ]

    def test_a_line_saying_removed_passes_until_the_sunset(self) -> None:
        text = "find_references was Removed in v2.0\n"
        assert self._found(text) == [(1, "find_references", True, False)]
        assert self._found(text, major=3) == [(1, "find_references", True, True)]

    def test_problem_text_says_what_to_do(self) -> None:
        unmarked, sunset = (
            removed.Mention("p.md", 3, "x", marked=False, sunset=False),
            removed.Mention("p.md", 4, "x", marked=True, sunset=True),
        )
        assert unmarked.fails and sunset.fails
        assert "say on the line that it was removed" in removed.problem(unmarked)
        assert "only history pages may name it" in removed.problem(sunset)


FACTS = index(
    [
        Fact("tool.live", {}, "`live`"),
        Fact("tool.other", {}, "`other`"),
        View("tools.core", ("tool.live", "tool.other"), "`live`, `other`"),
    ]
)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo with a live page, a history page and a removed-name record."""
    (tmp_path / "live.md").write_text("Use the live tool.\n", encoding="utf-8")
    (tmp_path / "history.md").write_text("old_tool did things.\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("## [Unreleased]\n\n## [2.1.0]\n", encoding="utf-8")
    (tmp_path / "docs/facts").mkdir(parents=True)
    (tmp_path / removed.REMOVED).write_text(
        removed.render([Removed("tool.old_tool", "word", "2.0.0")]), encoding="utf-8"
    )
    write_config(
        tmp_path,
        (DocEntry("live.md", "human", "prose"), DocEntry("history.md", "human", "history")),
    )
    monkeypatch.setattr(cli.registry, "build", lambda _root, *_extractors: FACTS)
    monkeypatch.setattr(
        cli.rules, "RULES", ()
    )  # #825's prose rules: tested in test_docs_facts_rules
    assert cli.generate(tmp_path) == 0
    return tmp_path


class TestCheck:
    def test_a_removed_name_on_a_live_page_fails(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (repo / "live.md").write_text("Call old_tool first.\n", encoding="utf-8")
        capsys.readouterr()

        assert cli.check(repo) == 1
        assert "live.md:1: names 'old_tool', which was removed" in capsys.readouterr().out

    def test_a_history_page_may_name_it(self, repo: Path) -> None:
        assert cli.check(repo) == 0

    def test_the_sunset_fails_even_a_marked_line(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        allowed = {removed.RULE_ID: ("names removed tool 'old_tool' beside 'removed'",)}
        write_config(repo, (DocEntry("live.md", "human", "prose", allow=allowed),))
        (repo / "live.md").write_text("old_tool was removed.\n", encoding="utf-8")
        assert cli.check(repo) == 0

        (repo / "CHANGELOG.md").write_text("## [3.0.0]\n", encoding="utf-8")
        capsys.readouterr()
        assert cli.check(repo) == 1
        assert "only history pages may name it now" in capsys.readouterr().out

    def test_a_marked_mention_must_be_allowed_by_its_exact_message(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A fix can't be traded for a new mention: allowances are exact messages (#837)."""
        message = "names removed tool 'old_tool' beside 'removed'"
        allowed = {removed.RULE_ID: (message,)}
        write_config(repo, (DocEntry("live.md", "human", "prose", allow=allowed),))

        (repo / "live.md").write_text("old_tool was removed.\nAlso removed: old_tool.\n", "utf-8")
        capsys.readouterr()
        assert cli.check(repo) == 1  # a second mention isn't covered by one allowance
        assert "not in the page's allow-list" in capsys.readouterr().out

        (repo / "live.md").write_text("Nothing removed here.\n", encoding="utf-8")
        assert cli.check(repo) == 1  # a stale allowance must be deleted
        assert "no longer found" in capsys.readouterr().out

    def test_allowance_messages_are_stable(self) -> None:
        mention = removed.Mention("p.md", 9, "callers", marked=True, sunset=False, kind="edge")
        assert removed.allowance(mention) == "names removed edge 'callers' beside 'removed'"
        assert [removed.kind_of(i) for i in ("tool.a", "tool.a.param.b", "env.X", "cli.x")] == [
            "tool",
            "parameter",
            "env var",
            "command",
        ]

    def test_a_disappearing_fact_is_recorded_in_the_same_run(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trimmed = index([Fact("tool.live", {}, "`live`")])
        monkeypatch.setattr(cli.registry, "build", lambda _root, *_extractors: trimmed)

        assert cli.check(repo) == 1  # snapshot, record and ledger are stale
        assert cli.generate(repo) == 0
        names = {e.fact_id: e for e in removed.load(repo)}
        assert names["tool.other"] == Removed("tool.other", "word", "unreleased")
        assert cli.check(repo) == 0

    def test_covers_naming_an_unknown_fact_fails(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_config(repo, (DocEntry("live.md", "human", "prose", covers=("tool.nope",)),))
        capsys.readouterr()

        assert cli.check(repo) == 1
        assert "live.md: `covers` names unknown fact IDs ['tool.nope']" in (capsys.readouterr().out)


class TestLedgerInCheck:
    def test_day_one_puts_every_uncovered_fact_in_the_baseline(self, repo: Path) -> None:
        assert ledger.load(repo) == ledger.Ledger(("tool.live", "tool.other"), {})

    def test_a_block_or_covers_on_a_live_page_covers_a_fact(self, repo: Path) -> None:
        (repo / "live.md").write_text(
            "<!-- fact:begin tool.live -->\n<!-- fact:end -->\n", encoding="utf-8"
        )
        assert cli.generate(repo) == 0
        assert ledger.load(repo) == ledger.Ledger(("tool.other",), {})

        write_config(repo, (DocEntry("live.md", "human", "prose", covers=("tools.core",)),))
        assert cli.generate(repo) == 0
        assert ledger.load(repo) == ledger.Ledger((), {})

    def test_a_block_on_a_history_page_does_not_cover(self, repo: Path) -> None:
        (repo / "history.md").write_text(
            "<!-- fact:begin tool.live -->\n<!-- fact:end -->\n", encoding="utf-8"
        )
        assert cli.generate(repo) == 0
        assert "tool.live" in ledger.load(repo).baseline  # type: ignore[union-attr]

    def test_a_new_fact_is_a_dated_entry_and_never_blocks(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grown = index([*FACTS.values(), Fact("tool.added", {}, "`added`")])
        monkeypatch.setattr(cli.registry, "build", lambda _root, *_extractors: grown)

        assert cli.generate(repo) == 0
        assert ledger.load(repo) == ledger.Ledger(
            ("tool.live", "tool.other"), {"tool.added": "unreleased"}
        )
        assert cli.check(repo) == 0


class TestRulesHook:
    """#825's env-name and server-command rules read removed names from the record."""

    def test_removed_names_are_the_env_and_command_entries(self, tmp_path: Path) -> None:
        (tmp_path / "docs/facts").mkdir(parents=True)
        (tmp_path / removed.REMOVED).write_text(
            removed.render(
                [
                    Removed("env.PYEYE_OLD", "word", "2.0.0"),
                    Removed("cli.script.pyeye-old", "word", "2.0.0"),
                    Removed("tool.old_tool", "word", "2.0.0"),
                ]
            ),
            encoding="utf-8",
        )
        # The record is the checked repository's own (#1091), not pyeye's checkout.
        assert rules._removed_names(tmp_path) == {"PYEYE_OLD", "pyeye-old"}

    def test_pyeyes_own_record(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        assert (repo / removed.REMOVED).is_file()
        # Today's record has no env var or command: none was ever removed.
        assert rules._removed_names(repo) == frozenset()
