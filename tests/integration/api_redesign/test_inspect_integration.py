"""Integration tests for the inspect MCP tool endpoint.

These tests exercise the MCP wrapper layer (server.py) end-to-end —
from the decorated function down through the operation into the fixture
project.  They verify:

1. The tool is registered (importable, callable, async).
2. Delegation to the underlying operation works correctly.
3. Universal fields are always present (handle, kind, scope, location, edge_counts).
4. Kind-dependent fields are present for class/function/module/variable.
5. Absence-vs-zero invariants hold (re_exports/highlights/tags absent, edge_counts={}).
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
    async def test_edge_counts_always_empty_dict(self) -> None:
        """edge_counts is always present and always {} in Phase 3."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert (
            result["edge_counts"] == {}
        ), f"edge_counts must be {{}} in Phase 3; got {result['edge_counts']!r}"

    @pytest.mark.asyncio
    async def test_absence_invariants_no_re_exports(self) -> None:
        """re_exports, highlights, tags are absent (Phase 3 contract)."""
        from pyeye.mcp.server import inspect

        result = await inspect(
            handle="mypackage._core.widgets.Widget",
            project_path=str(_FIXTURE),
        )

        assert "re_exports" not in result, "re_exports must be absent in Phase 3"
        assert "highlights" not in result, "highlights must be absent in Phase 3"
        assert "tags" not in result, "tags must be absent in Phase 3"
        assert "properties" not in result, "properties must be absent in Phase 3"


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
