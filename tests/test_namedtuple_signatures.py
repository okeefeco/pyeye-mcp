"""A typed NamedTuple shows its generated constructor, and None is never callable (#1126).

Jedi gave every class-form NamedTuple ``typing.NamedTuple``'s functional-form
signature, ``(typename, fields, /)``, and rendered the ``None`` instance as a
callable, so any attribute that can be ``None`` (``X | None``, ``Optional[X]``,
``= None``) carried ``"signature": "NoneType()"``. Poetry's ``Hexdigest`` showed
both, and a fresh agent was misled.

- A class that lists ``NamedTuple`` as a base shows the constructor its fields
  generate, in order, with their defaults.
- A subclass of such a class (fields inherited, not declared) shows no
  signature rather than the factory's: absent, never wrong.
- A signature Jedi renders for ``None`` is dropped. A variable that aliases a
  real callable (``alias = f``, ``kls = K``) keeps its signature.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline

SOURCE = '''\
import typing
import typing as t
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple, Optional


class Hexdigest(NamedTuple):
    """Poetry's shape: no defaults."""

    md5: str | None
    sha256: Optional[str]
    blake2_256: str


class WithDefaults(NamedTuple):
    name: str
    size: int = 0
    tag: Optional[str] = None

    def describe(self) -> str:
        return self.name


class Dotted(typing.NamedTuple):
    a: int


class Aliased(t.NamedTuple):
    b: str = "q"


class Empty(NamedTuple):
    pass


class Sub(Hexdigest):
    def total(self) -> int:
        return 1


@dataclass
class Point:
    x: int
    y: int | None = None


class Plain:
    a: int | None
    b: Optional[str] = None
    c: int


def f(a: int) -> int:
    return a


alias = f
kls = Point
maybe: int | None = None
handler: Callable[[int], int] | None = None
'''

CLASS_SIGNATURES = {
    "Hexdigest": "Hexdigest(md5: str | None, sha256: Optional[str], blake2_256: str)",
    "WithDefaults": "WithDefaults(name: str, size: int=0, tag: Optional[str]=None)",
    "Dotted": "Dotted(a: int)",
    "Aliased": "Aliased(b: str='q')",
    "Empty": "Empty()",
}

NONE_ABLE = [
    "Hexdigest.md5",
    "Hexdigest.sha256",
    "Hexdigest.blake2_256",
    "WithDefaults.tag",
    "Point.y",
    "Plain.a",
    "Plain.b",
    "Plain.c",
    "maybe",
    "handler",
]


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory: pytest.TempPathFactory) -> JediAnalyzer:
    root: Path = tmp_path_factory.mktemp("nt1126")
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "m.py").write_text(textwrap.dedent(SOURCE), encoding="utf-8")
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


class TestTheClassSignature:
    @pytest.mark.parametrize("name", list(CLASS_SIGNATURES))
    def test_outline_shows_the_generated_constructor(
        self, nodes: dict[str, dict[str, Any]], name: str
    ) -> None:
        assert nodes[name].get("signature") == CLASS_SIGNATURES[name]

    @pytest.mark.parametrize("name", ["Hexdigest", "WithDefaults"])
    @pytest.mark.asyncio
    async def test_inspect_agrees(self, analyzer: JediAnalyzer, name: str) -> None:
        result = await inspect(f"pkg.m.{name}", analyzer)

        assert result.get("signature") == CLASS_SIGNATURES[name]

    def test_a_subclass_of_a_namedtuple_shows_no_signature(
        self, nodes: dict[str, dict[str, Any]]
    ) -> None:
        """Its fields are inherited, not declared: absent, never the factory's."""
        assert "signature" not in nodes["Sub"]

    def test_no_class_shows_the_factory_signature(self, nodes: dict[str, dict[str, Any]]) -> None:
        shown = [n.get("signature", "") for n in nodes.values()]

        assert not [s for s in shown if "typename" in s], shown

    def test_a_dataclass_is_unchanged(self, nodes: dict[str, dict[str, Any]]) -> None:
        assert nodes["Point"].get("signature") == "Point(x: int, y: int | None=None)"

    def test_a_namedtuple_method_keeps_its_signature(
        self, nodes: dict[str, dict[str, Any]]
    ) -> None:
        assert nodes["WithDefaults.describe"].get("signature") == "describe(self) -> str"


class TestNoneIsNotCallable:
    @pytest.mark.parametrize("name", NONE_ABLE)
    def test_an_attribute_or_variable_shows_no_nonetype_signature(
        self, nodes: dict[str, dict[str, Any]], name: str
    ) -> None:
        assert "signature" not in nodes[name], nodes[name]

    @pytest.mark.asyncio
    async def test_inspect_agrees(self, analyzer: JediAnalyzer) -> None:
        result = await inspect("pkg.m.Hexdigest.md5", analyzer)

        assert "signature" not in result

    @pytest.mark.parametrize(
        ("name", "signature"),
        [("alias", "f(a: int) -> int"), ("kls", "Point(x: int, y: int | None=None)")],
    )
    def test_an_alias_of_a_real_callable_keeps_its_signature(
        self, nodes: dict[str, dict[str, Any]], name: str, signature: str
    ) -> None:
        assert nodes[name].get("signature") == signature
