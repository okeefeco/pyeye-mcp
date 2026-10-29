"""Uniform not-found contract for ``inspect`` / ``outline`` / ``expand`` (#545).

An unresolvable handle used to produce a FABRICATED answer: ``inspect`` and
``outline`` returned a ``kind: "variable"`` placeholder node, and ``expand``
returned ``stubs: []`` — which its own contract defines as "measured, none
found".  All three now return one explicit shape, built by a single helper::

    {"found": False, "handle": <input>, "reason": "unresolved", "detail": str}

(``expand`` additionally echoes ``edge``).  Every *successful* response carries
``found: True``, so a consumer branches on a field value, never on key presence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.not_found import NOT_FOUND_REASON, not_found
from pyeye.mcp.operations.outline import outline
from tests.conformance.response_linter import lint_response

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

_WIDGET_HANDLE = "mypackage._core.widgets.Widget"
_MAKE_WIDGET_HANDLE = "mypackage._core.widgets.make_widget"

_GHOST_HANDLE = "mypackage._core.widgets.does_not_exist_xyz"
# The #545 dogfooding repro shape: a real leaf name under a mistyped module path.
_MISTYPED_PATH_HANDLE = "mypackage._core.no_such_module.Widget"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# The helper — single source of truth for the shape
# ---------------------------------------------------------------------------


class TestNotFoundHelper:
    """``not_found`` builds the one shape all three operations return."""

    def test_shape_without_edge(self) -> None:
        result = not_found("pkg.mod.Thing")
        assert set(result) == {"found", "handle", "reason", "detail"}
        assert result["found"] is False
        assert result["handle"] == "pkg.mod.Thing"
        assert result["reason"] == NOT_FOUND_REASON == "unresolved"

    def test_shape_with_edge(self) -> None:
        result = not_found("pkg.mod.Thing", edge="members")
        assert set(result) == {"found", "handle", "edge", "reason", "detail"}
        assert result["edge"] == "members"

    def test_detail_points_at_resolve_with_last_segment(self) -> None:
        """The detail is an actionable next step, not a fuzzy "did you mean"."""
        detail = not_found("pkg.mod.Thing")["detail"]
        assert "resolve('Thing')" in detail
        assert "\n" not in detail

    def test_detail_for_single_segment_handle(self) -> None:
        assert "resolve('Thing')" in not_found("Thing")["detail"]


# ---------------------------------------------------------------------------
# Not-found: each operation returns exactly the helper's shape
# ---------------------------------------------------------------------------


class TestInspectNotFound:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", [_GHOST_HANDLE, _MISTYPED_PATH_HANDLE])
    async def test_unresolvable_handle_is_explicit_not_found(
        self, handle: str, analyzer: JediAnalyzer
    ) -> None:
        result = await inspect(handle, analyzer)
        assert result == not_found(handle)
        # Regression guard: none of the old fabricated node fields survive.
        assert "kind" not in result
        assert "location" not in result
        assert "edge_counts" not in result
        lint_response(result, "inspect")


class TestOutlineNotFound:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", [_GHOST_HANDLE, _MISTYPED_PATH_HANDLE])
    async def test_unresolvable_handle_is_explicit_not_found(
        self, handle: str, analyzer: JediAnalyzer
    ) -> None:
        result = await outline(handle, analyzer)
        assert result == not_found(handle)
        assert "node" not in result
        assert "children" not in result
        lint_response(result, "outline")


class TestExpandNotFound:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("edge", ["members", "callees", "imports", "subclasses"])
    async def test_unresolvable_source_is_explicit_not_found(
        self, edge: str, analyzer: JediAnalyzer
    ) -> None:
        result = await expand(_GHOST_HANDLE, edge, analyzer)
        assert result == not_found(_GHOST_HANDLE, edge=edge)
        lint_response(result, "expand")

    @pytest.mark.asyncio
    async def test_callees_not_found_claims_no_measurement(self, analyzer: JediAnalyzer) -> None:
        """The old path synthesized ``unresolved_call_sites: 0`` — a claim that
        every call site of a non-existent function resolved."""
        result = await expand(_GHOST_HANDLE, "callees", analyzer)
        assert "stubs" not in result
        assert "unresolved_call_sites" not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize("edge", ["callers", "bogus_edge"])
    async def test_not_found_precedes_unsupported_edge(
        self, edge: str, analyzer: JediAnalyzer
    ) -> None:
        """The handle is resolved before the edge registry is consulted, so an
        unsupported edge on a ghost handle reports the ghost — never a
        ``found: True`` unsupported result for a handle nobody resolved."""
        result = await expand(_GHOST_HANDLE, edge, analyzer)
        assert result == not_found(_GHOST_HANDLE, edge=edge)
        assert "unsupported" not in result


class TestNotFoundAtTheWire:
    """The MCP tool wrappers (full decorator stack) pass the shape through."""

    @pytest.mark.asyncio
    async def test_inspect_tool(self) -> None:
        from pyeye.mcp.server import inspect as inspect_tool

        result = await inspect_tool(handle=_GHOST_HANDLE, project_path=str(_FIXTURE))
        assert result == not_found(_GHOST_HANDLE)

    @pytest.mark.asyncio
    async def test_expand_tool(self) -> None:
        from pyeye.mcp.server import expand as expand_tool

        result = await expand_tool(handle=_GHOST_HANDLE, edge="callees", project_path=str(_FIXTURE))
        assert result == not_found(_GHOST_HANDLE, edge="callees")


class TestNotFoundIsUniformAcrossTools:
    @pytest.mark.asyncio
    async def test_shapes_differ_only_by_expand_edge(self, analyzer: JediAnalyzer) -> None:
        inspected = await inspect(_GHOST_HANDLE, analyzer)
        outlined = await outline(_GHOST_HANDLE, analyzer)
        expanded = await expand(_GHOST_HANDLE, "members", analyzer)

        assert inspected == outlined
        assert {k: v for k, v in expanded.items() if k != "edge"} == inspected


# ---------------------------------------------------------------------------
# Success: found is always present and True
# ---------------------------------------------------------------------------


class TestFoundTrueOnSuccess:
    @pytest.mark.asyncio
    async def test_inspect(self, analyzer: JediAnalyzer) -> None:
        result = await inspect(_WIDGET_HANDLE, analyzer)
        assert result["found"] is True
        assert result["kind"] == "class"
        lint_response(result, "inspect")

    @pytest.mark.asyncio
    async def test_outline_root_only(self, analyzer: JediAnalyzer) -> None:
        """``found`` is a response-level field: on the root tree, not on nested
        ``children`` trees."""
        result = await outline(_WIDGET_HANDLE, analyzer)
        assert result["found"] is True
        assert result["children"], "Widget has members — fixture precondition"
        for child in result["children"]:
            assert "found" not in child
        lint_response(result, "outline")

    @pytest.mark.asyncio
    async def test_expand_supported_branch(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "members", analyzer)
        assert result["found"] is True
        assert "stubs" in result
        lint_response(result, "expand")

    @pytest.mark.asyncio
    async def test_expand_registry_unsupported_branch(self, analyzer: JediAnalyzer) -> None:
        """The source WAS resolved first, so ``found: True`` is truthful here."""
        result = await expand(_WIDGET_HANDLE, "callers", analyzer)
        assert result["found"] is True
        assert result["unsupported"] is True
        assert result["source"] == _WIDGET_HANDLE
        lint_response(result, "expand")

    @pytest.mark.asyncio
    async def test_expand_wrong_kind_unsupported_branch(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_MAKE_WIDGET_HANDLE, "imported_by", analyzer)
        assert result["found"] is True
        assert result["unsupported"] is True
        lint_response(result, "expand")
