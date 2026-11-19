"""Two definitions of one name in one function: never answer with the other's location (#1022).

Jedi names a function-local class ``pkg.mod.outer.Twin``, so two ``class Twin``
in one function (``if``/``else`` branches, or a plain redefinition) share one
dotted name. pyeye used to pick the first definition for it, so ``resolve_at``
on the second answered with the first one's location, and ``resolve`` /
``inspect`` described a class the caller may not have meant.

Now:

- ``resolve`` on the shared dotted name answers ``ambiguous`` with every
  definition as a candidate, as a bare name does;
- ``resolve_at`` on a definition answers with that definition's own location,
  and on a use that could be either, ``ambiguous``;
- the handle-taking tools (``inspect``, ``expand``) answer not-found, saying
  why, rather than describing one of them.

A module-level ``if``/``else`` definition keeps #857's rule (the first binding).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve, resolve_at

SRC = (
    "def outer(flag):\n"  # 1
    "    if flag:\n"  # 2
    "        class Twin:\n"  # 3  Twin #1
    "            x = 1\n"  # 4
    "    else:\n"  # 5
    "        class Twin:\n"  # 6  Twin #2
    "            y = 2\n"  # 7
    "    class Again:\n"  # 8  Again #1
    "        pass\n"  # 9
    "    class Again:\n"  # 10 Again #2 (plain redefinition)
    "        pass\n"  # 11
    "    class Local:\n"  # 12 unique
    "        pass\n"  # 13
    "    return Twin, Again, Local\n"  # 14
    "\n"  # 15
    "if True:\n"  # 16
    "    def pick():\n"  # 17 module-level if/else (#857: first binding)
    "        return 1\n"  # 18
    "else:\n"  # 19
    "    def pick():\n"  # 20
    "        return 2\n"  # 21
)


@pytest.fixture
def project(tmp_path: Path) -> tuple[JediAnalyzer, str]:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/__init__.py").write_text("", encoding="utf-8")
    module = tmp_path / "app/m.py"
    module.write_text(SRC, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix()), module.as_posix()


def _lines(result: dict[str, Any]) -> list[int]:
    return sorted(c["location"]["line_start"] for c in result["candidates"])


class TestResolveOnTheSharedName:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("name", "lines"), [("Twin", [3, 6]), ("Again", [8, 10])])
    async def test_is_ambiguous_with_every_definition(
        self, project: tuple[JediAnalyzer, str], name: str, lines: list[int]
    ) -> None:
        analyzer, _ = project

        result = await resolve(f"app.m.outer.{name}", analyzer)

        assert result["found"] is True and result["ambiguous"] is True, result
        assert _lines(result) == lines
        assert {c["handle"] for c in result["candidates"]} == {f"app.m.outer.{name}"}

    @pytest.mark.asyncio
    async def test_a_unique_local_still_resolves(self, project: tuple[JediAnalyzer, str]) -> None:
        analyzer, _ = project

        result = await resolve("app.m.outer.Local", analyzer)

        assert result["found"] is True and "ambiguous" not in result
        assert result["location"]["line_start"] == 12

    @pytest.mark.asyncio
    async def test_a_module_level_if_else_keeps_the_first_binding(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        """#857's rule for module-level names is unchanged."""
        analyzer, _ = project

        result = await resolve("app.m.pick", analyzer)

        assert result["found"] is True and "ambiguous" not in result
        assert result["location"]["line_start"] == 17


class TestResolveAt:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("line", "column"), [(3, 14), (6, 14), (8, 10), (10, 10)])
    async def test_each_definition_answers_with_its_own_location(
        self, project: tuple[JediAnalyzer, str], line: int, column: int
    ) -> None:
        analyzer, module = project

        result = await resolve_at(module, line, column, analyzer)

        assert result["found"] is True and "ambiguous" not in result, result
        assert result["location"]["line_start"] == line

    @pytest.mark.asyncio
    async def test_a_use_that_could_be_either_is_ambiguous(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, module = project

        result = await resolve_at(module, 14, 12, analyzer)  # the `Twin` in `return Twin`

        assert result["found"] is True and result["ambiguous"] is True, result
        assert _lines(result) == [3, 6]


class TestHandleTakingTools:
    @pytest.mark.asyncio
    async def test_inspect_is_not_found_rather_than_one_of_them(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, _ = project

        result = await inspect("app.m.outer.Twin", analyzer)

        assert result["found"] is False and result["reason"] == "unresolved", result
        assert "2 definitions" in result["detail"]

    @pytest.mark.asyncio
    async def test_expand_is_not_found_rather_than_one_of_them(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, _ = project

        result = await expand("app.m.outer.Twin", "members", analyzer)

        assert result["found"] is False, result
