"""Tests for ``inspect.edge_counts.submodules`` (#423, Task 6).

The cheap counts-first signal for the ``submodules`` containment edge.  It is
delegated to the :func:`edges._enumerate_submodule_paths` source-of-truth so
the count and the enumeration can never diverge — the invariant pinned here is
``inspect(pkg).edge_counts["submodules"] == len(expand(pkg, "submodules").stubs)``.

Per the absence-vs-zero invariant (spec §4), ``submodules`` is present ONLY for
package handles: ABSENT for plain modules and for class/function/variable
handles (not-applicable, not a measured zero); a real *empty* package measures
``submodules == 0`` (present).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect

_CONTAINMENT = Path(__file__).parent / "fixtures" / "containment"
_REGULAR = _CONTAINMENT / "regular"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_REGULAR))


class TestSubmodulesCount:
    @pytest.mark.asyncio
    async def test_package_count_matches_expand(self, analyzer: JediAnalyzer) -> None:
        # The load-bearing invariant: count == number of expand stubs.
        node = await inspect("mypkg", analyzer)
        expanded = await expand("mypkg", "submodules", analyzer)
        assert node["edge_counts"]["submodules"] == len(expanded["stubs"])
        assert node["edge_counts"]["submodules"] == 3  # alpha, beta, sub

    @pytest.mark.asyncio
    async def test_absent_for_plain_module(self, analyzer: JediAnalyzer) -> None:
        # A non-package module: submodules is not applicable → ABSENT (not 0).
        node = await inspect("mypkg.alpha", analyzer)
        assert "submodules" not in node["edge_counts"]

    @pytest.mark.asyncio
    async def test_absent_for_class_handle(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("mypkg.alpha.A", analyzer)
        assert "submodules" not in node["edge_counts"]

    @pytest.mark.asyncio
    async def test_empty_package_measures_zero(self, analyzer: JediAnalyzer) -> None:
        # The `emptypkg` fixture is a package dir with ONLY __init__.py →
        # submodules == 0 (a measured zero, PRESENT — distinct from absent).
        node = await inspect("emptypkg", analyzer)
        assert node["edge_counts"]["submodules"] == 0
