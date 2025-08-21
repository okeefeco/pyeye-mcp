"""Tests for input validation and sanitization."""

import tempfile
from pathlib import Path

import pytest
from pycodemcp.validation import InputValidator, PathValidator, ValidationError, validate_mcp_inputs


class TestPathValidator:
    """Test path validation and sanitization."""

    def test_validate_normal_path(self):
        """Test validation of normal paths."""
        # Use platform-appropriate absolute path
        import os

        abs_path = (
            "C:\\Users\\user\\project\\file.py" if os.name == "nt" else "/home/user/project/file.py"
        )

        result = PathValidator.validate_path(abs_path)
        assert isinstance(result, Path)
        assert result.is_absolute()

        # Relative path
        result = PathValidator.validate_path("src/module.py")
        assert isinstance(result, Path)

    def test_reject_path_traversal(self):
        """Test rejection of path traversal attempts."""
        # These paths should be rejected because they resolve to restricted locations
        dangerous_paths = [
            "../../../etc/passwd",  # May resolve to /etc/passwd
            "/home/user/../../../etc/shadow",  # Resolves to /etc/shadow
        ]

        for path in dangerous_paths:
            # Skip if path doesn't resolve to a restricted location
            # (depends on where tests are run from)
            try:
                resolved = Path(path).resolve()
                if not any(
                    str(resolved).startswith(restricted)
                    for restricted in ["/etc/", "/root/", "/proc/", "/sys/"]
                ):
                    continue
            except (ValueError, RuntimeError, OSError):
                continue

            with pytest.raises(ValidationError) as exc_info:
                PathValidator.validate_path(path)
            error_msg = str(exc_info.value).lower()
            assert "restricted" in error_msg or "suspicious" in error_msg

        # These paths may only generate warnings, not errors
        warning_paths = [
            "../../.ssh/id_rsa",  # SSH keys generate warnings
            "test/../../secret.txt",  # May not be in restricted location
        ]

        # Just verify these don't crash
        import contextlib

        for path in warning_paths:
            with contextlib.suppress(ValidationError):
                PathValidator.validate_path(path)
                # It's ok if they're rejected

    def test_reject_null_bytes(self):
        """Test rejection of paths with null bytes."""
        with pytest.raises(ValidationError) as exc_info:
            PathValidator.validate_path("/path/with\x00null")
        assert "null bytes" in str(exc_info.value).lower()

    def test_empty_path(self):
        """Test rejection of empty paths."""
        with pytest.raises(ValidationError) as exc_info:
            PathValidator.validate_path("")
        assert "empty" in str(exc_info.value).lower()

    def test_base_path_restriction(self):
        """Test path restriction within base directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            allowed = base / "subdir" / "file.py"

            # Should allow paths within base
            result = PathValidator.validate_path(allowed, base)
            assert result.is_absolute()

            # Should reject paths outside base
            outside = Path("/etc/passwd")
            with pytest.raises(ValidationError) as exc_info:
                PathValidator.validate_path(outside, base)
            # Could be rejected for being outside base OR for being suspicious
            error_msg = str(exc_info.value).lower()
            assert "outside" in error_msg or "suspicious" in error_msg

    def test_warns_on_sensitive_paths(self, caplog):
        """Test warning on potentially sensitive paths."""
        import logging

        # Set logging level to capture warnings
        caplog.set_level(logging.WARNING)
        # This should warn but not fail
        PathValidator.validate_path(".git/config")
        assert "potentially sensitive" in caplog.text.lower()

    def test_is_safe_to_read(self):
        """Test file safety checks."""
        with tempfile.NamedTemporaryFile(suffix=".py") as tmpfile:
            # Write some content
            tmpfile.write(b"print('hello')")
            tmpfile.flush()

            # Should be safe to read
            assert PathValidator.is_safe_to_read(tmpfile.name)

            # Non-existent file
            assert not PathValidator.is_safe_to_read("/nonexistent/file.py")

            # Directory (not a file)
            assert not PathValidator.is_safe_to_read(Path(tmpfile.name).parent)

    def test_large_file_warning(self, caplog):
        """Test warning for large files."""
        with tempfile.NamedTemporaryFile(suffix=".py") as tmpfile:
            # Write large content
            tmpfile.write(b"x" * (11 * 1024 * 1024))  # 11MB
            tmpfile.flush()

            # Should not be safe to read
            assert not PathValidator.is_safe_to_read(tmpfile.name)
            assert "too large" in caplog.text.lower()


class TestInputValidator:
    """Test general input validation."""

    def test_validate_identifier(self):
        """Test Python identifier validation."""
        # Valid identifiers
        assert InputValidator.validate_identifier("my_function") == "my_function"
        assert InputValidator.validate_identifier("_private") == "_private"
        assert InputValidator.validate_identifier("Class123") == "Class123"

        # Valid module names (with dots)
        assert (
            InputValidator.validate_identifier("package.module", allow_dots=True)
            == "package.module"
        )
        assert InputValidator.validate_identifier("a.b.c.d", allow_dots=True) == "a.b.c.d"

        # Invalid identifiers
        with pytest.raises(ValidationError):
            InputValidator.validate_identifier("123invalid")

        with pytest.raises(ValidationError):
            InputValidator.validate_identifier("my-function")

        with pytest.raises(ValidationError):
            InputValidator.validate_identifier("module.name", allow_dots=False)

    def test_validate_line_number(self):
        """Test line number validation."""
        # Valid line numbers
        assert InputValidator.validate_line_number(1) == 1
        assert InputValidator.validate_line_number("42") == 42
        assert InputValidator.validate_line_number(10000) == 10000

        # Invalid line numbers
        with pytest.raises(ValidationError):
            InputValidator.validate_line_number(0)

        with pytest.raises(ValidationError):
            InputValidator.validate_line_number(-5)

        with pytest.raises(ValidationError):
            InputValidator.validate_line_number(10000000)

        with pytest.raises(ValidationError):
            InputValidator.validate_line_number("not a number")

    def test_validate_column_number(self):
        """Test column number validation."""
        # Valid column numbers
        assert InputValidator.validate_column_number(0) == 0
        assert InputValidator.validate_column_number("42") == 42
        assert InputValidator.validate_column_number(100) == 100

        # Invalid column numbers
        with pytest.raises(ValidationError):
            InputValidator.validate_column_number(-1)

        with pytest.raises(ValidationError):
            InputValidator.validate_column_number(100000)

        with pytest.raises(ValidationError):
            InputValidator.validate_column_number("invalid")

    def test_sanitize_string(self):
        """Test string sanitization."""
        # Normal string
        assert InputValidator.sanitize_string("hello world") == "hello world"

        # String with null bytes
        assert InputValidator.sanitize_string("hello\x00world") == "helloworld"

        # String with control characters
        assert InputValidator.sanitize_string("hello\x07\x08world") == "helloworld"

        # Long string (should truncate)
        long_str = "x" * 20000
        result = InputValidator.sanitize_string(long_str)
        assert len(result) == 10000

        # Empty string
        assert InputValidator.sanitize_string("") == ""
        assert InputValidator.sanitize_string(None) == ""


class TestValidateMCPInputsDecorator:
    """Test the validation decorator for MCP functions."""

    def test_decorator_validates_paths(self):
        """Test that decorator validates path parameters."""
        import os

        from pycodemcp.exceptions import ValidationError

        @validate_mcp_inputs
        def test_func(file: str, project_path: str = "."):
            return {"file": file, "project_path": project_path}

        # Valid paths - use platform-appropriate absolute path
        valid_path = "C:\\valid\\path.py" if os.name == "nt" else "/valid/path.py"

        result = test_func(valid_path, "/project")
        # The validation preserves paths that don't need resolution
        # On Windows, paths without ".." are kept as-is if not absolute
        expected = (
            str(Path(valid_path).resolve())
            if Path(valid_path).is_absolute()
            else str(Path(valid_path))
        )
        assert result["file"] == expected

        # Invalid path should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            test_func("../../etc/passwd", "/project")
        assert "Invalid file" in str(exc_info.value)

    def test_decorator_validates_line_column(self):
        """Test that decorator validates line and column parameters."""
        from pycodemcp.exceptions import ValidationError

        @validate_mcp_inputs
        def test_func(line: int, column: int):
            return {"line": line, "column": column}

        # Valid values
        result = test_func(10, 5)
        assert result == {"line": 10, "column": 5}

        # Invalid line should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            test_func(-1, 5)
        assert "Invalid line" in str(exc_info.value)

        # Invalid column should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            test_func(10, -1)
        assert "Invalid column" in str(exc_info.value)

    def test_decorator_validates_identifiers(self):
        """Test that decorator validates identifier parameters."""
        from pycodemcp.exceptions import ValidationError

        @validate_mcp_inputs
        def test_func(name: str, module_name: str):
            return {"name": name, "module_name": module_name}

        # Valid identifiers
        result = test_func("my_func", "package.module")
        assert result == {"name": "my_func", "module_name": "package.module"}

        # Invalid identifier should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            test_func("123invalid", "package.module")
        assert "Invalid name" in str(exc_info.value)

    def test_decorator_validates_path_lists(self):
        """Test that decorator validates lists of paths."""
        from pycodemcp.exceptions import ValidationError

        @validate_mcp_inputs
        def test_func(paths: list, packages: list):
            return {"paths": paths, "packages": packages}

        # Valid paths
        result = test_func(["/path1", "/path2"], ["/pkg1", "/pkg2"])
        assert len(result["paths"]) == 2
        assert len(result["packages"]) == 2

        # List with invalid path should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            test_func(["/valid", "../../etc/passwd"], ["/pkg1"])
        assert "Invalid path" in str(exc_info.value)
        assert "paths" in str(exc_info.value)

    def test_decorator_handles_none_values(self):
        """Test that decorator handles None values gracefully."""

        @validate_mcp_inputs
        def test_func(file: str = None, name: str = None):
            return {"file": file, "name": name}

        # None values should pass through
        result = test_func()
        assert result == {"file": None, "name": None}
        assert "error" not in result
