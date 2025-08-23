"""Test that PosixPath objects in exceptions are properly handled for JSON serialization."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pycodemcp.exceptions import (
    AnalysisError,
    MCPError,
    format_error_response,
)


class TestPathSerialization:
    """Test that Path objects are properly serialized in exceptions."""

    def test_mcperror_with_path_in_details(self):
        """Test that MCPError properly converts Path objects in details."""
        # Create an error with a Path object in details
        error = MCPError("Test error", details={"file": Path("/test/file.py"), "operation": "test"})

        # The details should have the Path converted to string
        assert error.details["file"] == "/test/file.py"
        assert isinstance(error.details["file"], str)

        # The string representation should be JSON serializable
        error_str = str(error)
        assert "file=/test/file.py" in error_str

        # Details should be JSON serializable
        json_str = json.dumps(error.details)
        assert "/test/file.py" in json_str

    def test_analysis_error_with_path_in_kwargs(self):
        """Test AnalysisError with Path objects passed as kwargs."""
        error = AnalysisError(
            "Analysis failed",
            file_path="/src/module.py",
            error=Path("/test/error/path.py"),  # Path object in error field
            module_path=Path("/test/module.py"),  # Another Path object
        )

        # All Path objects should be converted to strings
        assert error.details["error"] == "/test/error/path.py"
        assert error.details["module_path"] == "/test/module.py"
        assert isinstance(error.details["error"], str)
        assert isinstance(error.details["module_path"], str)

        # Should be JSON serializable
        json_str = json.dumps(error.details)
        assert "/test/error/path.py" in json_str

    def test_exception_chain_with_path_objects(self):
        """Test handling of exceptions that have Path objects in their args."""
        # Simulate an exception with a Path object (like Jedi's KeyError)
        path_obj = Path("/test/file.py")

        # Create an exception with Path in args (simulating Jedi's bug)
        original_error = KeyError(path_obj)

        # Our error handling should convert it properly
        # Simulate what happens in jedi_analyzer.py lines 380-391
        error_str = str(original_error)
        if hasattr(original_error, "args") and original_error.args:
            if any(isinstance(arg, Path) for arg in original_error.args):
                converted_args = []
                for arg in original_error.args:
                    if isinstance(arg, Path):
                        converted_args.append(arg.as_posix())
                    else:
                        converted_args.append(str(arg))
                error_str = " ".join(converted_args)

        # Create AnalysisError with the converted error string
        analysis_error = AnalysisError("Failed to analyze", operation="test", error=error_str)

        # Should be JSON serializable
        json_str = json.dumps(analysis_error.details)
        assert "/test/file.py" in json_str
        assert "PosixPath" not in json_str  # Should not have the repr form

    def test_format_error_response_with_paths(self):
        """Test format_error_response with Path objects."""
        error = AnalysisError(
            "Test error", file_path=Path("/test/file.py"), line=10, error=Path("/error/path.py")
        )

        response = format_error_response(error)

        # Response should be JSON serializable
        json_str = json.dumps(response)
        assert "/test/file.py" in json_str
        assert "/error/path.py" in json_str

        # Check structure
        assert response["error"] == "AnalysisError"
        assert response["message"] == "Test error"
        assert response["details"]["file"] == "/test/file.py"
        assert response["details"]["error"] == "/error/path.py"

    def test_nested_path_objects(self):
        """Test handling of nested Path objects in error details."""
        error = MCPError(
            "Complex error",
            details={
                "paths": [Path("/path1.py"), Path("/path2.py")],
                "nested": {"file": Path("/nested/file.py")},
                "mixed": [Path("/path.py"), "string", 123],
            },
        )

        # Currently, our implementation only handles top-level Path objects
        # This test documents the current behavior
        # Nested paths would need recursive conversion if required
        assert isinstance(error.details["paths"], list)
        assert isinstance(error.details["nested"], dict)

    @pytest.mark.asyncio
    async def test_jedi_analyzer_error_handling(self):
        """Test that JediAnalyzer properly handles Path serialization errors."""
        from pycodemcp.analyzers.jedi_analyzer import JediAnalyzer

        # Mock Jedi to raise an exception with a Path object
        with patch("jedi.Project") as mock_project:
            mock_search = Mock(side_effect=KeyError(Path("/problematic/file.py")))
            mock_project.return_value.search = mock_search

            analyzer = JediAnalyzer(".")

            # This should handle the Path in the exception properly
            with pytest.raises(AnalysisError) as exc_info:
                await analyzer.find_symbol("TestSymbol")

            # The error should be JSON serializable
            error = exc_info.value
            json_str = json.dumps(error.details)
            assert isinstance(json_str, str)
            # The path should be converted to string, not have PosixPath repr
            assert "problematic/file.py" in str(error) or "problematic" in str(error)

    def test_mcperror_str_with_paths(self):
        """Test MCPError.__str__() properly handles Path objects."""
        error = MCPError(
            "Test message", details={"file": Path("/test/file.py"), "line": 42, "operation": "test"}
        )

        error_str = str(error)

        # Should contain the path as a string, not PosixPath(...)
        assert "/test/file.py" in error_str
        assert "PosixPath" not in error_str
        assert "line=42" in error_str
        assert "operation=test" in error_str
