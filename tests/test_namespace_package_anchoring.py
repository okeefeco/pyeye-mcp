"""End-to-end acceptance for top-level PEP 420 namespace-package anchoring (#444).

#423's `submodules` enumerator handles namespace packages, but the cold-start
chain (`resolve` → `inspect` → `outline` → `expand`) could not anchor a
*top-level* namespace package (no `__init__.py`) as a project handle — Jedi
surfaces it as an unanchored `external`/`namespace` symbol with an empty
`module_path`.  These tests drive the REAL pipeline (through `resolve`, not the
internal enumerators that #423's tests deliberately bypass) against a project
**rooted at** a namespace package.

Fixture `tests/fixtures/ns420` (a real committed dir, NOT a tmp symlink):

    acme/                    # PEP 420 namespace package — NO __init__.py
      auth.py, api.py        # modules
      plugins/registry.py    # namespace SUBpackage — NO __init__.py
      core/__init__.py       # REGULAR subpackage
      core/engine.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve

_NS420 = Path(__file__).parent / "fixtures" / "ns420"
_EXPECTED_CHILDREN = {"acme.auth", "acme.api", "acme.plugins", "acme.core"}


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """Analyzer rooted AT the namespace package's parent (acme has no __init__)."""
    return JediAnalyzer(str(_NS420))


class TestResolveAnchorsNamespaceRoot:
    @pytest.mark.asyncio
    async def test_resolve_returns_project_handle(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("acme", analyzer)
        assert result.get("found") is True
        # No longer an unanchored ambiguous external pair.
        assert result.get("ambiguous") is not True
        assert result.get("handle") == "acme"
        assert result.get("scope") == "project"

    @pytest.mark.asyncio
    async def test_resolve_location_is_the_namespace_dir(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("acme", analyzer)
        loc = result.get("location") or {}
        # Dir-anchored: the location points at the acme/ directory itself.
        assert loc.get("file") == (_NS420 / "acme").as_posix()


class TestInspectAnchorsNamespaceRoot:
    @pytest.mark.asyncio
    async def test_inspect_is_package_with_submodule_count(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("acme", analyzer)
        assert node["scope"] == "project"
        assert node.get("is_package") is True
        assert node["edge_counts"].get("submodules") == 4

    @pytest.mark.asyncio
    async def test_count_matches_expand(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("acme", analyzer)
        expanded = await expand("acme", "submodules", analyzer)
        assert node["edge_counts"]["submodules"] == len(expanded["stubs"])


class TestExpandOutlineFromNamespaceRoot:
    @pytest.mark.asyncio
    async def test_expand_submodules_lists_children(self, analyzer: JediAnalyzer) -> None:
        result = await expand("acme", "submodules", analyzer)
        assert result.get("unsupported") is not True
        assert {s["handle"] for s in result["stubs"]} == _EXPECTED_CHILDREN

    @pytest.mark.asyncio
    async def test_outline_surveys_namespace_root(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("acme", analyzer)
        assert {c["node"]["handle"] for c in tree["children"]} == _EXPECTED_CHILDREN


class TestNamespaceSubpackageStillWorks:
    """Guard the already-working drill-from-a-child paths (issue: these pass today)."""

    @pytest.mark.asyncio
    async def test_namespace_subpackage_one_level_down(self, analyzer: JediAnalyzer) -> None:
        result = await expand("acme.plugins", "submodules", analyzer)
        assert {s["handle"] for s in result["stubs"]} == {"acme.plugins.registry"}

    @pytest.mark.asyncio
    async def test_regular_subpackage_anchors(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("acme.core", analyzer)
        assert result.get("found") is True
        assert result.get("scope") == "project"
        assert result.get("handle") == "acme.core"
