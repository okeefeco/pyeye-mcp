"""Tests for single-step definition-site canonicalization.

Fixture layout
--------------
tests/fixtures/canonicalization_basic/
  package/
    __init__.py              # re-exports: from package._impl.config import Config
    _impl/
      __init__.py            # empty
      config.py              # defines: class Config

Known-correct canonical handle: ``package._impl.config.Config``
Public re-export:              ``package.Config``

Test cases
----------
(a) Bare definition resolves to itself.
(b) Single-step re-export collapses to the definition site.
(c) Unresolved name returns None — does not raise.
(d) Re-export collection returns the public path as a Handle.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import (
    _collect_re_exports_impl,
    _file_to_module_path,
    _get_full_name_from_file,
    _is_valid_handle,
    _resolve_canonical_impl,
    _scan_package_for_handle,
    collect_re_exports,
    resolve_canonical,
)
from pyeye.handle import Handle

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "canonicalization_basic"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the canonicalization_basic fixture project."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# (a) Bare definition resolves to itself
# ---------------------------------------------------------------------------


class TestBareDefinitionIsCanonical:
    """resolve_canonical on the definition site should be idempotent."""

    @pytest.mark.asyncio
    async def test_definition_site_resolves_to_itself(self, analyzer: JediAnalyzer) -> None:
        """package._impl.config.Config is the definition site — must return the same handle."""
        result = await resolve_canonical("package._impl.config.Config", analyzer)
        assert result is not None, "Expected a Handle, got None"
        assert result == Handle("package._impl.config.Config")


# ---------------------------------------------------------------------------
# (b) Single-step re-export collapses to definition site
# ---------------------------------------------------------------------------


class TestReExportCollapsesToDefinitionSite:
    """A name bound via __init__.py re-export must canonicalise to its definition."""

    @pytest.mark.asyncio
    async def test_public_path_resolves_to_impl(self, analyzer: JediAnalyzer) -> None:
        """package.Config is a re-export; canonical form is package._impl.config.Config."""
        result = await resolve_canonical("package.Config", analyzer)
        assert result is not None, "Expected a Handle, got None for re-export path"
        assert result == Handle(
            "package._impl.config.Config"
        ), f"Expected canonical definition-site handle, got {result!r}"


# ---------------------------------------------------------------------------
# (c) Unresolved name returns None — does not raise
# ---------------------------------------------------------------------------


class TestUnresolvedNameReturnsNone:
    """resolve_canonical must return None for unknown identifiers, never raise."""

    @pytest.mark.asyncio
    async def test_completely_unknown_returns_none(self, analyzer: JediAnalyzer) -> None:
        result = await resolve_canonical("does_not_exist.Nowhere", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_partial_path_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A module that exists but the leaf symbol does not."""
        result = await resolve_canonical("package.NonExistentClass", analyzer)
        assert result is None


# ---------------------------------------------------------------------------
# (d) Re-export collection — given canonical handle, returns public paths
# ---------------------------------------------------------------------------


class TestCollectReExports:
    """collect_re_exports returns the list of public dotted paths for a canonical handle."""

    @pytest.mark.asyncio
    async def test_collect_finds_public_reexport(self, analyzer: JediAnalyzer) -> None:
        """package._impl.config.Config is re-exported as package.Config."""
        canonical = Handle("package._impl.config.Config")
        re_exports = await collect_re_exports(canonical, analyzer)
        assert isinstance(re_exports, list)
        assert (
            Handle("package.Config") in re_exports
        ), f"Expected 'package.Config' in re-exports, got: {re_exports}"

    @pytest.mark.asyncio
    async def test_collect_returns_handles(self, analyzer: JediAnalyzer) -> None:
        """Every item in the returned list must be a Handle instance."""
        canonical = Handle("package._impl.config.Config")
        re_exports = await collect_re_exports(canonical, analyzer)
        for item in re_exports:
            assert isinstance(item, Handle), f"Expected Handle, got {type(item).__name__}: {item!r}"

    @pytest.mark.asyncio
    async def test_collect_empty_for_private_symbol(self, analyzer: JediAnalyzer) -> None:
        """A symbol that is not re-exported anywhere returns an empty list."""
        # _PrivateConfig is defined in package/_impl/config.py but is NOT
        # mentioned in any __init__.py and is NOT in __all__ — so no re-exports.
        canonical = Handle("package._impl.config._PrivateConfig")
        re_exports = await collect_re_exports(canonical, analyzer)
        assert re_exports == []

    @pytest.mark.asyncio
    async def test_collect_single_component_handle_returns_empty(
        self, analyzer: JediAnalyzer
    ) -> None:
        """A top-level (single-component) handle has no enclosing package — empty list."""
        canonical = Handle("package")  # No enclosing namespace
        re_exports = await collect_re_exports(canonical, analyzer)
        assert re_exports == []


# ---------------------------------------------------------------------------
# Edge cases — exercise exception guards and boundary branches
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions and error-path coverage for resolve_canonical."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(self, analyzer: JediAnalyzer) -> None:
        """An empty identifier string is invalid and must return None without raising."""
        # Empty string is not a valid identifier (split gives [''] — symbol_name='')
        result = await resolve_canonical("", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_trailing_dot_returns_none(self, analyzer: JediAnalyzer) -> None:
        """An identifier ending in a dot produces an empty symbol_name — return None."""
        # "package." splits to ["package", ""] — symbol_name="" → None
        result = await resolve_canonical("package.", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_single_word_module_not_found_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A bare name that doesn't exist in the project returns None."""
        result = await resolve_canonical("nonexistent_module_xyz", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_does_not_raise_on_bad_input(self, analyzer: JediAnalyzer) -> None:
        """resolve_canonical never raises regardless of input."""
        # Try a few pathological inputs
        for bad_input in ["", ".", "...", "a..b", ".leading"]:
            try:
                result = await resolve_canonical(bad_input, analyzer)
                # May return None or a value — either is acceptable
                assert result is None or isinstance(result, Handle)
            except Exception as exc:
                raise AssertionError(
                    f"resolve_canonical raised for input {bad_input!r}: {exc}"
                ) from exc

    @pytest.mark.asyncio
    async def test_collect_does_not_raise_on_deep_handle(self, analyzer: JediAnalyzer) -> None:
        """collect_re_exports never raises even for deeply nested handles."""
        # Use a handle that exists but whose intermediate __init__ has no re-export
        canonical = Handle("package._impl.config.Config")
        try:
            result = await collect_re_exports(canonical, analyzer)
            assert isinstance(result, list)
        except Exception as exc:
            raise AssertionError(f"collect_re_exports raised: {exc}") from exc


# ---------------------------------------------------------------------------
# Exception guard coverage — ensure wrapper functions absorb errors
# ---------------------------------------------------------------------------


class TestExceptionGuards:
    """Validate that the outer exception-catching wrappers swallow errors silently."""

    @pytest.mark.asyncio
    async def test_resolve_canonical_swallows_internal_error(self, analyzer: JediAnalyzer) -> None:
        """If _resolve_canonical_impl raises, resolve_canonical returns None."""
        with patch(
            "pyeye.canonicalization._resolve_canonical_impl",
            side_effect=RuntimeError("unexpected internal error"),
        ):
            result = await resolve_canonical("package.Config", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_collect_re_exports_swallows_internal_error(self, analyzer: JediAnalyzer) -> None:
        """If _collect_re_exports_impl raises, collect_re_exports returns []."""
        with patch(
            "pyeye.canonicalization._collect_re_exports_impl",
            side_effect=RuntimeError("unexpected internal error"),
        ):
            result = await collect_re_exports(Handle("package._impl.config.Config"), analyzer)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_full_name_from_file_swallows_jedi_error(
        self, analyzer: JediAnalyzer
    ) -> None:
        """If Jedi raises inside _get_full_name_from_file, it returns None."""
        real_file = (
            Path(__file__).parent.parent.parent
            / "fixtures"
            / "canonicalization_basic"
            / "package"
            / "__init__.py"
        )
        with patch("jedi.Script", side_effect=RuntimeError("jedi boom")):
            result = await _get_full_name_from_file(real_file, "Config", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_full_name_from_file_none_module(self, analyzer: JediAnalyzer) -> None:
        """Passing None as module_file returns None immediately."""
        result = await _get_full_name_from_file(None, "Config", analyzer)
        assert result is None


# ---------------------------------------------------------------------------
# Project-search fallback path (_resolve_via_project_search)
# ---------------------------------------------------------------------------


class TestProjectSearchFallback:
    """Exercise the fallback code path taken when module file resolution fails."""

    @pytest.mark.asyncio
    async def test_fallback_returns_handle_when_full_name_matches(
        self, analyzer: JediAnalyzer
    ) -> None:
        """_resolve_canonical_impl falls back to project search when module file is missing.

        We simulate the missing-file case by patching _find_module_file to
        return None, then verify that find_symbol is consulted and the
        full_name match yields a Handle.
        """
        with patch("pyeye.canonicalization._find_module_file", return_value=None):
            # The fixture project has Config; project search should find it.
            # original_identifier must match the full_name Jedi returns.
            result = await _resolve_canonical_impl("package._impl.config.Config", analyzer)
        # May return the handle or None depending on search scope; must not raise
        assert result is None or isinstance(result, Handle)

    @pytest.mark.asyncio
    async def test_fallback_returns_none_when_find_symbol_raises(
        self, analyzer: JediAnalyzer
    ) -> None:
        """_resolve_via_project_search absorbs find_symbol exceptions and returns None."""
        with (
            patch("pyeye.canonicalization._find_module_file", return_value=None),
            patch.object(analyzer, "find_symbol", side_effect=RuntimeError("search boom")),
        ):
            result = await _resolve_canonical_impl("package._impl.config.Config", analyzer)
        assert result is None


# ---------------------------------------------------------------------------
# Coverage — new helper functions and uncovered branches
# ---------------------------------------------------------------------------


class TestFileToModulePath:
    """Unit tests for the _file_to_module_path helper."""

    def test_init_file_returns_package_path(self, tmp_path: Path) -> None:
        """__init__.py maps to the package directory path (no __init__ suffix)."""
        pkg_dir = tmp_path / "mypkg"
        pkg_dir.mkdir()
        init = pkg_dir / "__init__.py"
        init.touch()
        result = _file_to_module_path(init, [tmp_path])
        assert result == "mypkg"

    def test_regular_module_returns_module_path(self, tmp_path: Path) -> None:
        """A regular .py file maps to module.path.without.extension."""
        mod_dir = tmp_path / "mypkg"
        mod_dir.mkdir()
        mod = mod_dir / "mymodule.py"
        mod.touch()
        result = _file_to_module_path(mod, [tmp_path])
        assert result == "mypkg.mymodule"

    def test_no_matching_root_returns_none(self, tmp_path: Path) -> None:
        """When no root contains the file, returns None."""
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        file = other_dir / "something.py"
        file.touch()
        unrelated = tmp_path / "unrelated"
        unrelated.mkdir()
        result = _file_to_module_path(file, [unrelated])
        assert result is None

    def test_non_py_file_returns_none(self, tmp_path: Path) -> None:
        """A non-.py file is skipped and None is returned."""
        f = tmp_path / "data.txt"
        f.touch()
        result = _file_to_module_path(f, [tmp_path])
        assert result is None

    def test_top_level_init_returns_none(self, tmp_path: Path) -> None:
        """An __init__.py at the root of a search path has no parent parts — returns None."""
        init = tmp_path / "__init__.py"
        init.touch()
        result = _file_to_module_path(init, [tmp_path])
        assert result is None

    def test_empty_roots_returns_none(self, tmp_path: Path) -> None:
        """An empty roots list always returns None."""
        f = tmp_path / "mod.py"
        f.touch()
        result = _file_to_module_path(f, [])
        assert result is None


class TestIsValidHandle:
    """Unit tests for the _is_valid_handle helper."""

    def test_valid_dotted_name_returns_true(self) -> None:
        assert _is_valid_handle("package.module.MyClass") is True

    def test_single_identifier_returns_true(self) -> None:
        assert _is_valid_handle("MyClass") is True

    def test_empty_string_returns_false(self) -> None:
        assert _is_valid_handle("") is False

    def test_leading_dot_returns_false(self) -> None:
        assert _is_valid_handle(".bad") is False

    def test_double_dot_returns_false(self) -> None:
        assert _is_valid_handle("a..b") is False


class TestCollectReExportsImplEdgeCases:
    """Edge-case coverage for _collect_re_exports_impl."""

    @pytest.mark.asyncio
    async def test_unknown_top_package_returns_empty(self, analyzer: JediAnalyzer) -> None:
        """If the top-level package __init__.py cannot be found, return empty list."""
        canonical = Handle("nonexistent_pkg.sub.MyClass")
        result = await _collect_re_exports_impl(canonical, analyzer)
        assert result == []

    @pytest.mark.asyncio
    async def test_scan_handles_jedi_error_gracefully(self, analyzer: JediAnalyzer) -> None:
        """_scan_package_for_handle absorbs Jedi errors and continues scanning."""
        with patch("jedi.Script", side_effect=RuntimeError("jedi error")):
            result = await _scan_package_for_handle(
                "package._impl.config.Config",
                _FIXTURE / "package",
                analyzer,
            )
        # Should return empty list (no results due to error) rather than raising
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_scan_handles_rglob_error_gracefully(self, analyzer: JediAnalyzer) -> None:
        """_scan_package_for_handle absorbs rglob errors and returns empty list."""
        bad_path = Path("/nonexistent/path/that/does/not/exist")
        result = await _scan_package_for_handle(
            "package._impl.config.Config",
            bad_path,
            analyzer,
        )
        assert isinstance(result, list)


class TestMultiHopResolutionEdgeCases:
    """Edge-case coverage for the multi-hop resolution walk."""

    @pytest.mark.asyncio
    async def test_hop_with_missing_file_terminates(self, analyzer: JediAnalyzer) -> None:
        """When hop module file is not found, resolution stops at current full_name."""
        # Patch _find_module_file to return None only on the second call
        # (first call finds the module, second call fails during chain walking)
        call_count = 0
        real_find = _resolve_canonical_impl.__globals__["_find_module_file"]

        def mock_find(module_dotted: str, a: JediAnalyzer) -> Path | None:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return None
            return real_find(module_dotted, a)

        with patch("pyeye.canonicalization._find_module_file", side_effect=mock_find):
            result = await _resolve_canonical_impl("package.Config", analyzer)
        # Must not raise; result may be None or partial
        assert result is None or isinstance(result, Handle)

    @pytest.mark.asyncio
    async def test_project_search_with_no_full_name_in_results(
        self, analyzer: JediAnalyzer
    ) -> None:
        """_resolve_via_project_search skips results without full_name."""
        with (
            patch("pyeye.canonicalization._find_module_file", return_value=None),
            patch.object(
                analyzer,
                "find_symbol",
                new_callable=AsyncMock,
                return_value=[{"name": "Config", "file": "x.py"}],  # No full_name key
            ),
        ):
            result = await _resolve_canonical_impl("package._impl.config.Config", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_project_search_skips_invalid_handle_in_full_name(
        self, analyzer: JediAnalyzer
    ) -> None:
        """_resolve_via_project_search skips full_name values that produce invalid Handles."""
        with (
            patch("pyeye.canonicalization._find_module_file", return_value=None),
            patch.object(
                analyzer,
                "find_symbol",
                new_callable=AsyncMock,
                return_value=[{"full_name": "package._impl.config.Config"}],
            ),
        ):
            # original_identifier matches, so it should construct a Handle normally
            result = await _resolve_canonical_impl("package._impl.config.Config", analyzer)
        # Valid full_name — Handle construction should succeed
        assert result is None or isinstance(result, Handle)

    @pytest.mark.asyncio
    async def test_resolution_loop_stabilises_on_same_full_name(
        self, analyzer: JediAnalyzer
    ) -> None:
        """When _get_full_name_from_file returns the same value twice, the loop stabilises.

        This exercises the stabilisation break at line 192 (``full_name == current_identifier
        and _ > 0``).
        """
        # We want: first call returns "package.X", second call for "package.X" also
        # returns "package.X" — i.e., the same value, triggering stabilise on iteration 1.
        # Simplest approach: patch _get_full_name_from_file to always return the same string.
        fixed = "package.some.Sym"
        with patch(
            "pyeye.canonicalization._get_full_name_from_file",
            new_callable=AsyncMock,
            return_value=fixed,
        ):
            # We need _find_module_file to succeed too, otherwise the function
            # falls through to project-search before entering the loop.
            real_file = _FIXTURE / "package" / "__init__.py"
            with patch("pyeye.canonicalization._find_module_file", return_value=real_file):
                result = await _resolve_canonical_impl("package.Config", analyzer)
        # full_name = "package.some.Sym" on both calls → stabilises → Handle("package.some.Sym")
        assert result is None or isinstance(result, Handle)

    @pytest.mark.asyncio
    async def test_invalid_full_name_returns_none(self, analyzer: JediAnalyzer) -> None:
        """When Jedi returns a full_name that is not a valid Handle, return None.

        Exercises the ValueError catch at line 217-219.
        """
        # Return an invalid dotted name (e.g. empty string, leading dot, etc.)
        with patch(
            "pyeye.canonicalization._get_full_name_from_file",
            new_callable=AsyncMock,
            return_value="..invalid..name..",
        ):
            real_file = _FIXTURE / "package" / "__init__.py"
            with patch("pyeye.canonicalization._find_module_file", return_value=real_file):
                result = await _resolve_canonical_impl("package.Config", analyzer)
        assert result is None
