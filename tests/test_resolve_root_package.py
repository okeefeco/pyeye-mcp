"""Tests for root-package disambiguation in ``resolve`` (#423, Task 8).

``resolve("<pkg>")`` for a bare top-level package name should yield the SINGLE
root handle, not an ambiguous set — via a **structural** rule (§7.1) that keys on
file layout, not the name string, so a deeper symbol that merely shares the
root's name is never wrongly promoted.

``_is_top_level_package`` is the two-clause predicate; ``_select_root_package``
keeps the qualifying candidates, dedupes by handle, and promotes iff exactly one
distinct handle survives (else stays ambiguous).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import (
    _Candidate,
    _is_top_level_package,
    _Location,
    _select_root_package,
    resolve,
)

_ROOT = Path(__file__).parent / "fixtures" / "root_package"
_MYPKG_INIT = _ROOT / "mypkg" / "__init__.py"
_INNER = _ROOT / "mypkg" / "inner.py"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_ROOT))


def _loc(file: Path) -> _Location:
    return _Location(file=file.as_posix(), line_start=1, line_end=1, column_start=0, column_end=0)


def _candidate(handle: str, file: Path) -> _Candidate:
    return _Candidate(handle=handle, kind="module", scope="project", location=_loc(file))


class TestIsTopLevelPackage:
    def test_regular_root_init_qualifies(self, analyzer: JediAnalyzer) -> None:
        cand = _candidate("mypkg", _MYPKG_INIT)
        assert _is_top_level_package(cand, "mypkg", analyzer) is True

    def test_deeper_dotted_handle_rejected(self, analyzer: JediAnalyzer) -> None:
        # A deeper same-named symbol (mypkg.inner.mypkg) has dots → clause 1 fails.
        cand = _candidate("mypkg.inner.mypkg", _INNER)
        assert _is_top_level_package(cand, "mypkg", analyzer) is False

    def test_module_file_not_init_rejected(self, analyzer: JediAnalyzer) -> None:
        # A handle "mypkg" anchored on a plain X.py (not __init__, not a dir) →
        # clause 2 fails.
        cand = _candidate("mypkg", _ROOT / "mypkg.py")
        assert _is_top_level_package(cand, "mypkg", analyzer) is False

    def test_nested_init_not_under_root_rejected(self, analyzer: JediAnalyzer) -> None:
        # __init__.py whose grandparent is NOT a project root (a nested package)
        # → clause 2 fails.
        cand = _candidate("mypkg", _ROOT / "mypkg" / "sub" / "__init__.py")
        assert _is_top_level_package(cand, "mypkg", analyzer) is False


class TestSelectRootPackage:
    def test_promotes_unique_root_over_deeper(self, analyzer: JediAnalyzer) -> None:
        cands = [
            _candidate("mypkg", _MYPKG_INIT),
            _candidate("mypkg.inner.mypkg", _INNER),
        ]
        chosen = _select_root_package(cands, "mypkg", analyzer)
        assert chosen is not None
        assert chosen["handle"] == "mypkg"

    def test_no_qualifier_stays_ambiguous(self, analyzer: JediAnalyzer) -> None:
        # No candidate is a top-level package → None (ambiguity preserved).
        cands = [
            _candidate("mypkg.inner.mypkg", _INNER),
            _candidate("other.mypkg", _INNER),
        ]
        assert _select_root_package(cands, "mypkg", analyzer) is None

    def test_same_handle_same_file_collapses(self, analyzer: JediAnalyzer) -> None:
        # Two candidates with the same handle AND the same on-disk file (one
        # physical package surfaced twice) dedupe to one → promoted.
        cands = [
            _candidate("mypkg", _MYPKG_INIT),
            _candidate("mypkg", _MYPKG_INIT),
        ]
        chosen = _select_root_package(cands, "mypkg", analyzer)
        assert chosen is not None
        assert chosen["handle"] == "mypkg"

    def test_same_name_shadow_across_roots_stays_ambiguous(self) -> None:
        # Two genuinely-different top-level packages sharing an import name across
        # two roots (project root + a src-layout root): same handle, DIFFERENT
        # files. Promoting either would silently hide the collision → stay
        # ambiguous (#423 review #7).
        shadow = Path(__file__).parent / "fixtures" / "root_package_shadow"
        analyzer = JediAnalyzer(str(shadow))
        analyzer.source_roots = [shadow / "a", shadow / "b"]
        cands = [
            _candidate("mypkg", shadow / "a" / "mypkg" / "__init__.py"),
            _candidate("mypkg", shadow / "b" / "mypkg" / "__init__.py"),
        ]
        assert _select_root_package(cands, "mypkg", analyzer) is None


class TestResolveIntegration:
    @pytest.mark.asyncio
    async def test_bare_package_resolves_to_single_root(self, analyzer: JediAnalyzer) -> None:
        # The fixture has a top-level `mypkg` package AND a deeper symbol named
        # `mypkg` (mypkg.inner.mypkg); resolve must pick the root, not ambiguate.
        result = await resolve("mypkg", analyzer)
        assert result.get("found") is True
        assert result.get("ambiguous") is not True
        assert result.get("handle") == "mypkg"

    @pytest.mark.asyncio
    async def test_dotted_handle_unchanged(self, analyzer: JediAnalyzer) -> None:
        # A dotted handle resolves directly — disambiguation does not interfere.
        result = await resolve("mypkg.inner", analyzer)
        assert result.get("found") is True
        assert result.get("handle") == "mypkg.inner"
