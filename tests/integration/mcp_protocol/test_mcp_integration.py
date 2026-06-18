"""Integration tests for MCP tool layer to ensure async functions work correctly."""

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from pyeye.mcp.server import resolve, resolve_at
from pyeye.metrics import metrics
from pyeye.validation import validate_mcp_inputs


class TestAsyncDecorators:
    """Test that decorators properly handle async functions."""

    @pytest.mark.asyncio
    async def test_validate_mcp_inputs_preserves_async(self):
        """Test that validate_mcp_inputs decorator preserves async nature."""

        @validate_mcp_inputs
        async def test_async_func(name: str) -> str:
            await asyncio.sleep(0.001)
            return f"Hello {name}"

        # Function should still be async after decoration
        assert asyncio.iscoroutinefunction(test_async_func)

        # Should be able to await the result
        result = await test_async_func("World")
        assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_metrics_measure_preserves_async(self):
        """Test that metrics.measure decorator preserves async nature."""

        @metrics.measure("test_metric")
        async def test_async_func() -> str:
            await asyncio.sleep(0.001)
            return "Success"

        # Function should still be async after decoration
        assert asyncio.iscoroutinefunction(test_async_func)

        # Should be able to await the result
        result = await test_async_func()
        assert result == "Success"

        # Verify metric was recorded
        stats = metrics.get_stats("test_metric")
        assert stats["count"] > 0

    @pytest.mark.asyncio
    async def test_decorator_chain_preserves_async(self):
        """Test that a chain of decorators preserves async nature."""

        @validate_mcp_inputs
        @metrics.measure("chained_test")
        async def test_chained(name: str) -> str:
            await asyncio.sleep(0.001)
            return f"Chained {name}"

        # Function should still be async after multiple decorations
        assert asyncio.iscoroutinefunction(test_chained)

        # Should be able to await the result
        result = await test_chained("Test")
        assert result == "Chained Test"

    def test_sync_function_still_works(self):
        """Test that sync functions still work with the decorators."""

        @validate_mcp_inputs
        @metrics.measure("sync_test")
        def test_sync(name: str) -> str:
            return f"Sync {name}"

        # Function should NOT be async
        assert not asyncio.iscoroutinefunction(test_sync)

        # Should work without await
        result = test_sync("Works")
        assert result == "Sync Works"


class TestMCPToolIntegration:
    """Test that MCP tools return actual results, not coroutines."""

    @pytest.mark.asyncio
    @patch("pyeye.mcp.server._resolve_impl")
    @patch("pyeye.mcp.server.get_analyzer")
    async def test_resolve_returns_result_not_coroutine(self, mock_get_analyzer, mock_resolve_impl):
        """Test that resolve returns the actual result, not a coroutine."""
        # Setup mocks: get_analyzer is delegated to, the impl returns the result
        mock_get_analyzer.return_value = AsyncMock()
        mock_resolve_impl.return_value = {
            "found": True,
            "handle": "pkg.TestClass",
            "kind": "class",
            "scope": "project",
        }

        # The decorated function should still be async
        assert asyncio.iscoroutinefunction(resolve)

        # Call the function
        result = await resolve("TestClass", project_path=".")

        # Should get the actual result, not a coroutine object
        assert isinstance(result, dict)
        assert result["found"] is True
        assert result["handle"] == "pkg.TestClass"

    @pytest.mark.asyncio
    @patch("pyeye.mcp.server._resolve_at_impl")
    @patch("pyeye.mcp.server.get_analyzer")
    async def test_resolve_at_returns_result_not_coroutine(
        self, mock_get_analyzer, mock_resolve_at_impl
    ):
        """Test that resolve_at returns the actual result, not a coroutine."""
        # Setup mocks: get_analyzer is delegated to, the impl returns the result
        mock_get_analyzer.return_value = AsyncMock()
        mock_resolve_at_impl.return_value = {
            "found": True,
            "handle": "pkg.target.func",
            "kind": "function",
            "scope": "project",
        }

        # The decorated function should still be async
        assert asyncio.iscoroutinefunction(resolve_at)

        # Call the function
        result = await resolve_at("test.py", 10, 5, project_path=".")

        # Should get the actual result, not a coroutine object
        assert isinstance(result, dict)
        assert result["found"] is True
        assert result["handle"] == "pkg.target.func"

    @pytest.mark.asyncio
    async def test_simulated_mcp_tool_invocation(self):
        """Simulate how FastMCP would invoke a tool to ensure it works correctly."""

        @validate_mcp_inputs
        @metrics.measure("simulated_tool")
        async def simulated_tool(name: str) -> dict:
            """A simulated MCP tool."""
            await asyncio.sleep(0.001)
            return {"result": f"Processed {name}"}

        # This simulates what FastMCP does when invoking a tool
        # It checks if the function is a coroutine and awaits it if necessary

        # Get the tool function (after all decorators)
        tool_func = simulated_tool

        # Check if it's async (FastMCP does this)
        if asyncio.iscoroutinefunction(tool_func):
            # If async, create a coroutine and await it
            coroutine = tool_func("test_input")
            assert inspect.iscoroutine(coroutine)

            # FastMCP would await this
            result = await coroutine
            assert isinstance(result, dict)
            assert result["result"] == "Processed test_input"
        else:
            # If sync, just call it
            result = tool_func("test_input")
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_error_handling_in_async_decorator(self):
        """Test that errors are properly handled in async decorated functions."""

        @validate_mcp_inputs
        @metrics.measure("error_test")
        async def failing_tool(name: str) -> str:
            await asyncio.sleep(0.001)
            raise ValueError(f"Test error for {name}")

        # Function should still be async
        assert asyncio.iscoroutinefunction(failing_tool)

        # Should properly propagate the error
        with pytest.raises(ValueError, match="Test error for bad_input"):
            await failing_tool("bad_input")

        # Metric should record the error
        stats = metrics.get_stats("error_test")
        assert stats["errors"] > 0
