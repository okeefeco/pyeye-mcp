"""Integration tests for the inspect MCP tool endpoint.

These tests exercise the MCP wrapper layer (server.py) end-to-end —
from the decorated function down through the operation into the fixture
project.  They verify:

1. The tool is registered (importable, callable, async).
2. Delegation to the underlying operation works correctly.
3. Universal fields are always present (handle, kind, scope, location, edge_counts).
4. Kind-dependent fields are present for class/function/module/variable.
5. Absence-vs-zero invariants hold: re_exports present (possibly []) for non-module
   kinds; highlights/tags absent; edge_counts populated per Phase 4 contract.
6. External-scope handles (e.g. pathlib.Path) are handled gracefully.
7. The result is a plain dict (serialisation-safe).

Unit-level contract tests live in tests/unit/mcp/operations/test_inspect.py.
These integration tests verify only the MCP wrapper layer delegation.
"""

from __future__ import annotations

import inspect as _inspect_stdlib
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"

# ---------------------------------------------------------------------------
# Tool-registration assertions
# ---------------------------------------------------------------------------


class TestInspectToolRegistered:
    """Verify that inspect is importable from pyeye.mcp.server and is callable."""

    def test_inspect_is_importable(self) -> None:
        """inspect can be imported from pyeye.mcp.server."""
        from pyeye.mcp.server import inspect  # noqa: F401

    def test_inspect_is_callable(self) -> None:
        """inspect is a callable (decorated async function)."""
        from pyeye.mcp.server import inspect

        assert callable(inspect)

    def test_inspect_is_async(self) -> None:
        """inspect is an async function (or wrapped to behave as one)."""
        from pyeye.mcp.server import inspect

        assert _inspect_stdlib.iscoroutinefunction(inspect)


# ---------------------------------------------------------------------------
# Universal-fields contract (all kinds must include these)
# ---------------------------------------------------------------------------


class TestInspectUniversalFields:
    """Verify that universal fields are always present regardless of kind."""

    @pytest.mark.asyncio
    async def test_class_has_universal_fields(self) -> None:
        """inspect on a class returns all universal fields."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert "handle" in result
        assert "kind" in result
        assert "scope" in result
        assert "location" in result
        assert "docstring" in result
        assert "edge_counts" in result

    @pytest.mark.asyncio
    async def test_edge_counts_always_present_as_dict(self) -> None:
        """edge_counts is always present and is a dict (Phase 4: populated with measured edges)."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert isinstance(
            result["edge_counts"], dict
        ), f"edge_counts must be a dict; got {type(result['edge_counts'])!r}"
        # Phase 4: edge_counts is populated with measured edges for class handles.
        # All 5 measured edge types must be present for Widget (a class).
        for edge in ("members", "superclasses", "subclasses", "callers", "references"):
            assert edge in result["edge_counts"], (
                f"Phase 4 must populate edge_counts[{edge!r}] for class Widget; "
                f"got edge_counts={result['edge_counts']!r}"
            )

    @pytest.mark.asyncio
    async def test_absence_invariants_phase6(self) -> None:
        """Phase 6: re_exports PRESENT (possibly []) for non-module kinds; highlights/tags ABSENT.

        Widget is a class handle. Per Phase 6 spec:
          - re_exports: PRESENT, list[str] (Widget is re-exported via mypackage/__init__.py)
          - highlights: ABSENT (Phase 5, not yet wired)
          - tags: ABSENT (plugin kinds only)
          - properties: ABSENT (plugin kinds only)
        """
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        # Phase 6: re_exports is now PRESENT for class handles (possibly [])
        assert "re_exports" in result, (
            "re_exports must be PRESENT (Phase 6) for class handles; got absent. "
            "[] means measured-and-empty; absent means not measured for this kind."
        )
        assert isinstance(
            result["re_exports"], list
        ), f"re_exports must be a list; got {type(result['re_exports'])!r}"
        # Widget is re-exported via mypackage/__init__.py → expect ["mypackage.Widget"]
        assert "mypackage.Widget" in result["re_exports"], (
            f"Widget is re-exported via mypackage/__init__.py; "
            f"expected 'mypackage.Widget' in re_exports; got {result['re_exports']!r}"
        )

        # These remain absent in Phase 6
        assert "highlights" not in result, "highlights must be absent (Phase 5 wires it)"
        assert "tags" not in result, "tags must be absent for Python kinds"
        assert "properties" not in result, "properties must be absent for Python kinds"

    @pytest.mark.asyncio
    async def test_re_exports_end_to_end_widget(self) -> None:
        """End-to-end: re_exports for a re-exported class flows through MCP wrapper.

        Widget is defined in mypackage._core.widgets and re-exported in mypackage/__init__.py.
        inspect("mypackage._core.widgets.Widget") must return re_exports=["mypackage.Widget"].
        """
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert "re_exports" in result
        assert isinstance(result["re_exports"], list)
        assert (
            "mypackage.Widget" in result["re_exports"]
        ), f"Widget is re-exported as mypackage.Widget; got re_exports={result['re_exports']!r}"
        # Wire-format check: all elements must be plain str (JSON-serialisable)
        import json

        json.dumps(result["re_exports"])  # must not raise


# ---------------------------------------------------------------------------
# End-to-end: class inspection
# ---------------------------------------------------------------------------


class TestInspectClassEndToEnd:
    """End-to-end tests for class-kind symbols."""

    @pytest.mark.asyncio
    async def test_widget_class_inspection(self) -> None:
        """inspect on Widget returns kind=class, scope=project, with class fields."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["handle"] == "mypackage._core.widgets.Widget"
        assert result["kind"] == "class"
        assert result["scope"] == "project"
        assert "superclasses" in result
        assert isinstance(result["superclasses"], list)

    @pytest.mark.asyncio
    async def test_widget_class_location_is_pointer(self) -> None:
        """The location field is a pointer dict (no source content)."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        loc = result["location"]
        assert isinstance(loc, dict)
        assert "file" in loc
        assert "line_start" in loc
        assert "line_end" in loc
        # No source content ever
        assert "source" not in loc
        assert "text" not in loc
        assert "snippet" not in loc

    @pytest.mark.asyncio
    async def test_result_is_plain_dict(self) -> None:
        """The MCP wrapper must return a plain dict (serialisation-safe)."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict)
        # Spot-check all values are JSON-serialisable types
        import json

        json.dumps(result)  # must not raise


# ---------------------------------------------------------------------------
# End-to-end: function and method inspection
# ---------------------------------------------------------------------------


class TestInspectFunctionEndToEnd:
    """End-to-end tests for function and method symbols."""

    @pytest.mark.asyncio
    async def test_module_level_function(self) -> None:
        """inspect on make_widget returns kind=function with function fields."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.make_widget",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["handle"] == "mypackage._core.widgets.make_widget"
        assert result["kind"] == "function"
        assert result["scope"] == "project"
        assert "signature" in result
        assert "parameters" in result
        assert isinstance(result["parameters"], list)
        assert "is_async" in result
        assert "is_classmethod" in result
        assert "is_staticmethod" in result

    @pytest.mark.asyncio
    async def test_method_inside_class(self) -> None:
        """inspect on Widget.greet returns kind=method."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget.greet",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["kind"] == "method"
        assert result["scope"] == "project"
        assert "is_async" in result
        assert result["is_async"] is False


# ---------------------------------------------------------------------------
# End-to-end: module inspection
# ---------------------------------------------------------------------------


class TestInspectModuleEndToEnd:
    """End-to-end tests for module-kind symbols."""

    @pytest.mark.asyncio
    async def test_module_inspection(self) -> None:
        """inspect on a module handle returns kind=module with module fields."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["kind"] == "module"
        assert result["scope"] == "project"
        assert "is_package" in result
        assert isinstance(result["is_package"], bool)


# ---------------------------------------------------------------------------
# End-to-end: variable / attribute inspection
# ---------------------------------------------------------------------------


class TestInspectVariableEndToEnd:
    """End-to-end tests for variable and attribute symbols."""

    @pytest.mark.asyncio
    async def test_module_level_variable(self) -> None:
        """inspect on DEFAULT_NAME returns a variable-kind node."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.DEFAULT_NAME",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert result["handle"] == "mypackage._core.widgets.DEFAULT_NAME"
        assert result["scope"] == "project"
        # variable or statement — either is valid; what matters is universal fields
        assert "kind" in result
        assert "location" in result
        assert "edge_counts" in result


# ---------------------------------------------------------------------------
# End-to-end: external-scope handle
# ---------------------------------------------------------------------------


class TestInspectExternalScopeEndToEnd:
    """End-to-end test for symbols outside the project (e.g. stdlib)."""

    @pytest.mark.asyncio
    async def test_external_symbol_pathlib_path(self) -> None:
        """inspect on pathlib.Path returns a valid node with scope=external."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="pathlib.Path",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), "result must be a plain dict"
        assert "handle" in result
        assert "kind" in result
        assert "edge_counts" in result
        # Must be external scope (stdlib, not our project)
        assert result["scope"] == "external"


# ---------------------------------------------------------------------------
# Span location end-to-end
# ---------------------------------------------------------------------------


class TestInspectSpanLocationEndToEnd:
    """Verify that Location spans flow correctly through the full wrapper stack."""

    @pytest.mark.asyncio
    async def test_class_location_spans_name_and_body_end_to_end(self) -> None:
        """inspect() for a class returns a Location with name span + body span.

        Widget at line 21 in widgets.py:
        - 'Widget' is 6 characters → column_end - column_start == 6
        - Widget has a multi-line body → line_end > line_start
        """
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict)
        loc = result["location"]

        assert "column_start" in loc, f"column_start missing from location: {loc}"
        assert "column_end" in loc, f"column_end missing from location: {loc}"
        # Name span: "Widget" is 6 characters
        assert loc["column_end"] - loc["column_start"] == 6, (
            f"'Widget' is 6 chars; expected column span of 6 end-to-end, "
            f"got {loc['column_end'] - loc['column_start']} (loc={loc})"
        )
        # Body span: Widget body is multi-line
        assert loc["line_end"] > loc["line_start"], (
            f"Widget body is multi-line; expected line_end > line_start end-to-end; "
            f"got line_start={loc['line_start']}, line_end={loc['line_end']}"
        )
