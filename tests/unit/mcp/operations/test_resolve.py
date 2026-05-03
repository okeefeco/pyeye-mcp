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

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"


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
