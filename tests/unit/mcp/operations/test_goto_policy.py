"""One goto-disambiguation policy, and superclasses read from one place (#624).

Before #624, four call sites picked among Jedi ``goto`` results with four
different rules: callees and imports took the first match, superclasses
preferred a class and then took the first, and typeref required exactly one.
A first-match guess is a confident answer to an ambiguous question: the same
``.clear()`` call resolved to ``OrderedDict.clear`` in one file and
``MutableMapping.clear`` in another.

The one rule (``pyeye._goto``): exactly one distinct target, optionally after
preferring a kind, else no answer, which every caller already reports
honestly as unresolved.

Fixture: ``tests/fixtures/goto_policy`` (``gp``).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.project_manager import ProjectManager

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "goto_policy"
_SRC = Path(__file__).parent.parent.parent.parent.parent / "src" / "pyeye"


@pytest.fixture(scope="module")
def analyzer():  # type: ignore[no-untyped-def]
    # Module scope is set up before the autouse inert-Observer patch, so this
    # manager starts a REAL watcher: stop it, or it outlives the session (#807).
    manager = ProjectManager()
    try:
        yield manager.get_analyzer(str(_FIXTURE))
    finally:
        manager.cleanup_all()


def _def(full_name: str | None, type_: str = "function") -> SimpleNamespace:
    return SimpleNamespace(full_name=full_name, type=type_)


class TestPickTarget:
    """The no-guess rule itself."""

    def test_one_target(self) -> None:
        from pyeye._goto import pick_target

        d = _def("pkg.f")
        assert pick_target([d]) is d

    def test_duplicates_of_one_target_are_one_target(self) -> None:
        from pyeye._goto import pick_target

        first = _def("pkg.f")
        assert pick_target([first, _def("pkg.f")]) is first

    def test_two_distinct_targets_is_no_answer(self) -> None:
        from pyeye._goto import pick_target

        assert pick_target([_def("builtins.bytes.endswith"), _def("builtins.str.endswith")]) is None

    def test_unnamed_results_are_ignored(self) -> None:
        from pyeye._goto import pick_target

        named = _def("pkg.f")
        assert pick_target([_def(None), named]) is named
        assert pick_target([_def(None)]) is None
        assert pick_target([]) is None

    def test_prefer_breaks_a_tie_only_when_it_leaves_one(self) -> None:
        from pyeye._goto import pick_target

        cls = _def("pkg.Base", "class")
        assert pick_target([_def("pkg.base", "module"), cls], prefer="class") is cls
        two_classes = [_def("a.Base", "class"), _def("b.Base", "class")]
        assert pick_target(two_classes, prefer="class") is None

    def test_goto_errors_are_no_answer(self) -> None:
        from pyeye._goto import goto_target

        class Boom:
            def goto(self, *_args: object, **_kwargs: object) -> list:
                raise RecursionError("jedi")

        assert goto_target(Boom(), 1, 0) is None


class TestCalleesDoNotGuess:
    """Measurement: 10 of 3,752 src/pyeye call sites had several targets."""

    @pytest.mark.asyncio
    async def test_union_receiver_is_unresolved(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        r = await expand("gp.users.union_receiver", "callees", analyzer)
        assert r["stubs"] == []  # was builtins.bytes.endswith, a coin-flip
        assert r["unresolved_call_sites"] == 1

    @pytest.mark.asyncio
    async def test_try_except_fallback_binding_is_unresolved(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        r = await expand("gp.users.fallback_call", "callees", analyzer)
        assert [s["handle"] for s in r["stubs"]] == []  # was gp._slow.helper
        assert r["unresolved_call_sites"] == 1

    @pytest.mark.asyncio
    async def test_one_target_still_resolves(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        r = await expand("gp.users.unique_call", "callees", analyzer)
        assert [s["handle"] for s in r["stubs"]] == ["builtins.len"]
        assert r["unresolved_call_sites"] == 0


class TestImportsDoNotGuess:
    @pytest.mark.asyncio
    async def test_fallback_bound_names_are_unresolved_imports(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        r = await expand("gp.users", "imports", analyzer)
        assert [s["handle"] for s in r["stubs"]] == []  # were gp._slow.VALUE / .helper
        assert r["unresolved_imports"] == ["gp.VALUE", "gp.helper"]


class TestSuperclassesEdge:
    @pytest.mark.asyncio
    async def test_declaration_order(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        r = await expand("gp.bases.Ordered", "superclasses", analyzer)
        assert [s["handle"] for s in r["stubs"]] == ["gp.bases.Zeta", "gp.bases.Alpha"]
        assert r["unresolved_superclasses"] == []

    @pytest.mark.asyncio
    async def test_unresolved_base_is_listed_not_dropped(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        r = await expand("gp.bases.Mixed", "superclasses", analyzer)
        assert [s["handle"] for s in r["stubs"]] == ["gp.bases.Zeta"]
        assert r["unresolved_superclasses"] == ["_dynamic.Missing"]

    @pytest.mark.asyncio
    async def test_other_edges_carry_no_unresolved_superclasses(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        r = await expand("gp.bases.Ordered", "members", analyzer)
        assert "unresolved_superclasses" not in r


class TestInspectSuperclassesFieldReadsTheEdge:
    """The field is unchanged for clients: declaration order, raw text for a
    base that doesn't resolve.  It is now built from the edge's own walk."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", ["gp.bases.Ordered", "gp.bases.Mixed", "gp.bases.Zeta"])
    async def test_field_is_the_edge_in_declaration_order(self, analyzer, handle: str) -> None:  # type: ignore[no-untyped-def]
        node = await inspect(handle, analyzer)
        edge = await expand(handle, "superclasses", analyzer)
        resolved = [s["handle"] for s in edge["stubs"]]
        assert [
            b for b in node["superclasses"] if b not in edge["unresolved_superclasses"]
        ] == resolved
        assert node["edge_counts"]["superclasses"] == len(resolved)

    @pytest.mark.asyncio
    async def test_field_values_unchanged(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        assert (await inspect("gp.bases.Ordered", analyzer))["superclasses"] == [
            "gp.bases.Zeta",
            "gp.bases.Alpha",
        ]
        assert (await inspect("gp.bases.Mixed", analyzer))["superclasses"] == [
            "gp.bases.Zeta",
            "_dynamic.Missing",
        ]


class TestTyperefForwardRef:
    @pytest.mark.asyncio
    async def test_quoted_and_unquoted_annotation_name_the_same_class(self, analyzer) -> None:  # type: ignore[no-untyped-def]
        params = {p["name"]: p for p in (await inspect("gp.fwd.takes", analyzer))["parameters"]}
        assert params["direct"]["type"].get("handle") == "gp.fwd.Foo"
        assert params["quoted"]["type"].get("handle") == "gp.fwd.Foo"


class TestOnePicker:
    """Fitness: the goto-picking sites call the shared helper, not ``.goto()``."""

    @pytest.mark.parametrize(
        "module",
        ["mcp/operations/edges.py", "mcp/operations/inspect.py", "mcp/operations/typeref.py"],
    )
    def test_no_direct_goto_calls(self, module: str) -> None:
        tree = ast.parse((_SRC / module).read_text(encoding="utf-8"))
        calls = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "goto"
        ]
        assert calls == [], f"{module} calls .goto() directly at lines {calls}; use pyeye._goto"

    def test_typeref_has_no_attr_position_copy(self) -> None:
        tree = ast.parse((_SRC / "mcp/operations/typeref.py").read_text(encoding="utf-8"))
        defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "_attribute_target_position" not in defs
