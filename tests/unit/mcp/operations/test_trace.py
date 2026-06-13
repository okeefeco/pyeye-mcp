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
