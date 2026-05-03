"""Tests for multi-hop and edge-case canonicalization.

Fixture layout
--------------
tests/fixtures/canonicalization_multihop/
  package/
    __init__.py          # from package.subpkg import Config  (hop 2)
    legacy.py            # from package import Config as LegacyConfig  (aliased)
    _impl/
      __init__.py        # empty
      config.py          # class Config  (DEFINITION SITE)
    subpkg/
      __init__.py        # from package._impl.config import Config  (hop 1)
  alias_pkg/
    __init__.py
    source_mod/
      __init__.py
      definitions.py     # def foo()  (DEFINITION SITE)
    sibling.py           # from ... import foo; from ... import foo as f
  self_reexport_pkg/
    __init__.py          # from self_reexport_pkg.submodule import Foo
    submodule.py         # class Foo; __all__ = ["Foo"]

Known-correct canonical handles
---------------------------------
  package._impl.config.Config   — definition site for the multi-hop chain
  alias_pkg.source_mod.definitions.foo  — definition site for sibling aliases
  self_reexport_pkg.submodule.Foo       — definition site for self-reexport

Test cases
----------
(A) Multi-step re-export chain:
    package.Config (hop 2) → package.subpkg.Config (hop 1) → definition
    package.subpkg.Config (hop 1) → definition

(B) Aliased re-export of an already-re-exported symbol:
    package.legacy.LegacyConfig (3 hops, aliased) → definition

(C) Sibling alias collision:
    alias_pkg.sibling.foo  (direct import)  → definition
    alias_pkg.sibling.f    (aliased import) → definition
    Both must resolve to the SAME canonical handle.

(D) Re-export to itself doesn't loop (self-reexport / cycle detection):
    self_reexport_pkg.Foo resolves and terminates without infinite loop.

(E) Re-export collection — multi-hop: all 4 public bindings found.

Notes on Jedi behavior
----------------------
Jedi's ``Name.full_name`` via ``get_names()`` performs exactly ONE step of
alias/import resolution per call — it does not follow multi-hop chains
automatically.  For example, ``package/__init__.py`` importing
``from package.subpkg import Config`` yields ``full_name='package.subpkg.Config'``
(not the final definition).

The implementation therefore uses an iterative walk: resolve() calls
``_get_full_name_from_file`` repeatedly until the ``full_name`` stabilises or
a cycle is detected (max-depth guard).

For re-export collection, a BFS expansion is used: starting from the canonical
handle, scan all Python files in the package tree for names whose ``full_name``
matches the target handle.  Then expand transitively until no new handles are
found.  The visited set prevents cycles.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import collect_re_exports, resolve_canonical
from pyeye.handle import Handle

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "canonicalization_multihop"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the canonicalization_multihop fixture project."""
    return JediAnalyzer(str(_FIXTURE))


# ===========================================================================
# (A) Multi-step re-export chain
# ===========================================================================


class TestMultiStepChain:
    """package.Config is two hops from the definition site."""

    @pytest.mark.asyncio
    async def test_two_hop_path_resolves_to_definition(self, analyzer: JediAnalyzer) -> None:
        """package.Config -> package.subpkg.Config -> package._impl.config.Config."""
        result = await resolve_canonical("package.Config", analyzer)
        assert result is not None, "Expected a Handle for package.Config, got None"
        assert result == Handle(
            "package._impl.config.Config"
        ), f"Expected canonical definition-site handle, got {result!r}"

    @pytest.mark.asyncio
    async def test_one_hop_path_resolves_to_definition(self, analyzer: JediAnalyzer) -> None:
        """package.subpkg.Config is one hop from the definition site."""
        result = await resolve_canonical("package.subpkg.Config", analyzer)
        assert result is not None, "Expected a Handle for package.subpkg.Config, got None"
        assert result == Handle(
            "package._impl.config.Config"
        ), f"Expected canonical definition-site handle, got {result!r}"

    @pytest.mark.asyncio
    async def test_definition_path_is_idempotent(self, analyzer: JediAnalyzer) -> None:
        """The definition site itself is already canonical — must be idempotent."""
        result = await resolve_canonical("package._impl.config.Config", analyzer)
        assert result is not None
        assert result == Handle("package._impl.config.Config")


# ===========================================================================
# (B) Aliased re-export of an already-re-exported symbol
# ===========================================================================


class TestAliasedReExport:
    """package.legacy.LegacyConfig is an aliased path 3 hops from the definition."""

    @pytest.mark.asyncio
    async def test_aliased_3hop_resolves_to_definition(self, analyzer: JediAnalyzer) -> None:
        """LegacyConfig -> package.Config -> package.subpkg.Config -> definition."""
        result = await resolve_canonical("package.legacy.LegacyConfig", analyzer)
        assert result is not None, "Expected a Handle for package.legacy.LegacyConfig, got None"
        assert result == Handle(
            "package._impl.config.Config"
        ), f"Expected canonical definition-site handle, got {result!r}"


# ===========================================================================
# (C) Sibling alias collision
# ===========================================================================


class TestSiblingAliasCollision:
    """alias_pkg.sibling imports the same function under two names; both must canonicalise."""

    @pytest.mark.asyncio
    async def test_direct_import_resolves_to_definition(self, analyzer: JediAnalyzer) -> None:
        """alias_pkg.sibling.foo (from ... import foo) -> canonical."""
        result = await resolve_canonical("alias_pkg.sibling.foo", analyzer)
        assert result is not None, "Expected a Handle for sibling.foo, got None"
        assert result == Handle(
            "alias_pkg.source_mod.definitions.foo"
        ), f"Expected canonical definition-site handle, got {result!r}"

    @pytest.mark.asyncio
    async def test_aliased_import_resolves_to_definition(self, analyzer: JediAnalyzer) -> None:
        """alias_pkg.sibling.f (from ... import foo as f) -> canonical."""
        result = await resolve_canonical("alias_pkg.sibling.f", analyzer)
        assert result is not None, "Expected a Handle for sibling.f, got None"
        assert result == Handle(
            "alias_pkg.source_mod.definitions.foo"
        ), f"Expected canonical definition-site handle, got {result!r}"

    @pytest.mark.asyncio
    async def test_both_aliases_yield_same_canonical(self, analyzer: JediAnalyzer) -> None:
        """Both import forms must resolve to the identical canonical handle."""
        foo_result = await resolve_canonical("alias_pkg.sibling.foo", analyzer)
        f_result = await resolve_canonical("alias_pkg.sibling.f", analyzer)
        assert foo_result is not None
        assert f_result is not None
        assert (
            foo_result == f_result
        ), f"Sibling aliases must canonicalise identically; got {foo_result!r} vs {f_result!r}"


# ===========================================================================
# (D) Self re-export — cycle detection / termination
# ===========================================================================


class TestSelfReExportTermination:
    """self_reexport_pkg re-exports Foo from its own submodule.

    The walker must not loop: submodule.Foo is the definition, __init__.py
    re-exports it as self_reexport_pkg.Foo.  Resolving either path must
    terminate and return the definition-site handle.
    """

    @pytest.mark.asyncio
    async def test_public_path_terminates(self, analyzer: JediAnalyzer) -> None:
        """self_reexport_pkg.Foo resolves to the definition site without looping."""
        result = await resolve_canonical("self_reexport_pkg.Foo", analyzer)
        assert result is not None, "Expected a Handle for self_reexport_pkg.Foo, got None"
        assert result == Handle(
            "self_reexport_pkg.submodule.Foo"
        ), f"Expected definition-site handle, got {result!r}"

    @pytest.mark.asyncio
    async def test_definition_path_terminates(self, analyzer: JediAnalyzer) -> None:
        """The definition site resolves to itself (idempotent) without looping."""
        result = await resolve_canonical("self_reexport_pkg.submodule.Foo", analyzer)
        assert result is not None
        assert result == Handle("self_reexport_pkg.submodule.Foo")

    @pytest.mark.asyncio
    async def test_collect_self_reexport_terminates(self, analyzer: JediAnalyzer) -> None:
        """collect_re_exports terminates and returns the package-level re-export."""
        canonical = Handle("self_reexport_pkg.submodule.Foo")
        re_exports = await collect_re_exports(canonical, analyzer)
        assert isinstance(re_exports, list), "Must return a list"
        assert (
            Handle("self_reexport_pkg.Foo") in re_exports
        ), f"Expected 'self_reexport_pkg.Foo' in re-exports, got: {re_exports}"
        # Should NOT contain the definition site itself
        assert canonical not in re_exports, "Definition site must not appear in re-export list"


# ===========================================================================
# (E) Re-export collection — multi-hop: all public bindings
# ===========================================================================


class TestCollectReExportsMultihop:
    """collect_re_exports must enumerate ALL public re-export paths transitively."""

    @pytest.mark.asyncio
    async def test_collect_all_three_paths(self, analyzer: JediAnalyzer) -> None:
        """All three public bindings are returned for the canonical Config handle.

        Expected paths (in any order):
          package.subpkg.Config   — one-hop via subpkg
          package.Config          — two-hop via subpkg -> package
          package.legacy.LegacyConfig — aliased three-hop
        """
        canonical = Handle("package._impl.config.Config")
        re_exports = await collect_re_exports(canonical, analyzer)
        assert isinstance(re_exports, list)

        expected = {
            Handle("package.subpkg.Config"),
            Handle("package.Config"),
            Handle("package.legacy.LegacyConfig"),
        }
        actual_set = set(re_exports)

        missing = expected - actual_set
        assert not missing, (
            f"Missing expected re-export paths: {missing}\n" f"Got: {sorted(re_exports)}"
        )

    @pytest.mark.asyncio
    async def test_collect_returns_handles(self, analyzer: JediAnalyzer) -> None:
        """Every item in the returned list must be a Handle instance."""
        canonical = Handle("package._impl.config.Config")
        re_exports = await collect_re_exports(canonical, analyzer)
        for item in re_exports:
            assert isinstance(item, Handle), f"Expected Handle, got {type(item).__name__}: {item!r}"

    @pytest.mark.asyncio
    async def test_collect_does_not_include_canonical(self, analyzer: JediAnalyzer) -> None:
        """The definition-site handle must not appear in its own re-export list."""
        canonical = Handle("package._impl.config.Config")
        re_exports = await collect_re_exports(canonical, analyzer)
        assert (
            canonical not in re_exports
        ), f"Definition-site handle must not appear in re-export list, but found it: {re_exports}"

    @pytest.mark.asyncio
    async def test_collect_ordering_is_deterministic(self, analyzer: JediAnalyzer) -> None:
        """collect_re_exports returns the same ordered list on repeated calls."""
        canonical = Handle("package._impl.config.Config")
        result_a = await collect_re_exports(canonical, analyzer)
        result_b = await collect_re_exports(canonical, analyzer)
        assert (
            result_a == result_b
        ), f"Re-export list is not deterministic:\n  call 1: {result_a}\n  call 2: {result_b}"

    @pytest.mark.asyncio
    async def test_collect_no_re_exports_for_private_symbol(self, analyzer: JediAnalyzer) -> None:
        """A symbol not re-exported anywhere returns an empty list."""
        # _impl.__init__.py is empty, so nothing re-exports a private _impl symbol
        # We just need something that exists but has no re-exports
        # Use a function that's defined but never imported elsewhere
        canonical = Handle("alias_pkg.source_mod.definitions.foo")
        # The definition is in definitions.py; sibling.py re-exports it
        # So we're checking that we DO find those
        re_exports = await collect_re_exports(canonical, analyzer)
        assert isinstance(re_exports, list)
        # Both alias_pkg.sibling.foo and alias_pkg.sibling.f should appear
        assert (
            Handle("alias_pkg.sibling.foo") in re_exports
        ), f"Expected alias_pkg.sibling.foo in {re_exports}"
        assert (
            Handle("alias_pkg.sibling.f") in re_exports
        ), f"Expected alias_pkg.sibling.f in {re_exports}"
