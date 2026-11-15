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
    _collect_re_exports_impl,
    _is_valid_handle,
    _scan_package_for_handle,
    collect_re_exports,
)
from pyeye.handle import Handle
from tests.utils.resolver_helpers import canonical_handle

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "canonicalization_basic"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the canonicalization_basic fixture project."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# (a) Bare definition resolves to itself
# ---------------------------------------------------------------------------


class TestBareDefinitionIsCanonical:
    """Canonicalization (resolver.resolve_handle) of the definition site should be idempotent."""

    @pytest.mark.asyncio
    async def test_definition_site_resolves_to_itself(self, analyzer: JediAnalyzer) -> None:
        """package._impl.config.Config is the definition site — must return the same handle."""
        result = canonical_handle("package._impl.config.Config", analyzer)
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
        result = canonical_handle("package.Config", analyzer)
        assert result is not None, "Expected a Handle, got None for re-export path"
        assert result == Handle(
            "package._impl.config.Config"
        ), f"Expected canonical definition-site handle, got {result!r}"


# ---------------------------------------------------------------------------
# (c) Unresolved name returns None — does not raise
# ---------------------------------------------------------------------------


class TestUnresolvedNameReturnsNone:
    """Canonicalization must return None for unknown identifiers, never raise."""

    @pytest.mark.asyncio
    async def test_completely_unknown_returns_none(self, analyzer: JediAnalyzer) -> None:
        result = canonical_handle("does_not_exist.Nowhere", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_partial_path_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A module that exists but the leaf symbol does not."""
        result = canonical_handle("package.NonExistentClass", analyzer)
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
    """Boundary conditions and error-path coverage for canonicalization (resolver.resolve_handle)."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(self, analyzer: JediAnalyzer) -> None:
        """An empty identifier string is invalid and must return None without raising."""
        # Empty string is not a valid identifier (split gives [''] — symbol_name='')
        result = canonical_handle("", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_trailing_dot_returns_none(self, analyzer: JediAnalyzer) -> None:
        """An identifier ending in a dot produces an empty symbol_name — return None."""
        # "package." splits to ["package", ""] — symbol_name="" → None
        result = canonical_handle("package.", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_single_word_module_not_found_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A bare name that doesn't exist in the project returns None."""
        result = canonical_handle("nonexistent_module_xyz", analyzer)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_does_not_raise_on_bad_input(self, analyzer: JediAnalyzer) -> None:
        """Canonicalization never raises regardless of input."""
        # Try a few pathological inputs
        for bad_input in ["", ".", "...", "a..b", ".leading"]:
            try:
                result = canonical_handle(bad_input, analyzer)
                # May return None or a value — either is acceptable
                assert result is None or isinstance(result, Handle)
            except Exception as exc:
                raise AssertionError(
                    f"canonicalization raised for input {bad_input!r}: {exc}"
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
    async def test_collect_re_exports_propagates_internal_error(
        self, analyzer: JediAnalyzer
    ) -> None:
        """An internal failure propagates (#704): ``[]`` would claim "measured, none".

        ``inspect`` catches it and leaves ``re_exports`` absent (unknown).
        """
        with (
            patch(
                "pyeye.canonicalization._collect_re_exports_impl",
                side_effect=RuntimeError("unexpected internal error"),
            ),
            pytest.raises(RuntimeError, match="unexpected internal error"),
        ):
            await collect_re_exports(Handle("package._impl.config.Config"), analyzer)


# ---------------------------------------------------------------------------
# Project-search fallback path (_resolve_via_project_search)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# External (stdlib / site-packages) re-exports — #529
# ---------------------------------------------------------------------------


class TestExternalReExportCanonicalizes:
    """External re-export paths collapse to their definition site (#529).

    External modules are not project files, so ``find_module_file`` misses them;
    canonicalization must follow the import the way ``resolve`` does. Expected
    handles come from the runtime ``__module__``, so the tests hold on every
    Python version (``pathlib.Path`` moved to ``pathlib._local`` in 3.13).
    """

    @pytest.mark.asyncio
    async def test_star_import_reexport(self, analyzer: JediAnalyzer) -> None:
        """asyncio/__init__.py re-exports Queue via ``from .queues import *``."""
        import asyncio

        result = canonical_handle("asyncio.Queue", analyzer)
        assert result == Handle(f"{asyncio.Queue.__module__}.Queue")

    @pytest.mark.asyncio
    async def test_explicit_reexport(self, analyzer: JediAnalyzer) -> None:
        """json/__init__.py re-exports JSONDecoder via ``from .decoder import ...``."""
        import json

        result = canonical_handle("json.JSONDecoder", analyzer)
        assert result == Handle(f"{json.JSONDecoder.__module__}.JSONDecoder")

    @pytest.mark.asyncio
    async def test_pathlib_path_follows_python_version_layout(self, analyzer: JediAnalyzer) -> None:
        """pathlib.Path is defined in pathlib (<=3.12) or pathlib._local (3.13+)."""
        import pathlib

        result = canonical_handle("pathlib.Path", analyzer)
        assert result == Handle(f"{pathlib.Path.__module__}.Path")

    @pytest.mark.asyncio
    async def test_external_definition_site_is_idempotent(self, analyzer: JediAnalyzer) -> None:
        import asyncio

        canonical = f"{asyncio.Queue.__module__}.Queue"
        assert canonical_handle(canonical, analyzer) == Handle(canonical)

    @pytest.mark.asyncio
    async def test_unknown_external_leaf_returns_none(self, analyzer: JediAnalyzer) -> None:
        assert canonical_handle("json.NoSuchThingXyz", analyzer) is None


# ---------------------------------------------------------------------------
# Coverage — new helper functions and uncovered branches
# ---------------------------------------------------------------------------


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
    async def test_scan_propagates_a_jedi_error(self, analyzer: JediAnalyzer) -> None:
        """A file the scan can't read propagates (#704) rather than being skipped.

        Skipping it would return a re-export list that claims to be complete.
        """
        with (
            patch("pyeye.file_artifact_cache.get_script", side_effect=RuntimeError("jedi error")),
            pytest.raises(RuntimeError, match="jedi error"),
        ):
            await _scan_package_for_handle(
                "package._impl.config.Config",
                _FIXTURE / "package",
                analyzer,
            )

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
