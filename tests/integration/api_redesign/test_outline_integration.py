"""Integration tests for the outline MCP tool endpoint.

These tests exercise the MCP wrapper layer (server.py) end-to-end —
from the decorated function down through the operation into the fixture
project.  They verify:

1. The tool is registered (importable, callable, async).
2. A module skeleton call returns a well-formed OutlineTree over the wire.
3. A depth-bounded call exhibits the ``truncated``/``truncation_reason`` markers,
   AND the ABSENCE of ``children`` on truncated nodes survives wire serialisation
   (a serialiser that mangles absence to ``[]`` or ``null`` would break Contract 1).
4. Count-consistency (spec §6.4): for a fully-walked non-truncated container,
   ``len(children) == inspect(handle).edge_counts.members``.  Both derive from
   ``resolve_members``, so this catches divergence between the two consumers.

Unit-level contract tests live in tests/unit/mcp/operations/test_outline.py.
These integration tests verify only the MCP wrapper layer delegation.
"""

from __future__ import annotations

import inspect as _inspect_stdlib
import json
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"


# ---------------------------------------------------------------------------
# Tool-registration assertions
# ---------------------------------------------------------------------------


class TestOutlineToolRegistered:
    """Verify that outline is importable from pyeye.mcp.server and is callable."""

    def test_outline_is_importable(self) -> None:
        """outline can be imported from pyeye.mcp.server."""
        from pyeye.mcp.server import outline  # noqa: F401

    def test_outline_is_callable(self) -> None:
        """outline is a callable (decorated async function)."""
        from pyeye.mcp.server import outline

        assert callable(outline)

    def test_outline_is_async(self) -> None:
        """outline is an async function (or wrapped to behave as one)."""
        from pyeye.mcp.server import outline

        assert _inspect_stdlib.iscoroutinefunction(outline)


# ---------------------------------------------------------------------------
# End-to-end: module skeleton
# ---------------------------------------------------------------------------


class TestOutlineModuleSkeletonEndToEnd:
    """A module skeleton call returns a well-formed OutlineTree over the wire.

    ``mypackage._core.widgets`` is a module with a known set of top-level members
    (DEFAULT_NAME, Widget, Config, make_widget, Premium, Deluxe).  At default
    bounds (no max_depth, max_nodes=200) all members are walked and returned.
    """

    @pytest.mark.asyncio
    async def test_module_skeleton_returns_outline_tree(self) -> None:
        """outline(widgets module) returns a dict with 'node' and 'children' keys."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "node" in result, f"'node' missing from result: {result!r}"
        assert "children" in result, (
            "'children' must be present for a fully-walked module "
            f"(absence means 'not walked', which is wrong here); result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_module_skeleton_node_has_required_fields(self) -> None:
        """The root node Stub has handle/kind/scope/line_start/line_end."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        node = result["node"]
        assert isinstance(node, dict), f"node must be a plain dict; got {type(node)!r}"
        for field in ("handle", "kind", "scope", "line_start", "line_end"):
            assert field in node, f"node missing required field '{field}'; node={node!r}"

    @pytest.mark.asyncio
    async def test_module_skeleton_root_is_module_kind(self) -> None:
        """The root node has kind='module'."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        node = result["node"]
        assert (
            node["kind"] == "module"
        ), f"root node must have kind='module'; got {node.get('kind')!r}"

    @pytest.mark.asyncio
    async def test_module_skeleton_children_are_list(self) -> None:
        """children is a list of OutlineTree nodes."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        children = result["children"]
        assert isinstance(children, list), f"children must be a list; got {type(children)!r}"
        assert (
            len(children) > 0
        ), "mypackage._core.widgets has top-level members — children must be non-empty"

    @pytest.mark.asyncio
    async def test_module_skeleton_children_have_node_field(self) -> None:
        """Each child in the tree is an OutlineTree with a 'node' field."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        for i, child in enumerate(result["children"]):
            assert isinstance(child, dict), f"child[{i}] must be a plain dict; got {type(child)!r}"
            assert "node" in child, f"child[{i}] missing 'node' field; child={child!r}"

    @pytest.mark.asyncio
    async def test_module_skeleton_no_source_content(self) -> None:
        """No source content anywhere in the tree — spec §6 invariant 1."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        # Recursively check that no node contains 'source', 'text', or 'snippet'
        _forbidden = {"source", "text", "snippet"}

        def check_node(tree: dict, path: str) -> None:
            node = tree["node"]
            for bad_field in _forbidden:
                assert (
                    bad_field not in node
                ), f"source content '{bad_field}' found in node at {path}: {node!r}"
            for i, child in enumerate(tree.get("children", [])):
                check_node(child, f"{path}.children[{i}]")

        check_node(result, "root")

    @pytest.mark.asyncio
    async def test_module_skeleton_result_is_json_serialisable(self) -> None:
        """The module skeleton round-trips through json.dumps without error."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)
        assert "node" in roundtripped
        assert "children" in roundtripped

    @pytest.mark.asyncio
    async def test_module_skeleton_result_is_plain_dict(self) -> None:
        """The result is an exact plain dict — no custom type subclasses."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        assert (
            type(result) is dict  # noqa: E721
        ), f"result must be exact dict (not subclass); got {type(result)!r}"

    @pytest.mark.asyncio
    async def test_module_skeleton_fully_walked_omits_truncated(self) -> None:
        """A fully-walked tree node has no 'truncated' key (Contract 2 — absent-not-false)."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        assert "truncated" not in result, (
            "A fully-walked root must OMIT 'truncated' (absent-not-false, Contract 2); "
            f"got keys={list(result.keys())!r}"
        )


# ---------------------------------------------------------------------------
# End-to-end: depth-bounded call — truncation markers over the wire
# ---------------------------------------------------------------------------


class TestOutlineTruncationEndToEnd:
    """A depth-bounded call exhibits truncated/truncation_reason markers over the wire.

    ``mypackage._core.widgets`` has class members (Widget, Config, Premium, Deluxe).
    At ``max_depth=1`` the root (depth 0) is walked — its class children are placed
    at depth 1, which is the frontier.  Each of those class children has members,
    so they are marked ``truncated: "max_depth"`` and OMIT ``children``.

    The critical assertion here is that ``children`` is GENUINELY ABSENT (not ``[]``
    and not ``null``) on a truncated node — this is the Contract 1 absence that a
    naive serialiser would mangle.
    """

    @pytest.mark.asyncio
    async def test_depth_bounded_produces_truncated_nodes(self) -> None:
        """At max_depth=1, class children at the frontier are marked truncated."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        # The root itself must be fully walked (it is at depth 0, not the frontier).
        assert "children" in result, (
            "Root (depth 0) must have 'children' at max_depth=1; "
            f"got keys={list(result.keys())!r}"
        )

        # At least one class child must be truncated (Widget, Config, Premium, Deluxe all have members).
        truncated_children = [c for c in result["children"] if c.get("truncated") is True]
        assert len(truncated_children) > 0, (
            "At max_depth=1, class children with members must be marked truncated; "
            f"got children={[c['node']['handle'] for c in result['children']]!r}"
        )

    @pytest.mark.asyncio
    async def test_truncated_node_has_truncation_reason(self) -> None:
        """Every truncated node carries a truncation_reason."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        for child in result["children"]:
            if child.get("truncated") is True:
                assert "truncation_reason" in child, (
                    f"truncated node must carry 'truncation_reason'; "
                    f"got keys={list(child.keys())!r}; node={child['node']!r}"
                )
                assert child["truncation_reason"] in ("max_depth", "max_nodes", "external"), (
                    f"truncation_reason must be one of the three enum values; "
                    f"got {child['truncation_reason']!r}"
                )

    @pytest.mark.asyncio
    async def test_truncated_node_reason_is_max_depth(self) -> None:
        """Class children truncated at the depth frontier have reason='max_depth'."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        # Widget, Config, Premium, Deluxe are classes at the depth-1 frontier.
        class_children = [
            c
            for c in result["children"]
            if c["node"]["kind"] == "class" and c.get("truncated") is True
        ]
        assert len(class_children) > 0, "Expected at least one truncated class child at max_depth=1"
        for child in class_children:
            assert child["truncation_reason"] == "max_depth", (
                f"Class child at depth frontier must have reason='max_depth'; "
                f"got {child.get('truncation_reason')!r}; node={child['node']!r}"
            )

    @pytest.mark.asyncio
    async def test_truncated_node_children_absent_not_empty(self) -> None:
        """CRITICAL (Contract 1): truncated nodes have 'children' ABSENT, not [] or null.

        This is the exact serialiser-mangle that absence-vs-zero guards against.
        A truncated container MUST NOT appear to be an empty leaf (children: []).
        The key must be genuinely missing from the dict.
        """
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        for child in result["children"]:
            if child.get("truncated") is True:
                # The key must be GENUINELY ABSENT — not [] and not None.
                assert "children" not in child, (
                    f"Contract 1 VIOLATION: truncated node must have 'children' ABSENT "
                    f"(not [] or null); got 'children'={child.get('children')!r} "
                    f"in node={child['node']['handle']!r}"
                )

    @pytest.mark.asyncio
    async def test_absence_survives_json_round_trip(self) -> None:
        """Contract 1 absence survives json.dumps/loads — the easy serialiser-mangle target."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        # Round-trip through JSON
        roundtripped = json.loads(json.dumps(result))

        # After round-trip: truncated nodes must STILL have 'children' absent.
        for child in roundtripped["children"]:
            if child.get("truncated") is True:
                assert "children" not in child, (
                    f"Contract 1 VIOLATION after JSON round-trip: 'children' appeared "
                    f"in truncated node {child['node']['handle']!r}; "
                    f"got 'children'={child.get('children')!r}"
                )

    @pytest.mark.asyncio
    async def test_non_truncated_nodes_omit_truncated_key(self) -> None:
        """Contract 2: fully-walked (non-truncated) nodes omit 'truncated' entirely."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        for child in result["children"]:
            if child.get("truncated") is not True:
                # 'truncated' must be absent, not False.
                assert "truncated" not in child, (
                    f"Contract 2 VIOLATION: non-truncated node must OMIT 'truncated' "
                    f"(never 'truncated: false'); "
                    f"got {child.get('truncated')!r} in node={child['node']['handle']!r}"
                )

    @pytest.mark.asyncio
    async def test_genuine_leaf_at_frontier_gets_empty_children(self) -> None:
        """At the depth frontier, a container with no members gets children: [] (genuine leaf).

        Non-container kinds (function, variable, etc.) always get children: [] regardless
        of depth.  This test verifies the depth-frontier peek path too: make_widget is a
        function — it is a genuine leaf and must carry children: [] at any depth.
        """
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        # make_widget is a function — always a genuine leaf, never truncated.
        make_widget_child = next(
            (c for c in result["children"] if "make_widget" in c["node"]["handle"]),
            None,
        )
        assert make_widget_child is not None, "make_widget must be present in the module's children"
        assert (
            "children" in make_widget_child
        ), "make_widget (function) must have 'children' key present as a genuine leaf"
        assert make_widget_child["children"] == [], (
            f"make_widget (function) must have children=[] (genuine leaf); "
            f"got {make_widget_child['children']!r}"
        )
        assert (
            "truncated" not in make_widget_child
        ), "make_widget must not have 'truncated' (it is a genuine leaf)"

    @pytest.mark.asyncio
    async def test_depth_bounded_result_is_json_serialisable(self) -> None:
        """The depth-bounded result round-trips through json.dumps without error."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
            max_depth=1,
        )

        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)
        assert "children" in roundtripped


# ---------------------------------------------------------------------------
# End-to-end: count-consistency check — spec §6.4
# ---------------------------------------------------------------------------


class TestOutlineCountConsistencyEndToEnd:
    """Spec §6.4: for a fully-walked container, len(children) == inspect.edge_counts.members.

    Both ``outline`` and ``inspect`` derive from ``resolve_members``.  A divergence
    between them would indicate a bug in one consumer.

    Fixture: ``mypackage._core.widgets.Config`` — a small class with 2 attribute
    members (``debug``, ``host``) and no methods.  At default bounds (no max_depth,
    max_nodes=200) it is fully walked, so the count comparison is valid.

    ``inspect("mypackage._core.widgets.Config").edge_counts.members`` returns 2;
    ``outline("mypackage._core.widgets.Config").children`` must also be length 2.
    """

    @pytest.mark.asyncio
    async def test_config_outline_children_matches_inspect_edge_count(self) -> None:
        """len(outline.children) == inspect.edge_counts.members for Config."""
        from pyeye.mcp.server import (
            inspect as mcp_inspect,
            outline as mcp_outline,
        )

        # Get the member count from inspect.
        inspect_result = await mcp_inspect(
            handle="mypackage._core.widgets.Config",
            project_path=str(_FIXTURE),
        )
        inspect_members_count: int = inspect_result["edge_counts"]["members"]

        # Get the children from outline (fully walked — no truncation at defaults).
        outline_result = await mcp_outline(
            handle="mypackage._core.widgets.Config",
            project_path=str(_FIXTURE),
        )

        # Precondition: the outline must be fully walked (no truncated key on root).
        assert "truncated" not in outline_result, (
            "Precondition failed: Config root must not be truncated at default bounds; "
            f"got keys={list(outline_result.keys())!r}"
        )
        assert (
            "children" in outline_result
        ), "Precondition failed: Config root must have 'children' at default bounds"

        outline_children_count = len(outline_result["children"])

        assert outline_children_count == inspect_members_count, (
            f"Count-consistency failure (spec §6.4): "
            f"outline.children={outline_children_count} != "
            f"inspect.edge_counts.members={inspect_members_count}. "
            "Both derive from resolve_members — a divergence indicates a bug."
        )

    @pytest.mark.asyncio
    async def test_config_children_are_fully_walked_leaves(self) -> None:
        """Config's children (debug, host) are attribute leaves — each carries children: [].

        Contract 1 verification: the attribute nodes are fully walked and have
        children: [] (measured-empty, not-truncated genuine leaves).
        """
        from pyeye.mcp.server import outline as mcp_outline

        result = await mcp_outline(
            handle="mypackage._core.widgets.Config",
            project_path=str(_FIXTURE),
        )

        for i, child in enumerate(result["children"]):
            assert "children" in child, (
                f"Config.children[{i}] must have 'children' present (fully walked); "
                f"node={child['node']!r}"
            )
            assert child["children"] == [], (
                f"Config.children[{i}] must be a genuine leaf (children=[]); "
                f"node={child['node']!r}; got children={child['children']!r}"
            )
            assert (
                "truncated" not in child
            ), f"Config.children[{i}] must not be truncated; node={child['node']!r}"

    @pytest.mark.asyncio
    async def test_count_consistency_result_is_json_serialisable(self) -> None:
        """The Config outline round-trips through json.dumps without error."""
        from pyeye.mcp.server import outline as mcp_outline

        result = await mcp_outline(
            handle="mypackage._core.widgets.Config",
            project_path=str(_FIXTURE),
        )

        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)
        assert "node" in roundtripped
        assert "children" in roundtripped
        # Children survive round-trip.
        assert isinstance(roundtripped["children"], list)


# ---------------------------------------------------------------------------
# End-to-end: unresolvable-handle contract — "never raises" guarantee
# ---------------------------------------------------------------------------


class TestOutlineUnresolvableHandleEndToEnd:
    """Calling outline with a bogus handle must never raise and must return
    a minimal single-node OutlineTree with children: [].

    This is the docstring's "never raises" guarantee tested at the wire
    boundary (through the full decorator stack), not just the unit layer.
    """

    @pytest.mark.asyncio
    async def test_unresolvable_handle_does_not_raise(self) -> None:
        """outline with a bogus handle returns without raising."""
        from pyeye.mcp.server import outline

        # Must not raise any exception.
        result = await outline(
            handle="does.not.exist.Nope",
            project_path=str(_FIXTURE),
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_unresolvable_handle_returns_dict_with_required_keys(self) -> None:
        """outline with a bogus handle returns a plain dict with 'node' and 'children'."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="does.not.exist.Nope",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "node" in result, f"'node' missing from minimal-fallback result: {result!r}"
        assert "children" in result, (
            "'children' must be present on the minimal single-node fallback "
            f"(docstring guarantee); got keys={list(result.keys())!r}"
        )

    @pytest.mark.asyncio
    async def test_unresolvable_handle_returns_empty_children(self) -> None:
        """The minimal fallback OutlineTree has children: [] (no members to walk)."""
        from pyeye.mcp.server import outline

        result = await outline(
            handle="does.not.exist.Nope",
            project_path=str(_FIXTURE),
        )

        assert result["children"] == [], (
            f"Minimal fallback must have children=[] (docstring guarantee); "
            f"got children={result['children']!r}"
        )
