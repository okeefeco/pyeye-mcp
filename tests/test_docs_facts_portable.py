"""docs-facts runs on a repository that isn't pyeye (#1091, RFC #1083 step 1).

A spike ran ``pyeye.docs_facts`` on Scrapy; three seams crashed it:

- F1: ``cli.plan`` couldn't take extractors, so pyeye's own ran on the target;
- F2: pyeye's reference pages were always built;
- F3: pyeye-domain rules raised ``KeyError`` on facts the target doesn't have.

And one more, found while reading (F4): the removed-name rules read
``removed.json`` from pyeye's own checkout, not from the repo being checked.

A :class:`~pyeye.docs_facts.setup.Setup` now carries a repo's extractors, doc
registry, rules and pages; :func:`~pyeye.docs_facts.setup.pyeye_setup` is pyeye's.
Each rule declares the facts it needs, and one whose facts are absent is
skipped and reported, never run on half a fact set.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import MappingProxyType

import pytest

from pyeye.docs_facts import cli, registry, removed, rules
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.facts import Fact, code
from pyeye.docs_facts.registry import Extractor
from pyeye.docs_facts.removed import Removed
from pyeye.docs_facts.setup import Setup, pyeye_setup

# ---------------------------------------------------------------------------
# A small foreign repo: one extractor, one page, no pyeye facts
# ---------------------------------------------------------------------------


def _routes(root: Path) -> Iterator[Fact]:
    count = len(list((root / "app").glob("*.py")))
    yield Fact("app.module_count", count, code(str(count)))


ROUTES = Extractor("routes", ("app",), _routes)
PAGE = "docs/arch.md"


def _foreign(tmp_path: Path, text: str = "") -> tuple[Path, Setup]:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/a.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    page = text or (
        "# Architecture\n\nModules: <!-- fact:begin app.module_count --><!-- fact:end -->.\n"
    )
    (tmp_path / PAGE).write_text(page, encoding="utf-8")
    entry = DocEntry(PAGE, "human", "prose", MappingProxyType({}))
    setup = Setup(extractors=(ROUTES,), docs=(entry,), rules=rules.RULES, pages={})
    return tmp_path, setup


class TestTheSetupReachesThePlan:
    """F1 and F2: the plan uses the setup's extractors, docs and pages only."""

    def test_only_the_setups_extractors_run(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path)
        result = cli.plan(root, setup=setup)
        assert result.problems == []
        assert "`1`" in result.outputs[PAGE]
        assert not any(path.startswith("docs/reference/") for path in result.outputs)

    def test_generate_then_check_is_clean(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path)
        assert cli.generate(root, setup=setup) == 0
        assert cli.check(root, setup=setup) == 0

    def test_a_code_change_is_stale(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path)
        cli.generate(root, setup=setup)
        (root / "app/b.py").write_text("Y = 2\n", encoding="utf-8")
        assert cli.check(root, setup=setup) == 1

    def test_a_hand_edit_is_stale(self, tmp_path: Path) -> None:
        root, setup = _foreign(tmp_path)
        cli.generate(root, setup=setup)
        page = root / PAGE
        page.write_text(page.read_text(encoding="utf-8").replace("`1`", "`7`"), encoding="utf-8")
        assert cli.check(root, setup=setup) == 1

    def test_the_default_is_pyeyes_own_setup(self) -> None:
        own = pyeye_setup()
        assert own.extractors == registry.EXTRACTORS
        assert own.rules == rules.RULES


class TestRulesSayWhatTheyNeed:
    """F3: a rule whose facts are absent is skipped and reported, not crashed."""

    def test_every_rule_but_honest_claims_needs_pyeye_facts(self) -> None:
        needs = {rule.id: rule.requires for rule in rules.RULES}
        assert needs[rules.HONEST_CLAIMS] == frozenset()
        assert all(needs[rule_id] for rule_id in needs if rule_id != rules.HONEST_CLAIMS)

    def test_requirements_name_ids_or_prefixes(self) -> None:
        rule = rules.Rule(
            "x",
            frozenset({"prose"}),
            False,
            lambda _p, _f: [],
            requires=frozenset({"one.id", "edge."}),
        )
        assert rules.missing_facts(rule, {}) == ["edge.", "one.id"]
        facts = {"one.id": Fact("one.id", 1, "1"), "edge.members": Fact("edge.members", 1, "1")}
        assert rules.missing_facts(rule, facts) == []

    def test_skipped_rules_are_reported_and_the_rest_run(self, tmp_path: Path) -> None:
        text = "# Architecture\n\nThe handle does not exist. It is 40% faster.\n"
        root, setup = _foreign(tmp_path, text)
        result = cli.plan(root, setup=setup)
        skipped = [note for note in result.notes if note.startswith("skipped rule")]
        assert {note.split()[2].rstrip(":") for note in skipped} == {
            r.id for r in rules.RULES if r.id != rules.HONEST_CLAIMS
        }
        # honest-claims still runs; absence-prose (pyeye's convention) doesn't.
        assert any("honest-claims" in p for p in result.problems)
        assert not any("absence-prose" in p for p in result.problems)

    def test_pyeye_skips_nothing(self) -> None:
        facts = registry.build(Path(__file__).resolve().parents[1])
        assert [r.id for r in rules.RULES if rules.missing_facts(r, facts)] == []


class TestRemovedNamesComeFromTheCheckedRepo:
    """F4: ``removed.json`` is read from the root being checked, not pyeye's checkout."""

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        (tmp_path / "docs/facts").mkdir(parents=True)
        (tmp_path / removed.REMOVED).write_text(
            removed.render([Removed("env.PYEYE_OLD", "word", "2.0.0")]), encoding="utf-8"
        )
        return tmp_path

    def test_the_names_are_the_roots(self, root: Path) -> None:
        assert rules._removed_names(root) == {"PYEYE_OLD"}

    def test_no_root_means_none(self) -> None:
        assert rules._removed_names(None) == frozenset()
