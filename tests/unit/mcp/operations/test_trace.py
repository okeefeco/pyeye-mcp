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

_WIDGET_HANDLE = "mypackage._core.widgets.Widget"
#: A MODULE whose members include the ``Widget`` class, which itself has members
#: (methods) — a genuine two-level ``members`` tree for depth/truncation tests.
_WIDGETS_MODULE_HANDLE = "mypackage._core.widgets"

#: Stub keys always present (spec §4.1; ``signature`` is callable-only).
_STUB_REQUIRED_KEYS = {"handle", "kind", "scope", "line_start", "line_end"}


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


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


class TestStopsAtPredicate:
    """Unit tests for the ``_stops_at`` boundary predicate (kind-agnostic)."""

    def test_module_pattern_substring_match(self) -> None:
        assert _stops_at("mypackage._core.widgets", {"module_pattern": "_core"}) is True
        assert _stops_at("mypackage.usage", {"module_pattern": "_core"}) is False

    def test_exclude_tests_matches_test_modules(self) -> None:
        assert _stops_at("tests.unit.test_thing", {"exclude_tests": True}) is True
        assert _stops_at("pkg.test_helpers", {"exclude_tests": True}) is True
        assert _stops_at("mypackage.usage", {"exclude_tests": True}) is False

    def test_no_predicate_never_stops(self) -> None:
        assert _stops_at("anything.at.all", None) is False
        assert _stops_at("anything.at.all", {}) is False


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
