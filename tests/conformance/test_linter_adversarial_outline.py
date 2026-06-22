"""Adversarial test suite for the conformance linter — ``OutlineTree`` shape.

Each test targets one structural-floor (Check O) or layering (Check A) violation
for the ``outline`` operation, plus a dogfood test that runs REAL ``outline``
output through the linter.

Rule tags enforced here:
    O.1  ``node`` is REQUIRED and passes the Stub structural floor (S.*)
    O.2  ``truncated`` present ⇒ value is exactly ``true``, ``truncation_reason``
         present and in the outline enum, and ``children`` ABSENT.
         ``truncated: false`` rejected.
    O.3  ``truncated`` absent ⇒ ``truncation_reason`` absent.
    O.4  ``children`` present ⇒ list (possibly empty) of valid ``OutlineTree``.
    O.5  The outline ``truncation_reason`` enum includes ``external``; trace's
         narrower enum does NOT include ``external``.
    A.*  No source content anywhere in the tree, including at depth ≥ 2.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tests.conformance.response_linter import ConformanceViolation, lint_response

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "resolve_project"

# ---------------------------------------------------------------------------
# Minimal well-formed OutlineTree (depth-2 tree: module → class → method)
# ---------------------------------------------------------------------------

_STUB_MODULE: dict = {
    "handle": "mypackage._core.widgets",
    "kind": "module",
    "scope": "project",
    "line_start": 1,
    "line_end": 100,
}

_STUB_CLASS: dict = {
    "handle": "mypackage._core.widgets.Widget",
    "kind": "class",
    "scope": "project",
    "signature": "Widget(name: str)",
    "line_start": 10,
    "line_end": 50,
}

_STUB_METHOD: dict = {
    "handle": "mypackage._core.widgets.Widget.render",
    "kind": "method",
    "scope": "project",
    "signature": "render(self) -> str",
    "line_start": 20,
    "line_end": 25,
}

# A well-formed tree: module → class → method (both leaves carry children: [])
_VALID_OUTLINE: dict = {
    "node": _STUB_MODULE,
    "children": [
        {
            "node": _STUB_CLASS,
            "children": [
                {
                    "node": _STUB_METHOD,
                    "children": [],  # genuine leaf (method has no members)
                }
            ],
        }
    ],
}


def _clone() -> dict:
    return copy.deepcopy(_VALID_OUTLINE)


# ---------------------------------------------------------------------------
# TestOutlineAcceptsValid
# ---------------------------------------------------------------------------


class TestOutlineAcceptsValid:
    def test_well_formed_outline_passes(self) -> None:
        """A well-formed OutlineTree with children at depth 2 must not raise."""
        lint_response(_clone(), "outline")

    def test_empty_children_on_leaf_passes(self) -> None:
        """children: [] is a valid genuine-leaf marker (measured-empty)."""
        # Top-level node with no children (empty module-like)
        lint_response({"node": _STUB_MODULE, "children": []}, "outline")

    def test_truncated_node_passes(self) -> None:
        """A node cut off by max_depth with truncation_reason and no children passes."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_depth",
        }
        lint_response(tree, "outline")

    def test_truncated_max_nodes_passes(self) -> None:
        """O.5 — a max_nodes truncation carries member_count (the withheld count)."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_nodes",
            "member_count": 7,
        }
        lint_response(tree, "outline")

    def test_truncated_external_passes(self) -> None:
        """external is a valid truncation_reason for outline (not for trace)."""
        tree = {
            "node": {**_STUB_CLASS, "scope": "external"},
            "truncated": True,
            "truncation_reason": "external",
        }
        lint_response(tree, "outline")


# ---------------------------------------------------------------------------
# TestOutlineStructuralFloor (Check O)
# ---------------------------------------------------------------------------


class TestOutlineStructuralFloor:
    def test_missing_node_rejected(self) -> None:
        """O.1 — node is REQUIRED."""
        tree = _clone()
        del tree["node"]
        with pytest.raises(ConformanceViolation, match="node"):
            lint_response(tree, "outline")

    def test_node_must_be_dict(self) -> None:
        """O.1 — node must be a dict (Stub), not a string or list."""
        tree = _clone()
        tree["node"] = "not-a-stub"
        with pytest.raises(ConformanceViolation):
            lint_response(tree, "outline")

    def test_node_missing_handle_rejected(self) -> None:
        """O.1 — node passes the Stub structural floor: handle required."""
        tree = _clone()
        del tree["node"]["handle"]
        with pytest.raises(ConformanceViolation, match="handle"):
            lint_response(tree, "outline")

    def test_node_missing_scope_rejected(self) -> None:
        """O.1 — node passes the Stub structural floor: scope required."""
        tree = _clone()
        del tree["node"]["scope"]
        with pytest.raises(ConformanceViolation, match="scope"):
            lint_response(tree, "outline")

    def test_truncated_false_rejected(self) -> None:
        """O.2 — truncated: false is forbidden (absent-not-false contract)."""
        tree = _clone()
        tree["truncated"] = False
        with pytest.raises(ConformanceViolation, match="truncated.*false|false.*truncated"):
            lint_response(tree, "outline")

    def test_truncated_true_without_truncation_reason_rejected(self) -> None:
        """O.2 — truncated: true requires truncation_reason."""
        tree = {"node": _STUB_CLASS, "truncated": True}
        with pytest.raises(ConformanceViolation, match="truncation_reason"):
            lint_response(tree, "outline")

    def test_truncated_true_with_children_rejected(self) -> None:
        """O.2 — a truncated node must NOT carry children (absent-not-empty)."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_depth",
            "children": [],  # must be rejected — truncated + children is contradictory
        }
        with pytest.raises(ConformanceViolation, match="children"):
            lint_response(tree, "outline")

    def test_max_nodes_truncation_without_member_count_rejected(self) -> None:
        """O.5 — a max_nodes truncation MUST signpost member_count (#358)."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_nodes",
        }
        with pytest.raises(ConformanceViolation, match="member_count"):
            lint_response(tree, "outline")

    def test_member_count_bool_rejected(self) -> None:
        """O.5 — member_count must be a plain int, not a bool."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_nodes",
            "member_count": True,
        }
        with pytest.raises(ConformanceViolation, match="member_count"):
            lint_response(tree, "outline")

    def test_member_count_negative_rejected(self) -> None:
        """O.5 — member_count must be non-negative."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_nodes",
            "member_count": -1,
        }
        with pytest.raises(ConformanceViolation, match="member_count"):
            lint_response(tree, "outline")

    def test_max_depth_truncation_needs_no_member_count(self) -> None:
        """O.5 is scoped to max_nodes — a max_depth truncation needs no member_count."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_depth",
        }
        lint_response(tree, "outline")

    def test_truncation_reason_without_truncated_rejected(self) -> None:
        """O.3 — truncation_reason present without truncated is rejected."""
        tree = _clone()
        tree["truncation_reason"] = "max_depth"
        with pytest.raises(ConformanceViolation, match="truncation_reason"):
            lint_response(tree, "outline")

    def test_unknown_truncation_reason_rejected(self) -> None:
        """O.2 — truncation_reason must be one of the outline enum values."""
        tree = {
            "node": _STUB_CLASS,
            "truncated": True,
            "truncation_reason": "max_galaxies",  # not in the outline enum
        }
        with pytest.raises(ConformanceViolation, match="truncation_reason"):
            lint_response(tree, "outline")

    def test_children_must_be_list(self) -> None:
        """O.4 — children, when present, must be a list."""
        tree = _clone()
        tree["children"] = {"not": "a list"}
        with pytest.raises(ConformanceViolation, match="children"):
            lint_response(tree, "outline")

    def test_children_items_must_be_outline_trees(self) -> None:
        """O.4 — each item in children must be a valid OutlineTree (has node)."""
        tree = _clone()
        tree["children"] = ["not-a-tree"]  # string, not a dict
        with pytest.raises(ConformanceViolation):
            lint_response(tree, "outline")

    def test_child_missing_node_rejected(self) -> None:
        """O.4 — each child OutlineTree must have node."""
        tree = _clone()
        tree["children"] = [{"children": []}]  # no 'node' key
        with pytest.raises(ConformanceViolation, match="node"):
            lint_response(tree, "outline")

    def test_child_stub_floor_enforced(self) -> None:
        """O.1 via O.4 — Stub floor applied to each child node."""
        tree = _clone()
        tree["children"][0]["node"] = {
            "handle": "h",
            "kind": "class",
            # missing scope, line_start, line_end
        }
        with pytest.raises(ConformanceViolation):
            lint_response(tree, "outline")


# ---------------------------------------------------------------------------
# TestOutlineTruncationReasonEnum (O.5)
# ---------------------------------------------------------------------------


class TestOutlineTruncationReasonEnum:
    def test_external_is_accepted_for_outline(self) -> None:
        """O.5 — external is in the outline enum and must be accepted."""
        tree = {
            "node": {**_STUB_CLASS, "scope": "external"},
            "truncated": True,
            "truncation_reason": "external",
        }
        lint_response(tree, "outline")  # must not raise

    def test_external_is_rejected_for_trace(self) -> None:
        """O.5 — external is NOT in trace's enum; adding it did not loosen trace."""
        from tests.conformance.response_linter import _VALID_TRUNCATION_REASONS

        assert "external" not in _VALID_TRUNCATION_REASONS, (
            "external was incorrectly added to _VALID_TRUNCATION_REASONS (trace's "
            "constant). It must be in a separate outline-only constant."
        )

    def test_external_reason_on_trace_response_rejected(self) -> None:
        """Feeding external as a trace truncation_reason must be rejected by trace."""
        subgraph = {
            "nodes": {},
            "edges": [],
            "truncated": True,
            "truncation_reasons": ["external"],  # external is NOT valid for trace
            "unsupported_edges": [],
        }
        with pytest.raises(ConformanceViolation, match="truncation_reasons"):
            lint_response(subgraph, "trace")


# ---------------------------------------------------------------------------
# TestOutlineLayering (Check A)
# ---------------------------------------------------------------------------


class TestOutlineLayering:
    def test_source_key_at_root_rejected(self) -> None:
        """A.2 — a 'source' key at the root of an outline tree is rejected."""
        tree = _clone()
        tree["source"] = "def foo(): pass"
        with pytest.raises(ConformanceViolation):
            lint_response(tree, "outline")

    def test_body_key_in_node_stub_rejected(self) -> None:
        """A.2 — a 'body' key inside a node stub smuggles source content."""
        tree = _clone()
        tree["node"]["body"] = "def render(self):\n    return '<html>'"
        with pytest.raises(ConformanceViolation):
            lint_response(tree, "outline")

    def test_snippet_key_in_child_node_rejected(self) -> None:
        """A.2 — a 'snippet' key inside a child node is rejected."""
        tree = _clone()
        tree["children"][0]["node"]["snippet"] = "class Widget: ..."
        with pytest.raises(ConformanceViolation):
            lint_response(tree, "outline")

    def test_source_content_buried_at_depth_2_rejected(self) -> None:
        """A.* — layering check must reach source content at depth ≥ 2 in the tree.

        The violation is placed in the grandchild node (depth-2 child of root)
        to prove that _walk reaches into nested OutlineTree nodes.
        """
        tree = _clone()
        # The grandchild is tree["children"][0]["children"][0]
        grandchild_node = tree["children"][0]["children"][0]["node"]
        grandchild_node["body"] = "return '<html>'"
        with pytest.raises(ConformanceViolation, match="body|A.2"):
            lint_response(tree, "outline")

    def test_multiline_string_in_node_rejected(self) -> None:
        """A.1 — multi-line string value in a node field is rejected."""
        tree = _clone()
        # Inject a multi-line value into a non-allowlisted field
        tree["node"]["signature"] = "foo(\n    a: int,\n    b: str,\n    c: float,\n    d: bool\n)"
        with pytest.raises(ConformanceViolation, match="multi-line|signature"):
            lint_response(tree, "outline")

    def test_indented_code_block_in_node_rejected(self) -> None:
        """A.4 — indented code block pattern in a node field is rejected."""
        tree = _clone()
        tree["node"]["handle"] = "pkg.Widget    def __init__(self): pass"
        with pytest.raises(ConformanceViolation, match="indented"):
            lint_response(tree, "outline")


# ---------------------------------------------------------------------------
# TestRealOutlineOutputConforms
# ---------------------------------------------------------------------------


class TestRealOutlineOutputConforms:
    """Dogfood: real outline output passes the linter with no regressions."""

    @pytest.mark.asyncio
    async def test_real_outline_module_conforms(self) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.outline import outline

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await outline("mypackage._core.widgets.Widget", analyzer, max_depth=2)
        lint_response(result, "outline")  # must not raise

    @pytest.mark.asyncio
    async def test_real_outline_with_max_nodes_conforms(self) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.outline import outline

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await outline("mypackage._core.widgets", analyzer, max_nodes=5)
        lint_response(result, "outline")  # must not raise
