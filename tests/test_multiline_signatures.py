"""A signature whose source spans lines is shown whole, on one line (#1159).

Jedi's ``Signature.to_string()`` keeps the source text of each annotation,
default and return type, newlines included. ``_build_signature`` made it
single-line by keeping only the text before the first newline, so a split
annotation (Scrapy's ``Request.__init__`` ``headers: Mapping[str, Any]\\n |
...``) cut the signature off mid-parameter: no closing parenthesis, and every
later parameter and the return type gone.

Now a multi-line rendering is parsed and re-rendered with ``ast.unparse``,
the style pyeye's own renderers use. Collapsing the whitespace instead would
be wrong twice over: Jedi keeps a comment inside a split annotation, which
would swallow the rest of the line, and a triple-quoted default holds real
newlines that are part of its value. A rendering that won't parse falls back
to the declared signature, or is omitted, never cut off.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline

inspect_module = importlib.import_module("pyeye.mcp.operations.inspect")

_ML = '''\
from typing import Any, Mapping


def f(
    url: str,
    headers: Mapping[str, Any]
    | Mapping[bytes, Any]
    | None = None,
    flag: bool = False,
) -> None: ...


def commented(
    headers: Mapping[str, Any]  # str keys
    | None = None,
    sep: str = """a
  b""",
) -> None: ...


def split_return(a: dict[
    str, int
]) -> list[
    int
]: ...


def plain(a: int = 1, *rest: str, flag: bool = False) -> int:
    return a


class Request:
    def __init__(
        self,
        url: str,
        headers: Mapping[str, Any]
        | None = None,
        *,
        n: int = (1 +
                  2),
    ) -> None: ...

    def meth(
        self,
        body: bytes
        | str = b"",
    ) -> bytes: ...
'''

_WHOLE = {
    "pkg.ml.f": (
        "f(url: str, headers: Mapping[str, Any] | Mapping[bytes, Any] | None=None, "
        "flag: bool=False) -> None"
    ),
    "pkg.ml.commented": "commented(headers: Mapping[str, Any] | None=None, sep: str='a\\n  b') -> None",
    "pkg.ml.split_return": "split_return(a: dict[str, int]) -> list[int]",
    "pkg.ml.Request": "Request(url: str, headers: Mapping[str, Any] | None=None, *, n: int=1 + 2)",
    "pkg.ml.Request.meth": "meth(self, body: bytes | str=b'') -> bytes",
}


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "ml.py").write_text(_ML, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


def _balanced(signature: str) -> bool:
    depth = 0
    for char in signature:
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0


class TestTheWholeSignatureIsShown:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", sorted(_WHOLE))
    async def test_inspect(self, analyzer: JediAnalyzer, handle: str) -> None:
        node = await inspect(handle, analyzer)

        assert node["signature"] == _WHOLE[handle]

    @pytest.mark.asyncio
    async def test_outline_and_stubs(self, analyzer: JediAnalyzer) -> None:
        """Outline nodes are the stubs every edge returns, so this covers both."""
        module = await outline("pkg.ml", analyzer)
        cls = await outline("pkg.ml.Request", analyzer)

        shown = {
            c["node"]["handle"]: c["node"].get("signature")
            for tree in (module, cls)
            for c in tree["children"]
        }
        for handle, signature in _WHOLE.items():
            assert shown[handle] == signature, handle

    @pytest.mark.asyncio
    async def test_no_signature_is_cut_off(self, analyzer: JediAnalyzer) -> None:
        """Every signature shown is one line with balanced brackets."""
        module = await outline("pkg.ml", analyzer, max_depth=2)

        def walk(children: list[dict[str, Any]]) -> list[str]:
            found = []
            for child in children:
                if "signature" in child["node"]:
                    found.append(child["node"]["signature"])
                found += walk(child.get("children", []))
            return found

        signatures = walk(module["children"])
        assert len(signatures) >= len(_WHOLE)
        for signature in signatures:
            assert "\n" not in signature and "\r" not in signature, signature
            assert _balanced(signature), signature


class TestASingleLineRenderingIsUnchanged:
    @pytest.mark.asyncio
    async def test_jedis_own_formatting_stays(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("pkg.ml.plain", analyzer)

        assert node["signature"] == "plain(a: int=1, *rest: str, flag: bool=False) -> int"


def _name(rendered: str, names: list[str]) -> Any:
    signature = SimpleNamespace(
        params=[SimpleNamespace(name=n) for n in names],
        to_string=lambda: rendered,
        module_path=None,
    )
    return SimpleNamespace(
        name="f", module_path=None, line=None, get_signatures=lambda: [signature]
    )


class TestARenderingThatCantBeMadeWhole:
    def test_it_falls_back_to_the_declared_signature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(inspect_module, "_restricted_signature", lambda _s: False)
        monkeypatch.setattr(inspect_module, "_signature_from_source_ast", lambda _n: "f(a: int)")

        assert inspect_module._build_signature(_name("f(a: Weird[\n  ?!)", ["a"])) == "f(a: int)"

    def test_without_source_it_is_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(inspect_module, "_restricted_signature", lambda _s: False)
        monkeypatch.setattr(inspect_module, "_signature_from_source_ast", lambda _n: None)

        assert inspect_module._build_signature(_name("f(a: Weird[\n  ?!)", ["a"])) is None

    def test_a_crlf_rendering_is_made_whole(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(inspect_module, "_restricted_signature", lambda _s: False)

        rendered = "f(a: int\r\n    | None=None) -> None"
        assert inspect_module._build_signature(_name(rendered, ["a"])) == (
            "f(a: int | None=None) -> None"
        )
