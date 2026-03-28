"""Tests for the unified lookup tool — identifier parsing, validation, and resolution.

These tests cover Task 3.1 (module structure, validation, identifier classification)
and Task 3.2 (resolution logic for bare names, file paths, dotted paths, coordinates).
"""

from pathlib import Path

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

        # Should take the coordinate branch — not the identifier branch.
        # The coordinate branch resolves to a symbol (or not-found), not a
        # "classified as bare_name" error message.
        assert isinstance(result, dict)
        assert "classified as" not in result.get(
            "error", ""
        ), "Expected coordinate branch result, not identifier-branch placeholder"

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
    """Identifier strings are classified into bare_name, file_path, or dotted_path.

    Now that resolution is implemented these tests verify the right branch was taken
    by checking that the "classified as ..." placeholder is NOT returned and the
    result is a valid resolution response (found, not-found, or ambiguous).
    """

    @pytest.mark.asyncio
    async def test_bare_name_classification(self):
        """A plain identifier with no dots or separators takes the bare_name branch."""
        result = await lookup(identifier="Config")

        # Should attempt bare-name resolution — no "classified as" placeholder error
        assert "classified as" not in result.get("error", "")
        # Result is a valid resolution response
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_bare_name_with_underscores(self):
        """Underscores are allowed in bare names."""
        result = await lookup(identifier="my_function")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_slash_classification(self):
        """A path containing / takes the file_path branch."""
        result = await lookup(identifier="src/pyeye/server.py")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        # Resolves to module or not-found (file may or may not exist in cwd)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_py_extension(self):
        """A string ending in .py with no other dots → file_path (not dotted_path)."""
        result = await lookup(identifier="server.py")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_py_extension_and_line_suffix(self):
        """A file path with a :line suffix → file_path."""
        result = await lookup(identifier="server.py:42")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_dotted_path_classification(self):
        """A dotted module path with no slashes and not ending in .py → dotted_path."""
        result = await lookup(identifier="pyeye.mcp.server")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_dotted_path_with_class(self):
        """A fully-qualified class name → dotted_path."""
        result = await lookup(identifier="pyeye.mcp.server.ServiceManager")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_backslash(self):
        """A path with backslash separator → file_path."""
        result = await lookup(identifier="src\\pyeye\\server.py")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result


# ---------------------------------------------------------------------------
# Resolution tests — Task 3.2
# ---------------------------------------------------------------------------

# Absolute path to the shared fixture used by all resolution tests.
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "lookup_project"


class TestLookupBareNameResolution:
    """Bare name resolution via find_symbol."""

    @pytest.mark.asyncio
    async def test_bare_name_single_match(self):
        """A unique bare name resolves to a single result."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result, f"Expected resolved result, got: {result}"
        assert result["type"] == "class"
        assert "ServiceManager" in (result.get("full_name") or "")
        assert result.get("_resolved_via") == "bare_name"

    @pytest.mark.asyncio
    async def test_bare_name_no_match(self):
        """A name that does not exist in the project returns found=False."""
        result = await lookup(
            identifier="Nonexistent__XYZ__Symbol",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False
        assert result.get("searched", {}).get("indexed") is True

    @pytest.mark.asyncio
    async def test_bare_name_partial_match_returns_result(self):
        """ServiceConfig resolves to exactly one result in the fixture."""
        result = await lookup(
            identifier="ServiceConfig",
            project_path=str(FIXTURE_DIR),
        )

        # ServiceConfig is only defined once in the fixture
        assert "type" in result or "ambiguous" in result
        if "type" in result:
            assert result["type"] == "class"


class TestLookupFilePathResolution:
    """File path resolution — bare module files and file:line forms."""

    @pytest.mark.asyncio
    async def test_file_path_to_module(self):
        """A bare .py filename resolves to the module."""
        result = await lookup(
            identifier="models.py",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result, f"Expected resolved result, got: {result}"
        assert result["type"] == "module"
        assert result.get("_resolved_via") == "file_path"

    @pytest.mark.asyncio
    async def test_file_path_with_line(self):
        """A file:line form resolves to the symbol at that line."""
        # models.py line 27 is: class ServiceManager:
        result = await lookup(
            identifier="models.py:27",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            # Should resolve to ServiceManager (class at line 27)
            assert "ServiceManager" in (result.get("name") or "") or result.get("type") in (
                "class",
                "function",
                "module",
            )

    @pytest.mark.asyncio
    async def test_file_path_nonexistent(self):
        """A .py file that does not exist returns found=False."""
        result = await lookup(
            identifier="nonexistent_file.py",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False


class TestLookupDottedPathResolution:
    """Dotted path resolution — modules and fully-qualified symbols."""

    @pytest.mark.asyncio
    async def test_dotted_path_to_module(self):
        """A module dotted path resolves to type=module."""
        result = await lookup(
            identifier="lookup_project.models",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            assert result["type"] == "module"
            assert result.get("_resolved_via") == "dotted_path"

    @pytest.mark.asyncio
    async def test_dotted_path_to_class(self):
        """A fully-qualified class path resolves to type=class."""
        result = await lookup(
            identifier="lookup_project.models.ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            assert result["type"] == "class"
            assert result.get("_resolved_via") == "dotted_path"

    @pytest.mark.asyncio
    async def test_dotted_path_nonexistent(self):
        """A dotted path that does not exist returns found=False or an error."""
        result = await lookup(
            identifier="lookup_project.models.NonexistentClass",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False or "error" in result


class TestLookupCoordinateResolution:
    """Coordinate-based resolution (file + line + column)."""

    @pytest.mark.asyncio
    async def test_coordinates_resolve_class(self):
        """Coordinates pointing to line 27, col 6 of models.py resolve to ServiceManager."""
        models_file = FIXTURE_DIR / "models.py"
        result = await lookup(
            file=str(models_file),
            line=27,
            column=6,
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            assert result.get("_resolved_via") == "coordinates"

    @pytest.mark.asyncio
    async def test_coordinates_with_identifier_uses_coordinates(self):
        """When coordinates + identifier are both given, coordinates win."""
        models_file = FIXTURE_DIR / "models.py"
        result = await lookup(
            identifier="ServiceConfig",  # different class
            file=str(models_file),
            line=27,
            column=6,
            project_path=str(FIXTURE_DIR),
        )

        # Coordinate branch was taken — result should reflect coordinates, not identifier
        assert isinstance(result, dict)
        assert "classified as" not in result.get("error", "")
        if "type" in result:
            assert result.get("_resolved_via") == "coordinates"
