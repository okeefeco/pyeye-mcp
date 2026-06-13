"""Tests for the ``outline(handle, ...)`` operation — Phase 1 (Tasks 1.1 + 1.2).

``outline`` returns the structural skeleton of a module or class as a nested
tree of ``(node, children?)`` entries, with two load-bearing absence contracts
(spec §4.2):

  Contract 1 — ``children`` absent ⇔ not expanded (a cap fired).
    ``children: []`` = measured genuine leaf.  Missing ``children`` = "unknown."

  Contract 2 — ``truncated`` absent-not-false.
    ``truncated: true`` only on a cut-off node, always with ``truncation_reason``
    and absent ``children``.  Fully-walked nodes omit ``truncated`` entirely.

Fixture layout
--------------
nested_class_inspect (primary — has the nesting the outline tests need)::

    pkg.mod               ← module
      top_level_function  ← function (line 12) — genuine leaf
      Outer               ← class (line 17) — has members
        outer_method      ← method (line 20) — genuine leaf
        Inner             ← nested class (line 24) — has members
          inner_method    ← method (line 27) — genuine leaf
      Empty               ← class (line 35) — no members at all

resolve_project (supplementary — Widget has alphabetically-out-of-source-order
members, needed for the source-ordering test; xml.etree.ElementTree is used for
the external nested-container truncation test)::

    mypackage._core.widgets.Widget
      __init__   (line 34)   — method
      greet      (line 37)   — method
      slow_greet (line 41)   — method
      display_name (line 45) — property
      default    (line 50)   — method
      normalize  (line 55)   — method
      color      (line 29)   — attribute  ← alphabetically-earlier, line-earlier

    xml.etree.ElementTree  ← external module with nested class children
      ParseError            ← external class child → truncated: "external"
      Element               ← external class child → truncated: "external"
      … (9 container children total, all truncated: "external")

Note: source order diverges from alphabetical (e.g. ``color`` at line 29 comes
first in source but "c" sorts before "__"), so the ordering test verifies the
``(line_start, handle)`` key rather than alphabetical or definition order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

# Fixtures — real committed directories (no tmp-dir symlinks; Jedi degrades on
# macOS symlinked temp paths, see feedback_jedi_macos_tmp_symlink.md).
_FIXTURE_NESTED = Path(__file__).parent.parent.parent.parent / "fixtures" / "nested_class_inspect"
_FIXTURE_RESOLVE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

# Canonical handles — nested_class_inspect
_MOD_HANDLE = "pkg.mod"
_TOP_LEVEL_FUNC_HANDLE = "pkg.mod.top_level_function"
_OUTER_HANDLE = "pkg.mod.Outer"
_OUTER_METHOD_HANDLE = "pkg.mod.Outer.outer_method"
_INNER_HANDLE = "pkg.mod.Outer.Inner"
_INNER_METHOD_HANDLE = "pkg.mod.Outer.Inner.inner_method"
_EMPTY_HANDLE = "pkg.mod.Empty"

# Canonical handles — resolve_project (for source-order test)
_WIDGET_HANDLE = "mypackage._core.widgets.Widget"

# External stdlib handles — scope="external"
_PATHLIB_PATH_HANDLE = "pathlib.Path"
# xml.etree.ElementTree is an external module whose direct children include
# several classes (ParseError, Element, QName, …) — container children that
# must be truncated: "external" at depth ≥ 1 (spec §5.4).
_XML_ET_HANDLE = "xml.etree.ElementTree"


@pytest.fixture
def nested_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at nested_class_inspect fixture."""
    return JediAnalyzer(str(_FIXTURE_NESTED))


@pytest.fixture
def resolve_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE_RESOLVE))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STUB_REQUIRED_KEYS = frozenset({"handle", "kind", "scope", "line_start", "line_end"})
_SOURCE_CONTENT_KEYS = frozenset({"body", "source", "code", "snippet", "text"})


def _assert_is_stub(stub: dict[str, Any]) -> None:
    """Assert *stub* conforms to the spec §4.1 Stub shape."""
    assert isinstance(stub, dict), f"node must be a dict, got {type(stub)}"
    missing = _STUB_REQUIRED_KEYS - set(stub)
    assert not missing, f"stub missing required keys {missing}: {stub}"
    for forbidden in _SOURCE_CONTENT_KEYS:
        assert forbidden not in stub, f"stub leaked source content via {forbidden!r}: {stub}"


def _assert_contract1(tree: dict[str, Any]) -> None:
    """Assert the §4.2 Contract-1 and Contract-2 absence invariants hold,
    recursively on *tree* and all descendants.

    - ``truncated`` present ⇒ value is exactly ``True``, ``truncation_reason``
      present, ``children`` ABSENT.
    - ``truncated`` absent ⇒ ``truncation_reason`` absent.
    - A fully-walked node never carries ``truncated: False``.
    - ``children`` present ⇒ a list; each element is an ``OutlineTree``.
    """
    assert "node" in tree, f"OutlineTree missing 'node': {tree.keys()}"
    _assert_is_stub(tree["node"])

    if "truncated" in tree:
        # Contract 2: truncated is always exactly true, co-occurs with reason,
        # and the node has no children.
        assert (
            tree["truncated"] is True
        ), f"truncated must be True (never False, never a string): {tree['truncated']!r}"
        assert "truncation_reason" in tree, "truncated node must carry truncation_reason"
        assert "children" not in tree, "truncated node MUST NOT carry children (absence contract)"
    else:
        # Contract 2: truncation_reason absent when truncated absent.
        assert "truncation_reason" not in tree, "truncation_reason present without truncated"

    if "children" in tree:
        assert isinstance(
            tree["children"], list
        ), f"children must be a list, got {type(tree['children'])}"
        for child in tree["children"]:
            _assert_contract1(child)  # recursive


def _find_child(tree: dict[str, Any], handle: str) -> dict[str, Any] | None:
    """Return the direct child of *tree* whose node.handle == *handle*, or None."""
    for child in tree.get("children", []):
        if child["node"]["handle"] == handle:
            return child
    return None


def _count_nodes(tree: dict[str, Any]) -> int:
    """Count all nodes in the tree (root + all descendants)."""
    total = 1
    for child in tree.get("children", []):
        total += _count_nodes(child)
    return total


# ---------------------------------------------------------------------------
# Tests are placed in classes per concern so we can run subsets by class name.
# ---------------------------------------------------------------------------


class TestOutlineImport:
    """The module ``outline`` must be importable from
    ``pyeye.mcp.operations.outline`` before any functionality can be tested.

    Task 1.1: these tests are expected to FAIL with ImportError until
    Task 1.2 creates the module.
    """

    def test_outline_importable(self) -> None:
        """Import should succeed once the module is created (Task 1.2)."""
        from pyeye.mcp.operations.outline import outline  # noqa: F401  # type: ignore[import]

        assert callable(outline)


class TestOutlineModuleRoot:
    """Module handle → tree whose ``node`` is the module stub and whose
    ``children`` are the module's top-level definitions (functions + classes)."""

    @pytest.mark.asyncio
    async def test_module_root_node_is_module_stub(self, nested_analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        assert tree["node"]["handle"] == _MOD_HANDLE
        assert tree["node"]["kind"] == "module"

    @pytest.mark.asyncio
    async def test_module_children_are_top_level_definitions(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        assert "children" in tree, "module root must have children (was walked)"
        child_handles = {c["node"]["handle"] for c in tree["children"]}
        # Both top-level definitions must appear as direct children.
        assert (
            _TOP_LEVEL_FUNC_HANDLE in child_handles
        ), f"top_level_function missing from module children: {child_handles}"
        assert (
            _OUTER_HANDLE in child_handles
        ), f"Outer class missing from module children: {child_handles}"

    @pytest.mark.asyncio
    async def test_module_children_all_have_valid_stubs(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        for child in tree["children"]:
            _assert_is_stub(child["node"])


class TestOutlineClassRoot:
    """Class handle → tree whose ``children`` are its methods and nested classes."""

    @pytest.mark.asyncio
    async def test_class_root_node_is_class_stub(self, nested_analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_OUTER_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        assert tree["node"]["handle"] == _OUTER_HANDLE
        assert tree["node"]["kind"] == "class"

    @pytest.mark.asyncio
    async def test_class_children_are_methods_and_nested_classes(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_OUTER_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        assert "children" in tree, "class root must have children"
        child_handles = {c["node"]["handle"] for c in tree["children"]}
        assert (
            _OUTER_METHOD_HANDLE in child_handles
        ), f"outer_method missing from Outer children: {child_handles}"
        assert (
            _INNER_HANDLE in child_handles
        ), f"Inner nested class missing from Outer children: {child_handles}"


class TestOutlineLeafNodes:
    """Methods and functions are genuine leaves: ``children: []``."""

    @pytest.mark.asyncio
    async def test_method_is_genuine_leaf(self, nested_analyzer: JediAnalyzer) -> None:
        """A method node must carry ``children: []`` — measured empty, not missing."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_OUTER_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        method_node = _find_child(tree, _OUTER_METHOD_HANDLE)
        assert method_node is not None, "outer_method child not found"
        assert (
            "children" in method_node
        ), "method must carry children (was walked — resolve_members returns [] for methods)"
        assert method_node["children"] == [], "method children must be empty list (genuine leaf)"
        assert "truncated" not in method_node, "a genuine leaf must not carry truncated"

    @pytest.mark.asyncio
    async def test_function_is_genuine_leaf(self, nested_analyzer: JediAnalyzer) -> None:
        """A top-level function node must carry ``children: []``."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        func_node = _find_child(tree, _TOP_LEVEL_FUNC_HANDLE)
        assert func_node is not None, "top_level_function child not found"
        assert "children" in func_node, "function must carry children (was walked)"
        assert func_node["children"] == [], "function children must be empty list"
        assert "truncated" not in func_node, "a genuine leaf must not carry truncated"


class TestOutlineNestedClassRecursion:
    """Nested classes recurse — ``members`` hierarchy, not function bodies."""

    @pytest.mark.asyncio
    async def test_nested_class_inner_is_present_in_tree(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """module outline walks: mod → Outer → Inner (nested class)."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        outer_node = _find_child(tree, _OUTER_HANDLE)
        assert outer_node is not None, "Outer not in module children"
        assert "children" in outer_node, "Outer must have walked children"
        inner_node = _find_child(outer_node, _INNER_HANDLE)
        assert inner_node is not None, "Inner nested class not found in Outer children"
        assert inner_node["node"]["kind"] == "class"

    @pytest.mark.asyncio
    async def test_inner_class_method_is_leaf(self, nested_analyzer: JediAnalyzer) -> None:
        """inner_method inside Inner is a leaf (``children: []``)."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        outer_node = _find_child(tree, _OUTER_HANDLE)
        assert outer_node is not None
        inner_node = _find_child(outer_node, _INNER_HANDLE)
        assert inner_node is not None
        assert "children" in inner_node, "Inner must have walked children"
        inner_method_node = _find_child(inner_node, _INNER_METHOD_HANDLE)
        assert inner_method_node is not None, "inner_method not found in Inner children"
        assert inner_method_node["children"] == [], "inner_method is a genuine leaf"
        assert "truncated" not in inner_method_node


class TestOutlineMaxDepth:
    """``max_depth`` bounds recursion; the frontier peek distinguishes genuine
    empty containers from cut-off ones — the load-bearing §4.2 Contract 1 test.

    Both sides must be asserted explicitly so an implementation that skips the
    peek (emitting ``children: []`` for both cases) fails loudly.
    """

    @pytest.mark.asyncio
    async def test_max_depth_0_module_has_children_key_absent_for_top_level_defs(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """At max_depth=0, root is depth 0 and is the frontier; its non-empty
        children are cut off → ``truncated: "max_depth"``, NO ``children`` key."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer, max_depth=0)
        _assert_contract1(tree)
        # The module root itself is depth 0; the peek finds its children (non-empty),
        # so it must be marked truncated, NOT carry children: [].
        assert (
            "truncated" in tree
        ), "module at max_depth=0 has non-empty members → must be truncated"
        assert tree["truncated"] is True
        assert tree["truncation_reason"] == "max_depth"
        assert "children" not in tree, "truncated node must NOT carry children (absence contract)"

    @pytest.mark.asyncio
    async def test_max_depth_1_outer_children_walked_inner_cut_off(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """At max_depth=1: mod's children are depth 1 (walked); Outer at depth 1
        is ON the frontier; its children (including Inner) are peeked but not walked.
        Outer has non-empty members → truncated.
        top_level_function is a genuine leaf at depth 1 → children: [].
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer, max_depth=1)
        _assert_contract1(tree)
        # Module root must have walked children (depth 0, within limit).
        assert "children" in tree
        func_node = _find_child(tree, _TOP_LEVEL_FUNC_HANDLE)
        outer_node = _find_child(tree, _OUTER_HANDLE)
        assert func_node is not None, "top_level_function must be a child"
        assert outer_node is not None, "Outer must be a child"

        # top_level_function is at depth 1 on the frontier; peek finds no members →
        # genuine leaf → children: [].
        assert (
            "children" in func_node
        ), "top_level_function: peek finds no members → genuine leaf (children: [])"
        assert (
            func_node["children"] == []
        ), "top_level_function must have children: [] (genuine leaf, not truncated)"
        assert "truncated" not in func_node

        # Outer is at depth 1 on the frontier; peek finds non-empty members →
        # cut off → truncated: "max_depth", NO children key.
        assert (
            "truncated" in outer_node
        ), "Outer at max_depth=1 frontier has non-empty members → must be truncated"
        assert outer_node["truncated"] is True
        assert outer_node["truncation_reason"] == "max_depth"
        assert "children" not in outer_node, "Outer truncated node must NOT carry children"

    @pytest.mark.asyncio
    async def test_max_depth_none_walks_fully(self, nested_analyzer: JediAnalyzer) -> None:
        """max_depth=None (default) walks to all leaves; no truncated nodes."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)

        # No truncated nodes anywhere in the tree.
        def _has_truncated(t: dict[str, Any]) -> bool:
            if "truncated" in t:
                return True
            return any(_has_truncated(c) for c in t.get("children", []))

        assert not _has_truncated(tree), "unbounded outline must not truncate"
        # Inner.inner_method is accessible without truncation.
        outer_node = _find_child(tree, _OUTER_HANDLE)
        assert outer_node is not None
        inner_node = _find_child(outer_node, _INNER_HANDLE)
        assert inner_node is not None
        inner_method_node = _find_child(inner_node, _INNER_METHOD_HANDLE)
        assert inner_method_node is not None


class TestOutlineMaxNodes:
    """``max_nodes`` bounds total node count; hitting it marks not-yet-expanded
    containers ``truncated: "max_nodes"`` with NO ``children`` and NO peek."""

    @pytest.mark.asyncio
    async def test_max_nodes_1_only_root_expanded(self, nested_analyzer: JediAnalyzer) -> None:
        """max_nodes=1: root counts as node 1; no children expanded.
        The module root has non-empty members but the budget is already full →
        children absent (NOT peeked), truncated: "max_nodes"."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer, max_nodes=1)
        _assert_contract1(tree)
        assert _count_nodes(tree) == 1
        assert "truncated" in tree, "root with budget=1 and non-empty members must be truncated"
        assert tree["truncated"] is True
        assert tree["truncation_reason"] == "max_nodes"
        assert "children" not in tree

    @pytest.mark.asyncio
    async def test_max_nodes_respects_budget(self, nested_analyzer: JediAnalyzer) -> None:
        """Total node count never exceeds max_nodes."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        for budget in (2, 3, 4):
            tree = await outline(_MOD_HANDLE, nested_analyzer, max_nodes=budget)
            actual = _count_nodes(tree)
            assert actual <= budget, f"max_nodes={budget} violated: got {actual} nodes"

    @pytest.mark.asyncio
    async def test_max_nodes_marks_containers_not_peeked(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """When the budget is exhausted, not-yet-expanded containers carry
        ``truncated: "max_nodes"`` with ``children`` absent (no peek).

        Budget=3: root (1) + top_level_function (2) + Outer (3). When Outer is
        processed, the budget is full → Outer is truncated: "max_nodes" without
        any peek into its members.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        # Budget 3 puts Outer in the tree (node 3) but exhausts the budget before
        # Outer can be expanded — so Outer gets truncated: "max_nodes", no peek.
        tree = await outline(_MOD_HANDLE, nested_analyzer, max_nodes=3)
        _assert_contract1(tree)

        # Find any truncated-by-max_nodes node — must have no children key.
        def _find_max_nodes_truncated(t: dict[str, Any]) -> list[dict[str, Any]]:
            found = []
            if t.get("truncation_reason") == "max_nodes":
                found.append(t)
            for c in t.get("children", []):
                found.extend(_find_max_nodes_truncated(c))
            return found

        cut_off = _find_max_nodes_truncated(tree)
        assert cut_off, "expected at least one max_nodes-truncated node at budget=3"
        for node in cut_off:
            assert "children" not in node, "max_nodes truncated node must NOT carry children"


class TestOutlineMaxNodesTiebreaker:
    """When both a depth/external cap AND the node budget could fire on the same
    node, ``truncation_reason`` must be ``"max_nodes"`` (spec §5.4 tiebreaker).

    This pins a specific implementation choice — the budget is the harder global
    bound and wins the reporting tiebreaker.  An implementation that reverses the
    priority (reports ``"max_depth"`` when the budget also applies) fails here.
    """

    @pytest.mark.asyncio
    async def test_max_nodes_wins_over_max_depth_tiebreaker(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """Set max_depth=1 (Outer would be truncated "max_depth") AND max_nodes=3
        so both caps apply to Outer simultaneously.

        Structure at budget=3, depth=1:
          root (node 1): walked (depth 0)
          top_level_function (node 2): depth 1 = frontier, non-container → children: []
          Outer (node 3): depth 1 = frontier, container, budget now full

        Outer is at the depth frontier (has non-empty members → would be
        truncated: "max_depth") AND the budget is full (node_count == max_nodes →
        would be truncated: "max_nodes").  Both caps could fire.  The tiebreaker
        rule (spec §5.4) says max_nodes wins: truncation_reason must be "max_nodes".
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer, max_depth=1, max_nodes=3)
        _assert_contract1(tree)
        assert _count_nodes(tree) == 3

        # Both func and Outer are children of root (3 nodes total).
        func_node = _find_child(tree, _TOP_LEVEL_FUNC_HANDLE)
        outer_node = _find_child(tree, _OUTER_HANDLE)
        assert func_node is not None, "top_level_function must be a child"
        assert outer_node is not None, "Outer must be a child"

        # func (non-container, depth frontier): genuine leaf.
        assert func_node.get("children") == [], "top_level_function must be a genuine leaf"
        assert "truncated" not in func_node

        # Outer: BOTH depth-frontier (has members → would be max_depth) AND
        # budget-full (node 3 = max_nodes → would be max_nodes).
        # Tiebreaker: max_nodes must win.
        assert (
            "truncated" in outer_node
        ), "Outer at depth frontier with full budget must be truncated"
        assert outer_node["truncation_reason"] == "max_nodes", (
            f"budget+depth tiebreaker: expected 'max_nodes', "
            f"got {outer_node['truncation_reason']!r}"
        )
        assert "children" not in outer_node


class TestOutlineExternalCap:
    """External-scope handles are capped at one level; deeper external containers
    are ``truncated: "external"`` with ``children`` absent (no peek)."""

    @pytest.mark.asyncio
    async def test_external_root_gets_one_level(self, resolve_analyzer: JediAnalyzer) -> None:
        """The external root itself always gets one level of members (the asymmetry:
        root is walked, but deeper external containers are not)."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_PATHLIB_PATH_HANDLE, resolve_analyzer)
        _assert_contract1(tree)
        assert tree["node"]["scope"] == "external"
        # The root must have been walked (``children`` present, not truncated).
        assert "children" in tree, "external root must have children walked (one level)"
        assert "truncated" not in tree, (
            "the root itself must not be truncated — the external cap only applies "
            "to nodes BELOW the root"
        )

    @pytest.mark.asyncio
    async def test_external_nested_containers_truncated(
        self, resolve_analyzer: JediAnalyzer
    ) -> None:
        """Children of the external root that are themselves containers are capped:
        ``truncated: "external"``, no ``children`` key."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_PATHLIB_PATH_HANDLE, resolve_analyzer)
        _assert_contract1(tree)
        # Any child of pathlib.Path that is a class/module (container) must be
        # truncated with reason "external".
        children = tree.get("children", [])
        assert children, "pathlib.Path must have at least one child"
        container_children = [c for c in children if c["node"]["kind"] in ("class", "module")]
        for container in container_children:
            assert "truncated" in container, (
                f"external nested container {container['node']['handle']!r} " f"must be truncated"
            )
            assert container["truncation_reason"] == "external"
            assert "children" not in container


class TestOutlineEmptyContainerPeek:
    """At the ``max_depth`` frontier, the peek distinguishes a genuine-empty
    container (→ ``children: []``) from a non-empty cut-off one (→ truncated).

    This test exercises outline.py line 192 — the branch that fires when
    ``resolve_members`` returns [] for a container at the depth frontier.

    The Empty class in the nested_class_inspect fixture has no members;
    top_level_function is a non-container; Outer has members.  At max_depth=1:
    - top_level_function: non-container → short-circuits before peek → children: []
    - Outer: container, peek finds members → truncated: "max_depth"
    - Empty: container, peek finds NO members → children: []  ← line 192
    """

    @pytest.mark.asyncio
    async def test_empty_class_at_frontier_receives_children_not_truncated(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """Empty at the max_depth frontier must carry ``children: []`` (genuine
        empty container), NOT ``truncated: "max_depth"``.

        An implementation that skips the peek and always emits ``truncated`` for
        container nodes at the frontier would fail this test.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        # max_depth=1 puts all module children (including Empty) at the frontier.
        tree = await outline(_MOD_HANDLE, nested_analyzer, max_depth=1)
        _assert_contract1(tree)
        empty_node = _find_child(tree, _EMPTY_HANDLE)
        assert empty_node is not None, (
            f"Empty class not found as direct child of {_MOD_HANDLE}; "
            f"available: {[c['node']['handle'] for c in tree.get('children', [])]}"
        )
        # Empty is a class (container) with zero members — peek finds []:
        # it must receive children: [], NOT be truncated.
        assert "children" in empty_node, (
            "Empty at max_depth frontier: peek finds no members → "
            "must carry children: [] (genuine empty container), NOT be truncated"
        )
        assert (
            empty_node["children"] == []
        ), "Empty has no members — children must be the empty list"
        assert (
            "truncated" not in empty_node
        ), "Empty is a genuine empty container — must NOT carry truncated"

    @pytest.mark.asyncio
    async def test_empty_container_peek_both_sides_at_once(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """Simultaneous check: at max_depth=1, Outer (non-empty container at
        frontier) is truncated AND Empty (empty container at frontier) carries
        children: [].

        This pins both sides of the spec §5.3 peek distinction in one test so
        neither side can pass vacuously.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer, max_depth=1)
        _assert_contract1(tree)
        outer_node = _find_child(tree, _OUTER_HANDLE)
        empty_node = _find_child(tree, _EMPTY_HANDLE)
        assert outer_node is not None, "Outer must be a child of the module"
        assert empty_node is not None, "Empty must be a child of the module"

        # Non-empty container at frontier: truncated.
        assert "truncated" in outer_node
        assert outer_node["truncation_reason"] == "max_depth"
        assert "children" not in outer_node

        # Empty container at frontier: genuine empty (children: []).
        assert "children" in empty_node
        assert empty_node["children"] == []
        assert "truncated" not in empty_node


class TestOutlineExternalNestedContainerTruncation:
    """External nested containers (depth ≥ 1) are truncated: "external" with
    no ``children`` key (outline.py lines 182-184).

    This test exercises the branch that fires when an external container is
    encountered at depth ≥ 1 during the BFS walk.

    ``xml.etree.ElementTree`` is an external module whose direct members
    include several class children (ParseError, Element, QName, ElementTree,
    …).  When we outline the module, those class children are at depth 1 with
    scope="external" → they must each be truncated: "external", no children.

    The root module itself (depth 0) must NOT be truncated — the external cap
    only applies at depth ≥ 1 (spec §5.4 asymmetry).
    """

    @pytest.mark.asyncio
    async def test_external_module_root_walked_container_children_truncated(
        self, resolve_analyzer: JediAnalyzer
    ) -> None:
        """The external module root (depth 0) is walked; its class children
        (depth 1, scope=external) are each truncated: "external", no children.

        This directly exercises lines 182-184 of outline.py.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_XML_ET_HANDLE, resolve_analyzer)
        _assert_contract1(tree)

        # Root: external module, depth 0 — must be walked (one level).
        assert tree["node"]["scope"] == "external"
        assert "children" in tree, "external module root must have its children walked"
        assert "truncated" not in tree, "root at depth 0 must NOT be truncated by external cap"

        # Collect children whose kind is a container.
        children = tree["children"]
        assert children, "xml.etree.ElementTree must have at least one child"
        container_children = [c for c in children if c["node"]["kind"] in ("class", "module")]

        # xml.etree.ElementTree has at least 4 class children (ParseError, Element,
        # QName, ElementTree) — we assert there are some so the loop below runs.
        assert container_children, (
            "xml.etree.ElementTree must have at least one class/module child "
            "so that the external-cap branch (outline.py 182-184) is exercised"
        )

        # Each external container child at depth 1 must be truncated: "external",
        # with no children key (absence contract).
        for container in container_children:
            node = container["node"]
            assert "truncated" in container, (
                f"external nested container {node['handle']!r} at depth 1 "
                f"must be truncated (scope={node['scope']!r})"
            )
            assert container["truncated"] is True
            assert container["truncation_reason"] == "external", (
                f"{node['handle']!r}: expected truncation_reason='external', "
                f"got {container['truncation_reason']!r}"
            )
            assert "children" not in container, (
                f"truncated external container {node['handle']!r} "
                f"must NOT carry children (absence contract)"
            )

    @pytest.mark.asyncio
    async def test_external_root_vs_nested_asymmetry(self, resolve_analyzer: JediAnalyzer) -> None:
        """Assert the root-vs-nested asymmetry explicitly: root is walked,
        nested containers are not.  This pins spec §5.4 in a single focused test.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_XML_ET_HANDLE, resolve_analyzer)
        _assert_contract1(tree)

        # Root: walked (children present, no truncated key).
        assert "children" in tree
        assert "truncated" not in tree

        # At least one container child exists and is truncated: "external".
        container_children = [
            c for c in tree["children"] if c["node"]["kind"] in ("class", "module")
        ]
        assert container_children, "need at least one container child for asymmetry test"
        first = container_children[0]
        assert first.get("truncated") is True
        assert first.get("truncation_reason") == "external"
        assert "children" not in first


class TestOutlineSourceOrder:
    """Sibling ``children`` are ordered by ``(line_start, handle)`` — source order.

    Verified with a class whose members are alphabetically-out-of-source-order,
    confirming that the implementation sorts by line number not by name.
    """

    @pytest.mark.asyncio
    async def test_children_ordered_by_line_start(self, resolve_analyzer: JediAnalyzer) -> None:
        """Widget's methods appear in source order, not alphabetical order.

        Widget members (widgets.py line numbers):
          color      line 29  (attribute)
          name       line 32  (attribute)
          visible    line 33  (attribute)
          __init__   line 34  (method)
          greet      line 37  (method)
          slow_greet line 41  (method)
          display_name line 45 (property)
          default    line 50  (method)
          normalize  line 55  (method)

        Source order (ascending line_start) is NOT alphabetical order.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_WIDGET_HANDLE, resolve_analyzer)
        _assert_contract1(tree)
        assert "children" in tree, "Widget must have walked children"
        children = tree["children"]
        assert children, "Widget must have at least one child"

        line_starts = [c["node"]["line_start"] for c in children]
        # Source order: each successive line_start >= previous.
        for i in range(1, len(line_starts)):
            assert line_starts[i] >= line_starts[i - 1], (
                f"children not in source order at index {i}: "
                f"{line_starts[i-1]} > {line_starts[i]} "
                f"(handles: {children[i-1]['node']['handle']!r}, "
                f"{children[i]['node']['handle']!r})"
            )

        # The handles must NOT be in alphabetical order (confirming we're using
        # source order, not alpha order).
        handles = [c["node"]["handle"] for c in children]
        assert handles != sorted(handles), (
            "children unexpectedly in alphabetical order — source order and "
            "alphabetical order are the same, which means this fixture is unsuitable "
            "for this test. Choose a fixture whose source order != alpha order."
        )

    @pytest.mark.asyncio
    async def test_children_ordered_by_handle_when_same_line(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """When two children share the same line_start, the handle tiebreaker
        ensures a stable, deterministic sort.  This test pins the sort key but
        ONLY fires when a fixture actually has equal line numbers; otherwise it
        simply verifies source order is monotone (non-decreasing)."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        _assert_contract1(tree)
        children = tree.get("children", [])
        for i in range(1, len(children)):
            a = children[i - 1]["node"]
            b = children[i]["node"]
            assert (a["line_start"], a["handle"]) <= (
                b["line_start"],
                b["handle"],
            ), f"children not in (line_start, handle) order: {a['handle']!r} > {b['handle']!r}"


class TestOutlineTruncatedAbsenceContracts:
    """Explicit two-sided tests for the §4.2 absence contracts.

    These are the tests that fail loudly if an implementation skips the
    frontier peek or emits ``truncated: false`` on fully-walked nodes.
    """

    @pytest.mark.asyncio
    async def test_fully_walked_nodes_never_carry_truncated_false(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """No node in an unbounded outline may carry ``truncated: false``."""
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        def _find_truncated_false(t: dict[str, Any]) -> list[dict[str, Any]]:
            """Return all nodes where truncated is False."""
            bad = []
            if t.get("truncated") is False:
                bad.append(t)
            for c in t.get("children", []):
                bad.extend(_find_truncated_false(c))
            return bad

        tree = await outline(_MOD_HANDLE, nested_analyzer)
        bad = _find_truncated_false(tree)
        assert bad == [], f"found nodes with truncated=False: {bad}"

    @pytest.mark.asyncio
    async def test_genuine_leaf_carries_empty_children_not_truncated(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """A method (genuine leaf) carries ``children: []`` — NOT
        ``truncated: "max_depth"`` — even when at the depth frontier.

        This is the load-bearing §4.2 distinction test: an implementation
        that skips the peek would emit ``truncated: "max_depth"`` here instead.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        # max_depth=1 puts outer_method AT the frontier.
        tree = await outline(_OUTER_HANDLE, nested_analyzer, max_depth=1)
        _assert_contract1(tree)
        method_node = _find_child(tree, _OUTER_METHOD_HANDLE)
        assert method_node is not None, "outer_method must be a child of Outer"
        # The peek must determine it has no members → genuine leaf.
        assert "children" in method_node, (
            "outer_method at the depth frontier: peek finds no members → "
            "must carry children: [] (genuine leaf), NOT be truncated"
        )
        assert method_node["children"] == []
        assert (
            "truncated" not in method_node
        ), "a genuine leaf at the frontier must NOT be truncated"

    @pytest.mark.asyncio
    async def test_non_empty_container_at_frontier_is_truncated_not_empty(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        """A non-empty container at the depth frontier carries
        ``truncated: "max_depth"`` — NOT ``children: []``.

        Complement to the test above: together they pin BOTH sides of the
        peek distinction so an implementation that always emits ``[]`` or
        always emits ``truncated`` fails loudly.
        """
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        # max_depth=1 puts Outer at depth 1 (the frontier). Outer has members.
        tree = await outline(_MOD_HANDLE, nested_analyzer, max_depth=1)
        _assert_contract1(tree)
        outer_node = _find_child(tree, _OUTER_HANDLE)
        assert outer_node is not None
        assert (
            "truncated" in outer_node
        ), "Outer at max_depth=1 frontier with non-empty members must be truncated"
        assert outer_node["truncation_reason"] == "max_depth"
        assert "children" not in outer_node, "truncated node must NOT have children key"


class TestOutlineUnresolvableHandle:
    """An unresolvable handle yields a minimal single-node tree with
    ``children: []`` (mirrors ``inspect``'s minimal-node fallback)."""

    @pytest.mark.asyncio
    async def test_unresolvable_handle_returns_minimal_tree(
        self, nested_analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.outline import outline  # type: ignore[import]

        bad_handle = "definitely.not.a.real.symbol.in.any.fixture"
        tree = await outline(bad_handle, nested_analyzer)
        # Must not raise; must return a dict with a node.
        assert isinstance(tree, dict), "outline must return a dict even for bad handles"
        assert "node" in tree, "minimal fallback must have a node"
        # Must carry children: [] (minimal measured empty) — NOT be truncated.
        assert "children" in tree, "fallback tree must carry children: []"
        assert tree["children"] == [], "fallback tree children must be empty"
        assert "truncated" not in tree, "fallback tree must not be truncated"
