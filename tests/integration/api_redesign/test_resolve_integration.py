"""Integration tests for resolve and resolve_at MCP tool endpoints.

These tests exercise the MCP wrapper layer (server.py) end-to-end —
from the decorated function down through the operation into the fixture
project.  They verify:

1. Both tools are registered (importable, callable).
2. Delegation to the underlying operation works correctly.
3. The dict result shape matches the ResolveResult spec.
4. column=0 is honoured end-to-end through the wrapper (no truthiness bug).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"

# ---------------------------------------------------------------------------
# Tool-registration assertions
# ---------------------------------------------------------------------------


class TestResolveToolRegistered:
    """Verify that resolve is importable from pyeye.mcp.server and is callable."""

    def test_resolve_is_importable(self) -> None:
        """resolve can be imported from pyeye.mcp.server."""
        from pyeye.mcp.server import resolve  # noqa: F401

    def test_resolve_is_callable(self) -> None:
        """resolve is a callable (decorated async function)."""
        from pyeye.mcp.server import resolve

        assert callable(resolve)

    def test_resolve_is_async(self) -> None:
        """resolve is an async function (or wrapped to behave as one)."""
        from pyeye.mcp.server import resolve

        assert asyncio.iscoroutinefunction(resolve)


class TestResolveAtToolRegistered:
    """Verify that resolve_at is importable from pyeye.mcp.server and is callable."""

    def test_resolve_at_is_importable(self) -> None:
        """resolve_at can be imported from pyeye.mcp.server."""
        from pyeye.mcp.server import resolve_at  # noqa: F401

    def test_resolve_at_is_callable(self) -> None:
        """resolve_at is a callable (decorated async function)."""
        from pyeye.mcp.server import resolve_at

        assert callable(resolve_at)

    def test_resolve_at_is_async(self) -> None:
        """resolve_at is an async function (or wrapped to behave as one)."""
        from pyeye.mcp.server import resolve_at

        assert asyncio.iscoroutinefunction(resolve_at)


# ---------------------------------------------------------------------------
# End-to-end delegation via resolve()
# ---------------------------------------------------------------------------


class TestResolveEndToEnd:
    """End-to-end tests that call the MCP wrapper with real fixture data."""

    @pytest.mark.asyncio
    async def test_resolve_returns_canonical_handle_for_dotted_name(self) -> None:
        """resolve() with a FQN returns the canonical handle, kind, scope."""
        from pyeye.mcp.server import resolve

        project_path = str(_FIXTURE)
        result = await resolve(
            identifier="mypackage._core.widgets.Widget",
            project_path=project_path,
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["found"] is True
        assert result["handle"] == "mypackage._core.widgets.Widget"
        assert result["kind"] == "class"
        assert result["scope"] == "project"

    @pytest.mark.asyncio
    async def test_resolve_reexport_collapses_to_definition_site(self) -> None:
        """resolve() with a re-exported path collapses to the definition-site handle."""
        from pyeye.mcp.server import resolve

        project_path = str(_FIXTURE)
        result = await resolve(
            identifier="mypackage.Widget",
            project_path=project_path,
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["found"] is True
        # Re-exported path must resolve to the definition site, not the re-export
        assert result["handle"] == "mypackage._core.widgets.Widget"

    @pytest.mark.asyncio
    async def test_resolve_returns_not_found_for_invalid_name(self) -> None:
        """resolve() with an unknown name returns found=False with a reason."""
        from pyeye.mcp.server import resolve

        project_path = str(_FIXTURE)
        result = await resolve(
            identifier="completely_unknown_module.NobodyHere",
            project_path=project_path,
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["found"] is False
        assert "reason" in result
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    @pytest.mark.asyncio
    async def test_resolve_result_is_plain_dict_not_typeddict(self) -> None:
        """The MCP wrapper must return a plain dict (serialisation-safe)."""
        from pyeye.mcp.server import resolve

        project_path = str(_FIXTURE)
        result = await resolve(
            identifier="mypackage._core.widgets.Config",
            project_path=project_path,
        )

        # isinstance(TypedDict instance, dict) is True at runtime, but this
        # test primarily verifies the result has the expected keys.
        assert isinstance(result, dict)
        assert "found" in result


# ---------------------------------------------------------------------------
# End-to-end delegation via resolve_at()
# ---------------------------------------------------------------------------


class TestResolveAtEndToEnd:
    """End-to-end tests for the resolve_at MCP wrapper."""

    @pytest.mark.asyncio
    async def test_resolve_at_returns_canonical_handle_at_definition_site(self) -> None:
        """resolve_at at the Widget class definition returns the canonical handle."""
        from pyeye.mcp.server import resolve_at

        widgets_path = str(_FIXTURE / "mypackage" / "_core" / "widgets.py")
        project_path = str(_FIXTURE)

        # Line 21: "class Widget:" — column 6 is the 'W' of Widget
        result = await resolve_at(
            file=widgets_path,
            line=21,
            column=6,
            project_path=project_path,
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["found"] is True, f"Expected found=True, got: {result}"
        assert result["handle"] == "mypackage._core.widgets.Widget"
        assert result["kind"] == "class"
        assert result["scope"] == "project"

    @pytest.mark.asyncio
    async def test_resolve_at_returns_canonical_handle_at_use_site(self) -> None:
        """resolve_at at a Widget use site collapses to the definition-site handle."""
        from pyeye.mcp.server import resolve_at

        use_widget_path = str(_FIXTURE / "mypackage" / "use_widget.py")
        project_path = str(_FIXTURE)

        # Line 11: "w = Widget()" — column 4 is the 'W' of Widget (use site)
        result = await resolve_at(
            file=use_widget_path,
            line=11,
            column=4,
            project_path=project_path,
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["found"] is True, f"Expected found=True at use site, got: {result}"
        assert result["handle"] == "mypackage._core.widgets.Widget"

    @pytest.mark.asyncio
    async def test_resolve_at_column_zero_works_end_to_end(self) -> None:
        """column=0 is honoured through the MCP wrapper — no truthiness substitution.

        See test_resolve.py::TestResolveAt::test_column_zero_is_valid for full
        rationale.  In brief: column=0 lands on the 'class' keyword, which has no
        Jedi symbol, so the correct result is found=False.  A buggy wrapper that
        treats 0 as falsy would substitute a different column and return found=True
        for the Widget class.
        """
        from pyeye.mcp.server import resolve_at

        widgets_path = str(_FIXTURE / "mypackage" / "_core" / "widgets.py")
        project_path = str(_FIXTURE)

        # Line 21: "class Widget:" — column 0 is the 'c' of the 'class' keyword
        result = await resolve_at(
            file=widgets_path,
            line=21,
            column=0,
            project_path=project_path,
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["found"] is False, (
            f"column=0 on the 'class' keyword should be not-found; "
            f"if found=True this likely indicates a truthiness bug in the wrapper: {result}"
        )
        assert result["reason"] == "no_symbol_at_position"

    @pytest.mark.asyncio
    async def test_resolve_at_missing_file_returns_not_found(self) -> None:
        """resolve_at on a non-existent file returns found=False, reason='file_not_found'."""
        from pyeye.mcp.server import resolve_at

        result = await resolve_at(
            file="/nonexistent/path/missing.py",
            line=1,
            column=0,
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["found"] is False
        assert result["reason"] == "file_not_found"
