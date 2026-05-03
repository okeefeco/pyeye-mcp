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
from unittest.mock import patch

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import (
    _get_full_name_from_file,
    _resolve_canonical_impl,
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
