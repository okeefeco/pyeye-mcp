"""Adversarial test suite for the conformance linter — trace ``Subgraph`` shape.

Each test targets one structural-floor (Check T) or layering (Check A) violation
for the ``trace`` operation, plus a dogfood test that runs REAL ``trace`` output
through the linter.

Rule tags enforced here:
    T.1  nodes/edges/truncated/unsupported_edges present with correct types
    T.2  Each node value passes the Stub floor (S.*); node key == stub handle
    T.3  Each edge is {from, to, kind} single-line strs
    T.4  Each unsupported_edges entry is {edge, reason ∈ valid, detail non-empty}
    A.*  No source content anywhere in the Subgraph (layering)
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tests.conformance.response_linter import ConformanceViolation, lint_response

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "resolve_project"

# A well-formed Subgraph (two nodes, one members edge, no unsupported edges).
_VALID_SUBGRAPH: dict = {
    "nodes": {
        "mypackage._core.widgets.Widget": {
            "handle": "mypackage._core.widgets.Widget",
            "kind": "class",
            "scope": "project",
            "signature": "Widget(name: str)",
            "line_start": 10,
            "line_end": 50,
        },
        "mypackage._core.widgets.Widget.render": {
            "handle": "mypackage._core.widgets.Widget.render",
            "kind": "method",
            "scope": "project",
            "signature": "render(self) -> str",
            "line_start": 20,
            "line_end": 25,
        },
    },
    "edges": [
        {
            "from": "mypackage._core.widgets.Widget",
            "to": "mypackage._core.widgets.Widget.render",
            "kind": "members",
        },
    ],
    "truncated": False,
    "unsupported_edges": [],
}


def _clone() -> dict:
    return copy.deepcopy(_VALID_SUBGRAPH)


class TestTraceAcceptsValid:
    def test_valid_subgraph_passes(self) -> None:
        lint_response(_clone(), "trace")  # must not raise

    def test_unsupported_edges_entry_passes(self) -> None:
        sg = _clone()
        sg["unsupported_edges"] = [
            {
                "edge": "callers",
                "reason": "deferred_reference_backend",
                "detail": "Edge 'callers' requires the reference backend (#333).",
            }
        ]
        lint_response(sg, "trace")  # must not raise


class TestTraceStructuralFloor:
    def test_missing_nodes_rejected(self) -> None:
        sg = _clone()
        del sg["nodes"]
        with pytest.raises(ConformanceViolation, match="nodes"):
            lint_response(sg, "trace")

    def test_nodes_must_be_dict(self) -> None:
        sg = _clone()
        sg["nodes"] = []
        with pytest.raises(ConformanceViolation, match="nodes"):
            lint_response(sg, "trace")

    def test_missing_edges_rejected(self) -> None:
        sg = _clone()
        del sg["edges"]
        with pytest.raises(ConformanceViolation, match="edges"):
            lint_response(sg, "trace")

    def test_truncated_must_be_bool(self) -> None:
        sg = _clone()
        sg["truncated"] = "false"  # string, not bool
        with pytest.raises(ConformanceViolation, match="truncated"):
            lint_response(sg, "trace")

    def test_missing_unsupported_edges_rejected(self) -> None:
        sg = _clone()
        del sg["unsupported_edges"]
        with pytest.raises(ConformanceViolation, match="unsupported_edges"):
            lint_response(sg, "trace")

    def test_node_key_must_match_stub_handle(self) -> None:
        sg = _clone()
        # Corrupt the dedup-by-handle invariant: key != stub.handle.
        node = sg["nodes"]["mypackage._core.widgets.Widget"]
        node["handle"] = "mypackage._core.widgets.SomethingElse"
        with pytest.raises(ConformanceViolation, match="handle"):
            lint_response(sg, "trace")

    def test_node_failing_stub_floor_rejected(self) -> None:
        sg = _clone()
        # Drop a required Stub key from a node value.
        del sg["nodes"]["mypackage._core.widgets.Widget.render"]["scope"]
        with pytest.raises(ConformanceViolation, match="scope"):
            lint_response(sg, "trace")

    def test_edge_missing_kind_rejected(self) -> None:
        sg = _clone()
        del sg["edges"][0]["kind"]
        with pytest.raises(ConformanceViolation, match="kind"):
            lint_response(sg, "trace")

    def test_edge_endpoint_must_be_str(self) -> None:
        sg = _clone()
        sg["edges"][0]["to"] = 123
        with pytest.raises(ConformanceViolation):
            lint_response(sg, "trace")

    def test_unsupported_edge_bad_reason_rejected(self) -> None:
        sg = _clone()
        sg["unsupported_edges"] = [{"edge": "callers", "reason": "made_up_reason", "detail": "x"}]
        with pytest.raises(ConformanceViolation, match="reason"):
            lint_response(sg, "trace")

    def test_unsupported_edge_empty_detail_rejected(self) -> None:
        sg = _clone()
        sg["unsupported_edges"] = [
            {"edge": "callers", "reason": "deferred_reference_backend", "detail": ""}
        ]
        with pytest.raises(ConformanceViolation, match="detail"):
            lint_response(sg, "trace")


class TestTraceLayering:
    def test_source_content_in_node_stub_rejected(self) -> None:
        sg = _clone()
        # Smuggle source content into a node stub — layering (A.*) must reject it.
        sg["nodes"]["mypackage._core.widgets.Widget"]["body"] = "def render(self):\n    ..."
        with pytest.raises(ConformanceViolation):
            lint_response(sg, "trace")


class TestRealTraceOutputConforms:
    """Dogfood: real trace output passes the linter with no linter change needed."""

    @pytest.mark.asyncio
    async def test_real_members_trace_conforms(self) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.trace import trace

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await trace("mypackage._core.widgets.Widget", ["members"], analyzer, max_depth=2)
        lint_response(result, "trace")  # must not raise

    @pytest.mark.asyncio
    async def test_real_trace_with_deferred_edge_conforms(self) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.trace import trace

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await trace(
            "mypackage._core.widgets.Widget", ["members", "callers"], analyzer, max_depth=1
        )
        lint_response(result, "trace")  # must not raise
