"""A TypedDict class shows the keyword-only constructor its keys imply (#1129).

Jedi gives a TypedDict class ``dict``'s overloads, renamed, so its first
signature was the no-argument ``Movie()``. The ruling (maintainer, 2026-11-23):

- render ``Movie(*, key: T, key2: T=...)``: keyword-only parameters, and an
  optional key (``total=False``, ``NotRequired``) marked with ``...``, since it
  has no real default;
- ``Required`` / ``NotRequired`` override the class's totality per key, and
  ``ReadOnly`` doesn't appear;
- inherited keys only when every base resolves statically; otherwise no
  signature, never a partial one;
- the functional form, ``TypedDict("Movie", {...})``, gets no signature.

The ``=...`` spacing is the one every other rendered signature uses
(``ast.unparse``, as #1126's NamedTuple constructor: ``size: int=0``).
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Any

import pytest

from pyeye import _class_signatures
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline

SOURCE = """\
import random
import typing
from typing import TypedDict

from typing_extensions import NotRequired, ReadOnly, Required

from pkg.other import Remote


class Movie(TypedDict):
    title: str
    year: int | None


class Total(TypedDict, total=False):
    n: int
    m: Required[str]


class Mixed(TypedDict):
    a: NotRequired[int]
    b: ReadOnly[str]
    c: NotRequired[ReadOnly[bytes]]
    d: typing.Required[float]


class Dotted(typing.TypedDict):
    x: int


class Empty(TypedDict):
    pass


class Sub(Movie):
    rating: NotRequired[float]


class SubOfPartial(Total):
    extra: str


class Deep(Sub, Remote):
    deep: bytes


Either = Movie if random.random() else Total


class Ambiguous(Either):
    z: int


Func = TypedDict("Func", {"a": int})


class Plain:
    p: int
"""

OTHER = """\
from typing import TypedDict


class Remote(TypedDict, total=False):
    far: int
"""

SIGNATURES = {
    "Movie": "Movie(*, title: str, year: int | None)",
    "Total": "Total(*, n: int=..., m: str)",
    "Mixed": "Mixed(*, a: int=..., b: str, c: bytes=..., d: float)",
    "Dotted": "Dotted(*, x: int)",
    "Empty": "Empty()",
    "Sub": "Sub(*, title: str, year: int | None, rating: float=...)",
    "SubOfPartial": "SubOfPartial(*, n: int=..., m: str, extra: str)",
    "Deep": ("Deep(*, title: str, year: int | None, rating: float=..., far: int=..., deep: bytes)"),
}


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory: pytest.TempPathFactory) -> JediAnalyzer:
    root: Path = tmp_path_factory.mktemp("td1129")
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "m.py").write_text(textwrap.dedent(SOURCE), encoding="utf-8")
    (root / "pkg" / "other.py").write_text(textwrap.dedent(OTHER), encoding="utf-8")
    return JediAnalyzer(root.as_posix())


@pytest.fixture(scope="module")
def nodes(analyzer: JediAnalyzer) -> dict[str, dict[str, Any]]:
    """Every outlined node of ``pkg.m``, by its handle relative to the module."""
    import asyncio

    tree = asyncio.run(outline("pkg.m", analyzer, max_depth=2))
    found: dict[str, dict[str, Any]] = {}

    def walk(item: dict[str, Any]) -> None:
        node = item["node"]
        found[node["handle"].removeprefix("pkg.m.")] = node
        for child in item.get("children", []):
            walk(child)

    walk(tree)
    return found


class TestTypedDictSignature:
    @pytest.mark.parametrize("name", list(SIGNATURES))
    def test_outline_shows_the_keyword_only_constructor(
        self, nodes: dict[str, dict[str, Any]], name: str
    ) -> None:
        assert nodes[name].get("signature") == SIGNATURES[name]

    @pytest.mark.parametrize("name", ["Movie", "Total", "Deep"])
    @pytest.mark.asyncio
    async def test_inspect_agrees(self, analyzer: JediAnalyzer, name: str) -> None:
        result = await inspect(f"pkg.m.{name}", analyzer)
        assert result.get("signature") == SIGNATURES[name]

    def test_a_base_that_does_not_resolve_statically_gives_no_signature(
        self, nodes: dict[str, dict[str, Any]]
    ) -> None:
        """Never a partial one: its inherited keys can't be known."""
        assert "signature" not in nodes["Ambiguous"]

    def test_the_functional_form_gets_no_signature(self, nodes: dict[str, dict[str, Any]]) -> None:
        assert "signature" not in nodes["Func"]

    def test_no_typeddict_shows_dicts_overloads(self, nodes: dict[str, dict[str, Any]]) -> None:
        for name in [*SIGNATURES, "Ambiguous", "Func"]:
            signature = nodes[name].get("signature", "")
            assert "_VT" not in signature and "Mapping" not in signature, name

    def test_a_plain_class_is_unchanged(self, nodes: dict[str, dict[str, Any]]) -> None:
        assert nodes["Plain"].get("signature") == "Plain()"


class TestHelpers:
    """The rules one at a time, without Jedi."""

    @staticmethod
    def _cls(src: str) -> ast.ClassDef:
        node = ast.parse(textwrap.dedent(src)).body[0]
        assert isinstance(node, ast.ClassDef)
        return node

    @pytest.mark.parametrize(
        ("src", "total"),
        [
            ("class A(TypedDict): pass", True),
            ("class A(TypedDict, total=False): pass", False),
            ("class A(TypedDict, total=True): pass", True),
            ("class A(TypedDict, total=FLAG): pass", None),  # not a literal: unknown
        ],
    )
    def test_totality(self, src: str, total: bool | None) -> None:
        assert _class_signatures._totality(self._cls(src)) is total

    @pytest.mark.parametrize(
        ("annotation", "total", "shown", "required"),
        [
            ("int", True, "int", True),
            ("int", False, "int", False),
            ("Required[int]", False, "int", True),
            ("NotRequired[int]", True, "int", False),
            ("typing.NotRequired[int]", True, "int", False),
            ("ReadOnly[int]", False, "int", False),
            ("ReadOnly[Required[list[int]]]", False, "list[int]", True),
            ("Annotated[int, 'x']", True, "Annotated[int, 'x']", True),  # not a key qualifier
        ],
    )
    def test_qualified(self, annotation: str, total: bool, shown: str, required: bool) -> None:
        expr = ast.parse(annotation, mode="eval").body
        result, is_required = _class_signatures._qualified(expr, total)
        assert (ast.unparse(result), is_required) == (shown, required)

    def test_a_non_class_name_is_not_a_typeddict(self) -> None:
        class FakeName:
            type = "function"

        assert _class_signatures.typeddict_class(FakeName()) is None

    def test_an_inference_failure_is_not_a_typeddict(self) -> None:
        class FakeName:
            type = "class"

            def infer(self) -> list[object]:
                raise RuntimeError("jedi")

        assert _class_signatures.typeddict_class(FakeName()) is None


NON_LITERAL = """\
from typing import TypedDict

FLAG = False


class Flagged(TypedDict, total=FLAG):
    a: int


class NotTD:
    b: int


class Mixed(Flagged):
    c: int
"""


@pytest.mark.asyncio
async def test_a_non_literal_total_gives_no_signature(tmp_path: Path) -> None:
    """Its keys' requiredness can't be known statically, here or in a subclass."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "n.py").write_text(NON_LITERAL, encoding="utf-8")
    analyzer = JediAnalyzer(tmp_path.as_posix())
    for name in ("Flagged", "Mixed"):
        result = await inspect(f"pkg.n.{name}", analyzer)
        assert result["found"] and "signature" not in result, name
