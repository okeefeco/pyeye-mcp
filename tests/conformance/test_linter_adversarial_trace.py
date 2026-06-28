"""Adversarial test suite for the conformance linter — trace ``Subgraph`` shape.

Each test targets one structural-floor (Check T) or layering (Check A) violation
for the ``trace`` operation, plus a dogfood test that runs REAL ``trace`` output
through the linter.

Rule tags enforced here:
    T.1  nodes/edges/truncated/unsupported_edges present with correct types
    T.2  Each node value passes the Stub floor (S.*); node key == stub handle
    T.3  Each edge is {from, to, kind} single-line strs
    T.4  Each unsupported_edges entry is {edge, reason ∈ valid, detail non-empty}
    T.6  unresolved_roots (#488) is a REQUIRED list of non-empty single-line
         handle strings ([] = all roots resolved; absence rejected)
    T.7  unresolved_call_sites (#488), when present, is a {handle: count} dict
         (non-empty single-line keys, int counts >= 1); optional (absent = not
         measured, i.e. callees not traced)
    T.8  unresolved_imports (#494), when present, is a {handle: [target, ...]}
         dict (non-empty single-line keys, non-empty target-string lists);
         optional (absent = imports not traced)
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
    "truncation_reasons": [],
    "unsupported_edges": [],
    "unresolved_roots": [],
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

    def test_missing_truncation_reasons_rejected(self) -> None:
        sg = _clone()
        del sg["truncation_reasons"]
        with pytest.raises(ConformanceViolation, match="truncation_reasons"):
            lint_response(sg, "trace")

    def test_unknown_truncation_reason_rejected(self) -> None:
        sg = _clone()
        sg["truncated"] = True
        sg["truncation_reasons"] = ["max_galaxies"]
        with pytest.raises(ConformanceViolation, match="truncation_reasons"):
            lint_response(sg, "trace")

    def test_truncated_inconsistent_with_reasons_rejected(self) -> None:
        # truncated True but no reasons listed — the back-compat invariant breaks.
        sg = _clone()
        sg["truncated"] = True
        sg["truncation_reasons"] = []
        with pytest.raises(ConformanceViolation, match="consistency"):
            lint_response(sg, "trace")

    def test_valid_truncated_with_reason_passes(self) -> None:
        sg = _clone()
        sg["truncated"] = True
        sg["truncation_reasons"] = ["max_depth"]
        lint_response(sg, "trace")  # must not raise

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


class TestTraceUnresolvedRoots:
    """T.6 (#488) — ``unresolved_roots`` honesty field.

    Always present (root resolution is always measured): ``[]`` when every root
    resolved, the failed handles otherwise.  It is a REQUIRED list of non-empty
    single-line handle strings — absence is a conformance violation (a broken
    trace), exactly like its sibling ``unsupported_edges``.
    """

    def test_missing_unresolved_roots_rejected(self) -> None:
        sg = _clone()
        del sg["unresolved_roots"]
        with pytest.raises(ConformanceViolation, match="unresolved_roots"):
            lint_response(sg, "trace")

    def test_empty_unresolved_roots_passes(self) -> None:
        # [] is the measured "every root resolved" answer — valid, not absent.
        sg = _clone()
        sg["unresolved_roots"] = []
        lint_response(sg, "trace")  # must not raise

    def test_present_non_empty_unresolved_roots_passes(self) -> None:
        sg = _clone()
        sg["unresolved_roots"] = ["mypackage._core.widgets.NoSuchSymbol"]
        lint_response(sg, "trace")  # must not raise

    def test_unresolved_roots_must_be_list(self) -> None:
        sg = _clone()
        sg["unresolved_roots"] = "mypackage._core.widgets.NoSuchSymbol"
        with pytest.raises(ConformanceViolation, match="unresolved_roots"):
            lint_response(sg, "trace")

    def test_unresolved_roots_entry_must_be_str(self) -> None:
        sg = _clone()
        sg["unresolved_roots"] = [123]
        with pytest.raises(ConformanceViolation, match="unresolved_roots"):
            lint_response(sg, "trace")

    def test_unresolved_roots_entry_must_be_non_empty(self) -> None:
        sg = _clone()
        sg["unresolved_roots"] = ["   "]
        with pytest.raises(ConformanceViolation, match="unresolved_roots"):
            lint_response(sg, "trace")


class TestTraceUnresolvedCallSites:
    """T.7 (#488 interior honesty) — ``unresolved_call_sites`` map.

    Optional (present only when ``callees`` was traced — absent = not measured).
    When present it is a dict of ``{handle: count}`` where each key is a non-empty
    single-line handle string and each count is an int >= 1 (zero counts are
    omitted — the absent key already says "complete here").
    """

    def test_absent_passes(self) -> None:
        # The members-only valid subgraph omits it — callees were not measured.
        lint_response(_clone(), "trace")  # must not raise

    def test_empty_map_passes(self) -> None:
        sg = _clone()
        sg["unresolved_call_sites"] = {}
        lint_response(sg, "trace")  # must not raise

    def test_populated_map_passes(self) -> None:
        sg = _clone()
        sg["unresolved_call_sites"] = {"mypackage._core.callees_fixture.orchestrate": 1}
        lint_response(sg, "trace")  # must not raise

    def test_must_be_dict(self) -> None:
        sg = _clone()
        sg["unresolved_call_sites"] = ["mypackage._core.callees_fixture.orchestrate"]
        with pytest.raises(ConformanceViolation, match="unresolved_call_sites"):
            lint_response(sg, "trace")

    def test_count_must_be_int(self) -> None:
        sg = _clone()
        sg["unresolved_call_sites"] = {"mypackage._core.callees_fixture.orchestrate": "1"}
        with pytest.raises(ConformanceViolation, match="unresolved_call_sites"):
            lint_response(sg, "trace")

    def test_count_must_be_positive(self) -> None:
        # 0 must be omitted, not recorded.
        sg = _clone()
        sg["unresolved_call_sites"] = {"mypackage._core.callees_fixture.orchestrate": 0}
        with pytest.raises(ConformanceViolation, match="unresolved_call_sites"):
            lint_response(sg, "trace")

    def test_count_must_not_be_bool(self) -> None:
        sg = _clone()
        sg["unresolved_call_sites"] = {"mypackage._core.callees_fixture.orchestrate": True}
        with pytest.raises(ConformanceViolation, match="unresolved_call_sites"):
            lint_response(sg, "trace")

    def test_key_must_be_non_empty_str(self) -> None:
        sg = _clone()
        sg["unresolved_call_sites"] = {"   ": 2}
        with pytest.raises(ConformanceViolation, match="unresolved_call_sites"):
            lint_response(sg, "trace")


class TestTraceUnresolvedImports:
    """T.8 (#494 interior honesty) — ``unresolved_imports`` map.

    Optional (present only when ``imports`` was traced). When present it is a
    dict ``{handle: [target, ...]}`` with non-empty single-line handle keys and
    non-empty lists of non-empty single-line import-target strings.
    """

    def test_absent_passes(self) -> None:
        lint_response(_clone(), "trace")  # members-only subgraph omits it

    def test_empty_map_passes(self) -> None:
        sg = _clone()
        sg["unresolved_imports"] = {}
        lint_response(sg, "trace")

    def test_populated_map_passes(self) -> None:
        sg = _clone()
        sg["unresolved_imports"] = {
            "mypackage._core.imports_fixture": ["_nonexistent_pkg_494.missing_symbol"]
        }
        lint_response(sg, "trace")

    def test_must_be_dict(self) -> None:
        sg = _clone()
        sg["unresolved_imports"] = ["pkg.thing"]
        with pytest.raises(ConformanceViolation, match="unresolved_imports"):
            lint_response(sg, "trace")

    def test_value_must_be_non_empty_list(self) -> None:
        sg = _clone()
        sg["unresolved_imports"] = {"mypackage._core.imports_fixture": []}
        with pytest.raises(ConformanceViolation, match="unresolved_imports"):
            lint_response(sg, "trace")

    def test_target_must_be_str(self) -> None:
        sg = _clone()
        sg["unresolved_imports"] = {"mypackage._core.imports_fixture": [123]}
        with pytest.raises(ConformanceViolation, match="unresolved_imports"):
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
