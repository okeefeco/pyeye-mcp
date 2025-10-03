"""Custom exceptions for PyEye Server.

This module defines a hierarchy of exceptions for better error handling
and debugging throughout the application.
"""

from pathlib import Path
from typing import Any


class MCPError(Exception):
    """Base exception for all MCP server errors.

    All custom exceptions should inherit from this class to allow
    catching all MCP-related errors with a single except clause.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """Initialize the exception with a message and optional details.

        Args:
            message: Human-readable error message
            details: Additional context about the error
        """
        super().__init__(message)
        self.message = message
        # Convert Path objects to strings in details to ensure JSON serialization
        self.details = {}
        if details:
            for k, v in details.items():
                if isinstance(v, Path):
                    self.details[k] = v.as_posix()
                else:
                    self.details[k] = v

    def __str__(self) -> str:
        """Return a formatted error message."""
        if self.details:
            # Convert Path objects to strings to avoid serialization issues
            formatted_details = {}
            for k, v in self.details.items():
                if isinstance(v, Path):
                    formatted_details[k] = v.as_posix()
                else:
                    formatted_details[k] = v
            details_str = ", ".join(f"{k}={v}" for k, v in formatted_details.items())
            return f"{self.message} ({details_str})"
        return self.message


class AnalysisError(MCPError):
    """Raised when code analysis operations fail.

    This includes Jedi analysis failures, parsing errors, or when
    the analyzer cannot process the provided code.
    """

    def __init__(
        self, message: str, file_path: str | None = None, line: int | None = None, **kwargs: Any
    ):
        """Initialize analysis error with file context.

        Args:
            message: Error description
            file_path: Path to the file being analyzed
            line: Line number where error occurred
            **kwargs: Additional details
        """
        details = kwargs
        if file_path:
            details["file"] = file_path
        if line is not None:
            details["line"] = line
        super().__init__(message, details)


class ConfigurationError(MCPError):
    """Raised for configuration-related issues.

    This includes invalid configuration files, missing required settings,
    or incompatible configuration values.
    """

    def __init__(
        self,
        message: str,
        config_file: str | None = None,
        setting: str | None = None,
        **kwargs: Any,
    ):
        """Initialize configuration error.

        Args:
            message: Error description
            config_file: Path to problematic config file
            setting: Name of the problematic setting
            **kwargs: Additional details
        """
        details = kwargs
        if config_file:
            details["config_file"] = config_file
        if setting:
            details["setting"] = setting
        super().__init__(message, details)


class PluginError(MCPError):
    """Raised when plugin operations fail.

    This includes plugin initialization failures, incompatible plugin
    versions, or errors during plugin execution.
    """

    def __init__(
        self,
        message: str,
        plugin_name: str | None = None,
        operation: str | None = None,
        **kwargs: Any,
    ):
        """Initialize plugin error.

        Args:
            message: Error description
            plugin_name: Name of the plugin that failed
            operation: Operation that was being performed
            **kwargs: Additional details
        """
        details = kwargs
        if plugin_name:
            details["plugin"] = plugin_name
        if operation:
            details["operation"] = operation
        super().__init__(message, details)


class ValidationError(MCPError):
    """Raised when input validation fails.

    This includes invalid parameters, out-of-range values, or
    malformed input data.
    """

    def __init__(
        self,
        message: str,
        parameter: str | None = None,
        value: Any = None,
        expected: str | None = None,
        **kwargs: Any,
    ):
        """Initialize validation error.

        Args:
            message: Error description
            parameter: Name of the invalid parameter
            value: The invalid value provided
            expected: Description of expected value/format
            **kwargs: Additional details
        """
        details = kwargs
        if parameter:
            details["parameter"] = parameter
        if value is not None:
            details["value"] = str(value)
        if expected:
            details["expected"] = expected
        super().__init__(message, details)


class ProjectNotFoundError(MCPError):
    """Raised when a requested project cannot be found or accessed."""

    def __init__(self, project_path: str, **kwargs: Any):
        """Initialize project not found error.

        Args:
            project_path: Path to the project that wasn't found
            **kwargs: Additional details
        """
        details = kwargs
        details["project_path"] = project_path
        super().__init__(f"Project not found: {Path(project_path).as_posix()}", details)


class FileAccessError(MCPError):
    """Raised when file operations fail.

    This includes permission errors, missing files, or I/O errors.
    """

    def __init__(self, message: str, file_path: str, operation: str | None = None, **kwargs: Any):
        """Initialize file access error.

        Args:
            message: Error description
            file_path: Path to the file
            operation: Operation that failed (read, write, etc.)
            **kwargs: Additional details
        """
        details = kwargs
        details["file_path"] = file_path
        if operation:
            details["operation"] = operation
        super().__init__(message, details)


class CacheError(MCPError):
    """Raised when cache operations fail.

    This includes cache invalidation errors, serialization failures,
    or cache storage issues.
    """

    def __init__(
        self,
        message: str,
        cache_key: str | None = None,
        operation: str | None = None,
        **kwargs: Any,
    ):
        """Initialize cache error.

        Args:
            message: Error description
            cache_key: The cache key involved
            operation: Cache operation that failed
            **kwargs: Additional details
        """
        details = kwargs
        if cache_key:
            details["cache_key"] = cache_key
        if operation:
            details["operation"] = operation
        super().__init__(message, details)


class TimeoutError(MCPError):
    """Raised when an operation exceeds its time limit.

    This includes analysis timeouts, file operation timeouts,
    or network timeouts.
    """

    def __init__(
        self,
        message: str,
        timeout_seconds: float | None = None,
        operation: str | None = None,
        **kwargs: Any,
    ):
        """Initialize timeout error.

        Args:
            message: Error description
            timeout_seconds: The timeout limit that was exceeded
            operation: Operation that timed out
            **kwargs: Additional details
        """
        details = kwargs
        if timeout_seconds is not None:
            details["timeout_seconds"] = timeout_seconds
        if operation:
            details["operation"] = operation
        super().__init__(message, details)


class DependencyError(MCPError):
    """Raised when required dependencies are missing or incompatible.

    This includes missing Python packages, version conflicts,
    or unavailable system dependencies.
    """

    def __init__(
        self,
        message: str,
        dependency: str | None = None,
        required_version: str | None = None,
        installed_version: str | None = None,
        **kwargs: Any,
    ):
        """Initialize dependency error.

        Args:
            message: Error description
            dependency: Name of the dependency
            required_version: Required version specification
            installed_version: Currently installed version
            **kwargs: Additional details
        """
        details = kwargs
        if dependency:
            details["dependency"] = dependency
        if required_version:
            details["required_version"] = required_version
        if installed_version:
            details["installed_version"] = installed_version
        super().__init__(message, details)


def format_error_response(error: Exception) -> dict[str, Any]:
    """Format an exception for MCP error responses.

    Args:
        error: The exception to format

    Returns:
        Dictionary with error details suitable for MCP responses
    """
    if isinstance(error, MCPError):
        return {"error": type(error).__name__, "message": error.message, "details": error.details}
    else:
        # Handle standard Python exceptions
        return {"error": type(error).__name__, "message": str(error), "details": {}}
