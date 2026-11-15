"""Regression: every primitive reports a kind from the closed vocabulary (#623).

Before #623 slice 1, a project PEP 420 namespace package emitted by the
``imports`` edge surfaced as ``kind: "namespace"``, outside the documented
vocabulary, because ``_normalise_kind`` passed unknown Jedi types through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.kinds import KINDS
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from tests.conformance.response_linter import lint_response


@pytest.fixture
def namespace_project(tmp_path: Path) -> JediAnalyzer:
    """A project whose ``main`` imports a PEP 420 package (no ``__init__.py``)."""
    pkg = tmp_path / "nspkg"
    pkg.mkdir()
    (pkg / "sub.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import nspkg\nfrom nspkg import sub\n", encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


async def test_imports_edge_reports_namespace_package_as_module(
    namespace_project: JediAnalyzer,
) -> None:
    result = await expand("main", "imports", namespace_project)
    lint_response(result, "expand")
    kinds = {stub["handle"]: stub["kind"] for stub in result["stubs"]}
    assert kinds["nspkg"] == "module"  # was "namespace" before #623
    assert set(kinds.values()) <= KINDS


async def test_resolve_and_inspect_agree_namespace_package_is_a_module(
    namespace_project: JediAnalyzer,
) -> None:
    resolved = await resolve("nspkg", namespace_project)
    inspected = await inspect("nspkg", namespace_project)
    lint_response(resolved, "resolve")
    lint_response(inspected, "inspect")
    assert resolved["kind"] == "module"
    assert inspected["kind"] == "module"
