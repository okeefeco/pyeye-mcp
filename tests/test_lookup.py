"""Tests for the unified lookup tool — identifier parsing and validation logic.

These tests cover Task 3.1: module structure, validation, and identifier
classification.  Resolution logic (Tasks 3.2-3.3) is tested elsewhere once
implemented.
"""

import pytest

from pyeye.mcp.lookup import lookup


class TestLookupCoordinatePrecedence:
    """Coordinates take precedence when all three are supplied together with identifier."""

    @pytest.mark.asyncio
    async def test_coordinates_take_precedence_over_identifier(self, tmp_path):
        """When all three coordinates + identifier are given, coordinates win."""
        sample = tmp_path / "sample.py"
        sample.write_text("class MyClass:\n    pass\n")

        result = await lookup(
            identifier="MyClass",
            file=str(sample),
            line=1,
            column=6,
            project_path=str(tmp_path),
        )

        # Should take the coordinate branch (placeholder response, not bare_name)
        assert isinstance(result, dict)
        # Coordinate branch returns the coordinate-resolution placeholder
        assert "error" in result
        assert (
            "classified as" not in result["error"]
        ), "Expected coordinate branch placeholder, not identifier branch"
        assert "Coordinate" in result["error"] or "coordinate" in result["error"]

    @pytest.mark.asyncio
    async def test_column_zero_is_valid_coordinate(self, tmp_path):
        """column=0 must be treated as a valid coordinate (not falsy None check)."""
        sample = tmp_path / "sample.py"
        sample.write_text("x = 1\n")

        result = await lookup(
            file=str(sample),
            line=1,
            column=0,
            project_path=str(tmp_path),
        )

        # Should take coordinate branch, not "coordinates incomplete" branch
        assert "Coordinates incomplete" not in result.get("error", "")


class TestLookupPartialCoordinates:
    """Partial coordinates (some but not all) produce a clear error."""

    @pytest.mark.asyncio
    async def test_file_and_line_without_column_errors(self, tmp_path):
        """file + line but no column → Coordinates incomplete error."""
        sample = tmp_path / "sample.py"
        sample.write_text("x = 1\n")

        result = await lookup(
            file=str(sample),
            line=1,
            project_path=str(tmp_path),
        )

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]

    @pytest.mark.asyncio
    async def test_file_only_errors(self, tmp_path):
        """file only → Coordinates incomplete error."""
        sample = tmp_path / "sample.py"
        sample.write_text("x = 1\n")

        result = await lookup(
            file=str(sample),
            project_path=str(tmp_path),
        )

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]

    @pytest.mark.asyncio
    async def test_line_only_errors(self):
        """line only → Coordinates incomplete error."""
        result = await lookup(line=5)

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]

    @pytest.mark.asyncio
    async def test_line_and_column_without_file_errors(self):
        """line + column without file → Coordinates incomplete error."""
        result = await lookup(line=1, column=0)

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]


class TestLookupNoInputs:
    """When neither identifier nor coordinates are provided, return clear error."""

    @pytest.mark.asyncio
    async def test_no_inputs_returns_error(self):
        """Calling lookup with no arguments returns an error."""
        result = await lookup()

        assert "error" in result
        assert "identifier" in result["error"].lower() or "Either" in result["error"]

    @pytest.mark.asyncio
    async def test_project_path_only_returns_error(self):
        """project_path alone is not enough to resolve anything."""
        result = await lookup(project_path=".")

        assert "error" in result
        assert "identifier" in result["error"].lower() or "Either" in result["error"]


class TestLookupIdentifierClassification:
    """Identifier strings are classified into bare_name, file_path, or dotted_path."""

    @pytest.mark.asyncio
    async def test_bare_name_classification(self):
        """A plain identifier with no dots or separators → bare_name."""
        result = await lookup(identifier="Config")

        assert "error" in result
        assert "bare_name" in result["error"]

    @pytest.mark.asyncio
    async def test_bare_name_with_underscores(self):
        """Underscores are allowed in bare names."""
        result = await lookup(identifier="my_function")

        assert "error" in result
        assert "bare_name" in result["error"]

    @pytest.mark.asyncio
    async def test_file_path_with_slash_classification(self):
        """A path containing / → file_path."""
        result = await lookup(identifier="src/pyeye/server.py")

        assert "error" in result
        assert "file_path" in result["error"]

    @pytest.mark.asyncio
    async def test_file_path_with_py_extension(self):
        """A string ending in .py with no other dots → file_path (not dotted_path)."""
        result = await lookup(identifier="server.py")

        assert "error" in result
        assert "file_path" in result["error"]

    @pytest.mark.asyncio
    async def test_file_path_with_py_extension_and_line_suffix(self):
        """A file path with a :line suffix → file_path."""
        result = await lookup(identifier="server.py:42")

        assert "error" in result
        # server.py:42 ends with a colon-number, but "server.py" still ends with .py
        # so the rule fires on the .py suffix
        assert "file_path" in result["error"]

    @pytest.mark.asyncio
    async def test_dotted_path_classification(self):
        """A dotted module path with no slashes and not ending in .py → dotted_path."""
        result = await lookup(identifier="pyeye.mcp.server")

        assert "error" in result
        assert "dotted_path" in result["error"]

    @pytest.mark.asyncio
    async def test_dotted_path_with_class(self):
        """A fully-qualified class name → dotted_path."""
        result = await lookup(identifier="pyeye.mcp.server.ServiceManager")

        assert "error" in result
        assert "dotted_path" in result["error"]

    @pytest.mark.asyncio
    async def test_file_path_with_backslash(self):
        """A path with backslash separator → file_path."""
        result = await lookup(identifier="src\\pyeye\\server.py")

        assert "error" in result
        assert "file_path" in result["error"]
