"""Tests for the ``trace(start, follow, ...)`` operation — Phase 4 (Task 4.1+4.2).

``trace`` is the bounded multi-hop BFS primitive.  It composes the single-hop
edge registry (``members``, ``callees``, ``imported_by``) across hops and returns
a ``Subgraph`` (spec §``trace``)::

    type Subgraph = {
      nodes: Map<Handle, Stub>                       # deduped by handle
      edges: { from: Handle, to: Handle, kind }[]    # NOT deduped across kinds
      truncated: boolean    # max_depth/max_nodes hit BEFORE natural termination
    }

Termination: dedup by handle (visit once); edges *to* already-visited handles are
recorded (cycles stay visible) but do not trigger re-expansion — so cyclic graphs
terminate even at unbounded depth.

Fixture facts (``tests/fixtures/resolve_project``):
- ``mypackage._core.widgets.Widget`` — a class WITH members (members happy path).
- ``mypackage._core.widgets`` — a module imported by several other modules.
"""

from collections import Counter
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.trace import _stops_at, trace

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

#: The subclasses_edge fixture (#348/#422): ``pkg.base.Animal`` has DIRECT
#: subclasses {Mammal, Lizard} and the grandchild {Dog} one hop deeper.  Because
#: the ``subclasses`` edge is now a single hop (#422), ``trace`` over it must
#: walk level-by-level — Dog appears only at depth ≥ 2, never at depth 1.
_SUBCLASSES_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "subclasses_edge"
_ANIMAL_HANDLE = "pkg.base.Animal"
_MAMMAL_HANDLE = "pkg.middle.Mammal"  # direct subclass of Animal
_DOG_HANDLE = "pkg.middle.Dog"  # indirect (grandchild) of Animal via Mammal
_LIZARD_HANDLE = "script_animal.Lizard"  # direct subclass in a non-importable script

_WIDGET_HANDLE = "mypackage._core.widgets.Widget"
#: A MODULE whose members include the ``Widget`` class, which itself has members
#: (methods) — a genuine two-level ``members`` tree for depth/truncation tests.
_WIDGETS_MODULE_HANDLE = "mypackage._core.widgets"
#: A function whose ``callees`` mix project (``make_widget``) and external
#: (``math.sqrt``, ``builtins.float``) nodes — for scope-filter tests (#351).
_ORCHESTRATE_HANDLE = "mypackage._core.callees_fixture.orchestrate"

#: Stub keys always present (spec §4.1; ``signature`` is callable-only).
_STUB_REQUIRED_KEYS = {"handle", "kind", "scope", "line_start", "line_end"}


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


@pytest.fixture
def subclasses_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the subclasses_edge fixture (#348/#422)."""
    return JediAnalyzer(str(_SUBCLASSES_FIXTURE))


def _assert_is_stub(stub: dict) -> None:
    """Assert *stub* conforms to the Phase-1 §4.1 Stub shape (no source content)."""
    assert isinstance(stub, dict), f"stub must be a dict, got {type(stub)}"
    missing = _STUB_REQUIRED_KEYS - set(stub)
    assert not missing, f"stub missing required keys {missing}: {stub}"
    for forbidden in ("body", "source", "code", "snippet", "text"):
        assert forbidden not in stub, f"stub leaked source content via {forbidden!r}: {stub}"


class TestTraceMembersOneHop:
    """The core happy path: a single-edge, single-hop trace over ``members``."""

    @pytest.mark.asyncio
    async def test_returns_subgraph_shape(self, analyzer: JediAnalyzer) -> None:
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=1)
        # Subgraph triple.
        assert set(result) >= {"nodes", "edges", "truncated"}
        assert isinstance(result["nodes"], dict)
        assert isinstance(result["edges"], list)
        assert isinstance(result["truncated"], bool)

    @pytest.mark.asyncio
    async def test_start_and_members_are_nodes(self, analyzer: JediAnalyzer) -> None:
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=1)
        # The start handle is the root node of the subgraph.
        assert _WIDGET_HANDLE in result["nodes"]
        # Widget has members, so the closure has more than just the root.
        assert len(result["nodes"]) > 1, "expected the start plus its member nodes"
        # Every node value is a well-formed stub.
        for stub in result["nodes"].values():
            _assert_is_stub(stub)

    @pytest.mark.asyncio
    async def test_records_members_edges_from_start(self, analyzer: JediAnalyzer) -> None:
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=1)
        member_edges = [
            e for e in result["edges"] if e["from"] == _WIDGET_HANDLE and e["kind"] == "members"
        ]
        assert member_edges, "expected members edges from the start handle"
        # Every edge endpoint must itself be a node (the graph is closed).
        for edge in result["edges"]:
            assert edge["from"] in result["nodes"], f"edge from-handle not a node: {edge}"
            assert edge["to"] in result["nodes"], f"edge to-handle not a node: {edge}"


class TestTraceTruncated:
    """``truncated`` is True ONLY when a cap cut off reachable nodes before
    natural termination — never merely because a cap was set."""

    @pytest.mark.asyncio
    async def test_truncated_true_when_depth_cuts_off_reachable_nodes(
        self, analyzer: JediAnalyzer
    ) -> None:
        # The module's members include ``Widget``, a class that ITSELF has
        # members (methods).  At max_depth=1 those grandchildren are reachable
        # but not visited → truncated.
        result = await trace(_WIDGETS_MODULE_HANDLE, ["members"], analyzer, max_depth=1)
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_truncated_false_when_fully_explored(self, analyzer: JediAnalyzer) -> None:
        # Tracing the Widget class with ample depth: Widget → methods, and
        # methods have no further members → the whole closure is returned.
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=5)
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_cutoff_does_not_leak_beyond_depth_nodes_or_edges(
        self, analyzer: JediAnalyzer
    ) -> None:
        # Truncation must not smuggle beyond-depth handles in: the graph stays
        # closed (every edge endpoint is a node) even when truncated.
        result = await trace(_WIDGETS_MODULE_HANDLE, ["members"], analyzer, max_depth=1)
        assert result["truncated"] is True
        for edge in result["edges"]:
            assert edge["from"] in result["nodes"], f"edge from-handle not a node: {edge}"
            assert edge["to"] in result["nodes"], f"edge to-handle not a node: {edge}"


class TestTraceMaxNodes:
    """``max_nodes`` bounds the node count; hitting it sets ``truncated``."""

    @pytest.mark.asyncio
    async def test_max_nodes_caps_node_count_and_truncates(self, analyzer: JediAnalyzer) -> None:
        # A deep-enough trace of the module would yield well over two nodes;
        # max_nodes=2 must cap the closure and report truncation.
        result = await trace(
            _WIDGETS_MODULE_HANDLE, ["members"], analyzer, max_depth=3, max_nodes=2
        )
        assert len(result["nodes"]) <= 2
        assert result["truncated"] is True
        # The graph stays closed even when the node cap cut the walk short.
        for edge in result["edges"]:
            assert edge["from"] in result["nodes"], f"edge from-handle not a node: {edge}"
            assert edge["to"] in result["nodes"], f"edge to-handle not a node: {edge}"

    @pytest.mark.asyncio
    async def test_under_cap_is_not_truncated(self, analyzer: JediAnalyzer) -> None:
        # A generous cap on a small closure leaves truncated False.
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=5, max_nodes=100)
        assert len(result["nodes"]) < 100
        assert result["truncated"] is False


class TestTraceTruncationReasons:
    """``truncation_reasons`` distinguishes the depth frontier from the node
    budget so the agent knows which cap to raise (#352)."""

    @pytest.mark.asyncio
    async def test_depth_cut_reports_max_depth(self, analyzer: JediAnalyzer) -> None:
        # Module members at depth 1: Widget's methods are cut by depth, not budget.
        result = await trace(_WIDGETS_MODULE_HANDLE, ["members"], analyzer, max_depth=1)
        assert result["truncated"] is True
        assert result["truncation_reasons"] == ["max_depth"]

    @pytest.mark.asyncio
    async def test_node_budget_cut_reports_max_nodes(self, analyzer: JediAnalyzer) -> None:
        # Generous depth, tight node budget: only the budget fires.
        result = await trace(
            _WIDGETS_MODULE_HANDLE, ["members"], analyzer, max_depth=5, max_nodes=2
        )
        assert result["truncated"] is True
        assert result["truncation_reasons"] == ["max_nodes"]

    @pytest.mark.asyncio
    async def test_both_caps_report_both(self, analyzer: JediAnalyzer) -> None:
        # Shallow depth AND a tight budget on the multi-path imported_by graph:
        # the budget fills during root expansion, and frontier nodes still have
        # unvisited importers cut by depth — both causes fire.
        result = await trace(
            _WIDGETS_MODULE_HANDLE, ["imported_by"], analyzer, max_depth=1, max_nodes=3
        )
        assert result["truncated"] is True
        assert set(result["truncation_reasons"]) == {"max_depth", "max_nodes"}

    @pytest.mark.asyncio
    async def test_no_truncation_empty_reasons(self, analyzer: JediAnalyzer) -> None:
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=5)
        assert result["truncated"] is False
        assert result["truncation_reasons"] == []


class TestTraceDeferredEdgeInFollow:
    """A deferred/unsupported edge in ``follow`` is surfaced explicitly — never
    silently dropped (which would falsely imply "no such neighbours")."""

    @pytest.mark.asyncio
    async def test_deferred_edge_surfaced_while_supported_edge_traversed(
        self, analyzer: JediAnalyzer
    ) -> None:
        result = await trace(_WIDGET_HANDLE, ["members", "callers"], analyzer, max_depth=1)
        # The supported edge is still traversed (partial value is preserved).
        assert any(e["kind"] == "members" for e in result["edges"])
        # The deferred edge is reported, not silently omitted.
        unsupported = result["unsupported_edges"]
        callers = next((u for u in unsupported if u["edge"] == "callers"), None)
        assert callers is not None, f"'callers' not surfaced: {unsupported}"
        assert callers["reason"] == "deferred_reference_backend"
        # No edge in the graph carries the unsupported kind.
        assert not any(e["kind"] == "callers" for e in result["edges"])

    @pytest.mark.asyncio
    async def test_unknown_edge_surfaced(self, analyzer: JediAnalyzer) -> None:
        result = await trace(_WIDGET_HANDLE, ["definitely_not_an_edge"], analyzer, max_depth=1)
        unsupported = result["unsupported_edges"]
        assert any(
            u["edge"] == "definitely_not_an_edge" and u["reason"] == "unknown_edge"
            for u in unsupported
        ), unsupported

    @pytest.mark.asyncio
    async def test_all_supported_follow_reports_empty_unsupported(
        self, analyzer: JediAnalyzer
    ) -> None:
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=1)
        assert result["unsupported_edges"] == []


class TestTraceReportIssuesPointer:
    """#458 — a trace that hit a limitation points at where to report it.

    The pointer lives once at the top level of the response (not duplicated onto
    every ``unsupported_edges`` entry), present only when an edge was unsupported.
    """

    @pytest.mark.asyncio
    async def test_unsupported_edge_adds_top_level_report_issues(
        self, analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp import meta

        result = await trace(_WIDGET_HANDLE, ["members", "callers"], analyzer, max_depth=1)
        assert result["unsupported_edges"], "precondition: an edge must be unsupported"
        assert result["report_issues"] == meta.issues_url()

    @pytest.mark.asyncio
    async def test_all_supported_follow_has_no_report_issues(self, analyzer: JediAnalyzer) -> None:
        result = await trace(_WIDGET_HANDLE, ["members"], analyzer, max_depth=1)
        assert result["unsupported_edges"] == []
        assert "report_issues" not in result


class TestStopsAtPredicate:
    """Unit tests for the ``_stops_at`` boundary predicate.

    Signature is ``_stops_at(handle, scope, stop_when)`` — scope is needed for the
    ``exclude_external`` key (scope is not derivable from the handle string).
    """

    def test_module_pattern_substring_match(self) -> None:
        assert _stops_at("mypackage._core.widgets", "project", {"module_pattern": "_core"}) is True
        assert _stops_at("mypackage.usage", "project", {"module_pattern": "_core"}) is False

    def test_exclude_tests_matches_test_modules(self) -> None:
        assert _stops_at("tests.unit.test_thing", "project", {"exclude_tests": True}) is True
        assert _stops_at("pkg.test_helpers", "project", {"exclude_tests": True}) is True
        assert _stops_at("mypackage.usage", "project", {"exclude_tests": True}) is False

    def test_exclude_external_matches_external_scope(self) -> None:
        # scope-aware: external adjacents are a boundary; project ones are not.
        assert _stops_at("math.sqrt", "external", {"exclude_external": True}) is True
        assert _stops_at("builtins.float", "external", {"exclude_external": True}) is True
        assert _stops_at("mypackage.usage", "project", {"exclude_external": True}) is False

    def test_no_predicate_never_stops(self) -> None:
        assert _stops_at("anything.at.all", "external", None) is False
        assert _stops_at("anything.at.all", "external", {}) is False


class TestTraceExcludeExternal:
    """``stop_when={'exclude_external': True}`` prunes external nodes and frees
    the node budget for project nodes (#351)."""

    @pytest.mark.asyncio
    async def test_drops_external_nodes(self, analyzer: JediAnalyzer) -> None:
        # Baseline: orchestrate's callees include external nodes.
        full = await trace(_ORCHESTRATE_HANDLE, ["callees"], analyzer, max_depth=1)
        assert any(
            n["scope"] == "external" for n in full["nodes"].values()
        ), "fixture must have external callees to prune"

        pruned = await trace(
            _ORCHESTRATE_HANDLE,
            ["callees"],
            analyzer,
            max_depth=1,
            stop_when={"exclude_external": True},
        )
        externals = [h for h, n in pruned["nodes"].items() if n["scope"] == "external"]
        assert externals == [], f"exclude_external left external nodes: {externals}"
        # Project callees still present; graph stays closed.
        assert any(n["scope"] == "project" for n in pruned["nodes"].values())
        for edge in pruned["edges"]:
            assert edge["from"] in pruned["nodes"], f"edge from-handle not a node: {edge}"
            assert edge["to"] in pruned["nodes"], f"edge to-handle not a node: {edge}"

    @pytest.mark.asyncio
    async def test_external_nodes_do_not_consume_budget(self, analyzer: JediAnalyzer) -> None:
        # The budget-starvation fix: pruned externals never count against
        # max_nodes, so the whole cap is spent on project nodes.
        cap = 3
        without = await trace(
            _ORCHESTRATE_HANDLE, ["callees"], analyzer, max_depth=2, max_nodes=cap
        )
        with_excl = await trace(
            _ORCHESTRATE_HANDLE,
            ["callees"],
            analyzer,
            max_depth=2,
            max_nodes=cap,
            stop_when={"exclude_external": True},
        )
        proj_without = sum(1 for n in without["nodes"].values() if n["scope"] == "project")
        proj_with = sum(1 for n in with_excl["nodes"].values() if n["scope"] == "project")
        # Freeing externals can only help project nodes fit under the cap.
        assert proj_with >= proj_without
        # And the cap is now spent entirely on project nodes.
        assert all(n["scope"] == "project" for n in with_excl["nodes"].values())


class TestTraceStopWhen:
    """``stop_when`` prunes the traversal at the predicate boundary."""

    @pytest.mark.asyncio
    async def test_module_pattern_prunes_matching_adjacents(self, analyzer: JediAnalyzer) -> None:
        # Baseline: importers of widgets include several ``_core.*`` modules.
        full = await trace(_WIDGETS_MODULE_HANDLE, ["imported_by"], analyzer, max_depth=1)
        core_importers = [h for h in full["nodes"] if "_core" in h and h != _WIDGETS_MODULE_HANDLE]
        assert core_importers, "fixture should have _core importers to prune"

        # With module_pattern '_core', those adjacents are pruned at the boundary;
        # the start (itself a _core module) is a root and is never pruned.
        pruned = await trace(
            _WIDGETS_MODULE_HANDLE,
            ["imported_by"],
            analyzer,
            max_depth=1,
            stop_when={"module_pattern": "_core"},
        )
        leaked = [h for h in pruned["nodes"] if "_core" in h and h != _WIDGETS_MODULE_HANDLE]
        assert leaked == [], f"module_pattern did not prune _core adjacents: {leaked}"
        # Non-matching importers survive (e.g. mypackage.usage / use_widget).
        assert any(h.startswith("mypackage.") and "_core" not in h for h in pruned["nodes"])
        # The graph stays closed — no edge points at a pruned (absent) node.
        for edge in pruned["edges"]:
            assert edge["from"] in pruned["nodes"], f"edge from-handle not a node: {edge}"
            assert edge["to"] in pruned["nodes"], f"edge to-handle not a node: {edge}"


class TestTraceMultiHopAndMultiEdge:
    """Regression locks for multi-hop depth and multi-edge ``follow``."""

    @pytest.mark.asyncio
    async def test_two_hop_members_reaches_second_level(self, analyzer: JediAnalyzer) -> None:
        result = await trace(_WIDGETS_MODULE_HANDLE, ["members"], analyzer, max_depth=2)
        # Widget is a depth-1 member of the module...
        assert _WIDGET_HANDLE in result["nodes"]
        # ...and the 2nd hop expanded it: members edges originate FROM Widget.
        second_hop = [
            e for e in result["edges"] if e["from"] == _WIDGET_HANDLE and e["kind"] == "members"
        ]
        assert second_hop, "expected 2nd-hop members edges from Widget"
        for edge in second_hop:
            assert edge["to"] in result["nodes"], f"2nd-hop target not a node: {edge}"

    @pytest.mark.asyncio
    async def test_multi_edge_follow_labels_each_kind(self, analyzer: JediAnalyzer) -> None:
        result = await trace(
            _WIDGETS_MODULE_HANDLE, ["members", "imported_by"], analyzer, max_depth=1
        )
        kinds = {e["kind"] for e in result["edges"]}
        # Both edge types are present and correctly labelled (not deduped across kinds).
        assert "members" in kinds
        assert "imported_by" in kinds
        assert result["unsupported_edges"] == []
        for edge in result["edges"]:
            assert edge["from"] in result["nodes"], f"edge from-handle not a node: {edge}"
            assert edge["to"] in result["nodes"], f"edge to-handle not a node: {edge}"


class TestTraceSubclassesPerHop:
    """``trace`` over the now-single-hop ``subclasses`` edge walks level-by-level (#422).

    Before #422 the resolver returned the full closure at every hop, so the whole
    closure collapsed onto depth 1 and ``max_depth`` was meaningless.  With the
    resolver returning DIRECT children only, ``trace`` does a proper BFS: the
    grandchild ``Dog`` is reachable only at depth ≥ 2.
    """

    @pytest.mark.asyncio
    async def test_depth_1_yields_direct_children_not_grandchild(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        result = await trace(
            _ANIMAL_HANDLE, ["subclasses"], subclasses_analyzer, max_depth=1, max_nodes=100
        )
        nodes = set(result["nodes"])
        assert _MAMMAL_HANDLE in nodes, "direct subclass Mammal must be at depth 1"
        assert _LIZARD_HANDLE in nodes, "direct subclass Lizard must be at depth 1"
        # The defining assertion: the grandchild is NOT one hop away — it must not
        # appear at depth 1 (it would have, under the old per-hop-closure bug).
        assert _DOG_HANDLE not in nodes, "grandchild Dog must NOT appear at depth 1"
        # A reachable node was cut at the depth frontier → truncated via max_depth.
        assert result["truncated"] is True
        assert "max_depth" in result["truncation_reasons"]

    @pytest.mark.asyncio
    async def test_depth_2_reaches_grandchild(self, subclasses_analyzer: JediAnalyzer) -> None:
        result = await trace(
            _ANIMAL_HANDLE, ["subclasses"], subclasses_analyzer, max_depth=2, max_nodes=100
        )
        nodes = set(result["nodes"])
        assert {
            _MAMMAL_HANDLE,
            _LIZARD_HANDLE,
            _DOG_HANDLE,
        } <= nodes, f"depth 2 must reach the grandchild Dog; got {sorted(nodes)!r}"
        # The closure is fully explored at depth 2 → natural termination.
        assert result["truncated"] is False


class TestTraceCycleSafe:
    """Cycle-safe termination + dedup on a fan-in / multi-path graph."""

    @pytest.mark.asyncio
    async def test_terminates_dedups_and_records_fanin_edges(self, analyzer: JediAnalyzer) -> None:
        # The imported_by closure is a multi-path graph (more edges than a tree).
        result = await trace(_WIDGETS_MODULE_HANDLE, ["imported_by"], analyzer, max_depth=10)
        # Natural termination despite the cyclic/multi-path structure.
        assert result["truncated"] is False
        # Fan-in: more edges than a spanning tree (nodes - 1) would have.
        assert len(result["edges"]) > len(result["nodes"]) - 1
        # A fan-in target is reached by multiple edges but appears as ONE node
        # (dedup), and every edge endpoint is a node (cycle edges stay visible).
        incoming = Counter(e["to"] for e in result["edges"])
        fan_in = [target for target, count in incoming.items() if count > 1]
        assert fan_in, "expected at least one fan-in target"
        for target in fan_in:
            assert target in result["nodes"], "fan-in target must be a single deduped node"
        for edge in result["edges"]:
            assert edge["from"] in result["nodes"], f"edge from-handle not a node: {edge}"
            assert edge["to"] in result["nodes"], f"edge to-handle not a node: {edge}"
