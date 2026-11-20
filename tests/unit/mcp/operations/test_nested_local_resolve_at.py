"""A definition two or more function levels deep is a real symbol with no handle (#1026).

Jedi gives such a definition ``full_name=None``, and ``resolve_at`` answered
``no_symbol_at_position``, which tells the caller they pointed at nothing. There
IS a symbol there. Per #1011's ruling it stays handleless, so the honest answer
is ``unresolved``, with a detail that says why and names the nearest enclosing
scope that has a handle. One function level deep is named (#1025); a position
with no definition still says ``no_symbol_at_position``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve, resolve_at

SRC = (
    "def outer():\n"  # 1
    "    def mid():\n"  # 2
    "        class Deep:\n"  # 3
    "            pass\n"  # 4
    "        y = 2\n"  # 5
    "        def deepf():\n"  # 6
    "            pass\n"  # 7
    "        return Deep\n"  # 8
    "    class One:\n"  # 9
    "        pass\n"  # 10
    "    return mid\n"  # 11
    "\n"  # 12
)


@pytest.fixture
def project(tmp_path: Path) -> tuple[JediAnalyzer, str]:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/__init__.py").write_text("", encoding="utf-8")
    module = tmp_path / "app/m.py"
    module.write_text(SRC, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix()), module.as_posix()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("line", "column", "name", "kind"),
    [(3, 14, "Deep", "class"), (5, 8, "y", "variable"), (6, 12, "deepf", "function")],
)
async def test_a_nested_local_is_unresolved_not_absent(
    project: tuple[JediAnalyzer, str], line: int, column: int, name: str, kind: str
) -> None:
    analyzer, path = project
    result = await resolve_at(path, line, column, analyzer)

    assert result["found"] is False
    assert result["reason"] == "unresolved"  # an existing reason, never a new one
    detail = result["detail"]
    assert f"{name!r}" in detail and kind in detail
    assert "outer" in detail and "mid" in detail  # the function chain it sits in
    assert "no handle" in detail
    assert "'app.m.outer.mid'" in detail  # the nearest enclosing scope with one


@pytest.mark.asyncio
async def test_the_named_enclosing_scope_really_resolves(
    project: tuple[JediAnalyzer, str],
) -> None:
    analyzer, _ = project
    assert (await resolve("app.m.outer.mid", analyzer))["found"] is True


@pytest.mark.asyncio
async def test_the_file_line_form_says_the_same(project: tuple[JediAnalyzer, str]) -> None:
    analyzer, path = project
    result = await resolve(f"{path}:3", analyzer)

    assert result["found"] is False
    assert result["reason"] == "unresolved"
    assert "'Deep'" in result["detail"]


@pytest.mark.asyncio
async def test_one_function_level_is_still_named(project: tuple[JediAnalyzer, str]) -> None:
    analyzer, path = project
    result = await resolve_at(path, 9, 10, analyzer)

    assert result["found"] is True
    assert result["handle"] == "app.m.outer.One"


@pytest.mark.asyncio
async def test_a_position_with_nothing_there_is_still_no_symbol(
    project: tuple[JediAnalyzer, str],
) -> None:
    analyzer, path = project
    result = await resolve_at(path, 12, 0, analyzer)  # the blank last line

    assert result["found"] is False
    assert result["reason"] == "no_symbol_at_position"
