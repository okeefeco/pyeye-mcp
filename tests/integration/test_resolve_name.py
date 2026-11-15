"""Regression: bare names — an exact top-level module wins (#623 slice 4).

Before slice 4, ``resolve("functools")`` in a project with its own
``functools`` module (jaraco's ``jaraco.functools``) answered with the
project module, silently, though the bare name is exactly stdlib
``functools``.  The rule now: a bare name that is itself a complete top-level
module resolves to that module; same-named project symbols and submodules are
reached by their dotted handles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from tests.conformance.response_linter import lint_response


@pytest.fixture
def project(tmp_path: Path) -> JediAnalyzer:
    files = {
        "pkg/__init__.py": "from pkg._impl import Thing\n",
        "pkg/_impl.py": "class Thing:\n    pass\n",
        "pkg/functools.py": '"""A project module named like a stdlib one (jaraco.functools)."""\n',
        "pkg/other.py": "def inspect() -> None:\n    pass\n",
        "util/__init__.py": "",
        "util/a.py": "def helper() -> int:\n    return 1\n",
        "util/b.py": "def helper() -> int:\n    return 2\n",
    }
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


@pytest.mark.parametrize(
    "bare",
    [
        "functools",  # a project MODULE shares the name (pkg.functools)
        "inspect",  # a project FUNCTION shares the name (pkg.other.inspect)
        "os",  # no project definition at all
    ],
)
async def test_exact_top_level_module_wins(project: JediAnalyzer, bare: str) -> None:
    result = await resolve(bare, project)
    lint_response(result, "resolve")
    assert result.get("ambiguous") is not True, result
    assert (result["found"], result["handle"], result["kind"], result["scope"]) == (
        True,
        bare,
        "module",
        "external",
    )


@pytest.mark.parametrize(
    ("dotted", "kind"),
    [("pkg.functools", "module"), ("pkg.other.inspect", "function")],
)
async def test_same_named_project_symbols_stay_reachable_by_dotted_handle(
    project: JediAnalyzer, dotted: str, kind: str
) -> None:
    result = await resolve(dotted, project)
    assert (result["found"], result["handle"], result["kind"], result["scope"]) == (
        True,
        dotted,
        kind,
        "project",
    )


async def test_two_project_definitions_stay_ambiguous(project: JediAnalyzer) -> None:
    result = await resolve("helper", project)
    lint_response(result, "resolve")
    assert result.get("ambiguous") is True
    handles = [c["handle"] for c in result["candidates"]]
    assert handles == ["util.a.helper", "util.b.helper"]
    # Every candidate is canonical, so each one round-trips through inspect.
    for handle in handles:
        node = await inspect(handle, project)
        assert node["found"] is True and node["handle"] == handle


async def test_alias_and_definition_collapse_to_one_canonical_answer(
    project: JediAnalyzer,
) -> None:
    result = await resolve("Thing", project)
    assert result.get("ambiguous") is not True, result
    assert result["handle"] == "pkg._impl.Thing"


async def test_unknown_bare_name_is_not_found(project: JediAnalyzer) -> None:
    result = await resolve("no_such_name_anywhere_xyz", project)
    lint_response(result, "resolve")
    assert result["found"] is False
