"""A function-local class's members are measured and named, never a false zero (#1025).

Jedi names a function-local class (``app.m.outer.Local``) but gives every
member of it ``full_name=None``. The ``members`` edge filtered on ``full_name``,
so a local class with a non-empty body reported ``members: 0`` and
``expand(…, "members")`` ``[]``: a measured zero that is false. The members
are now read from the class's own scope and named in pyeye's existing
notation, ``app.m.outer.Local.x``, and those handles resolve and round-trip.
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
    "    class Local:\n"  # 2
    "        x = 1\n"  # 3
    "        def m(self):\n"  # 4
    "            return 2\n"  # 5
    "        class Inner:\n"  # 6
    "            y = 3\n"  # 7
    "    if flag:\n"  # 8
    "        class Twin:\n"  # 9
    "            z = 1\n"  # 10
    "    else:\n"  # 11
    "        class Twin:\n"  # 12
    "            w = 2\n"  # 13
    "    return Local, Twin\n"  # 14
    "\n"  # 15
    "class Top:\n"  # 16
    "    x = 1\n"  # 17
)

LOCAL = "app.m.outer.Local"
#: handle -> (line, column) of its definition
MEMBERS = {
    f"{LOCAL}.x": (3, 8),
    f"{LOCAL}.m": (4, 12),
    f"{LOCAL}.Inner": (6, 14),
}


@pytest.fixture
def project(tmp_path: Path) -> tuple[JediAnalyzer, str]:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/__init__.py").write_text("", encoding="utf-8")
    module = tmp_path / "app/m.py"
    module.write_text(SRC, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix()), module.as_posix()


async def _members(handle: str, analyzer: JediAnalyzer) -> list[str]:
    result: dict[str, Any] = dict(await expand(handle, "members", analyzer))
    assert result["found"] is True and "unsupported" not in result, result
    return sorted(s["handle"] for s in result["stubs"])


class TestMembersOfALocalClass:
    @pytest.mark.asyncio
    async def test_expand_lists_the_class_body(self, project: tuple[JediAnalyzer, str]) -> None:
        analyzer, _ = project

        assert await _members(LOCAL, analyzer) == sorted(MEMBERS)

    @pytest.mark.asyncio
    async def test_inspect_counts_what_expand_lists(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, _ = project

        node: dict[str, Any] = dict(await inspect(LOCAL, analyzer))

        assert node["edge_counts"]["members"] == len(await _members(LOCAL, analyzer)) == 3

    @pytest.mark.asyncio
    async def test_a_nested_class_in_a_local_class_has_its_members_too(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, _ = project
        inner = f"{LOCAL}.Inner"

        node: dict[str, Any] = dict(await inspect(inner, analyzer))

        assert await _members(inner, analyzer) == [f"{inner}.y"]
        assert node["edge_counts"]["members"] == 1

    @pytest.mark.asyncio
    async def test_a_module_level_class_is_unchanged(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, _ = project

        assert await _members("app.m.Top", analyzer) == ["app.m.Top.x"]


class TestTheMemberHandlesRoundTrip:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", sorted(MEMBERS))
    async def test_resolve_finds_each_at_its_definition(
        self, project: tuple[JediAnalyzer, str], handle: str
    ) -> None:
        analyzer, _ = project

        result: dict[str, Any] = dict(await resolve(handle, analyzer))

        assert result["found"] is True and result["handle"] == handle, result
        assert result["location"]["line_start"] == MEMBERS[handle][0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", sorted(MEMBERS))
    async def test_resolve_at_names_each_definition_the_same(
        self, project: tuple[JediAnalyzer, str], handle: str
    ) -> None:
        analyzer, module = project
        line, column = MEMBERS[handle]

        result: dict[str, Any] = dict(await resolve_at(module, line, column, analyzer))

        assert result["found"] is True and result["handle"] == handle, result
        assert result["location"]["line_start"] == line

    @pytest.mark.asyncio
    async def test_inspect_of_a_member_answers(self, project: tuple[JediAnalyzer, str]) -> None:
        analyzer, _ = project

        node: dict[str, Any] = dict(await inspect(f"{LOCAL}.m", analyzer))

        assert node["found"] is True and node["kind"] == "method", node


class TestMembersOfACollidingLocalClass:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("member", ["z", "w"])
    async def test_stay_unresolved_because_the_class_is_ambiguous(
        self, project: tuple[JediAnalyzer, str], member: str
    ) -> None:
        """``Twin`` names two classes (#1022), so ``Twin.z`` names no single member."""
        analyzer, _ = project

        result: dict[str, Any] = dict(await resolve(f"app.m.outer.Twin.{member}", analyzer))

        assert result["found"] is False, result


class TestWhatStaysUnnamed:
    """Only members of a class with one function above are named (#1011, #1026)."""

    @pytest.mark.asyncio
    async def test_a_member_of_a_class_in_a_nested_function(self, tmp_path: Path) -> None:
        (tmp_path / "app").mkdir()
        (tmp_path / "app/__init__.py").write_text("", encoding="utf-8")
        module = tmp_path / "app/n.py"
        module.write_text(
            "def outer():\n"  # 1
            "    def mid():\n"  # 2
            "        class Deep:\n"  # 3
            "            q = 1\n"  # 4
            "        return Deep\n"  # 5
            "    return mid\n",  # 6
            encoding="utf-8",
        )
        analyzer = JediAnalyzer(tmp_path.as_posix())

        deep_member: dict[str, Any] = dict(await resolve("app.n.outer.mid.Deep.q", analyzer))
        at_q: dict[str, Any] = dict(await resolve_at(module.as_posix(), 4, 12, analyzer))

        assert deep_member["found"] is False
        assert at_q["found"] is False
