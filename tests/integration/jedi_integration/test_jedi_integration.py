"""Integration tests with real Jedi to catch Path serialization issues.

These tests address the gap identified in issue #141 where mocked tests
don't catch the actual PosixPath serialization errors that occur with real Jedi.
"""

import json
import tempfile
from pathlib import Path

import pytest

from pycodemcp.analyzers.jedi_analyzer import JediAnalyzer
from pycodemcp.exceptions import AnalysisError, format_error_response


class TestJediIntegration:
    """Integration tests using real Jedi library, not mocks."""

    @pytest.mark.asyncio
    async def test_find_symbol_with_real_jedi_success(self):
        """Test find_symbol with real Jedi returns JSON-serializable results."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a real Python file
            test_file = Path(temp_dir) / "test_module.py"
            test_file.write_text(
                """
class TestClass:
    def test_method(self):
        pass

def test_function():
    return 42

TEST_CONSTANT = "value"
"""
            )

            # Use real JediAnalyzer
            analyzer = JediAnalyzer(temp_dir)

            # Test finding a class
            results = await analyzer.find_symbol("TestClass")
            assert len(results) > 0

            # Verify the file field is a string, not a Path object
            assert isinstance(results[0]["file"], str)
            assert results[0]["file"].endswith("test_module.py")

            # Verify the entire result is JSON serializable
            json_str = json.dumps(results)
            assert "TestClass" in json_str
            assert "test_module.py" in json_str

            # Test finding a function
            results = await analyzer.find_symbol("test_function")
            assert len(results) > 0
            assert isinstance(results[0]["file"], str)

            # Verify JSON serialization
            json.dumps(results)  # Should not raise

    @pytest.mark.asyncio
    async def test_find_symbol_nonexistent_json_serializable(self):
        """Test that errors for non-existent symbols are JSON-serializable."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create an empty Python file
            test_file = Path(temp_dir) / "empty.py"
            test_file.write_text("")

            analyzer = JediAnalyzer(temp_dir)

            # Search for non-existent symbol
            results = await analyzer.find_symbol("NonExistentSymbol")

            # Should return empty list, not error
            assert results == []

            # Result should be JSON serializable
            json.dumps(results)

    @pytest.mark.asyncio
    async def test_error_response_json_serializable(self):
        """Test that error responses with Path objects are JSON-serializable."""
        # Test with a project that doesn't exist to trigger an error
        try:
            JediAnalyzer("/nonexistent/path")
            # This should fail during initialization
            raise AssertionError("Should have raised an error")
        except Exception as e:
            # Format the error response
            error_response = format_error_response(e)

            # Should be JSON serializable
            json_str = json.dumps(error_response)
            assert isinstance(json_str, str)

            # Should not contain PosixPath repr
            assert "PosixPath" not in json_str

    @pytest.mark.asyncio
    async def test_find_symbol_in_real_codebase(self):
        """Test find_symbol on the actual codebase to replicate the reported issue."""
        # Use the current project directory
        analyzer = JediAnalyzer(".")

        # Try to find symbols that exist in our codebase
        symbols_to_test = ["JediAnalyzer", "AnalysisError", "MCPError"]

        for symbol in symbols_to_test:
            try:
                results = await analyzer.find_symbol(symbol)

                if results:
                    # Verify file field is a string
                    for result in results:
                        assert isinstance(
                            result.get("file"), str
                        ), f"File field for {symbol} is not a string: {type(result.get('file'))}"

                    # Verify JSON serialization works
                    json_str = json.dumps(results)
                    assert isinstance(json_str, str)

            except AnalysisError as e:
                # Even if there's an error, it should be JSON serializable
                error_response = format_error_response(e)
                json_str = json.dumps(error_response)
                assert isinstance(json_str, str)
                assert "PosixPath" not in json_str

    @pytest.mark.asyncio
    async def test_goto_definition_json_serializable(self):
        """Test goto_definition returns JSON-serializable results."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(
                """
def target_function():
    pass

# Usage
target_function()
"""
            )

            analyzer = JediAnalyzer(temp_dir)

            # Test goto definition
            result = await analyzer.goto_definition(
                file=str(test_file), line=5, column=0  # Line with function call
            )

            if result:
                # Verify file field is a string
                assert isinstance(result.get("file"), str)

                # Verify JSON serialization
                json.dumps(result)

    @pytest.mark.asyncio
    async def test_find_references_json_serializable(self):
        """Test find_references returns JSON-serializable results."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(
                """
class MyClass:
    pass

obj1 = MyClass()
obj2 = MyClass()
"""
            )

            analyzer = JediAnalyzer(temp_dir)

            # Find references to MyClass
            results = await analyzer.find_references(
                file=str(test_file),
                line=1,  # Line with class definition
                column=6,  # Position of "MyClass"
            )

            # Verify all results have string file paths
            for result in results:
                if "file" in result:
                    assert isinstance(result["file"], str)

            # Verify JSON serialization
            json.dumps(results)

    @pytest.mark.asyncio
    async def test_mcp_server_response_serialization(self):
        """Test that MCP server responses are always JSON-serializable."""
        # Import the actual MCP server function
        from pycodemcp.server import find_symbol

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a test file
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text("class TestClass: pass")

            # Test successful response
            try:
                results = await find_symbol("TestClass", project_path=temp_dir)
                # Should be JSON serializable
                json_str = json.dumps(results)
                assert isinstance(json_str, str)
            except Exception as e:
                # Even errors should be serializable
                error_response = format_error_response(e)
                json_str = json.dumps(error_response)
                assert isinstance(json_str, str)

    @pytest.mark.asyncio
    async def test_complex_project_structure(self):
        """Test with a more complex project structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a package structure
            package_dir = Path(temp_dir) / "mypackage"
            package_dir.mkdir()

            # Create __init__.py
            init_file = package_dir / "__init__.py"
            init_file.write_text("from .module import MyClass")

            # Create module.py
            module_file = package_dir / "module.py"
            module_file.write_text(
                """
class MyClass:
    def method(self):
        return "test"
"""
            )

            # Create a script that uses the package
            script_file = Path(temp_dir) / "script.py"
            script_file.write_text(
                """
from mypackage import MyClass

obj = MyClass()
"""
            )

            analyzer = JediAnalyzer(temp_dir)

            # Find the class
            results = await analyzer.find_symbol("MyClass")

            # Should find it and be JSON serializable
            for result in results:
                if "file" in result:
                    assert isinstance(result["file"], str)

            json.dumps(results)

    def test_path_in_exception_details(self):
        """Test that Path objects in exception details are properly handled."""
        from pathlib import Path

        from pycodemcp.exceptions import AnalysisError

        # This simulates what happens internally when Jedi fails
        path_obj = Path("/some/problematic/file.py")

        # Create an error with a Path object in details
        error = AnalysisError(
            "Test error",
            file_path=path_obj,  # Path object, not string!
            error=path_obj,  # Another Path object
            line=42,
        )

        # Format for MCP response
        response = format_error_response(error)

        # Should be JSON serializable
        json_str = json.dumps(response)

        # Should not contain PosixPath repr
        assert "PosixPath" not in json_str
        assert "/some/problematic/file.py" in json_str

    @pytest.mark.asyncio
    async def test_get_call_hierarchy_json_serializable(self):
        """Test that get_call_hierarchy handles Path serialization properly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(
                """
def caller_function():
    target_function()

def target_function():
    print("Hello")
    helper_function()

def helper_function():
    pass
"""
            )

            analyzer = JediAnalyzer(temp_dir)

            # Test successful case
            result = await analyzer.get_call_hierarchy("target_function")

            # Should be JSON serializable
            json.dumps(result)

            # Test error case - function not found
            result = await analyzer.get_call_hierarchy("NonExistentFunction")

            # Even error results should be JSON serializable
            json.dumps(result)

    @pytest.mark.asyncio
    async def test_all_mcp_tools_json_serializable(self):
        """Test that all MCP tool responses are JSON-serializable."""
        from pycodemcp.server import (
            get_module_info,
            list_modules,
            list_packages,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a simple module
            test_file = Path(temp_dir) / "test_module.py"
            test_file.write_text(
                """
def test_function():
    pass
"""
            )

            # Test each MCP tool
            tools_to_test = [
                (list_modules, {"project_path": temp_dir}),
                (list_packages, {"project_path": temp_dir}),
                (get_module_info, {"module_path": "test_module", "project_path": temp_dir}),
            ]

            for tool_func, kwargs in tools_to_test:
                try:
                    result = await tool_func(**kwargs)
                    # Should be JSON serializable
                    json.dumps(result)
                except Exception as e:
                    # Even errors should be serializable
                    error_response = format_error_response(e)
                    json.dumps(error_response)
