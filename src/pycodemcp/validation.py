"""Input validation and sanitization for file paths and user inputs."""

import re
from pathlib import Path
from typing import Any

from .exceptions import ValidationError


class PathValidator:
    """Validates and sanitizes file paths for security."""

    # Patterns for potentially dangerous file names
    DANGEROUS_NAMES = [
        r"\.git/",  # Git directory
        r"\.ssh/",  # SSH keys
        r"\.aws/",  # AWS credentials
        r"^\.env$",  # Environment files
        r"\.pem$",  # Certificate files
        r"\.key$",  # Key files
        r"^/etc/",  # System config (Unix)
        r"^/proc/",  # Process info (Unix)
        r"^/sys/",  # System info (Unix)
    ]

    @classmethod
    def validate_path(cls, path: str | Path, base_path: str | Path | None = None) -> Path:
        """Validate and sanitize a file path.

        Args:
            path: The path to validate
            base_path: Optional base path to restrict access within

        Returns:
            Validated Path object

        Raises:
            ValidationError: If the path is invalid or potentially dangerous
        """
        if not path:
            raise ValidationError("Path cannot be empty")

        # Convert to string for validation
        path_str = Path(path).as_posix()

        # Check for null bytes
        if "\x00" in path_str:
            raise ValidationError("Path contains null bytes")

        # Check for suspicious patterns that might be attacks
        # Even if they don't exist, we should reject them
        if "..." in path_str:
            raise ValidationError("Path contains suspicious triple dots")

        # Check for attempts to access system directories
        # even if they resolve to non-existent paths
        suspicious_components = ["/etc/", "/root/", "/proc/", "/sys/", "/dev/"]
        path_lower = path_str.lower()
        for comp in suspicious_components:
            if comp in path_lower:
                raise ValidationError(f"Path contains suspicious component: {comp}")

        # Convert to Path object
        try:
            path_obj = Path(path_str)
            # Only resolve if the path contains .. or is absolute
            # This preserves relative paths for testing
            if ".." in path_str or path_obj.is_absolute():
                resolved_path = path_obj.resolve()
            else:
                # Keep relative paths as-is
                resolved_path = path_obj
        except (ValueError, RuntimeError) as e:
            raise ValidationError(f"Invalid path: {e}") from e

        # Check the path (resolved or not) for dangerous locations
        path_to_check = resolved_path.as_posix()

        # Check for actual security issues in paths
        suspicious_resolved_patterns = [
            r"^/etc/",
            r"^/root/",
            r"^/proc/",
            r"^/sys/",
            r"^/dev/",
            r"/etc/",  # Also check if /etc/ appears anywhere in path
            r"/root/",  # Also check if /root/ appears anywhere
        ]

        for pattern in suspicious_resolved_patterns:
            if re.search(pattern, path_to_check):
                raise ValidationError(f"Path resolves to restricted location: {pattern}")

        # If base_path is provided, ensure the path is within it
        if base_path:
            base = Path(base_path).resolve()
            try:
                # Check if path is relative to base
                # Resolve for this check only
                check_path = (
                    resolved_path if resolved_path.is_absolute() else resolved_path.resolve()
                )
                check_path.relative_to(base)
            except ValueError as e:
                raise ValidationError(f"Path {check_path.as_posix()} is outside base directory {base}") from e

        # Check for dangerous file names
        path_str_normalized = resolved_path.as_posix().replace("\\", "/")
        for pattern in cls.DANGEROUS_NAMES:
            if re.search(pattern, path_str_normalized, re.IGNORECASE):
                # Log warning but don't block - these might be legitimate
                import logging

                logging.getLogger(__name__).warning(
                    f"Accessing potentially sensitive path: {path_str_normalized}"
                )

        return resolved_path

    @classmethod
    def is_safe_to_read(cls, path: str | Path, max_size: int = 10 * 1024 * 1024) -> bool:
        """Check if a file is safe to read.

        Args:
            path: Path to check
            max_size: Maximum file size in bytes (default 10MB)

        Returns:
            True if the file appears safe to read
        """
        try:
            path_obj = cls.validate_path(path)

            # Check if file exists
            if not path_obj.exists():
                return False

            # Check if it's a regular file
            if not path_obj.is_file():
                return False

            # Check file size
            if path_obj.stat().st_size > max_size:
                import logging

                logging.getLogger(__name__).warning(
                    f"File too large: {path_obj.as_posix()} ({path_obj.stat().st_size} bytes)"
                )
                return False

            # Check if it's a symlink pointing outside project
            if path_obj.is_symlink():
                target = path_obj.resolve()
                # Could add additional checks here
                import logging

                logging.getLogger(__name__).info(f"Following symlink: {path_obj.as_posix()} -> {target.as_posix()}")

            return True

        except (ValidationError, OSError):
            return False


class InputValidator:
    """General input validation utilities."""

    @staticmethod
    def validate_identifier(name: str, allow_dots: bool = True) -> str:
        """Validate a Python identifier or module name.

        Args:
            name: The identifier to validate
            allow_dots: Whether to allow dots (for module names)

        Returns:
            The validated identifier

        Raises:
            ValidationError: If the identifier is invalid
        """
        if not name:
            raise ValidationError("Identifier cannot be empty")

        # Check length
        if len(name) > 255:
            raise ValidationError("Identifier too long")

        # Check for null bytes
        if "\x00" in name:
            raise ValidationError("Identifier contains null bytes")

        # Validate format
        if allow_dots:
            # Module name format: word.word.word
            pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$"
        else:
            # Simple identifier
            pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"

        if not re.match(pattern, name):
            raise ValidationError(f"Invalid identifier format: {name}")

        return name

    @staticmethod
    def validate_line_number(line: Any, max_line: int = 1000000) -> int:
        """Validate a line number.

        Args:
            line: The line number to validate
            max_line: Maximum allowed line number

        Returns:
            The validated line number

        Raises:
            ValidationError: If the line number is invalid
        """
        try:
            line_num = int(line)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"Invalid line number: {line}") from e

        if line_num < 1:
            raise ValidationError("Line number must be positive")

        if line_num > max_line:
            raise ValidationError(f"Line number too large: {line_num}")

        return line_num

    @staticmethod
    def validate_column_number(column: Any, max_column: int = 10000) -> int:
        """Validate a column number.

        Args:
            column: The column number to validate
            max_column: Maximum allowed column number

        Returns:
            The validated column number

        Raises:
            ValidationError: If the column number is invalid
        """
        try:
            col_num = int(column)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"Invalid column number: {column}") from e

        if col_num < 0:
            raise ValidationError("Column number must be non-negative")

        if col_num > max_column:
            raise ValidationError(f"Column number too large: {col_num}")

        return col_num

    @staticmethod
    def sanitize_string(text: str, max_length: int = 10000) -> str:
        """Sanitize a string for safe use.

        Args:
            text: The string to sanitize
            max_length: Maximum allowed length

        Returns:
            The sanitized string
        """
        if not text:
            return ""

        # Remove null bytes
        text = text.replace("\x00", "")

        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length]

        # Remove control characters except common ones (tab, newline, etc.)
        text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)

        return text


def validate_mcp_inputs(func: Any) -> Any:
    """Decorator to validate inputs for MCP tool functions.

    This decorator validates common MCP tool parameters and raises
    ValidationError for invalid inputs rather than returning error dicts.
    Properly handles both sync and async functions.
    """
    import asyncio
    import functools
    import inspect

    def validate_arguments(sig: Any, args: Any, kwargs: Any) -> Any:
        """Common validation logic for both sync and async wrappers."""
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        # Validate based on parameter names
        for param_name, value in bound.arguments.items():
            if value is None:
                continue

            # File path validation
            if param_name in ["file", "file_path", "path", "project_path"]:
                try:
                    validated = PathValidator.validate_path(value)
                    bound.arguments[param_name] = str(validated)
                except ValidationError as e:
                    # Raise the error to be handled by the exception handler
                    raise ValidationError(
                        f"Invalid {param_name}: {e}", parameter=param_name, value=str(value)
                    ) from e

            # Line number validation
            elif param_name == "line":
                try:
                    bound.arguments[param_name] = InputValidator.validate_line_number(value)
                except ValidationError as e:
                    raise ValidationError(
                        f"Invalid line number: {e}", parameter="line", value=str(value)
                    ) from e

            # Column number validation
            elif param_name == "column":
                try:
                    bound.arguments[param_name] = InputValidator.validate_column_number(value)
                except ValidationError as e:
                    raise ValidationError(
                        f"Invalid column number: {e}", parameter="column", value=str(value)
                    ) from e

            # Module/identifier name validation
            elif param_name in ["name", "module_name", "function_name", "import_path"]:
                try:
                    bound.arguments[param_name] = InputValidator.validate_identifier(
                        value, allow_dots=param_name in ["module_name", "import_path"]
                    )
                except ValidationError as e:
                    raise ValidationError(
                        f"Invalid {param_name}: {e}", parameter=param_name, value=str(value)
                    ) from e

            # List validation for paths
            elif param_name in ["paths", "repo_paths", "project_paths", "packages"]:
                if isinstance(value, list):
                    validated_list = []
                    for i, item in enumerate(value):
                        try:
                            validated = PathValidator.validate_path(item)
                            validated_list.append(str(validated))
                        except ValidationError as e:
                            raise ValidationError(
                                f"Invalid path at index {i} in {param_name}: {e}",
                                parameter=param_name,
                                value=str(item),
                                index=i,
                            ) from e
                    bound.arguments[param_name] = validated_list

        return bound

    # Get function signature once
    sig = inspect.signature(func)

    # Check if the function is async
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = validate_arguments(sig, args, kwargs)
            return await func(*bound.args, **bound.kwargs)

        return async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = validate_arguments(sig, args, kwargs)
            return func(*bound.args, **bound.kwargs)

        return sync_wrapper
