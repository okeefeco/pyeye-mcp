"""Regression tests for deterministic location.file path form (#603).

The ``location.file`` path form returned for symbols in the root project
must be deterministic regardless of whether ``project_path`` was supplied
as a relative or absolute path, or which form was called first in the
process.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp import server
from pyeye.project_manager import ProjectManager


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a temporary Python package project."""
    pkg_dir = tmp_path / "samplepkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("ANSWER = 42\n", encoding="utf-8")
    return tmp_path


def test_jedi_analyzer_canonicalizes_relative_project_path(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JediAnalyzer directly canonicalizes relative project_path to resolved absolute Path."""
    monkeypatch.chdir(sample_project.parent)
    rel_path = sample_project.name

    analyzer = JediAnalyzer(rel_path)
    assert analyzer.project_path.is_absolute()
    assert analyzer.project_path == sample_project.resolve()


def test_project_manager_get_analyzer_canonicalizes_path(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ProjectManager.get_analyzer instantiates and caches analyzer with canonical resolved path."""
    monkeypatch.chdir(sample_project.parent)
    rel_path = sample_project.name

    pm = ProjectManager()
    analyzer = pm.get_analyzer(rel_path)
    assert analyzer.project_path.is_absolute()
    assert analyzer.project_path == sample_project.resolve()


@pytest.mark.asyncio
async def test_resolve_location_file_deterministic_call_order(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """location.file returned by resolve() is always the canonical resolved absolute POSIX path.

    Regardless of whether project_path is passed as relative first, then absolute,
    or vice-versa, the resulting location.file is identical and absolute.
    """
    monkeypatch.chdir(sample_project.parent)
    rel_path = sample_project.name
    abs_path = str(sample_project.resolve())

    # Call 1: relative project_path
    res1 = await server.resolve("samplepkg", project_path=rel_path)
    assert res1.get("found") is True
    file1 = res1.get("location", {}).get("file")
    assert file1 is not None
    assert Path(file1).is_absolute()

    # Call 2: absolute project_path
    res2 = await server.resolve("samplepkg", project_path=abs_path)
    assert res2.get("found") is True
    file2 = res2.get("location", {}).get("file")
    assert file2 is not None

    # Determinism: file forms must match exactly
    assert file1 == file2
    expected_posix = (sample_project.resolve() / "samplepkg" / "__init__.py").as_posix()
    assert file1 == expected_posix
