"""A TYPE_CHECKING-only binding never hides the runtime definition of the same name (#1106).

Scrapy's ``Spider`` declares ``parse: CallbackT`` under ``if TYPE_CHECKING:``
and defines ``def parse(self, response, **kwargs)`` in the ``else:`` branch.
The resolver kept the FIRST binding, so ``members``, ``inspect`` and
``outline`` reported ``parse`` as an ``attribute`` at the annotation, with no
signature or docstring. The runtime binding now wins for kind, signature,
docstring and location, as the implementation wins over ``@overload`` stubs
(#1088), using #1081's reading of the guard. A name bound ONLY under the guard
is unchanged.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from pyeye._module_scope import type_only_lines
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.resolver import prefer_runtime_bindings

_SPIDER = '''\
import typing
from typing import TYPE_CHECKING, Any, Callable

CallbackT = Callable[..., Any]


class Spider:
    if TYPE_CHECKING:
        parse: CallbackT
    else:

        def parse(self, response: str, **kwargs: Any) -> None:
            """Handle a response."""
            raise NotImplementedError


class Reversed:
    if not TYPE_CHECKING:

        def parse(self, response):
            """Runtime first."""
            return response
    else:
        parse: CallbackT


class Dotted:
    if typing.TYPE_CHECKING:
        parse: CallbackT
    else:

        def parse(self, response):
            """Via typing.TYPE_CHECKING."""
            return response


class OnlyDeclared:
    if TYPE_CHECKING:
        parse: CallbackT


if TYPE_CHECKING:
    handler: CallbackT
else:

    def handler(x):
        """Module level."""
        return x

'''


def _line(needle: str, nth: int = 1) -> int:
    hits = [i for i, line in enumerate(_SPIDER.splitlines(), 1) if needle in line]
    return hits[nth - 1]


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "spider.py").write_text(_SPIDER, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


def _start(result: Any) -> int:
    assert result.get("found", True) is True, result
    return int(result["location"]["line_start"])


def _runtime_line(handle: str) -> int:
    return {
        "pkg.spider.Spider.parse": _line("def parse(self, response: str, **kwargs: Any) -> None:"),
        "pkg.spider.Reversed.parse": _line("def parse(self, response):", 1),
        "pkg.spider.Dotted.parse": _line("def parse(self, response):", 2),
        "pkg.spider.handler": _line("def handler(x):"),
    }[handle]


_DOCS = {
    "pkg.spider.Spider.parse": "Handle a response.",
    "pkg.spider.Reversed.parse": "Runtime first.",
    "pkg.spider.Dotted.parse": "Via typing.TYPE_CHECKING.",
    "pkg.spider.handler": "Module level.",
}
_HANDLES = list(_DOCS)
_SIGNATURES = {
    "pkg.spider.Spider.parse": "parse(self, response: str, **kwargs: Any) -> None",
    "pkg.spider.Reversed.parse": "parse(self, response)",
    "pkg.spider.Dotted.parse": "parse(self, response)",
    "pkg.spider.handler": "handler(x)",
}


class TestTypeOnlyLines:
    def test_the_guarded_branch_only(self) -> None:
        lines = type_only_lines(ast.parse(_SPIDER))

        assert _line("parse: CallbackT", 1) in lines
        assert _line("parse: CallbackT", 2) in lines  # the else of ``if not``
        assert _line("parse: CallbackT", 3) in lines  # typing.TYPE_CHECKING
        assert _line("handler: CallbackT") in lines
        for handle in _HANDLES:
            assert _runtime_line(handle) not in lines

    def test_an_aliased_guard_and_a_plain_if(self) -> None:
        tree = ast.parse(
            "from typing import TYPE_CHECKING as TC\n"
            "import sys\n"
            "if TC:\n"
            "    a: int\n"
            "if sys.version_info >= (3, 12):\n"
            "    b = 1\n"
        )

        assert type_only_lines(tree) == frozenset({4})


class TestTheRuntimeDefinitionWins:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", _HANDLES)
    async def test_resolve(self, analyzer: JediAnalyzer, handle: str) -> None:
        result = await resolve(handle, analyzer)

        assert result["kind"] in ("method", "function"), result
        assert _start(result) == _runtime_line(handle)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", _HANDLES)
    async def test_inspect(self, analyzer: JediAnalyzer, handle: str) -> None:
        node = await inspect(handle, analyzer)

        assert node["kind"] in ("method", "function"), node
        assert _start(node) == _runtime_line(handle)
        assert node["docstring"] == _DOCS[handle]
        assert node["signature"] == _SIGNATURES[handle]

    @pytest.mark.asyncio
    async def test_inspect_reads_the_runtime_annotations(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("pkg.spider.Spider.parse", analyzer)

        assert [(p["name"], p.get("type", {}).get("raw")) for p in node["parameters"]] == [
            ("self", None),
            ("response", "str"),
            ("kwargs", "Any"),
        ]
        assert node["return_type"]["raw"] == "None"

    @pytest.mark.asyncio
    async def test_resolve_at_on_the_declaration(
        self, analyzer: JediAnalyzer, tmp_path: Path
    ) -> None:
        line = _line("parse: CallbackT", 1)
        result = await resolve_at((tmp_path / "pkg" / "spider.py").as_posix(), line, 8, analyzer)

        assert result.get("handle") == "pkg.spider.Spider.parse"
        assert _start(result) == _runtime_line("pkg.spider.Spider.parse")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", ["Spider", "Reversed", "Dotted"])
    async def test_members(self, analyzer: JediAnalyzer, cls: str) -> None:
        edge = await expand(f"pkg.spider.{cls}", "members", analyzer)

        stubs = [s for s in edge["stubs"] if s["handle"].endswith(".parse")]
        assert len(stubs) == 1, edge
        assert stubs[0]["kind"] == "method", stubs
        assert stubs[0]["line_start"] == _runtime_line(f"pkg.spider.{cls}.parse")

    @pytest.mark.asyncio
    async def test_module_members(self, analyzer: JediAnalyzer) -> None:
        edge = await expand("pkg.spider", "members", analyzer)

        stubs = [s for s in edge["stubs"] if s["handle"] == "pkg.spider.handler"]
        assert len(stubs) == 1, edge
        assert stubs[0]["kind"] == "function", stubs
        assert stubs[0]["line_start"] == _runtime_line("pkg.spider.handler")

    @pytest.mark.asyncio
    async def test_outline(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("pkg.spider.Spider", analyzer)

        children = [
            c["node"] for c in tree["children"] if c["node"]["handle"] == "pkg.spider.Spider.parse"
        ]
        assert len(children) == 1, tree
        assert children[0]["kind"] == "method", children
        assert children[0]["line_start"] == _runtime_line("pkg.spider.Spider.parse")


class TestADeclarationAloneIsUnchanged:
    @pytest.mark.asyncio
    async def test_inspect(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("pkg.spider.OnlyDeclared.parse", analyzer)

        assert node["kind"] == "attribute", node
        assert _start(node) == _line("parse: CallbackT", 4)

    @pytest.mark.asyncio
    async def test_members(self, analyzer: JediAnalyzer) -> None:
        edge = await expand("pkg.spider.OnlyDeclared", "members", analyzer)

        assert [(s["handle"], s["kind"]) for s in edge["stubs"]] == [
            ("pkg.spider.OnlyDeclared.parse", "attribute")
        ]


class _Name:
    """A stand-in for a Jedi ``Name``: just its file and line."""

    def __init__(self, module_path: Path | None, line: int) -> None:
        self.module_path = module_path
        self.line = line


class TestPreferRuntimeBindings:
    @pytest.fixture
    def guarded(self, tmp_path: Path) -> Path:
        path = tmp_path / "m.py"
        path.write_text(
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    a: int\n    b: int\nelse:\n    a = 1\n"
        )
        return path

    def test_drops_the_type_only_bindings(self, guarded: Path) -> None:
        names = [_Name(guarded, 3), _Name(guarded, 6)]

        assert prefer_runtime_bindings(names) == [names[1]]

    def test_all_type_only_is_unchanged(self, guarded: Path) -> None:
        names = [_Name(guarded, 3), _Name(guarded, 4)]

        assert prefer_runtime_bindings(names) == names

    def test_names_from_several_files_are_unchanged(self, guarded: Path, tmp_path: Path) -> None:
        names = [_Name(guarded, 3), _Name(tmp_path / "other.py", 6)]

        assert prefer_runtime_bindings(names) == names

    def test_a_file_python_cant_parse_is_unchanged(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.py"
        path.write_text("if TYPE_CHECKING:\n    a: int\ndef (:\n")
        names = [_Name(path, 2), _Name(path, 3)]

        assert prefer_runtime_bindings(names) == names
