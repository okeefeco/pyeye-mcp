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


#: function name -> (its parameters, its body after ``class X(Base): pass``,
#: the graph's reason, or None when X is named)
REBINDINGS: dict[str, tuple[str, str, str | None]] = {
    # Another binding of X in the function's own scope: X names two things.
    "assigned": ("", "X = list(X)", "ambiguous_local"),
    "augmented": ("", "X += 1", "ambiguous_local"),
    "deleted": ("", "del X", "ambiguous_local"),
    "looped": ("", "for X in ():\n        pass", "ambiguous_local"),
    "caught": (
        "",
        "try:\n        pass\n    except Exception as X:\n        pass",
        "ambiguous_local",
    ),
    "withed": ("", "with open('f') as X:\n        pass", "ambiguous_local"),
    "walrused": ("", "if (X := 1):\n        pass", "ambiguous_local"),
    "redefined": ("", "def X():\n        pass", "ambiguous_local"),
    # The Python reference's other binding forms (#1049 ruling): Jedi doesn't
    # list these as a second ``f.X``, so both sides count from pyeye._bindings.
    "parameter": ("X", "pass", "ambiguous_local"),
    "imported": ("", "import os as X", "ambiguous_local"),
    "from_imported": ("", "from os import path as X", "ambiguous_local"),
    "match_captured": ("", "match 1:\n        case X:\n            pass", "ambiguous_local"),
    # A binding in another scope, or of an attribute, leaves X unique.
    "comprehended": ("", "_ = [X for X in ()]", None),
    "lambdaed": ("", "_ = lambda X: X", None),
    "nested": ("", "def g():\n        X = 1", None),
    "attributed": ("", "X.attr = 1", None),
}

#: A class in a local class shares its name with a binding in that class's body.
MEMBER_SRC = (
    "\ndef holder():\n    class Form(Base):\n        Meta = 1\n"
    "        class Meta(Base):\n            pass\n    return Form\n"
)


def _rebinding_module() -> str:
    parts = ["from app.base import Base\n"]
    for fn, (params, body, _) in REBINDINGS.items():
        parts.append(f"\ndef {fn}({params}):\n    class X(Base):\n        pass\n    {body}\n")
    return "".join(parts) + MEMBER_SRC


class TestTheGraphNamesOnlyWhatResolveResolves:
    """A class is named only if no other binding in its function shares its name.

    ``resolve`` places a local name by every binding Jedi lists in that scope
    (#1022), so the graph counts the same ones. Found by #1024's django
    round-trip: ``class sender`` then ``del sender``.
    """

    @pytest.fixture
    def rebinding(self, tmp_path: Path) -> JediAnalyzer:
        files = {
            "app/__init__.py": "",
            "app/base.py": "class Base:\n    pass\n",
            "app/r.py": _rebinding_module(),
        }
        for rel, text in files.items():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text(text, encoding="utf-8")
        return JediAnalyzer(tmp_path.as_posix())

    @pytest.mark.asyncio
    async def test_each_rebinding_gets_its_reason(self, rebinding: JediAnalyzer) -> None:
        result: dict[str, Any] = dict(await expand(BASE, "subclasses", rebinding, max_stubs=None))

        named = {s["handle"] for s in result["stubs"]}
        reasons = {e["reason"] for e in result["handleless_subclasses"]}
        got = {fn: None if f"app.r.{fn}.X" in named else "ambiguous_local" for fn in REBINDINGS}
        assert got == {fn: reason for fn, (_, _, reason) in REBINDINGS.items()}
        assert "app.r.holder.Form" in named and "app.r.holder.Form.Meta" not in named
        # Every ambiguous X, plus the Meta that shares its name with ``Meta = 1``.
        assert (
            len(result["handleless_subclasses"]) == list(got.values()).count("ambiguous_local") + 1
        )
        assert reasons <= {"ambiguous_local"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fn", sorted(REBINDINGS))
    async def test_resolve_agrees_with_the_graph(self, rebinding: JediAnalyzer, fn: str) -> None:
        result: dict[str, Any] = dict(await resolve(f"app.r.{fn}.X", rebinding))

        if REBINDINGS[fn][2] is None:
            assert result["found"] is True and result["handle"] == f"app.r.{fn}.X", result
        else:
            assert result.get("handle") is None, result

    @pytest.mark.asyncio
    async def test_resolve_agrees_on_a_class_body_rebinding(self, rebinding: JediAnalyzer) -> None:
        result: dict[str, Any] = dict(await resolve("app.r.holder.Form.Meta", rebinding))

        assert result.get("handle") is None, result


class TestTheAmbiguousAnswerNamesEverySite:
    """resolve's detail lists each binding of the name, by line and form (#1049).

    Text only: ``candidates`` stay the definitions Jedi can anchor, and no
    response key is added (coordinator-3, 2026-11-21).
    """

    @pytest.fixture
    def rebinding(self, tmp_path: Path) -> JediAnalyzer:
        files = {
            "app/__init__.py": "",
            "app/base.py": "class Base:\n    pass\n",
            "app/r.py": _rebinding_module(),
        }
        for rel, text in files.items():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text(text, encoding="utf-8")
        return JediAnalyzer(tmp_path.as_posix())

    @pytest.mark.asyncio
    async def test_resolve_is_ambiguous_with_the_one_anchorable_candidate(
        self, rebinding: JediAnalyzer
    ) -> None:
        """A parameter has no definition to anchor on: the class is the only candidate."""
        result: dict[str, Any] = dict(await resolve("app.r.parameter.X", rebinding))
        twins: dict[str, Any] = dict(await resolve("app.r.redefined.X", rebinding))

        assert result["found"] is True and result["ambiguous"] is True, result
        assert [c["kind"] for c in result["candidates"]] == ["class"]
        assert set(result) == set(twins)  # #1022's shape, no new key

    @pytest.mark.asyncio
    async def test_the_not_found_detail_names_every_site(self, rebinding: JediAnalyzer) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result: dict[str, Any] = dict(await inspect("app.r.parameter.X", rebinding))
        twins: dict[str, Any] = dict(await inspect("app.r.redefined.X", rebinding))

        assert result["found"] is False and result["reason"] == "unresolved", result
        assert "a parameter at line" in result["detail"] and "a class at line" in result["detail"]
        assert set(result) == set(twins)
