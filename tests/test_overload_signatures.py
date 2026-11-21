"""inspect: an overloaded function's signature and ``overloads`` field (#1088 ruling).

The maintainer's ruling (via designer, 2026-11-22):

1. ``signature`` / ``parameters`` / ``return_type`` come from the single
   implementation, the ``def`` without ``@overload``, which is the anchor
   since #1089. A new field ``overloads`` lists the overloads' signatures in
   source order: ``[]`` when the definition was read and has none, absent
   when it couldn't be read, exactly like ``deprecation``. Overload-only
   definitions (a ``.pyi``, a Protocol) take the first overload's signature,
   and ``overloads`` lists them all. On ``inspect`` only.
2. A ``@deprecated`` on an individual overload deprecates one call form:
   ``{"kind": "conditional", "via": "decorator", "line"}`` (B.6 widened). An
   overload-only definition never reports a checked ``[]``: its body isn't
   there, so without overload-decorator evidence ``deprecation`` is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from tests.conformance.response_linter import ConformanceViolation, lint_response

_SPIDER = """\
import warnings
from typing import overload

from typing_extensions import deprecated


@overload
def iterate(result: int) -> int: ...


@overload
@deprecated("str input is deprecated")
def iterate(result: str) -> str: ...


@overload
def iterate(result: bytes) -> bytes: ...


def iterate(result):
    if isinstance(result, bytes):
        warnings.warn("bytes are deprecated", DeprecationWarning)
    return result


@overload
def old(x: int) -> int: ...


@overload
def old(x: str) -> str: ...


@deprecated("use new()")
def old(x):
    return x


def plain(x: int) -> int:
    return x
"""

_METHODS = """\
from typing import Protocol, overload

from typing_extensions import deprecated


class C:
    @overload
    def m(self, x: int) -> int: ...

    @overload
    def m(self, x: str) -> str: ...

    def m(self, x):
        return x


class P(Protocol):
    @overload
    def m(self, x: int) -> int: ...

    @overload
    def m(self, x: str) -> str: ...


class Q(Protocol):
    @overload
    def m(self, x: int) -> int: ...

    @overload
    @deprecated("str is deprecated")
    def m(self, x: str) -> str: ...
"""

_STUB = """\
from typing import overload

@overload
def f(x: int) -> int: ...
@overload
def f(x: str) -> str: ...
"""


def _line(text: str, needle: str, nth: int = 1) -> int:
    return [i for i, line in enumerate(text.splitlines(), 1) if needle in line][nth - 1]


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "spider.py").write_text(_SPIDER, encoding="utf-8")
    (pkg / "methods.py").write_text(_METHODS, encoding="utf-8")
    (pkg / "stubbed.pyi").write_text(_STUB, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


async def _node(analyzer: JediAnalyzer, handle: str) -> dict[str, Any]:
    node = await inspect(handle, analyzer)
    assert node["found"] is True, node
    lint_response(node, "inspect")
    return node


class TestWithAnImplementation:
    @pytest.mark.asyncio
    async def test_the_signature_is_the_implementations(self, analyzer: JediAnalyzer) -> None:
        node = await _node(analyzer, "pkg.spider.iterate")

        assert node["signature"] == "iterate(result)"
        assert [p["name"] for p in node["parameters"]] == ["result"]
        assert node["return_type"] is None  # the implementation is unannotated

    @pytest.mark.asyncio
    async def test_overloads_lists_every_overload_in_source_order(
        self, analyzer: JediAnalyzer
    ) -> None:
        node = await _node(analyzer, "pkg.spider.iterate")

        assert node["overloads"] == [
            "iterate(result: int) -> int",
            "iterate(result: str) -> str",
            "iterate(result: bytes) -> bytes",
        ]

    @pytest.mark.asyncio
    async def test_a_deprecated_overload_is_conditional_evidence(
        self, analyzer: JediAnalyzer
    ) -> None:
        """One call form is deprecated (str input), not the function."""
        node = await _node(analyzer, "pkg.spider.iterate")

        assert node["deprecation"] == [
            {"kind": "conditional", "via": "decorator", "line": _line(_SPIDER, "@deprecated")},
            {
                "kind": "conditional",
                "via": "warn",
                "line": _line(_SPIDER, '"bytes are deprecated"'),
            },
        ]

    @pytest.mark.asyncio
    async def test_a_deprecated_implementation_is_unconditional(
        self, analyzer: JediAnalyzer
    ) -> None:
        node = await _node(analyzer, "pkg.spider.old")

        assert node["deprecation"] == [
            {
                "kind": "unconditional",
                "via": "decorator",
                "line": _line(_SPIDER, '@deprecated("use new()")'),
            }
        ]
        assert node["signature"] == "old(x)"

    @pytest.mark.asyncio
    async def test_an_overloaded_method(self, analyzer: JediAnalyzer) -> None:
        node = await _node(analyzer, "pkg.methods.C.m")

        assert node["signature"] == "m(self, x)"
        assert node["overloads"] == ["m(self, x: int) -> int", "m(self, x: str) -> str"]
        assert node["deprecation"] == []


class TestOverloadOnly:
    @pytest.mark.asyncio
    async def test_the_first_overload_is_the_signature_and_all_are_listed(
        self, analyzer: JediAnalyzer
    ) -> None:
        node = await _node(analyzer, "pkg.methods.P.m")

        assert node["signature"] == "m(self, x: int) -> int"
        assert node["overloads"] == ["m(self, x: int) -> int", "m(self, x: str) -> str"]

    @pytest.mark.asyncio
    async def test_no_body_means_no_checked_empty_deprecation(self, analyzer: JediAnalyzer) -> None:
        node = await _node(analyzer, "pkg.methods.P.m")

        assert "deprecation" not in node

    @pytest.mark.asyncio
    async def test_a_deprecated_overload_is_still_reported(self, analyzer: JediAnalyzer) -> None:
        node = await _node(analyzer, "pkg.methods.Q.m")

        assert node["deprecation"] == [
            {"kind": "conditional", "via": "decorator", "line": _line(_METHODS, "@deprecated")}
        ]

    @pytest.mark.asyncio
    async def test_a_stub_file(self, analyzer: JediAnalyzer) -> None:
        node = await _node(analyzer, "pkg.stubbed.f")

        assert node["signature"] == "f(x: int) -> int"
        assert node["overloads"] == ["f(x: int) -> int", "f(x: str) -> str"]
        assert "deprecation" not in node


class TestWithoutOverloads:
    @pytest.mark.asyncio
    async def test_a_plain_function_has_an_empty_list(self, analyzer: JediAnalyzer) -> None:
        node = await _node(analyzer, "pkg.spider.plain")

        assert node["overloads"] == []
        assert node["signature"] == "plain(x: int) -> int"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", ["pkg.methods.C", "pkg.spider"])
    async def test_other_kinds_have_no_field(self, analyzer: JediAnalyzer, handle: str) -> None:
        assert "overloads" not in await _node(analyzer, handle)


class TestTheLinterRules:
    @staticmethod
    def _node(**extra: Any) -> dict[str, Any]:
        node: dict[str, Any] = {
            "found": True,
            "handle": "pkg.mod.f",
            "kind": "function",
            "scope": "project",
            "location": {"file": "/x/pkg/mod.py", "line_start": 1, "line_end": 2},
            "docstring": None,
            "signature": "f()",
            "parameters": [],
            "is_async": False,
            "edge_counts": {},
        }
        node.update(extra)
        return node

    def test_b6_accepts_a_conditional_decorator(self) -> None:
        lint_response(
            self._node(deprecation=[{"kind": "conditional", "via": "decorator", "line": 4}]),
            "inspect",
        )

    @pytest.mark.parametrize("value", [[], ["f(x: int) -> int", "f(x: str) -> str"]])
    def test_b7_accepts_a_list_of_signatures(self, value: Any) -> None:
        lint_response(self._node(overloads=value), "inspect")

    @pytest.mark.parametrize(
        "value", [None, "f(x: int) -> int", [""], ["f(x)\n-> int"], [3], [None]]
    )
    def test_b7_rejects_anything_else(self, value: Any) -> None:
        with pytest.raises(ConformanceViolation, match=r"B\.7"):
            lint_response(self._node(overloads=value), "inspect")

    def test_b7_rejects_it_on_a_kind_it_does_not_apply_to(self) -> None:
        with pytest.raises(ConformanceViolation, match=r"B\.7"):
            lint_response(self._node(kind="class", overloads=[]), "inspect")
