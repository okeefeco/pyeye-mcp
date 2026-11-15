"""A namespace package's directory anchor is "no source file", never a crash (#775).

A PEP 420 namespace package is anchored on its directory (#444), so the
``location.file`` pyeye emits for it is a directory, and an agent may pass it
straight back to ``resolve_at`` / ``resolve("<dir>:<line>")``. Reading it raised
``IsADirectoryError``, which #704 made a crash, and main's push-only exhaustive
path run went red for 15 merges. A directory is now the existing
``file_not_found`` miss, with a ``detail`` saying why.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve, resolve_at
from tests.conformance.response_linter import lint_response


@pytest.fixture
def project(tmp_path: Path) -> Path:
    ns = tmp_path / "nspkg" / "inner"  # nspkg: a namespace package (no __init__.py)
    ns.mkdir(parents=True)
    (ns / "__init__.py").write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def analyzer(project: Path) -> JediAnalyzer:
    return JediAnalyzer(project.as_posix())


def _assert_directory_miss(result: dict, directory: Path) -> None:
    assert result["found"] is False
    assert result["reason"] == "file_not_found"
    assert "is a directory" in result["detail"]
    assert directory.as_posix() in result["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("line, column", [(1, 0), (5, 3)])
async def test_resolve_at_on_a_directory_is_a_miss_not_a_crash(
    project: Path, analyzer: JediAnalyzer, line: int, column: int
) -> None:
    directory = project / "nspkg"
    result = await resolve_at(directory.as_posix(), line, column, analyzer)
    _assert_directory_miss(result, directory)
    lint_response(result, "resolve_at")


@pytest.mark.asyncio
async def test_resolve_file_line_on_a_directory_is_a_miss(
    project: Path, analyzer: JediAnalyzer
) -> None:
    directory = project / "nspkg"
    result = await resolve(f"{directory.as_posix()}:1", analyzer)
    _assert_directory_miss(result, directory)
    lint_response(result, "resolve")


@pytest.mark.asyncio
async def test_a_real_file_still_resolves(project: Path, analyzer: JediAnalyzer) -> None:
    result = await resolve_at(
        (project / "nspkg" / "inner" / "__init__.py").as_posix(), 1, 4, analyzer
    )
    assert result["found"] is True
    assert result["handle"] == "nspkg.inner.f"
