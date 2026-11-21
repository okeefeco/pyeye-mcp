"""A definition Jedi's parser can't read is never answered with phantoms (#1074).

parso 0.8.7, Jedi's parser, doesn't know some newer syntax. In a definition's
HEADER it error-recovers by dropping the ``def`` or ``class`` and leaving its
body's statements in the enclosing scope (the #1074 survey):

- PEP 646 ``*args: *Ts``, ``tuple[*Ts]`` as an annotation, ``Generic[*Ts]`` as
  a base, and a module-level ``x: tuple[*Ts] = ...``;
- PEP 695 ``[*Ts, **P]`` type parameters, and ``type Pair[T] = ...``.

So ``members`` listed the dropped body's names (``loop``, ``asyncio``) and the
real definition was invisible. Now, in a file Jedi parsed with errors, a name is
a member, or resolves, only if ``ast`` binds it in that scope; a definition only
``ast`` sees answers not-found, saying the syntax is the reason.

Newer syntax in a BODY (PEP 701 f-strings, ``match``, ``except*``, PEP 758) also
raises parse errors but loses nothing; those cases guard against over-reach.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve

AFTER = "\n\ndef after():\n    pass\n"


class Gap:
    """One damaging shape: its module source, and what must and mustn't be listed."""

    def __init__(
        self,
        minimum: tuple[int, int],
        source: str,
        members: list[str],
        lost: str,
        lost_line: int,
        phantoms: tuple[str, ...] = (),
        scope: str = "",
        kind: str = "function",
    ) -> None:
        self.minimum = minimum
        self.source = source
        self.members = members
        self.lost = lost
        self.lost_line = lost_line
        self.phantoms = phantoms
        self.scope = scope  # a class to list members of, instead of the module
        self.kind = kind  # the lost definition's kind in unreadable_definitions


GAPS = {
    "pep646_star_args": Gap(
        (3, 11),
        "def call_later(delay, *args: *Ts) -> int:\n"
        "    import asyncio\n"
        "    loop = asyncio\n"
        "    return loop" + AFTER,
        members=["after"],
        lost="call_later",
        lost_line=1,
        phantoms=("loop", "asyncio"),
    ),
    "pep646_star_annotation": Gap(
        (3, 11),
        "def target(x: tuple[*Ts]):\n    inner = 1\n    return inner" + AFTER,
        members=["after"],
        lost="target",
        lost_line=1,
        phantoms=("inner",),
    ),
    "pep646_generic_base": Gap(
        (3, 11),
        "from typing import Generic\n\n\nclass Box(Generic[*Ts]):\n    def m(self):\n"
        "        pass" + AFTER,
        members=["after"],
        lost="Box",
        lost_line=4,
        phantoms=("m",),
        kind="class",
    ),
    "pep646_module_annotation": Gap(
        (3, 11),
        "x: tuple[*Ts] = ()" + AFTER,
        members=["after"],
        lost="x",
        lost_line=1,
        kind="variable",
    ),
    "pep646_method_header": Gap(
        (3, 11),
        "class K:\n    def m(self, *a: *Ts):\n        inner = 1\n        return inner\n\n"
        "    def n(self):\n        pass\n",
        members=["n"],
        lost="K.m",
        lost_line=2,
        phantoms=("inner",),
        scope="K",
        kind="method",
    ),
    "pep695_star_type_params": Gap(
        (3, 12),
        "def target[*Ts, **P](*a: *Ts):\n    inner = 1\n    return inner" + AFTER,
        members=["after"],
        lost="target",
        lost_line=1,
        phantoms=("inner",),
    ),
    "pep695_generic_alias": Gap(
        (3, 12),
        "type Pair[T] = tuple[T, T]" + AFTER,
        members=["after"],
        lost="Pair",
        lost_line=1,
        kind="variable",
    ),
}

#: Newer syntax in a body: parse errors, but nothing lost (the survey's harmless
#: cases). The module's members are exactly these, and each resolves.
HARMLESS = {
    "pep701_nested_quotes": ((3, 12), 'def target(d):\n    return f"{d["k"]}"' + AFTER),
    "pep701_multiline": ((3, 12), 'def target(a):\n    return f"{\n        a\n    }"' + AFTER),
    "match": (
        (3, 10),
        "def target(p):\n    match p:\n        case [x, *rest]:\n            return x" + AFTER,
    ),
    "except_star": (
        (3, 11),
        "def target():\n    try:\n        pass\n    except* ValueError:\n        pass" + AFTER,
    ),
    "paren_with": (
        (3, 10),
        "def target(a, b):\n    with (open(a) as x, open(b) as y):\n        return x, y" + AFTER,
    ),
    "pep646_callable": (
        (3, 11),
        "from typing import Callable\n\n\ndef target(f: Callable[[*Ts], object]):\n"
        "    return f" + AFTER,
    ),
    "pep758_except": (
        (3, 14),
        "def target():\n    try:\n        pass\n    except ValueError, TypeError:\n        pass"
        + AFTER,
    ),
}


def _project(tmp_path: Path, source: str) -> tuple[JediAnalyzer, Path]:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("", encoding="utf-8")
    module = tmp_path / "pkg/m.py"
    module.write_text(source, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix()), module


def _leaves(result: dict[str, Any]) -> list[str]:
    return [s["handle"].rsplit(".", 1)[1] for s in result.get("stubs") or []]


def _needs(minimum: tuple[int, int]) -> Any:
    return pytest.mark.skipif(
        sys.version_info < minimum, reason=f"syntax needs Python {minimum[0]}.{minimum[1]}"
    )


GAP_PARAMS = [pytest.param(gap, id=name, marks=_needs(gap.minimum)) for name, gap in GAPS.items()]
HARMLESS_PARAMS = [
    pytest.param(source, id=name, marks=_needs(minimum))
    for name, (minimum, source) in HARMLESS.items()
]


@pytest.mark.parametrize("gap", GAP_PARAMS)
async def test_members_list_no_phantoms(tmp_path: Path, gap: Gap) -> None:
    analyzer, _ = _project(tmp_path, gap.source)
    container = f"pkg.m.{gap.scope}" if gap.scope else "pkg.m"
    result = await expand(container, "members", analyzer)
    assert _leaves(result) == gap.members


@pytest.mark.parametrize("gap", GAP_PARAMS)
async def test_outline_lists_no_phantoms(tmp_path: Path, gap: Gap) -> None:
    analyzer, _ = _project(tmp_path, gap.source)
    container = f"pkg.m.{gap.scope}" if gap.scope else "pkg.m"
    result = await outline(container, analyzer)
    names = [child["node"]["handle"].rsplit(".", 1)[1] for child in result.get("children") or []]
    assert names == gap.members


@pytest.mark.parametrize("gap", GAP_PARAMS)
async def test_a_lost_definition_says_why(tmp_path: Path, gap: Gap) -> None:
    """resolve, inspect, expand and outline: not found, naming the line and the parser."""
    analyzer, module = _project(tmp_path, gap.source)
    handle = f"pkg.m.{gap.lost}"
    where = f"{module.as_posix()}:{gap.lost_line}"
    results = {
        "resolve": await resolve(handle, analyzer),
        "inspect": await inspect(handle, analyzer),
        "expand": await expand(handle, "enclosing_scope", analyzer),
        "outline": await outline(handle, analyzer),
    }
    for tool, result in results.items():
        assert result["found"] is False, tool
        detail = result.get("detail") or ""
        assert where in detail, (tool, detail)
        assert "parser can't read" in detail, (tool, detail)


@pytest.mark.parametrize(
    "gap", [p for p in GAP_PARAMS if p.values[0].phantoms]  # type: ignore[union-attr]
)
async def test_a_phantom_does_not_resolve(tmp_path: Path, gap: Gap) -> None:
    """A dropped body's name, as Jedi places it, is not a definition there."""
    analyzer, _ = _project(tmp_path, gap.source)
    for phantom in gap.phantoms:
        container = f"pkg.m.{gap.scope}." if gap.scope else "pkg.m."
        result = await resolve(container + phantom, analyzer)
        assert result["found"] is False, phantom
        assert "parser can't read" in (result.get("detail") or ""), phantom


@pytest.mark.parametrize("source", HARMLESS_PARAMS)
async def test_body_syntax_loses_nothing(tmp_path: Path, source: str) -> None:
    analyzer, _ = _project(tmp_path, source)
    expected = [n for n in ("Callable", "target", "after") if f"def {n}" in source]
    assert _leaves(await expand("pkg.m", "members", analyzer)) == expected
    for name in expected:
        assert (await resolve(f"pkg.m.{name}", analyzer))["found"] is True


def test_a_clean_file_has_no_syntax_errors(tmp_path: Path) -> None:
    analyzer, module = _project(tmp_path, "def f():\n    return 1\n")
    script = file_artifact_cache.get_script(module, analyzer.project)
    assert file_artifact_cache.has_syntax_errors(script) is False


def test_a_damaged_file_has_syntax_errors(tmp_path: Path) -> None:
    analyzer, module = _project(tmp_path, GAPS["pep646_star_args"].source)
    script = file_artifact_cache.get_script(module, analyzer.project)
    assert file_artifact_cache.has_syntax_errors(script) is True


# ---------------------------------------------------------------------------
# The disclosure: unreadable_definitions (maintainer's ruling via designer)
# ---------------------------------------------------------------------------


def _entry(gap: Gap) -> dict[str, Any]:
    return {
        "name": gap.lost.rsplit(".", 1)[-1],
        "kind": gap.kind,
        "line": gap.lost_line,
        "reason": "parser_unsupported_syntax",
    }


@pytest.mark.parametrize("gap", GAP_PARAMS)
async def test_members_list_what_the_parser_lost(tmp_path: Path, gap: Gap) -> None:
    analyzer, _ = _project(tmp_path, gap.source)
    container = f"pkg.m.{gap.scope}" if gap.scope else "pkg.m"
    result = await expand(container, "members", analyzer)
    assert result["unreadable_definitions"] == [_entry(gap)]


@pytest.mark.parametrize("gap", GAP_PARAMS)
async def test_outline_lists_what_the_parser_lost(tmp_path: Path, gap: Gap) -> None:
    analyzer, _ = _project(tmp_path, gap.source)
    container = f"pkg.m.{gap.scope}" if gap.scope else "pkg.m"
    result = await outline(container, analyzer)
    assert result["unreadable_definitions"] == [_entry(gap)]


@pytest.mark.parametrize("gap", GAP_PARAMS)
async def test_inspect_counts_what_the_parser_lost(tmp_path: Path, gap: Gap) -> None:
    analyzer, _ = _project(tmp_path, gap.source)
    container = f"pkg.m.{gap.scope}" if gap.scope else "pkg.m"
    result = await inspect(container, analyzer)
    assert result["unreadable_definition_count"] == 1
    assert result["edge_counts"]["members"] == len(gap.members)


async def test_a_clean_file_measures_none_lost(tmp_path: Path) -> None:
    """Absence vs zero: measured and none lost is ``[]`` / ``0``, never absent."""
    analyzer, _ = _project(tmp_path, "class C:\n    def m(self):\n        pass\n" + AFTER)
    for container in ("pkg.m", "pkg.m.C"):
        assert (await expand(container, "members", analyzer))["unreadable_definitions"] == []
        assert (await outline(container, analyzer))["unreadable_definitions"] == []
        assert (await inspect(container, analyzer))["unreadable_definition_count"] == 0


async def test_absent_where_members_were_not_measured(tmp_path: Path) -> None:
    analyzer, _ = _project(tmp_path, "class C:\n    pass\n" + AFTER)
    assert "unreadable_definitions" not in await expand("pkg.m.C", "superclasses", analyzer)
    assert "unreadable_definition_count" not in await inspect("pkg.m.after", analyzer)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="PEP 646 needs Python 3.11")
async def test_trace_counts_lost_definitions_per_node(tmp_path: Path) -> None:
    from pyeye.mcp.operations.trace import trace

    analyzer, _ = _project(tmp_path, GAPS["pep646_star_args"].source)
    walked = await trace("pkg.m", ["members"], analyzer, max_depth=1)
    assert walked["unreadable_definition_counts"] == {"pkg.m": 1}
    other = await trace("pkg.m", ["imports"], analyzer, max_depth=1)
    assert "unreadable_definition_counts" not in other


# ---------------------------------------------------------------------------
# What the guard leaves alone in a damaged file
# ---------------------------------------------------------------------------

DAMAGED_WITH_NEIGHBOURS = (
    "import os\n"
    "from .other import Thing\n"
    "\n"
    "\n"
    "def call_later(delay, *args: *Ts) -> int:\n"
    "    loop = 1\n"
    "    return loop\n"
)


@pytest.fixture
def damaged(tmp_path: Path) -> JediAnalyzer:
    analyzer, _ = _project(tmp_path, DAMAGED_WITH_NEIGHBOURS)
    (tmp_path / "pkg/other.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    return analyzer


@_needs((3, 11))
class TestTheGuardLeavesAlone:
    async def test_the_module_itself(self, damaged: JediAnalyzer) -> None:
        assert (await resolve("pkg.m", damaged))["found"] is True

    async def test_a_re_export_through_it(self, damaged: JediAnalyzer) -> None:
        result = await resolve("pkg.m.Thing", damaged)
        assert (result["found"], result["handle"]) == (True, "pkg.other.Thing")

    async def test_an_attribute_through_an_import(self, damaged: JediAnalyzer) -> None:
        result = await resolve("pkg.m.os.path", damaged)
        assert result["found"] is True

    async def test_a_name_bound_nowhere_is_an_ordinary_miss(self, damaged: JediAnalyzer) -> None:
        result = await resolve("pkg.m.nowhere", damaged)
        assert result["found"] is False
        assert "parser can't read" not in (result.get("detail") or "")

    async def test_a_file_gone_since_jedi_read_it(
        self, damaged: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def gone(*_args: Any, **_kwargs: Any) -> bool:
            raise FileNotFoundError("removed")

        monkeypatch.setattr(file_artifact_cache, "file_has_syntax_errors", gone)
        result = await resolve("pkg.m.call_later", damaged)
        assert result["found"] is False
        assert "parser can't read" not in (result.get("detail") or "")


class TestParseGapsAst:
    """``pyeye._parse_gaps`` on ``ast`` alone."""

    def test_own_scopes_reach_guarded_definitions(self) -> None:
        import ast

        from pyeye._parse_gaps import own_scopes

        tree = ast.parse(
            "try:\n    pass\nexcept ImportError:\n    def in_handler(): pass\n"
            "match x:\n    case 1:\n        class InCase: pass\n"
            "if True:\n    def in_if(): pass\n"
            "def outer():\n    def inner(): pass\n"
        )
        assert [s.name for s in own_scopes(tree)] == ["in_handler", "InCase", "in_if", "outer"]

    def test_scope_named_and_binding_line_miss_honestly(self) -> None:
        import ast

        from pyeye._parse_gaps import binding_line, scope_named

        tree = ast.parse("class K:\n    x = 1\n")
        assert scope_named(tree, ["Nope"]) is None
        assert binding_line(tree, []) is None
        assert binding_line(tree, ["Nope", "x"]) is None
        assert binding_line(tree, ["K", "x"]) == 2
        assert binding_line(tree, ["K", "y"]) is None


def test_misplaced_skips_a_name_jedi_cant_place_under_its_module(tmp_path: Path) -> None:
    """A module anchor, or a full_name outside its module (``__main__.X``), isn't checked."""
    from types import SimpleNamespace

    from pyeye import resolver

    analyzer, module = _project(tmp_path, "x = 1\n")
    for full_name in ("pkg.m", "__main__.x"):
        anchor = SimpleNamespace(
            module_path=module, full_name=full_name, module_name="pkg.m", line=1, name="x"
        )
        assert resolver._misplaced("pkg.m.x", anchor, analyzer) is None
