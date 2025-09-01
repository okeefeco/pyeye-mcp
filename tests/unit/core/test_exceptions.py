"""Tests for custom exception handling."""

import pytest

from pycodemcp.exceptions import (
    AnalysisError,
    CacheError,
    ConfigurationError,
    DependencyError,
    FileAccessError,
    MCPError,
    PluginError,
    ProjectNotFoundError,
    TimeoutError,
    ValidationError,
    format_error_response,
)


class TestMCPError:
    """Test the base MCPError class."""

    def test_basic_error(self):
        """Test creating a basic error with message."""
        error = MCPError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_error_with_details(self):
        """Test creating an error with additional details."""
        error = MCPError("Connection failed", {"host": "localhost", "port": 5432})
        assert str(error) == "Connection failed (host=localhost, port=5432)"
        assert error.details["host"] == "localhost"
        assert error.details["port"] == 5432


class TestAnalysisError:
    """Test the AnalysisError class."""

    def test_analysis_error_with_file(self):
        """Test analysis error with file context."""
        error = AnalysisError("Failed to parse", file_path="/path/to/file.py", line=42)
        assert "Failed to parse" in str(error)
        assert error.details["file"] == "/path/to/file.py"
        assert error.details["line"] == 42

    def test_analysis_error_without_context(self):
        """Test analysis error without file context."""
        error = AnalysisError("General analysis failure")
        assert str(error) == "General analysis failure"
        assert "file" not in error.details
        assert "line" not in error.details


class TestConfigurationError:
    """Test the ConfigurationError class."""

    def test_config_error_with_file(self):
        """Test configuration error with file and setting."""
        error = ConfigurationError(
            "Invalid value",
            config_file="/path/to/config.json",
            setting="max_workers",
            value="invalid",
        )
        assert "Invalid value" in str(error)
        assert error.details["config_file"] == "/path/to/config.json"
        assert error.details["setting"] == "max_workers"
        assert error.details["value"] == "invalid"


class TestPluginError:
    """Test the PluginError class."""

    def test_plugin_error(self):
        """Test plugin error with plugin name and operation."""
        error = PluginError(
            "Plugin initialization failed",
            plugin_name="DjangoPlugin",
            operation="detect",
            reason="Missing Django settings",
        )
        assert "Plugin initialization failed" in str(error)
        assert error.details["plugin"] == "DjangoPlugin"
        assert error.details["operation"] == "detect"
        assert error.details["reason"] == "Missing Django settings"


class TestValidationError:
    """Test the ValidationError class."""

    def test_validation_error(self):
        """Test validation error with parameter details."""
        error = ValidationError(
            "Invalid line number",
            parameter="line",
            value=-1,
            expected="positive integer",
        )
        assert "Invalid line number" in str(error)
        assert error.details["parameter"] == "line"
        assert error.details["value"] == "-1"
        assert error.details["expected"] == "positive integer"


class TestProjectNotFoundError:
    """Test the ProjectNotFoundError class."""

    def test_project_not_found(self):
        """Test project not found error."""
        error = ProjectNotFoundError("/nonexistent/project")
        assert "Project not found: /nonexistent/project" in str(error)
        assert error.details["project_path"] == "/nonexistent/project"


class TestFileAccessError:
    """Test the FileAccessError class."""

    def test_file_access_error(self):
        """Test file access error with operation."""
        error = FileAccessError("Permission denied", file_path="/etc/passwd", operation="write")
        assert "Permission denied" in str(error)
        assert error.details["file_path"] == "/etc/passwd"
        assert error.details["operation"] == "write"


class TestCacheError:
    """Test the CacheError class."""

    def test_cache_error(self):
        """Test cache error with key and operation."""
        error = CacheError("Cache miss", cache_key="symbol:MyClass", operation="get", ttl=300)
        assert "Cache miss" in str(error)
        assert error.details["cache_key"] == "symbol:MyClass"
        assert error.details["operation"] == "get"
        assert error.details["ttl"] == 300


class TestTimeoutError:
    """Test the TimeoutError class."""

    def test_timeout_error(self):
        """Test timeout error with duration."""
        error = TimeoutError(
            "Analysis timed out", timeout_seconds=30.0, operation="find_references"
        )
        assert "Analysis timed out" in str(error)
        assert error.details["timeout_seconds"] == 30.0
        assert error.details["operation"] == "find_references"


class TestDependencyError:
    """Test the DependencyError class."""

    def test_dependency_error(self):
        """Test dependency error with version info."""
        error = DependencyError(
            "Version conflict",
            dependency="jedi",
            required_version=">=0.18.0",
            installed_version="0.17.2",
        )
        assert "Version conflict" in str(error)
        assert error.details["dependency"] == "jedi"
        assert error.details["required_version"] == ">=0.18.0"
        assert error.details["installed_version"] == "0.17.2"


class TestFormatErrorResponse:
    """Test the format_error_response function."""

    def test_format_mcp_error(self):
        """Test formatting an MCPError for response."""
        error = ValidationError(
            "Invalid input", parameter="name", value="123", expected="identifier"
        )
        response = format_error_response(error)

        assert response["error"] == "ValidationError"
        assert response["message"] == "Invalid input"
        assert response["details"]["parameter"] == "name"
        assert response["details"]["value"] == "123"
        assert response["details"]["expected"] == "identifier"

    def test_format_standard_exception(self):
        """Test formatting a standard Python exception."""
        error = ValueError("Invalid value")
        response = format_error_response(error)

        assert response["error"] == "ValueError"
        assert response["message"] == "Invalid value"
        assert response["details"] == {}

    def test_format_exception_with_attributes(self):
        """Test formatting an exception with custom attributes."""
        # FileNotFoundError has special handling for filename attribute
        error = FileNotFoundError("File not found")
        error.filename = "/path/to/missing.txt"  # type: ignore
        response = format_error_response(error)

        assert response["error"] == "FileNotFoundError"
        # FileNotFoundError includes filename in its string representation
        assert "/path/to/missing.txt" in response["message"]
        # Standard exceptions don't include custom attributes in details
        assert response["details"] == {}


class TestExceptionInheritance:
    """Test that custom exceptions properly inherit from MCPError."""

    def test_all_exceptions_inherit_from_mcp_error(self):
        """Test that all custom exceptions inherit from MCPError."""
        exceptions = [
            AnalysisError("test"),
            ConfigurationError("test"),
            PluginError("test"),
            ValidationError("test"),
            ProjectNotFoundError("test"),
            FileAccessError("test", "test"),
            CacheError("test"),
            TimeoutError("test"),
            DependencyError("test"),
        ]

        for exc in exceptions:
            assert isinstance(exc, MCPError)
            assert isinstance(exc, Exception)

    def test_exception_catching(self):
        """Test that MCPError can catch all custom exceptions."""
        exceptions = [
            (AnalysisError, {"message": "test"}),
            (ConfigurationError, {"message": "test"}),
            (PluginError, {"message": "test"}),
            (ValidationError, {"message": "test"}),
            (ProjectNotFoundError, {"project_path": "test"}),
            (FileAccessError, {"message": "test", "file_path": "test"}),
            (CacheError, {"message": "test"}),
            (TimeoutError, {"message": "test"}),
            (DependencyError, {"message": "test"}),
        ]

        for exc_class, kwargs in exceptions:
            with pytest.raises(MCPError):
                raise exc_class(**kwargs)
