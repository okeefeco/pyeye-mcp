"""Regression tests for #603: project_path form must not leak into results.

Before the fix, ``ProjectManager.get_analyzer`` keyed its analyzer cache on the
*resolved* path but constructed the ``JediAnalyzer`` from the *raw*
``project_path`` string. When the first call in a process used a relative path,
the Jedi project was rooted at that relative path, and every later
``location.file`` for the root project came back relative, whatever form later
calls passed. The result depended on call history (a determinism failure).

Contract pinned here: the analyzer's root and every ``location.file`` are the
resolved absolute path, whatever the call order or path spelling.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve
from pyeye.project_manager import ProjectManager


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal project at ``<tmp>/proj``, with CWD set to ``<tmp>``.

    Relative spelling of the project is then ``"proj"``, and ``"."`` is reached
    by chdir-ing into the project itself.
    """
    root = tmp_path / "proj"
    pkg = root / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("class Widget:\n    pass\n")
    monkeypatch.chdir(tmp_path)
    return root


def _spell(form: str, root: Path) -> str:
    if form == "abs":
        return root.resolve().as_posix()
    return "proj"


def _assert_absolute_root_file(file: str, root: Path) -> None:
    p = Path(file)
    assert p.is_absolute(), f"location.file must be absolute, got {file!r}"
    assert p.resolve() == (root / "mypkg" / "mod.py").resolve()


@pytest.mark.parametrize(
    "order",
    [["abs"], ["rel"], ["abs", "rel"], ["rel", "abs"]],
    ids=["abs", "rel", "abs-then-rel", "rel-then-abs"],
)
@pytest.mark.asyncio
async def test_location_file_absolute_regardless_of_call_order(
    project: Path, order: list[str]
) -> None:
    """Every call returns the same absolute location.file, whatever came first."""
    manager = ProjectManager(max_projects=10)
    files = []
    for form in order:
        analyzer = manager.get_analyzer(_spell(form, project))
        result = await resolve("mypkg.mod.Widget", analyzer)
        assert result["found"] is True, result
        files.append(result["location"]["file"])

    for f in files:
        _assert_absolute_root_file(f, project)
    assert len(set(files)) == 1, f"same query, different paths: {files}"


@pytest.mark.asyncio
async def test_default_dot_project_path_yields_absolute_location(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool default ``project_path="."`` is relative too; it must not leak."""
    monkeypatch.chdir(project)
    manager = ProjectManager(max_projects=10)
    analyzer = manager.get_analyzer(".")
    result = await resolve("mypkg.mod.Widget", analyzer)
    assert result["found"] is True, result
    _assert_absolute_root_file(result["location"]["file"], project)


def test_cached_analyzer_root_is_resolved_and_shared(project: Path) -> None:
    """Relative and absolute spellings share one analyzer, rooted absolutely."""
    manager = ProjectManager(max_projects=10)
    rel = manager.get_analyzer("proj")
    absolute = manager.get_analyzer(project.resolve().as_posix())
    assert rel is absolute
    assert rel.project_path.is_absolute()
    assert rel.project_path == project.resolve()


def test_jedi_analyzer_resolves_relative_project_path(project: Path) -> None:
    """Defence in depth: a directly-constructed analyzer also normalises its root."""
    analyzer = JediAnalyzer("proj")
    assert analyzer.project_path.is_absolute()
    assert analyzer.project_path == project.resolve()
    assert Path(os.fspath(analyzer.project.path)).is_absolute()
