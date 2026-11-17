"""The honest-claims rule (D12, #844): a number in prose needs a fact, a record or a source."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from pyeye.docs_facts import claims, rules
from pyeye.docs_facts.claim_seeds import SEEDS
from pyeye.docs_facts.docs import DOCS, DocEntry, registered_files

ROOT = Path(__file__).parent.parent


def _labels(text: str) -> list[str]:
    return [c.label for c in claims.claims(text)]


class TestPatterns:
    @pytest.mark.parametrize(
        ("text", "label"),
        [
            ("Indexing is 40% faster.", "percentage"),
            ("It finds 90 % of bugs.", "percentage"),
            ("Cold lookups are 2.5x faster.", "multiplier"),
            ("A 2-3x improvement.", "multiplier"),
            ("The roughly 0.03× wire cost.", "multiplier"),
            ("Each call takes 50 ms.", "duration"),
            ("It finishes in 5–7 s on the repo.", "duration"),
            ("A 5min TTL.", "duration"),
            ("Heartbeat every 30 seconds.", "duration"),
            ("Memory grows by 100 MB.", "size"),
            ("About ~17,500 bytes per copy.", "size"),
            ("As of 2025, clients support MCP.", "as-of"),
            ("It currently has 17 tools.", "currently-N"),
            ("The server ships 17+ core tools.", "N-plus"),
            ("This saves tokens on every call.", "token-savings"),
            ("A 90% token reduction.", "percentage"),
        ],
    )
    def test_each_kind_of_claim_is_caught(self, text: str, label: str) -> None:
        assert label in _labels(text), _labels(text)

    @pytest.mark.parametrize(
        "text",
        [
            "The docs had named 18 variables that don't exist.",  # bare count: review's job
            "Requires Python 3.11+ and uv.",  # a version
            "Released in v2.1.0, which removed it.",
            "See #568 and PR #837.",
            "Use `--cov-fail-under=85` and `0.5 s`.",  # inline code
            "Start with `python -m pyeye.mcp`.",
            "The 3 core edges and 2 kinds.",
        ],
    )
    def test_honest_prose_passes(self, text: str) -> None:
        assert claims.claims(text) == []

    def test_n_plus_reports_the_whole_noun(self) -> None:
        (claim,) = claims.claims("Ships 17+ core tools.")

        assert claim.text == "17+ core"


class TestSkips:
    def test_code_fences_are_skipped(self) -> None:
        text = "Intro.\n\n```python\nassert elapsed < 0.2  # 200 ms\n```\n"

        assert claims.claims(text) == []

    def test_markdown_fences_are_skipped(self) -> None:
        """A ``markdown`` fence shows syntax; its numbers aren't claims."""
        text = "```markdown\nCoverage must stay above 85%.\n```\n"

        assert claims.claims(text) == []

    def test_plain_text_fences_are_still_read(self) -> None:
        """A file tree with comments is prose: "17+ core tools" in one is a claim."""
        text = "```\nserver.py  # Main MCP server with 17+ core tools\n```\n"

        assert _labels(text) == ["N-plus"]

    def test_badges_link_targets_and_comments_are_skipped(self) -> None:
        text = (
            "[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](x)\n"
            "<!-- a 50% note for maintainers -->\n"
        )

        assert claims.claims(text) == []

    def test_line_numbers_survive_the_skips(self) -> None:
        text = "```python\nx = 1\n```\n\nIt is 40% faster.\n"

        assert [c.line for c in claims.claims(text)] == [5]


class TestBacking:
    def test_a_primary_source_on_the_line_backs_it(self) -> None:
        text = "FAT has a 2 s timestamp resolution ([spec](https://example.org/fat)).\n"

        assert claims.claims(text) == []

    def test_a_linked_record_backs_it(self, tmp_path: Path) -> None:
        (tmp_path / "records").mkdir()
        (tmp_path / "records" / "run.md").write_text("x", encoding="utf-8")
        text = "The first query takes 5 s ([record](../records/run.md#first)).\n"
        records = frozenset({"records/run.md"})

        assert claims.claims(text, "docs/page.md", tmp_path, records) == []

    def test_a_link_to_a_page_that_isnt_a_record_doesnt(self, tmp_path: Path) -> None:
        text = "The first query takes 5 s ([notes](notes.md)).\n"

        assert claims.claims(text, "docs/page.md", tmp_path, frozenset({"records/run.md"}))

    def test_a_record_needs_its_front_matter(self) -> None:
        good = '---\ndate: "2026-11-17"\ncommand: "uv run pytest"\ncommit: "fc49ab5e"\n---\nx\n'
        bad = "---\ndate: 2026-11-17\ncommand:\n---\nx\n"

        assert claims.record_problems("r.md", good) == []
        assert [p.split("`")[1] for p in claims.record_problems("r.md", bad)] == [
            "command",
            "commit",
        ]
        assert len(claims.record_problems("r.md", "no front matter\n")) == 3


class TestMessages:
    def test_the_key_names_the_claim_and_the_message_adds_the_line(self) -> None:
        (claim,) = claims.claims("Cold lookups take 50 ms each.")

        assert claim.key == "unbacked duration '50 ms'"
        assert claim.message.startswith(claim.key + ": Cold lookups")


class TestOnTheRegistry:
    @staticmethod
    def _run(
        tmp_path: Path, path: str, text: str, kind: str, **allow: tuple[str, ...]
    ) -> list[str]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        entry = DocEntry(path, "human", kind, MappingProxyType(dict(allow)))  # type: ignore[arg-type]
        return rules.run(
            tmp_path,
            {},
            (entry,),
            rules=[r for r in rules.RULES if r.id == "honest-claims"],
            descriptions={},
            strings=(),
        )

    def test_history_pages_are_checked(self, tmp_path: Path) -> None:
        problems = self._run(tmp_path, "docs/migration-guide.md", "It is 2.5x faster.\n", "history")

        assert any("honest-claims: unbacked multiplier '2.5x'" in p for p in problems)

    def test_released_changelog_sections_are_exempt(self, tmp_path: Path) -> None:
        text = "## [Unreleased]\n\n- 40% faster.\n\n## [1.0.0] - 2025-01-01\n\n- 2-3x faster.\n"

        problems = self._run(tmp_path, "CHANGELOG.md", text, "history")

        assert any("'40%'" in p for p in problems)
        assert not any("3x" in p for p in problems)

    def test_fact_blocks_back_their_numbers(self, tmp_path: Path) -> None:
        text = (
            "Coverage stays above <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end -->.\n"
        )

        assert self._run(tmp_path, "p.md", text, "prose") == []

    def test_a_seeded_claim_passes_and_a_new_one_fails(self, tmp_path: Path) -> None:
        text = "It is 40% faster.\n\nAnd 2x smaller.\n"
        seeds = {"honest-claims": ("unbacked percentage '40%'",)}

        problems = self._run(tmp_path, "p.md", text, "prose", **seeds)

        detail = [p for p in problems if p.startswith("p.md:") and not p.startswith("p.md: ")]
        assert detail == ["p.md:3: honest-claims: unbacked multiplier '2x': And 2x smaller."]

    def test_a_record_page_is_checked_for_front_matter(self, tmp_path: Path) -> None:
        problems = self._run(tmp_path, "records/r.md", "no front matter\n", "record")

        assert any("a record must give `date`" in p for p in problems)

    def test_record_pages_hold_the_numbers_themselves(self, tmp_path: Path) -> None:
        text = '---\ndate: "d"\ncommand: "c"\ncommit: "x"\n---\nIt took 5 s.\n'

        assert self._run(tmp_path, "records/r.md", text, "record") == []


class TestSeeds:
    def test_every_seeded_page_is_registered(self) -> None:
        """A seed for an unregistered page would never be checked, or removed."""
        registered = {path for path, _ in registered_files(ROOT)}

        assert set(SEEDS) <= registered

    def test_seeds_reach_the_registry(self) -> None:
        by_path = {e.path: e for e in DOCS}

        for path, keys in SEEDS.items():
            assert by_path[path].allow["honest-claims"] == keys, path


def test_env_defaults_are_bindable_inline() -> None:
    """A documented default is a bound fact ("default <block>0.5</block> s"), not a restatement."""
    from pyeye.docs_facts import registry

    facts = registry.build(ROOT)
    view = facts["env.PYEYE_WATCHER_DEBOUNCE.default"]

    assert view.markdown == str(facts["env.PYEYE_WATCHER_DEBOUNCE"].value["default"])  # type: ignore[union-attr]
    assert facts["env.PYEYE_CACHE_TTL.default"].markdown == str(
        facts["env.PYEYE_CACHE_TTL"].value["default"]  # type: ignore[union-attr]
    )


def test_a_stale_seed_points_at_the_seed_file() -> None:
    entry = DocEntry("p.md", "human", "prose", MappingProxyType({"honest-claims": ("x",)}))

    problem = rules.ratchet(entry, "honest-claims", [])

    assert problem is not None and "claim_seeds.py" in problem
    other = rules.ratchet(
        DocEntry("p.md", "human", "prose", MappingProxyType({"absence-prose": ("x",)})),
        "absence-prose",
        [],
    )
    assert other is not None and "docs.py" in other
