"""An ``@overload``'ed function anchors on its implementation (#1088).

The resolver kept the FIRST of several same-named bindings for overloads
(#857 preserved that older answer). So ``resolve``, ``resolve_at``, ``inspect``
and every edge read from the function's body described the first overload
stub: its location, its signature, ``deprecation: []`` though the
implementation warns, and ``callees: []`` from the stub's ``...`` body (a false
measured-empty). The definition without ``@overload`` (``typing.overload`` or
``typing_extensions.overload``, however imported) is now the anchor. Overload-only
definitions (a ``.pyi``, a Protocol) keep the first overload; a property's
setter and an ``if``/``else`` pair are unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve, resolve_at

_SPIDER = """\
import warnings
from typing import overload


@overload
def iterate(result: int) -> int: ...


@overload
def iterate(result: str) -> str: ...


@overload
def iterate(result: bytes) -> bytes: ...


def iterate(result):
    if isinstance(result, bytes):
        warnings.warn("bytes are deprecated", DeprecationWarning)
    return result
"""

_SPELLINGS = """\
import typing

import typing_extensions as te


@typing.overload
def via_module(x: int) -> int: ...


@typing.overload
def via_module(x: str) -> str: ...


def via_module(x):
    return x


@te.overload
def via_extensions(x: int) -> int: ...


@te.overload
def via_extensions(x: str) -> str: ...


def via_extensions(x):
    return x
"""

_METHODS = """\
from typing import overload


class C:
    @overload
    def m(self, x: int) -> int: ...

    @overload
    def m(self, x: str) -> str: ...

    def m(self, x):
        return str(x)
"""

_OVERLOAD_ONLY = """\
from typing import Protocol, overload


class P(Protocol):
    @overload
    def m(self, x: int) -> int: ...

    @overload
    def m(self, x: str) -> str: ...
"""

_STUB = """\
from typing import overload

@overload
def f(x: int) -> int: ...
@overload
def f(x: str) -> str: ...
"""

_UNCHANGED = """\
import sys


class K:
    @property
    def value(self) -> int:
        return 1

    @value.setter
    def value(self, new: int) -> None:
        pass


if sys.version_info >= (3, 12):
    def branch() -> int:
        return 1
else:
    def branch() -> int:
        return 2
"""


def _line(text: str, needle: str, nth: int = 1) -> int:
    """The 1-indexed line of the *nth* line in *text* containing *needle*."""
    hits = [i for i, line in enumerate(text.splitlines(), 1) if needle in line]
    return hits[nth - 1]


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name, text in {
        "spider.py": _SPIDER,
        "spellings.py": _SPELLINGS,
        "methods.py": _METHODS,
        "protocol.py": _OVERLOAD_ONLY,
        "unchanged.py": _UNCHANGED,
    }.items():
        (pkg / name).write_text(text, encoding="utf-8")
    (pkg / "stubbed.pyi").write_text(_STUB, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


def _start(result: Any) -> int:
    assert result.get("found") is True, result
    return int(result["location"]["line_start"])


_IMPL = _line(_SPIDER, "def iterate(result):")


class TestTheImplementationIsTheAnchor:
    @pytest.mark.asyncio
    async def test_resolve(self, analyzer: JediAnalyzer) -> None:
        assert _start(await resolve("pkg.spider.iterate", analyzer)) == _IMPL

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nth", [1, 2, 3, 4])
    async def test_resolve_at_on_any_definition_gives_the_same_answer(
        self, analyzer: JediAnalyzer, tmp_path: Path, nth: int
    ) -> None:
        line = _line(_SPIDER, "def iterate(", nth)
        result = await resolve_at((tmp_path / "pkg" / "spider.py").as_posix(), line, 4, analyzer)

        assert result.get("handle") == "pkg.spider.iterate"
        assert _start(result) == _IMPL

    @pytest.mark.asyncio
    async def test_inspect_describes_the_implementation(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("pkg.spider.iterate", analyzer)

        assert _start(node) == _IMPL
        # ``signature`` is the overloads' or the implementation's: that shape is
        # #1088's design question, so this PR doesn't pin it.
        assert node["deprecation"] == [
            {"kind": "conditional", "via": "warn", "line": _line(_SPIDER, '"bytes are deprecated"')}
        ]

    @pytest.mark.asyncio
    async def test_callees_come_from_the_implementations_body(self, analyzer: JediAnalyzer) -> None:
        """The first stub's ``...`` body made this a false measured-empty."""
        edge = await expand("pkg.spider.iterate", "callees", analyzer)

        handles = {stub["handle"] for stub in edge["stubs"]}
        assert "builtins.isinstance" in handles, edge
        assert any(h.endswith("warnings.warn") for h in handles), edge  # _warnings.warn

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handle", "needle"),
        [
            ("pkg.spellings.via_module", "def via_module(x):"),
            ("pkg.spellings.via_extensions", "def via_extensions(x):"),
        ],
    )
    async def test_every_spelling_of_overload_is_recognised(
        self, analyzer: JediAnalyzer, handle: str, needle: str
    ) -> None:
        assert _start(await resolve(handle, analyzer)) == _line(_SPELLINGS, needle)

    @pytest.mark.asyncio
    async def test_an_overloaded_method(self, analyzer: JediAnalyzer, tmp_path: Path) -> None:
        impl = _line(_METHODS, "def m(self, x):")
        node = await inspect("pkg.methods.C.m", analyzer)
        first = await resolve_at(
            (tmp_path / "pkg" / "methods.py").as_posix(), _line(_METHODS, "def m("), 8, analyzer
        )

        assert _start(node) == impl
        assert _start(first) == impl


class TestWithoutAnImplementation:
    @pytest.mark.asyncio
    async def test_overload_only_keeps_the_first_overload(self, analyzer: JediAnalyzer) -> None:
        """A Protocol (or any overload-only definition) has no body to prefer."""
        node = await inspect("pkg.protocol.P.m", analyzer)

        assert _start(node) == _line(_OVERLOAD_ONLY, "def m(")

    @pytest.mark.asyncio
    async def test_an_overload_only_stub_keeps_the_first_overload(
        self, analyzer: JediAnalyzer, tmp_path: Path
    ) -> None:
        result = await resolve_at(
            (tmp_path / "pkg" / "stubbed.pyi").as_posix(), _line(_STUB, "def f(", 2), 4, analyzer
        )

        assert _start(result) == _line(_STUB, "def f(")


class TestOtherSameNamedDefinitionsAreUnchanged:
    @pytest.mark.asyncio
    async def test_a_property_keeps_its_getter(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("pkg.unchanged.K.value", analyzer)

        assert _start(node) == _line(_UNCHANGED, "def value(self) -> int:")

    @pytest.mark.asyncio
    async def test_an_if_else_pair_keeps_the_first(self, analyzer: JediAnalyzer) -> None:
        assert _start(await resolve("pkg.unchanged.branch", analyzer)) == _line(
            _UNCHANGED, "def branch()"
        )
