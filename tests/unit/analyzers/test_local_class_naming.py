"""Unique function-local classes are named; handle segments are str.isidentifier() (#1024).

The maintainer's ruling on #1011:

1. A handle segment is any Python identifier (PEP 3131), so ``Héllo`` is one.
2. A function-local class is named in pyeye's existing notation
   (``pkg.mod.func.Name``, ``pkg.mod.Cls.meth.Name``) when it is one function
   level deep and its dotted name is unique; a class in a named one follows
   (``pkg.mod.func.Name.Inner``, as #1025 names members). Otherwise it stays
   handleless: ``ambiguous_local`` (the dotted name is defined more than once,
   or an enclosing class's is) or ``nested_local`` (two or more function
   levels deep). ``function_local`` is gone; ``no_module_path`` and
   ``not_a_handle`` stay.

Every newly named class round-trips: ``resolve(handle)`` and
``resolve_at(file, line, column)`` give the same handle and location.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.handle import Handle
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.resolve import resolve, resolve_at

BASE = "app.base.Base"

SRC = (
    "from app.base import Base\n"  # 1
    "\n"  # 2
    "def outer(flag):\n"  # 3
    "    class Local(Base):\n"  # 4   app.m.outer.Local
    "        class Inner(Base):\n"  # 5   app.m.outer.Local.Inner
    "            pass\n"  # 6
    "    if flag:\n"  # 7
    "        class Twin(Base):\n"  # 8   ambiguous_local
    "            class Kid(Base):\n"  # 9   ambiguous_local (under a twin)
    "                pass\n"  # 10
    "    else:\n"  # 11
    "        class Twin(Base):\n"  # 12  ambiguous_local
    "            pass\n"  # 13
    "    def mid():\n"  # 14
    "        class Deep(Base):\n"  # 15  nested_local
    "            pass\n"  # 16
    "    return Local, Twin, mid\n"  # 17
    "\n"  # 18
    "class C:\n"  # 19
    "    def meth(self):\n"  # 20
    "        class InMeth(Base):\n"  # 21  app.m.C.meth.InMeth
    "            pass\n"  # 22
    "        return InMeth\n"  # 23
    "\n"  # 24
    "class Héllo(Base):\n"  # 25  app.m.Héllo
    "    pass\n"  # 26
)

#: Newly named class -> (line, column of its name)
NAMED = {
    "app.m.outer.Local": (4, 10),
    "app.m.outer.Local.Inner": (5, 14),
    "app.m.C.meth.InMeth": (21, 14),
    "app.m.Héllo": (25, 6),
}


@pytest.fixture(autouse=True)
def _fresh_graph_store() -> Any:
    project_graph.invalidate()
    yield
    project_graph.invalidate()


@pytest.fixture
def project(tmp_path: Path) -> tuple[JediAnalyzer, str]:
    files = {
        "app/__init__.py": "",
        "app/base.py": "class Base:\n    pass\n",
        "app/m.py": SRC,
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix()), (tmp_path / "app/m.py").as_posix()


class TestTheHandleGrammar:
    @pytest.mark.parametrize("value", ["app.m.Héllo", "pkg.ünïcode.Ω", "a.b_c.D9"])
    def test_any_python_identifier_is_a_segment(self, value: str) -> None:
        assert Handle(value) == value

    @pytest.mark.parametrize("value", ["app.0001_initial.M", "a.<locals>.B", "a..b", "a.b-c"])
    def test_a_non_identifier_segment_is_still_rejected(self, value: str) -> None:
        with pytest.raises(ValueError):
            Handle(value)


class TestTheClassGraph:
    @pytest.mark.asyncio
    async def test_named_and_handleless_subclasses(self, project: tuple[JediAnalyzer, str]) -> None:
        analyzer, _ = project

        result: dict[str, Any] = dict(await expand(BASE, "subclasses", analyzer, max_stubs=None))

        assert sorted(s["handle"] for s in result["stubs"]) == sorted(NAMED)
        assert sorted(
            (e["name"], e["line"], e["reason"]) for e in result["handleless_subclasses"]
        ) == [
            ("Deep", 15, "nested_local"),
            ("Kid", 9, "ambiguous_local"),
            ("Twin", 8, "ambiguous_local"),
            ("Twin", 12, "ambiguous_local"),
        ]

    @pytest.mark.asyncio
    async def test_a_class_nested_in_a_named_local_class_is_named(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, _ = project

        result = await analyzer.find_subclasses(BASE)

        names = {e["full_name"] for e in result["subclasses"]}
        assert "app.m.outer.Local.Inner" in names

    @pytest.mark.asyncio
    async def test_function_local_is_no_longer_a_reason(
        self, project: tuple[JediAnalyzer, str]
    ) -> None:
        analyzer, _ = project

        result = await analyzer.find_subclasses(BASE)

        reasons = {e.get("unnamed_reason") for e in result["subclasses"]}
        assert "function_local" not in reasons
        assert reasons <= {
            None,
            "ambiguous_local",
            "nested_local",
            "no_module_path",
            "not_a_handle",
        }


class TestEveryNewlyNamedClassRoundTrips:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", sorted(NAMED))
    async def test_resolve_and_resolve_at_agree(
        self, project: tuple[JediAnalyzer, str], handle: str
    ) -> None:
        analyzer, module = project
        line, column = NAMED[handle]

        by_name: dict[str, Any] = dict(await resolve(handle, analyzer))
        by_position: dict[str, Any] = dict(await resolve_at(module, line, column, analyzer))

        assert by_name["found"] is True and by_name["handle"] == handle, by_name
        assert by_position["found"] is True and by_position["handle"] == handle, by_position
        assert by_name["location"]["line_start"] == by_position["location"]["line_start"] == line
