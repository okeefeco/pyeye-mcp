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

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.trace import trace

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
