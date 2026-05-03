"""Tests for the resolve(identifier) operation — Task 2.2.

Fixture layout
--------------
tests/fixtures/resolve_project/
  mypackage/
    __init__.py           # re-exports Widget from _core.widgets
    helpers.py            # defines Widget (second, ambiguous definition)
    _core/
      __init__.py         # empty
      widgets.py          # defines Widget (canonical) and Config (unique)

Known-correct canonical handle for Widget: ``mypackage._core.widgets.Widget``
Public re-export path: ``mypackage.Widget``
Ambiguous bare name: ``Widget`` → two candidates in project

Test cases
----------
(a) Bare name with single project match → success result
(b) FQN dotted path → success result with canonical handle
(c) Re-exported path → collapses to canonical definition site
(d) File path with line → success result via position lookup
(e) File path without line → module handle
(f) Unresolved identifier → {found: false, reason: ...}
(g) Every success variant includes ``scope``
(h) Ambiguous bare name → candidates each carry kind, scope, location
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"
_RESOLVE_FIXTURE = _FIXTURE  # Alias used in some test helpers


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# (a) Bare name with a single project match → success
# ---------------------------------------------------------------------------


class TestBareNameSingleMatch:
    """A bare name that uniquely identifies one project symbol should return success."""

    @pytest.mark.asyncio
    async def test_unique_bare_name_returns_success(self, analyzer: JediAnalyzer) -> None:
        """Config appears in exactly one project file — resolve should succeed."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Config", analyzer)

        assert result["found"] is True
        assert "ambiguous" not in result
        assert "handle" in result
        assert result["handle"] == "mypackage._core.widgets.Config"

    @pytest.mark.asyncio
    async def test_single_match_includes_kind(self, analyzer: JediAnalyzer) -> None:
        """Single-match success must include a non-empty kind."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Config", analyzer)

        assert result["found"] is True
        assert "kind" in result
        assert result["kind"] == "class"


# ---------------------------------------------------------------------------
# (b) FQN dotted path → success
# ---------------------------------------------------------------------------


class TestFQNDottedPath:
    """A fully-qualified dotted name should resolve to its canonical handle."""

    @pytest.mark.asyncio
    async def test_fqn_resolves_to_canonical(self, analyzer: JediAnalyzer) -> None:
        """mypackage._core.widgets.Config resolves to the same canonical handle."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("mypackage._core.widgets.Config", analyzer)

        assert result["found"] is True
        assert "ambiguous" not in result
        assert result["handle"] == "mypackage._core.widgets.Config"

    @pytest.mark.asyncio
    async def test_fqn_includes_scope(self, analyzer: JediAnalyzer) -> None:
        """FQN result must include scope field — Task 2.1 contract."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("mypackage._core.widgets.Config", analyzer)

        assert result["found"] is True
        assert "scope" in result
        assert result["scope"] in ("project", "external")


# ---------------------------------------------------------------------------
# (c) Re-exported path collapses to canonical definition site
# ---------------------------------------------------------------------------


class TestReExportedPathCollapses:
    """A public re-export path should resolve to the definition site handle."""

    @pytest.mark.asyncio
    async def test_reexport_collapses_to_definition(self, analyzer: JediAnalyzer) -> None:
        """mypackage.Widget is re-exported; canonical is mypackage._core.widgets.Widget."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("mypackage.Widget", analyzer)

        assert result["found"] is True
        assert "ambiguous" not in result
        assert result["handle"] == "mypackage._core.widgets.Widget"

    @pytest.mark.asyncio
    async def test_reexport_result_includes_scope(self, analyzer: JediAnalyzer) -> None:
        """Re-export result must include scope."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("mypackage.Widget", analyzer)

        assert result["found"] is True
        assert "scope" in result


# ---------------------------------------------------------------------------
# (d) File path with line → symbol at that position
# ---------------------------------------------------------------------------


class TestFilePathWithLine:
    """src/foo.py:N should resolve to the symbol defined at that line."""

    @pytest.mark.asyncio
    async def test_file_with_line_resolves_to_symbol(self, analyzer: JediAnalyzer) -> None:
        """mypackage/_core/widgets.py:7 is 'class Widget' — should resolve to Widget."""
        from pyeye.mcp.operations.resolve import resolve

        widgets_path = (_FIXTURE / "mypackage" / "_core" / "widgets.py").as_posix()
        result = await resolve(f"{widgets_path}:7", analyzer)

        assert result["found"] is True
        assert "ambiguous" not in result
        assert "handle" in result
        # The resolved symbol at line 7 (class Widget)
        assert "Widget" in result["handle"]

    @pytest.mark.asyncio
    async def test_file_with_line_includes_scope(self, analyzer: JediAnalyzer) -> None:
        """File:line result must include scope."""
        from pyeye.mcp.operations.resolve import resolve

        widgets_path = (_FIXTURE / "mypackage" / "_core" / "widgets.py").as_posix()
        result = await resolve(f"{widgets_path}:7", analyzer)

        assert result["found"] is True
        assert "scope" in result


# ---------------------------------------------------------------------------
# (e) File path without line → module handle
# ---------------------------------------------------------------------------


class TestFilePathWithoutLine:
    """A bare file path (no :N) should resolve to the module handle."""

    @pytest.mark.asyncio
    async def test_file_path_resolves_to_module(self, analyzer: JediAnalyzer) -> None:
        """widgets.py without line → mypackage._core.widgets module handle."""
        from pyeye.mcp.operations.resolve import resolve

        widgets_path = (_FIXTURE / "mypackage" / "_core" / "widgets.py").as_posix()
        result = await resolve(widgets_path, analyzer)

        assert result["found"] is True
        assert "ambiguous" not in result
        assert result["handle"] == "mypackage._core.widgets"

    @pytest.mark.asyncio
    async def test_file_path_kind_is_module(self, analyzer: JediAnalyzer) -> None:
        """Module resolution should have kind='module'."""
        from pyeye.mcp.operations.resolve import resolve

        widgets_path = (_FIXTURE / "mypackage" / "_core" / "widgets.py").as_posix()
        result = await resolve(widgets_path, analyzer)

        assert result["found"] is True
        assert result["kind"] == "module"


# ---------------------------------------------------------------------------
# (f) Unresolved identifier → {found: false, reason: ...}
# ---------------------------------------------------------------------------


class TestUnresolvedIdentifier:
    """An identifier that cannot be resolved must return found=False with a reason."""

    @pytest.mark.asyncio
    async def test_unknown_dotted_name_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """Completely unknown identifier should return found=False."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("does_not_exist.Nowhere", analyzer)

        assert result["found"] is False
        assert "reason" in result
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    @pytest.mark.asyncio
    async def test_missing_file_path_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """A file path that doesn't exist should return found=False."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("/nonexistent/path/file.py", analyzer)

        assert result["found"] is False
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_not_found_reason_is_descriptive(self, analyzer: JediAnalyzer) -> None:
        """The reason string should be a known discriminating value."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("completely_unknown_module.UnknownClass", analyzer)

        assert result["found"] is False
        # Reason must be a non-empty string indicating what went wrong
        assert result["reason"] in (
            "unresolved",
            "file_not_found",
            "no_symbol_at_position",
            "invalid_identifier",
        )


# ---------------------------------------------------------------------------
# (g) Every success variant includes scope
# ---------------------------------------------------------------------------


class TestSuccessVariantsIncludeScope:
    """All success paths must include a scope field per the Task 2.1 contract."""

    @pytest.mark.asyncio
    async def test_bare_name_success_has_scope(self, analyzer: JediAnalyzer) -> None:
        """Bare name success must include scope."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Config", analyzer)

        assert result["found"] is True
        assert "scope" in result
        assert result["scope"] in ("project", "external")

    @pytest.mark.asyncio
    async def test_config_is_project_scope(self, analyzer: JediAnalyzer) -> None:
        """A class defined in the fixture project should have scope='project'."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Config", analyzer)

        assert result["found"] is True
        assert result["scope"] == "project"


# ---------------------------------------------------------------------------
# (h) Ambiguous bare name → candidates carry kind, scope, location
# ---------------------------------------------------------------------------


class TestAmbiguousBareName:
    """A bare name matching multiple project symbols should return an ambiguous result."""

    @pytest.mark.asyncio
    async def test_ambiguous_bare_name_returns_ambiguous(self, analyzer: JediAnalyzer) -> None:
        """Widget exists in both _core.widgets and helpers — should be ambiguous."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Widget", analyzer)

        # Should be ambiguous (multiple matches)
        assert result["found"] is True
        assert result.get("ambiguous") is True
        assert "candidates" in result
        assert len(result["candidates"]) >= 2

    @pytest.mark.asyncio
    async def test_ambiguous_candidates_carry_required_fields(self, analyzer: JediAnalyzer) -> None:
        """Each candidate must carry handle, kind, scope, and location."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Widget", analyzer)

        assert result["found"] is True
        assert result.get("ambiguous") is True

        for candidate in result["candidates"]:
            assert "handle" in candidate, f"Missing 'handle' in {candidate}"
            assert "kind" in candidate, f"Missing 'kind' in {candidate}"
            assert "scope" in candidate, f"Missing 'scope' in {candidate}"
            assert "location" in candidate, f"Missing 'location' in {candidate}"
            # Validate location shape
            loc = candidate["location"]
            assert "file" in loc
            assert "line_start" in loc
            assert "line_end" in loc
            assert isinstance(loc["line_start"], int)
            assert isinstance(loc["line_end"], int)

    @pytest.mark.asyncio
    async def test_ambiguous_candidates_are_deterministically_ordered(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Candidates must be sorted by (scope, file, line_start) ascending.

        project < external, then alphabetical by file, then ascending line.
        """
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Widget", analyzer)

        assert result["found"] is True
        assert result.get("ambiguous") is True
        candidates = result["candidates"]
        assert len(candidates) >= 2

        # Verify ordering: project before external
        scopes = [c["scope"] for c in candidates]
        for i in range(len(scopes) - 1):
            if scopes[i] == "external" and scopes[i + 1] == "project":
                pytest.fail(
                    f"external candidate appears before project at position {i}: " f"{scopes}"
                )

        # Within same scope, verify alphabetical by file then ascending line
        project_candidates = [c for c in candidates if c["scope"] == "project"]
        for i in range(len(project_candidates) - 1):
            loc_a = project_candidates[i]["location"]
            loc_b = project_candidates[i + 1]["location"]
            key_a = (loc_a["file"], loc_a["line_start"])
            key_b = (loc_b["file"], loc_b["line_start"])
            assert key_a <= key_b, f"Candidates not sorted: {key_a} > {key_b}"

    @pytest.mark.asyncio
    async def test_ambiguous_candidates_have_valid_scopes(self, analyzer: JediAnalyzer) -> None:
        """All candidates must have scope in ('project', 'external')."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("Widget", analyzer)

        assert result["found"] is True
        for candidate in result["candidates"]:
            assert candidate["scope"] in (
                "project",
                "external",
            ), f"Invalid scope: {candidate['scope']}"


# ---------------------------------------------------------------------------
# Identifier form parser (unit tests for the helper)
# ---------------------------------------------------------------------------


class TestIdentifierFormParser:
    """Unit tests for the _parse_identifier helper."""

    def test_file_with_line(self) -> None:
        """Path:int should be detected as file_with_line."""
        from pyeye.mcp.operations.resolve import _parse_identifier

        form = _parse_identifier("/src/foo.py:42")
        assert form["kind"] == "file_with_line"
        assert form["path"] == "/src/foo.py"
        assert form["line"] == 42

    def test_file_without_line(self) -> None:
        """A .py path without colon-int should be file_only."""
        from pyeye.mcp.operations.resolve import _parse_identifier

        form = _parse_identifier("/src/foo.py")
        assert form["kind"] == "file_only"
        assert form["path"] == "/src/foo.py"

    def test_file_with_slash(self) -> None:
        """A path with / (no .py extension) should be file_only."""
        from pyeye.mcp.operations.resolve import _parse_identifier

        form = _parse_identifier("src/subdir/module")
        assert form["kind"] == "file_only"

    def test_dotted_name(self) -> None:
        """A dotted name without / or \\ should be dotted_name."""
        from pyeye.mcp.operations.resolve import _parse_identifier

        form = _parse_identifier("a.b.c.Config")
        assert form["kind"] == "dotted_name"
        assert form["name"] == "a.b.c.Config"

    def test_bare_name(self) -> None:
        """A single identifier (no dots) should be bare_name."""
        from pyeye.mcp.operations.resolve import _parse_identifier

        form = _parse_identifier("Config")
        assert form["kind"] == "bare_name"
        assert form["name"] == "Config"


# ---------------------------------------------------------------------------
# Kind recovery for non-class dotted names
# ---------------------------------------------------------------------------


class TestKindRecovery:
    """Resolving a dotted name for a function must return kind='function', not 'class'."""

    @pytest.mark.asyncio
    async def test_function_dotted_name_returns_function_kind(self, analyzer: JediAnalyzer) -> None:
        """mypackage._core.widgets.make_widget is a function — kind must be 'function'."""
        from pyeye.mcp.operations.resolve import resolve

        result = await resolve("mypackage._core.widgets.make_widget", analyzer)

        assert result["found"] is True, f"Expected found=True, got: {result}"
        assert "ambiguous" not in result
        assert result["handle"] == "mypackage._core.widgets.make_widget"
        assert (
            result["kind"] == "function"
        ), f"Expected kind='function' for a factory function, got: {result['kind']!r}"


# ---------------------------------------------------------------------------
# Task 2.3: resolve_at(file, line, column) — position-based resolution
# ---------------------------------------------------------------------------

# Fixture coordinates (1-indexed line, 0-indexed column per Jedi convention):
#
#   widgets.py line 7: "class Widget:"
#     - column 6 → 'W' of Widget (the class name)
#     - column 0 → 'c' of class keyword
#   widgets.py line 1: '"""Widget implementation — the definition site.'
#     - column 3 → inside the docstring literal
#   use_widget.py line 11: "w = Widget()"
#     - column 4 → 'W' of Widget (use site)


class TestResolveAt:
    """Task 2.3: resolve_at(file, line, column) converts a position to a canonical handle."""

    # (a) Position on a known symbol → success with handle
    @pytest.mark.asyncio
    async def test_position_on_symbol_returns_success(self, analyzer: JediAnalyzer) -> None:
        """Pointing at the 'W' of 'class Widget' returns the canonical Widget handle."""
        from pyeye.mcp.operations.resolve import resolve_at

        widgets_path = str(_FIXTURE / "mypackage" / "_core" / "widgets.py")
        # Line 7: "class Widget:" — column 6 is 'W'
        result = await resolve_at(widgets_path, 7, 6, analyzer)

        assert result["found"] is True, f"Expected found=True, got: {result}"
        assert "ambiguous" not in result
        assert result["handle"] == "mypackage._core.widgets.Widget"
        assert result["kind"] == "class"
        assert "scope" in result
        assert result["scope"] == "project"

    # (b) Position on whitespace → no_symbol_at_position
    @pytest.mark.asyncio
    async def test_position_on_whitespace_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """Pointing at a blank line yields found=False, reason='no_symbol_at_position'."""
        from pyeye.mcp.operations.resolve import resolve_at

        widgets_path = str(_FIXTURE / "mypackage" / "_core" / "widgets.py")
        # Line 6 is blank (the blank line between the module docstring and class Widget)
        result = await resolve_at(widgets_path, 6, 0, analyzer)

        assert result["found"] is False
        assert result["reason"] == "no_symbol_at_position"

    # (c) Position on a literal → no_symbol_at_position
    @pytest.mark.asyncio
    async def test_position_on_literal_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """Pointing inside a string literal yields found=False, reason='no_symbol_at_position'."""
        from pyeye.mcp.operations.resolve import resolve_at

        widgets_path = str(_FIXTURE / "mypackage" / "_core" / "widgets.py")
        # Line 1: '"""Widget implementation — the definition site.'
        # Column 10 is inside the docstring literal (well past the opening quotes)
        result = await resolve_at(widgets_path, 1, 10, analyzer)

        assert result["found"] is False
        assert result["reason"] == "no_symbol_at_position"

    # (d) column=0 is valid — must NOT be treated as falsy
    @pytest.mark.asyncio
    async def test_column_zero_is_valid(self, analyzer: JediAnalyzer) -> None:
        """column=0 is a legitimate column (start of line); implementation must not use 'if column:'.

        Empirical Jedi behaviour at column=0 on ``class Widget:``
        ----------------------------------------------------------
        column=0 lands on the ``c`` of the ``class`` keyword.  Jedi's ``goto()`` at a
        bare keyword returns no definitions (the keyword has no ``full_name``), so the
        correct result is ``found=False, reason='no_symbol_at_position'``.

        Why this proves the truthiness-bug contract
        -------------------------------------------
        A buggy implementation using ``if column:`` would silently treat ``0`` as falsy
        and substitute a fallback column (e.g. the heuristic column 6, which is ``W`` of
        ``Widget``).  Column 6 *does* resolve successfully to Widget.  The two cases are
        therefore distinguishable:

        - column=0 correctly honoured  → ``found=False`` (keyword, no symbol)
        - column=0 silently replaced by 6 → ``found=True, handle='…Widget'``

        Asserting ``found is False`` with ``reason='no_symbol_at_position'`` proves that
        column=0 was passed through unchanged.  If the assertion ever becomes
        ``found=True``, it is a strong indicator of the truthiness bug (or a Jedi
        behaviour change that should be re-examined).
        """
        from pyeye.mcp.operations.resolve import resolve_at

        widgets_path = str(_FIXTURE / "mypackage" / "_core" / "widgets.py")
        # Line 7: "class Widget:" — column 0 is 'c' of the 'class' keyword.
        # Jedi returns no definitions for a bare keyword → correct outcome is not-found.
        result = await resolve_at(widgets_path, 7, 0, analyzer)

        # Column 0 must be accepted (no TypeError / crash) and treated as-is.
        # The correct Jedi outcome at the class keyword is no_symbol_at_position —
        # NOT the Widget class that would appear if column were silently moved to 6.
        assert result["found"] is False, (
            f"column=0 on the 'class' keyword should be not-found; "
            f"if found=True this likely indicates a truthiness bug (column 0 → column 6): {result}"
        )
        assert result["reason"] == "no_symbol_at_position"

    # (e) Use site (not definition) still returns canonical handle
    @pytest.mark.asyncio
    async def test_use_site_returns_canonical_handle(self, analyzer: JediAnalyzer) -> None:
        """Pointing at a Widget usage in use_widget.py returns the definition-site handle."""
        from pyeye.mcp.operations.resolve import resolve_at

        use_widget_path = str(_FIXTURE / "mypackage" / "use_widget.py")
        # Line 11: "w = Widget()" — column 4 is 'W' of Widget (use site)
        result = await resolve_at(use_widget_path, 11, 4, analyzer)

        assert result["found"] is True, f"Expected found=True at use site, got: {result}"
        assert "ambiguous" not in result
        # Must resolve to the definition site, not the use site
        assert result["handle"] == "mypackage._core.widgets.Widget"

    @pytest.mark.asyncio
    async def test_kind_recovery_via_canonical_fallback(self, analyzer: JediAnalyzer) -> None:
        """When find_symbol returns no match, _kind_for_canonical recovers kind
        by re-deriving from the canonical handle's definition file.

        Forces the fallback path: stub find_symbol to return nothing, so
        _resolve_dotted_name cannot get kind from the fast path and must
        call _kind_for_canonical instead.
        """
        from pyeye.mcp.operations.resolve import resolve

        # Force the fallback: stub find_symbol to return nothing
        with patch.object(analyzer, "find_symbol", new=AsyncMock(return_value=[])):
            result = await resolve("mypackage._core.widgets.make_widget", analyzer)

        assert result["found"] is True, f"Expected found=True, got: {result}"
        assert result["handle"] == "mypackage._core.widgets.make_widget"
        assert (
            result["kind"] == "function"
        ), f"_kind_for_canonical fallback should recover 'function', got: {result['kind']!r}"

    @pytest.mark.asyncio
    async def test_kind_for_canonical_bare_module_returns_module(
        self, analyzer: JediAnalyzer
    ) -> None:
        """A bare module name (no dot in handle) returns kind='module'."""
        from pyeye.mcp.operations.resolve import _kind_for_canonical

        kind = _kind_for_canonical("mypackage", analyzer)
        assert kind == "module"

    @pytest.mark.asyncio
    async def test_kind_for_canonical_nonexistent_module_returns_variable(
        self, analyzer: JediAnalyzer
    ) -> None:
        """A handle whose module file cannot be found returns kind='variable'."""
        from pyeye.mcp.operations.resolve import _kind_for_canonical

        kind = _kind_for_canonical("nonexistent_pkg.some.Symbol", analyzer)
        assert kind == "variable"


# ---------------------------------------------------------------------------
# Identifier form parser — edge cases
# ---------------------------------------------------------------------------


class TestIdentifierFormParserEdgeCases:
    """Additional edge-case tests for _parse_identifier."""

    def test_dotted_name_with_colon_integer_classifies_as_dotted(self) -> None:
        """A dotted FQN with a colon-line suffix is NOT a file:line — it's a dotted name.

        The file:line regex matches ``mypackage.Widget:42`` but the path guard
        rejects it (no ``/``, ``\\``, or ``.py`` ending) so it falls through to
        dotted_name classification.  A future regex change could silently break this.
        """
        from pyeye.mcp.operations.resolve import _parse_identifier

        result = _parse_identifier("mypackage.Widget:42")
        assert result["kind"] == "dotted_name"
        # The full string is preserved as the name (will fail resolution gracefully later)
        assert result["name"] == "mypackage.Widget:42"


# ---------------------------------------------------------------------------
# Internal helper coverage — error paths and edge cases
# ---------------------------------------------------------------------------


class TestNormaliseKind:
    """Unit tests for the _normalise_kind helper."""

    def test_none_returns_variable(self) -> None:
        """None jedi_type maps to 'variable'."""
        from pyeye.mcp.operations.resolve import _normalise_kind

        assert _normalise_kind(None) == "variable"

    def test_unknown_type_returns_itself(self) -> None:
        """An unknown type string is passed through unchanged."""
        from pyeye.mcp.operations.resolve import _normalise_kind

        assert _normalise_kind("some_new_jedi_type") == "some_new_jedi_type"

    def test_class_maps_correctly(self) -> None:
        from pyeye.mcp.operations.resolve import _normalise_kind

        assert _normalise_kind("class") == "class"

    def test_statement_maps_to_variable(self) -> None:
        from pyeye.mcp.operations.resolve import _normalise_kind

        assert _normalise_kind("statement") == "variable"


class TestResolveBareNameErrorPaths:
    """Error-path coverage for _resolve_bare_name."""

    @pytest.mark.asyncio
    async def test_find_symbol_raises_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """When find_symbol raises, _resolve_bare_name returns not-found."""
        from pyeye.mcp.operations.resolve import _resolve_bare_name

        with patch.object(analyzer, "find_symbol", side_effect=RuntimeError("boom")):
            result = await _resolve_bare_name("Config", analyzer)

        assert result["found"] is False
        assert result["reason"] == "unresolved"

    @pytest.mark.asyncio
    async def test_matches_without_full_name_returns_not_found(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Matches that lack full_name are filtered out — returns not-found."""
        from pyeye.mcp.operations.resolve import _resolve_bare_name

        with patch.object(
            analyzer,
            "find_symbol",
            new=AsyncMock(return_value=[{"name": "Config", "file": "x.py"}]),
        ):
            result = await _resolve_bare_name("Config", analyzer)

        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_empty_matches_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """Empty find_symbol results return not-found."""
        from pyeye.mcp.operations.resolve import _resolve_bare_name

        with patch.object(analyzer, "find_symbol", new=AsyncMock(return_value=[])):
            result = await _resolve_bare_name("Config", analyzer)

        assert result["found"] is False


class TestHandleToFile:
    """Unit tests for the _handle_to_file helper."""

    def test_single_component_handle_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A Handle with no dot (bare module) returns None — no module part to look up."""
        from pyeye.handle import Handle
        from pyeye.mcp.operations.resolve import _handle_to_file

        result = _handle_to_file(Handle("mypackage"), analyzer)
        assert result is None

    def test_known_handle_returns_posix_path(self, analyzer: JediAnalyzer) -> None:
        """A valid handle returns a posix-formatted path string."""
        from pyeye.handle import Handle
        from pyeye.mcp.operations.resolve import _handle_to_file

        result = _handle_to_file(Handle("mypackage._core.widgets.Widget"), analyzer)
        assert result is not None
        assert "/" in result  # posix path
        assert not result.startswith("\\")


class TestResolveFileLineErrorPaths:
    """Error-path coverage for _resolve_file_line."""

    @pytest.mark.asyncio
    async def test_nonexistent_file_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """A file path that does not exist returns file_not_found."""
        from pyeye.mcp.operations.resolve import _resolve_file_line

        result = await _resolve_file_line(Path("/nonexistent/path/file.py"), 1, analyzer)
        assert result["found"] is False
        assert result["reason"] == "file_not_found"

    @pytest.mark.asyncio
    async def test_goto_raises_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """When script.goto() raises, returns no_symbol_at_position."""
        import jedi

        from pyeye.mcp.operations.resolve import _resolve_file_line

        widgets_path = _FIXTURE / "mypackage" / "_core" / "widgets.py"

        with patch.object(jedi.Script, "goto", side_effect=RuntimeError("jedi fail")):
            result = await _resolve_file_line(widgets_path, 7, analyzer)

        assert result["found"] is False
        assert result["reason"] == "no_symbol_at_position"


class TestResolveFileOnlyErrorPaths:
    """Error-path coverage for _resolve_file_only."""

    @pytest.mark.asyncio
    async def test_nonexistent_file_returns_not_found(self, analyzer: JediAnalyzer) -> None:
        """A file path that does not exist returns file_not_found."""
        from pyeye.mcp.operations.resolve import _resolve_file_only

        result = await _resolve_file_only(Path("/nonexistent/file.py"), analyzer)
        assert result["found"] is False
        assert result["reason"] == "file_not_found"

    @pytest.mark.asyncio
    async def test_file_with_no_module_path_returns_not_found(
        self, analyzer: JediAnalyzer, tmp_path: Path
    ) -> None:
        """A file that exists but cannot be mapped to a module returns unresolved."""
        from pyeye.mcp.operations.resolve import _resolve_file_only

        # File outside project root — _get_import_path_for_file returns None/empty
        temp_file = tmp_path / "orphan.py"
        temp_file.write_text("x = 1")
        result = await _resolve_file_only(temp_file, analyzer)
        assert result["found"] is False
        assert result["reason"] == "unresolved"


class TestFindSymbolColumnOnLine:
    """Unit tests for the _find_symbol_column_on_line helper."""

    def test_out_of_range_line_returns_zero(self, tmp_path: Path) -> None:
        """A line number beyond the file's last line returns 0."""
        from pyeye.mcp.operations.resolve import _find_symbol_column_on_line

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n")
        assert _find_symbol_column_on_line(f, 999) == 0

    def test_zero_line_returns_zero(self, tmp_path: Path) -> None:
        """Line 0 is out of range (1-indexed), returns 0."""
        from pyeye.mcp.operations.resolve import _find_symbol_column_on_line

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n")
        assert _find_symbol_column_on_line(f, 0) == 0

    def test_empty_line_returns_zero(self, tmp_path: Path) -> None:
        """A line containing only whitespace returns 0."""
        from pyeye.mcp.operations.resolve import _find_symbol_column_on_line

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n   \ny = 2\n")
        assert _find_symbol_column_on_line(f, 2) == 0

    def test_exception_returns_zero(self) -> None:
        """An unreadable path returns 0 (exception absorbed)."""
        from pyeye.mcp.operations.resolve import _find_symbol_column_on_line

        result = _find_symbol_column_on_line(Path("/nonexistent/path.py"), 1)
        assert result == 0

    def test_class_keyword_skipped(self, tmp_path: Path) -> None:
        """'class' keyword is skipped to land on the class name."""
        from pyeye.mcp.operations.resolve import _find_symbol_column_on_line

        f = tmp_path / "sample.py"
        f.write_text("class MyClass:\n    pass\n")
        col = _find_symbol_column_on_line(f, 1)
        # "class " is 6 chars, so column should be 6
        assert col == 6

    def test_def_keyword_skipped(self, tmp_path: Path) -> None:
        """'def' keyword is skipped to land on the function name."""
        from pyeye.mcp.operations.resolve import _find_symbol_column_on_line

        f = tmp_path / "sample.py"
        f.write_text("def my_func():\n    pass\n")
        col = _find_symbol_column_on_line(f, 1)
        # "def " is 4 chars
        assert col == 4
