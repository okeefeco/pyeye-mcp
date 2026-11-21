"""Every edge stub handle resolves uniquely back to the stub (#1071).

Edges named a stub from Jedi's ``full_name`` alone (``_handle_for_name``), so:

- (a) a class nested in a function-local class, which ``resolve`` names
  ``app.m.f.Outer.Inner`` (#1025), had no edge handle at all: Jedi's
  ``full_name`` is ``None`` there;
- (b) a function-local name bound more than once (#1049's binding rule, or
  #1022's two ``class`` statements) was emitted as ``app.m.g.X``, a handle
  ``resolve`` answers as ``ambiguous``.

Edges now name a stub by the rules ``resolve`` uses, and keep a function-local
handle only when ``resolve`` places it back at that same definition; otherwise
the adjacent is an honest loss (``unresolved_superclasses`` with reason
``no_handle``), never an ambiguous handle.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyeye import resolver
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.resolve import resolve

SRC = (
    "def f():\n"  # 1
    "    class Outer:\n"  # 2
    "        class Inner:\n"  # 3  (a): named app.m.f.Outer.Inner by #1025
    "            pass\n"  # 4
    "    class C(Outer.Inner):\n"  # 5
    "        pass\n"  # 6
    "    return C\n"  # 7
    "\n"  # 8
    "def g(X):\n"  # 9   (b): the parameter binds X too (#1049)
    "    class X:\n"  # 10
    "        pass\n"  # 11
    "    class D(X):\n"  # 12
    "        pass\n"  # 13
    "    return D\n"  # 14
    "\n"  # 15
    "def h(flag):\n"  # 16
    "    if flag:\n"  # 17
    "        class Twin:\n"  # 18  two class statements (#1022)
    "            pass\n"  # 19
    "    else:\n"  # 20
    "        class Twin:\n"  # 21
    "            pass\n"  # 22
    "    class E(Twin):\n"  # 23
    "        pass\n"  # 24
    "    return E\n"  # 25
    "\n"  # 26
    "def k():\n"  # 27  the plain case keeps its handle
    "    class Base:\n"  # 28
    "        pass\n"  # 29
    "    class Child(Base):\n"  # 30
    "        pass\n"  # 31
    "    return Child\n"  # 32
)

#: Every source the sweep expands: the module, its functions, and each local
#: class that has a unique handle.
SOURCES = (
    "app.m",
    "app.m.f",
    "app.m.f.Outer",
    "app.m.f.Outer.Inner",
    "app.m.f.C",
    "app.m.g",
    "app.m.g.D",
    "app.m.h",
    "app.m.h.E",
    "app.m.k",
    "app.m.k.Base",
    "app.m.k.Child",
)

EDGES = ("members", "superclasses", "subclasses", "enclosing_scope")


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app/m.py").write_text(SRC, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix())


def _handles(result: dict[str, Any]) -> list[str]:
    return [s["handle"] for s in result.get("stubs") or []]


async def test_a_class_nested_in_a_local_class_is_named(analyzer: JediAnalyzer) -> None:
    """(a): ``C(Outer.Inner)``'s base is ``app.m.f.Outer.Inner``, the handle resolve gives."""
    result = await expand("app.m.f.C", "superclasses", analyzer)
    assert _handles(result) == ["app.m.f.Outer.Inner"]
    assert result["unresolved_superclasses"] == []


async def test_subclasses_agree_for_a_nested_local_base(analyzer: JediAnalyzer) -> None:
    """The class graph names that base the same way, so the edges stay symmetric (#1057)."""
    result = await expand("app.m.f.Outer.Inner", "subclasses", analyzer)
    assert _handles(result) == ["app.m.f.C"]


async def test_a_name_bound_twice_is_an_honest_loss(analyzer: JediAnalyzer) -> None:
    """(b): no ``…g.X`` stub resolve would call ambiguous; the base is unresolved, ``no_handle``.

    goto finds one class, but the parameter ``X`` binds the name too (#1049),
    so the class has no unique handle.
    """
    result = await expand("app.m.g.D", "superclasses", analyzer)
    assert _handles(result) == []
    assert result["unresolved_superclasses"] == ["X"]
    assert result["unresolved_superclass_details"] == [{"base": "X", "reason": "no_handle"}]


async def test_ambiguous_candidates_list_only_handles_resolve_accepts(
    analyzer: JediAnalyzer,
) -> None:
    """Two ``class Twin`` in one function: ``ambiguous``, and ``…h.Twin`` isn't a candidate.

    Both definitions share the handle ``app.m.h.Twin``, which resolve answers as
    ambiguous (#1022), so it can't be listed; ``candidate_count`` still counts
    both, per #1065's ``candidate_count > len(candidates)`` rule.
    """
    result = await expand("app.m.h.E", "superclasses", analyzer)
    assert _handles(result) == []
    assert result["unresolved_superclasses"] == ["Twin"]
    assert result["unresolved_superclass_details"] == [
        {"base": "Twin", "reason": "ambiguous", "candidates": [], "candidate_count": 2}
    ]


async def test_a_unique_local_base_keeps_its_handle(analyzer: JediAnalyzer) -> None:
    assert _handles(await expand("app.m.k.Child", "superclasses", analyzer)) == ["app.m.k.Base"]
    assert _handles(await expand("app.m.k.Base", "subclasses", analyzer)) == ["app.m.k.Child"]


async def test_every_stub_round_trips_uniquely(analyzer: JediAnalyzer) -> None:
    """Every stub any swept edge emits resolves, unambiguously, to itself and its location."""
    problems = []
    seen = 0
    for source in SOURCES:
        found = await resolve(source, analyzer)
        assert found.get("found") and not found.get("ambiguous"), (source, found)
        for edge in EDGES:
            result = await expand(source, edge, analyzer)
            for stub in result.get("stubs") or []:
                seen += 1
                back = await resolve(stub["handle"], analyzer)
                where = stub.get("line_start")
                if (
                    not back.get("found")
                    or back.get("ambiguous")
                    or back.get("handle") != stub["handle"]
                    or (back.get("location") or {}).get("line_start") != where
                ):
                    problems.append((source, edge, stub["handle"], back))
    assert problems == []
    assert seen > 0


class TestLocalDefinitionHandle:
    """``resolver.local_definition_handle``: keep a local handle only if resolve gives it back."""

    @staticmethod
    def _name(line: int) -> SimpleNamespace:
        return SimpleNamespace(module_path=Path("/p/app/m.py"), line=line)

    @pytest.fixture
    def local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(resolver, "is_function_local", lambda _name: True)

    def _resolves_to(self, monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
        monkeypatch.setattr(resolver, "resolve_item", lambda _handle, _analyzer: result)

    def test_a_definition_outside_a_function_is_not_checked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(resolver, "is_function_local", lambda _name: False)
        self._resolves_to(monkeypatch, None)  # never consulted
        assert resolver.local_definition_handle(self._name(3), "app.m.X", None) == "app.m.X"

    @pytest.mark.usefixtures("local")
    def test_resolve_back_at_the_same_definition_keeps_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._resolves_to(
            monkeypatch, resolver.Resolved("app.m.f.X", "class", "project", self._name(3))
        )
        assert resolver.local_definition_handle(self._name(3), "app.m.f.X", None) == "app.m.f.X"

    @pytest.mark.usefixtures("local")
    def test_resolve_at_another_definition_drops_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._resolves_to(
            monkeypatch, resolver.Resolved("app.m.f.X", "class", "project", self._name(9))
        )
        assert resolver.local_definition_handle(self._name(3), "app.m.f.X", None) is None

    @pytest.mark.usefixtures("local")
    def test_a_handle_resolve_refuses_is_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._resolves_to(monkeypatch, resolver.NotFound("unresolved", "ambiguous"))
        assert resolver.local_definition_handle(self._name(3), "app.m.f.X", None) is None


@pytest.mark.parametrize(
    "target",
    [
        None,
        # No Jedi full_name, and not a member of a local class: no name at all.
        SimpleNamespace(full_name=None, parent=lambda: None),
        # A definition Jedi can't place in a module (#714).
        SimpleNamespace(full_name="__main__.X", module_path=None, type="class"),
    ],
)
def test_the_graph_keys_no_base_it_cannot_name(analyzer: JediAnalyzer, target: Any) -> None:
    assert analyzer._base_target_name(target) is None
