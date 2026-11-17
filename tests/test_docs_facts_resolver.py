"""The resolver's strategy and bare-name policy are data the docs bind (#830, C15)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye import resolver
from pyeye.docs_facts import registry
from pyeye.docs_facts.extractors import resolver as extractor
from pyeye.docs_facts.facts import Fact, View

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def facts() -> dict[str, Any]:
    return {f.id: f for f in extractor.extract(ROOT)}


class TestTables:
    def test_step_names_are_unique_and_every_side_has_steps(self) -> None:
        names = [s.name for s in (*resolver.STRATEGY, *resolver.PROJECT_STRATEGY)]
        names += [s.name for s in resolver.EXTERNAL_STRATEGY]
        assert len(names) == len(set(names))
        assert resolver.STRATEGY and resolver.PROJECT_STRATEGY and resolver.EXTERNAL_STRATEGY

    def test_resolve_runs_exactly_the_tables_in_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_resolve is the tables: replace every step and record the order it calls them."""
        called: list[str] = []

        def recorder(name: str) -> Any:
            def run(*_args: Any) -> None:
                called.append(name)

            return run

        for table in ("STRATEGY", "PROJECT_STRATEGY", "EXTERNAL_STRATEGY"):
            steps = getattr(resolver, table)
            monkeypatch.setattr(
                resolver,
                table,
                tuple(resolver.Step(s.name, s.summary, recorder(s.name)) for s in steps),
            )
        for inside, side in (
            (True, resolver.PROJECT_STRATEGY),
            (False, resolver.EXTERNAL_STRATEGY),
        ):
            called.clear()
            monkeypatch.setattr(resolver, "_top_level_in_project", lambda *_a, v=inside: v)
            assert resolver._resolve("a.b", object(), hops=0) is None  # type: ignore[arg-type]
            assert called == [s.name for s in (*resolver.STRATEGY, *side)]

    def test_the_first_step_that_answers_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answer = ("a.b", object())
        monkeypatch.setattr(
            resolver,
            "STRATEGY",
            (
                resolver.Step("first", "", lambda *_a: answer),
                resolver.Step("never", "", lambda *_a: pytest.fail("ran after an answer")),
            ),
        )
        assert resolver._resolve("a.b", object(), hops=0) is answer  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_resolve_name_runs_the_policy_in_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[str] = []

        def recorder(name: str) -> Any:
            async def run(*_args: Any) -> None:
                called.append(name)

            return run

        monkeypatch.setattr(
            resolver,
            "BARE_NAME_POLICY",
            tuple(
                resolver.NameRule(r.name, r.summary, recorder(r.name))
                for r in resolver.BARE_NAME_POLICY
            ),
        )
        result = await resolver.resolve_name("thing", object())  # type: ignore[arg-type]

        assert called == ["shadow", "exact_module", "name_index", "members"]
        assert isinstance(result, resolver.NotFound)

    def test_decide(self) -> None:
        one = resolver.Resolved("a.b", "class", "project", None)
        assert resolver._decide({}) is None
        assert resolver._decide({"a.b": one}) is one


class TestFacts:
    def test_each_step_is_a_fact_with_its_side_and_position(self, facts: dict[str, Any]) -> None:
        sides = (
            ("all", resolver.STRATEGY),
            ("project", resolver.PROJECT_STRATEGY),
            ("external", resolver.EXTERNAL_STRATEGY),
        )
        for side, table in sides:
            for i, step in enumerate(table, 1):
                fact = facts[f"resolver.strategy.{step.name}"]
                assert isinstance(fact, Fact)
                assert fact.value == {"side": side, "position": i, "summary": step.summary}

    def test_each_rule_is_a_fact(self, facts: dict[str, Any]) -> None:
        for i, rule in enumerate(resolver.BARE_NAME_POLICY, 1):
            assert facts[f"resolver.bare_name.{rule.name}"].value == {
                "position": i,
                "summary": rule.summary,
            }

    def test_the_views_list_every_item(self, facts: dict[str, Any]) -> None:
        strategy, policy = facts["resolver.strategy"], facts["resolver.bare_name"]
        assert isinstance(strategy, View) and isinstance(policy, View)
        assert len(strategy.members) == sum(
            len(t)
            for t in (resolver.STRATEGY, resolver.PROJECT_STRATEGY, resolver.EXTERNAL_STRATEGY)
        )
        assert policy.markdown.startswith("1. `shadow`")

    def test_the_family_is_registered(self) -> None:
        assert "resolver" in {p for e in registry.EXTRACTORS for p in e.prefixes}
