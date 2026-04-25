"""Tests for symbol-name-based resolution in find_references.

This test module is part of the TDD implementation for GitHub issue #316
(tool ergonomics improvements).  ALL tests in this file are expected to
FAIL or ERROR against the current implementation because the
``symbol_name`` parameter and the associated validation / resolution logic
have not been added yet.  That is intentional — these tests drive Task 2.2
(parameter changes & validation) and Task 2.3 (symbol resolution logic).

Expected failure modes against the unmodified server:
- TypeError: find_references() got an unexpected keyword argument 'symbol_name'
- TypeError: find_references() missing required positional arguments
"""

from pathlib import Path

import pytest

from pyeye.mcp.server import find_references

# ---------------------------------------------------------------------------
# Fixture paths (relative to this file so tests are location-independent)
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SYMBOL_REF_FIXTURE = _FIXTURES_DIR / "symbol_references"
_ALT_FIXTURE = _FIXTURES_DIR / "symbol_references_alt"


# ===========================================================================
# Validation tests
# ===========================================================================


class TestSymbolReferencesValidation:
    """Tests for input validation when calling find_references with symbol_name."""

    @pytest.mark.asyncio
    async def test_coordinates_take_precedence_over_symbol_name(self, tmp_path: Path):
        """When all three coordinates are supplied together with symbol_name,
        the coordinates should be used and symbol_name ignored.

        The result should be a list (not an error dict), confirming that the
        coordinate-based path was taken.

        NOTE: Currently errors with TypeError because symbol_name is not a
        recognised parameter.
        """
        # Create a minimal inline fixture so coordinates actually point at
        # something Jedi can analyse.
        sample = tmp_path / "sample.py"
        sample.write_text("""\
class MyClass:
    pass


obj = MyClass()
""")

        result = await find_references(
            file=sample.as_posix(),
            line=1,
            column=6,
            project_path=str(tmp_path),
            # symbol_name is supplied but coordinates are complete — coords win.
            symbol_name="MyClass",
        )

        assert isinstance(
            result, list
        ), f"Expected a list of references when coordinates are provided, got: {result}"

    @pytest.mark.asyncio
    async def test_partial_coordinates_error(self, tmp_path: Path):
        """Passing file + line but omitting column should return an error dict
        with 'Coordinates incomplete' in the message.

        NOTE: Currently errors with TypeError because symbol_name is not a
        recognised parameter and the required ``column`` argument is missing.
        """
        sample = tmp_path / "sample.py"
        sample.write_text("class Foo: pass\n")

        result = await find_references(
            file=sample.as_posix(),
            line=1,
            project_path=str(tmp_path),
            symbol_name="Foo",
            # column intentionally omitted to trigger partial-coordinate error
        )

        assert isinstance(
            result, dict
        ), f"Expected an error dict for partial coordinates, got: {result}"
        assert "error" in result, f"Expected 'error' key in result: {result}"
        assert (
            "Coordinates incomplete" in result["error"]
        ), f"Expected 'Coordinates incomplete' in error message, got: {result['error']}"

    @pytest.mark.asyncio
    async def test_no_args_error(self):
        """Calling find_references with neither coordinates nor symbol_name
        should return an error dict indicating both paths are unavailable.

        NOTE: Currently raises TypeError because the required positional
        arguments file/line/column are missing.
        """
        result = await find_references(
            project_path=".",
            # No file, line, column, and no symbol_name
        )

        assert isinstance(
            result, dict
        ), f"Expected an error dict when no args provided, got: {result}"
        assert "error" in result, f"Expected 'error' key in result: {result}"
        assert "Either symbol_name or file+line+column" in result["error"], (
            f"Expected 'Either symbol_name or file+line+column' in error, "
            f"got: {result['error']}"
        )


# ===========================================================================
# Resolution tests
# ===========================================================================


class TestSymbolReferencesResolution:
    """Tests for the symbol-name-to-coordinates resolution path."""

    @pytest.mark.asyncio
    async def test_single_match_returns_references(self):
        """When symbol_name resolves to exactly one definition, find_references
        should return a list of reference dicts.

        Uses the ``UniqueWidget`` class that appears only once in the
        symbol_references fixture project.

        NOTE: Currently errors with TypeError — symbol_name not yet supported.
        """
        result = await find_references(
            symbol_name="UniqueWidget",
            project_path=str(_SYMBOL_REF_FIXTURE),
        )

        assert isinstance(
            result, list
        ), f"Expected a list of references for unique symbol, got: {result}"
        assert len(result) > 0, "Expected at least one reference for UniqueWidget"
        # Each reference dict should have at minimum a 'file' key
        for ref in result:
            assert "file" in ref, f"Reference dict missing 'file' key: {ref}"

    @pytest.mark.asyncio
    async def test_no_match_returns_error(self):
        """When symbol_name matches no definition in the project, an error
        dict with 'No symbol found' should be returned.

        NOTE: Currently errors with TypeError — symbol_name not yet supported.
        """
        result = await find_references(
            symbol_name="NonexistentSymbol",
            project_path=str(_SYMBOL_REF_FIXTURE),
        )

        assert isinstance(
            result, dict
        ), f"Expected an error dict for unresolved symbol, got: {result}"
        assert "error" in result, f"Expected 'error' key in result: {result}"
        assert (
            "No symbol found" in result["error"]
        ), f"Expected 'No symbol found' in error message, got: {result['error']}"

    @pytest.mark.asyncio
    async def test_multiple_matches_returns_disambiguation(self):
        """When symbol_name matches more than one definition, the response
        should be a disambiguation dict with an 'error' string and a
        'matches' list.

        Uses ``Config`` which exists in both ``module_a.config`` and
        ``module_b.config`` in the symbol_references fixture project.

        Each match entry should include: name, type, file, line, column,
        full_name.

        NOTE: Currently errors with TypeError — symbol_name not yet supported.
        """
        result = await find_references(
            symbol_name="Config",
            project_path=str(_SYMBOL_REF_FIXTURE),
        )

        assert isinstance(
            result, dict
        ), f"Expected a disambiguation dict for ambiguous symbol, got: {result}"
        assert "error" in result, f"Expected 'error' key in result: {result}"
        assert "matches" in result, f"Expected 'matches' key in result: {result}"

        matches = result["matches"]
        assert isinstance(matches, list), f"Expected matches to be a list: {matches}"
        assert (
            len(matches) >= 2
        ), f"Expected at least 2 matches for ambiguous 'Config', got: {matches}"

        required_fields = {"name", "type", "file", "line", "column", "full_name"}
        for match in matches:
            missing = required_fields - set(match.keys())
            assert not missing, f"Match entry missing fields {missing}: {match}"

    @pytest.mark.asyncio
    async def test_builtin_symbol_returns_error(self):
        """When symbol_name resolves only to a built-in (no user-defined
        definition with a file path), an error dict containing 'built-in'
        should be returned.

        NOTE: Currently errors with TypeError — symbol_name not yet supported.
        """
        result = await find_references(
            symbol_name="int",
            project_path=str(_SYMBOL_REF_FIXTURE),
        )

        assert isinstance(
            result, dict
        ), f"Expected an error dict for built-in symbol, got: {result}"
        assert "error" in result, f"Expected 'error' key in result: {result}"
        assert (
            "built-in" in result["error"].lower()
        ), f"Expected 'built-in' in error message, got: {result['error']}"


# ===========================================================================
# Interaction tests
# ===========================================================================


class TestSymbolReferencesInteraction:
    """Tests for interactions between symbol_name and other parameters."""

    @pytest.mark.asyncio
    async def test_fields_does_not_filter_disambiguation_matches(self):
        """When symbol_name is ambiguous and fields is supplied, the
        disambiguation dict's 'matches' entries should NOT be filtered by
        fields — the caller needs all fields to make a meaningful choice.

        NOTE: Currently errors with TypeError — symbol_name not yet supported.
        """
        result = await find_references(
            symbol_name="Config",
            project_path=str(_SYMBOL_REF_FIXTURE),
            fields=["file", "line"],
        )

        # Should still be a disambiguation dict (not a field-filtered list)
        assert isinstance(
            result, dict
        ), f"Expected disambiguation dict even with fields param, got: {result}"
        assert "matches" in result, f"Expected 'matches' key in result: {result}"

        matches = result["matches"]
        # Each match must still carry the full set of fields needed for
        # disambiguation — not just the requested subset.
        required_fields = {"name", "type", "file", "line", "column", "full_name"}
        for match in matches:
            missing = required_fields - set(match.keys())
            assert not missing, (
                f"Disambiguation match should not be field-filtered; "
                f"missing fields {missing}: {match}"
            )

    @pytest.mark.asyncio
    async def test_include_definitions_false_with_symbol_name(self):
        """include_definitions=False should propagate through symbol_name
        resolution so that the definition itself is excluded from results.
        """
        # First get results WITH definitions to establish baseline
        with_defs = await find_references(
            symbol_name="UniqueWidget",
            project_path=str(_SYMBOL_REF_FIXTURE),
            include_definitions=True,
        )
        assert isinstance(with_defs, list), f"Expected list, got: {with_defs}"

        # Now get results WITHOUT definitions
        without_defs = await find_references(
            symbol_name="UniqueWidget",
            project_path=str(_SYMBOL_REF_FIXTURE),
            include_definitions=False,
        )
        assert isinstance(without_defs, list), f"Expected list, got: {without_defs}"

        # Without definitions should have fewer (or equal) results
        assert len(without_defs) <= len(with_defs), (
            f"include_definitions=False should not return more results than True: "
            f"{len(without_defs)} vs {len(with_defs)}"
        )

        # No result should be marked as a definition
        for ref in without_defs:
            assert not ref.get(
                "is_definition", False
            ), f"include_definitions=False should exclude definitions: {ref}"

    @pytest.mark.asyncio
    async def test_include_subclasses_with_symbol_name(self):
        """include_subclasses=True should work through the symbol_name
        resolution path — the resolved coordinates are passed on with the
        flag set, and the result should still be a list.

        NOTE: Currently errors with TypeError — symbol_name not yet supported.
        """
        result = await find_references(
            symbol_name="UniqueWidget",
            project_path=str(_SYMBOL_REF_FIXTURE),
            include_subclasses=True,
        )

        assert isinstance(
            result, list
        ), f"Expected a list of references with include_subclasses=True, got: {result}"

    @pytest.mark.asyncio
    async def test_fqn_resolves_without_disambiguation(self):
        """A fully qualified symbol_name like 'module_a.config.Config' should
        resolve to exactly one match and return references — not trigger
        disambiguation even though the short name 'Config' is ambiguous.
        """
        # Short name is ambiguous (2 Config classes)
        ambiguous = await find_references(
            symbol_name="Config",
            project_path=str(_SYMBOL_REF_FIXTURE),
        )
        assert (
            isinstance(ambiguous, dict) and "matches" in ambiguous
        ), f"Expected disambiguation for short name 'Config', got: {ambiguous}"

        # FQN should resolve unambiguously — use the full dotted path
        # including the package prefix (symbol_references.module_a.config.Config)
        result = await find_references(
            symbol_name="symbol_references.module_a.config.Config",
            project_path=str(_SYMBOL_REF_FIXTURE),
        )
        assert isinstance(result, list), f"Expected list of references for FQN, got: {result}"
        assert (
            len(result) > 0
        ), "Expected at least one reference for symbol_references.module_a.config.Config"

    @pytest.mark.asyncio
    async def test_project_path_forwarding(self):
        """symbol_name resolution should use project_path to scope the search.

        ``AltModel`` only exists in the alternate fixture project; it should
        NOT be found when searching the default symbol_references fixture, but
        SHOULD be found when project_path points to symbol_references_alt.

        NOTE: Currently errors with TypeError — symbol_name not yet supported.
        """
        result = await find_references(
            symbol_name="AltModel",
            project_path=str(_ALT_FIXTURE),
        )

        assert isinstance(result, list), (
            f"Expected a list of references when AltModel is found in alt project, "
            f"got: {result}"
        )
        assert (
            len(result) > 0
        ), "Expected at least one reference for AltModel in the alt fixture project"
        # All references should be inside the alt fixture directory
        for ref in result:
            if ref.get("file"):
                assert (
                    str(_ALT_FIXTURE) in ref["file"] or "models" in ref["file"]
                ), f"Reference file should be inside the alt fixture project: {ref['file']}"
