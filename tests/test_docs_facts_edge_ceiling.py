"""Each edge a tool description exposes states its own ceiling (#827, design C12).

The ``edge-ceiling`` rule (:func:`pyeye.docs_facts.rules.missing_edge_ceiling`)
and the ``ceiling`` / ``ceilings`` slot forms that satisfy it, both built on
:func:`pyeye.docs_facts.describe.ceiling_statement`, so the text a slot renders
is exactly the text the rule looks for.
"""

from __future__ import annotations

import pytest

from pyeye.docs_facts import describe, rules
from pyeye.docs_facts.describe import SlotError, ceiling_statement, fill
from pyeye.docs_facts.facts import Fact, view
from pyeye.mcp.operations.edges import CEILING_MEANINGS, EDGE_CEILINGS, EDGE_RESOLVERS


def _facts() -> dict:
    members = Fact(
        "edge.members",
        {"status": "implemented", "applies_to": ["class"], "ceiling": "static_definitions"},
        "",
    )
    scope = Fact(
        "edge.enclosing_scope", {"status": "implemented", "applies_to": [], "ceiling": None}, ""
    )
    ceiling = Fact("ceiling.static_definitions", {"meaning": "definitions written in source"}, "")
    return {
        f.id: f for f in (members, scope, ceiling, view("edges.implemented", [members, scope], ""))
    }


def _tool(text: str) -> rules.Page:
    return rules.Page("tool:t", text, text, None)


_STATED = "``static_definitions``: definitions written in source"


class TestSlotForms:
    def test_ceiling_states_an_edge_inline(self) -> None:
        assert fill("Ceiling: <<fact:edge.members:ceiling>>.", _facts()) == f"Ceiling: {_STATED}."

    def test_an_exact_edge_says_so(self) -> None:
        assert fill("<<fact:edge.enclosing_scope:ceiling>>", _facts()) == "exact (no ceiling)"

    def test_ceilings_lists_each_edge_on_its_own_line(self) -> None:
        doc = "Ceilings:\n\n    <<fact:edges.implemented:ceilings>>\n"
        assert fill(doc, _facts()) == (
            "Ceilings:\n\n"
            f"    - On ``members``: {_STATED}.\n"
            "    - On ``enclosing_scope``: exact (no ceiling).\n"
        )

    def test_ceilings_is_a_block_form(self) -> None:
        with pytest.raises(SlotError, match="on a line of its own"):
            fill("Ceilings: <<fact:edges.implemented:ceilings>>", _facts())

    def test_a_non_edge_has_no_ceiling(self) -> None:
        with pytest.raises(SlotError, match="is not an edge"):
            fill("<<fact:ceiling.static_definitions:ceiling>>", _facts())

    def test_a_ceiling_without_a_fact_fails(self) -> None:
        facts = _facts()
        del facts["ceiling.static_definitions"]
        with pytest.raises(SlotError, match="has no fact"):
            fill("<<fact:edge.members:ceiling>>", facts)


class TestRule:
    def test_an_entry_must_state_its_own_ceiling(self) -> None:
        text = "Edges:\n  - ``members``  — class members.\n  - ``other``  — " + _STATED + ".\n"
        assert rules.missing_edge_ceiling(_tool(text), _facts()) == [
            rules.Finding(2, "the 'members' entry doesn't state its ceiling")
        ]

    def test_an_entry_that_states_it_passes(self) -> None:
        text = f"Edges:\n  - ``members``  — class members.  Ceiling:\n    {_STATED}.\n"
        assert rules.missing_edge_ceiling(_tool(text), _facts()) == []

    def test_a_named_edge_needs_its_ceiling_somewhere(self) -> None:
        example = 'follow: e.g. ``["members"]``'  # an example names the edge too
        assert rules.missing_edge_ceiling(_tool(example), _facts()) == [
            rules.Finding(1, "exposes the 'members' edge without its ceiling")
        ]
        text = "Walks\nthe ``members`` edge."
        assert rules.missing_edge_ceiling(_tool(text), _facts()) == [
            rules.Finding(2, "exposes the 'members' edge without its ceiling")
        ]
        rendered = fill("Walks ``members``.\n\n<<fact:edges.implemented:ceilings>>", _facts())
        assert rules.missing_edge_ceiling(_tool(rendered), _facts()) == []

    def test_an_exact_edge_is_never_flagged(self) -> None:
        assert rules.missing_edge_ceiling(_tool("- ``enclosing_scope``  — x"), _facts()) == []

    def test_registered_pages_are_not_scanned(self) -> None:
        page = rules.Page("p.md", "the ``members`` edge", "the ``members`` edge", "prose")
        assert rules.missing_edge_ceiling(page, _facts()) == []

    def test_the_rule_runs_over_the_tool_descriptions(self) -> None:
        rule = next(r for r in rules.RULES if r.id == rules.EDGE_CEILING)
        assert rule.descriptions
        assert rule.kinds == frozenset()


def test_every_live_description_passes() -> None:
    facts = describe.load_time_facts()
    problems = {
        name: found
        for name, text in rules._tool_descriptions().items()
        if (found := rules.missing_edge_ceiling(_tool(text), facts))
    }
    assert problems == {}


@pytest.mark.parametrize("tool", ["expand", "trace"])
def test_the_edge_tools_state_every_ceiling(tool: str) -> None:
    """``expand`` and ``trace`` expose every implemented edge, so they state every ceiling."""
    text = " ".join(rules._tool_descriptions()[tool].split())
    for edge in EDGE_RESOLVERS:
        if edge in EDGE_CEILINGS:
            ceiling = EDGE_CEILINGS[edge]
            assert f"``{ceiling}``: {CEILING_MEANINGS[ceiling]}" in text, (tool, edge)


def test_ceiling_statement_matches_the_registry() -> None:
    facts = describe.load_time_facts()
    for edge, ceiling in EDGE_CEILINGS.items():
        fact = facts[f"edge.{edge}"]
        assert isinstance(fact, Fact)
        assert ceiling_statement(fact, facts) == f"``{ceiling}``: {CEILING_MEANINGS[ceiling]}"
