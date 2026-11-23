"""A ``*args``/``**kwargs`` forwarder shows its declared signature, never Jedi's guess (#1125).

Jedi follows ``*args``/``**kwargs`` into the call they're forwarded to and
renders the callee's parameters as the forwarder's signature. For Scrapy's
``LxmlLinkExtractor._extract_links(self, *args, **kwargs)`` that gave
``(self, response_url, ..., /, *, response_url, ...)``: invalid Python (each
name positional-only AND keyword-only), with ``selector`` dropped. A partial
forwarder (``def f(self, a, *args, **kw)``) or a function forwarder got a
plausible but invented signature instead.

A signature pyeye shows must match the source: Jedi's rendering is kept only
when its parameter names are the declared ones, in order; otherwise the
declared signature is rendered from the AST (#437's fallback). A rendering with
a duplicated parameter name is never shown.
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

# The package re-exports the ``inspect`` function under the module's name.
inspect_module = importlib.import_module("pyeye.mcp.operations.inspect")

_FW = """\
from typing import Any


class Parser:
    def _extract(self, selector, response_url: str, response_encoding: str, base_url: str) -> list[str]:
        return []


def target(selector, url: str, *, strict: bool = False) -> int:
    return 0


class Extractor:
    def _extract(self, *args: Any, **kwargs: Any) -> list[str]:
        return Parser()._extract(*args, **kwargs)

    def partial(self, a: int, *args: Any, **kw: Any) -> int:
        return target(a, *args, **kw)


def to_function(*args: Any, **kwargs: Any) -> int:
    return target(*args, **kwargs)


def plain(a: int = 1, *rest: str, flag: bool = False) -> int:
    return a


class Kinds:
    @classmethod
    def make(cls, a: int = 1) -> int:
        return a

    @staticmethod
    def helper(a, b=2):
        return a
"""

_DECLARED = {
    "pkg.fw.Extractor._extract": "_extract(self, *args: Any, **kwargs: Any) -> list[str]",
    "pkg.fw.Extractor.partial": "partial(self, a: int, *args: Any, **kw: Any) -> int",
    "pkg.fw.to_function": "to_function(*args: Any, **kwargs: Any) -> int",
}


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "fw.py").write_text(_FW, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


class TestForwardersShowTheirDeclaredSignature:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", sorted(_DECLARED))
    async def test_inspect(self, analyzer: JediAnalyzer, handle: str) -> None:
        node = await inspect(handle, analyzer)

        assert node["signature"] == _DECLARED[handle]

    @pytest.mark.asyncio
    async def test_outline(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("pkg.fw.Extractor", analyzer)

        shown = {c["node"]["handle"]: c["node"].get("signature") for c in tree["children"]}
        assert shown["pkg.fw.Extractor._extract"] == _DECLARED["pkg.fw.Extractor._extract"]
        assert shown["pkg.fw.Extractor.partial"] == _DECLARED["pkg.fw.Extractor.partial"]


class TestOtherSignaturesAreUnchanged:
    @pytest.mark.asyncio
    async def test_a_plain_function_keeps_jedis_rendering(self, analyzer: JediAnalyzer) -> None:
        """Jedi renders defaults without spaces (``a: int=1``); that stays as it was."""
        node = await inspect("pkg.fw.plain", analyzer)

        assert node["signature"] == "plain(a: int=1, *rest: str, flag: bool=False) -> int"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handle", "shown"),
        # A classmethod gets no signature at all today (#1128, separate);
        # the cls-dropping rule is pinned below on its own.
        [("pkg.fw.Kinds.helper", "helper(a, b=2)")],
    )
    async def test_a_staticmethod_keeps_jedis_rendering(
        self, analyzer: JediAnalyzer, handle: str, shown: str
    ) -> None:
        assert (await inspect(handle, analyzer))["signature"] == shown

    @pytest.mark.asyncio
    async def test_the_callee_is_unaffected(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("pkg.fw.target", analyzer)

        assert node["signature"] == "target(selector, url: str, *, strict: bool=False) -> int"


def _fake_signature(names: list[str], rendered: str) -> Any:
    params = [SimpleNamespace(name=name) for name in names]
    return SimpleNamespace(params=params, to_string=lambda: rendered, module_path=None)


class TestTheDuplicateNameGuard:
    def test_a_duplicated_name_with_no_source_is_not_shown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing to fall back to: the signature is omitted, never shown invalid."""
        name = SimpleNamespace(
            name="f",
            module_path=None,
            line=None,
            get_signatures=lambda: [_fake_signature(["a", "a"], "f(a, /, *, a)")],
        )
        monkeypatch.setattr(inspect_module, "_restricted_signature", lambda _s: False)

        assert inspect_module._build_signature(name) is None

    def test_a_rendering_missing_a_declared_parameter_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rendering without the declared ``cls`` is replaced by the declared one.

        pyeye never gets such a rendering today: Jedi gives a classmethod's
        ``def`` no signature at all on every path (#1128 renders it from the
        source, ``cls`` shown). If Jedi ever did drop ``cls``, the declared
        signature, with ``cls``, is what's shown, consistent with #1128.
        """
        name = SimpleNamespace(
            name="make",
            module_path="/x/mod.py",
            line=3,
            get_signatures=lambda: [_fake_signature(["a"], "make(a: int=1)")],
        )
        monkeypatch.setattr(inspect_module, "_restricted_signature", lambda _s: False)
        monkeypatch.setattr(inspect_module, "_declared_parameter_names", lambda _n: ["cls", "a"])
        monkeypatch.setattr(
            inspect_module, "_signature_from_source_ast", lambda _n: "make(cls, a: int = 1)"
        )

        assert inspect_module._build_signature(name) == "make(cls, a: int = 1)"

    def test_distinct_names_with_no_source_are_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        name = SimpleNamespace(
            name="f",
            module_path=None,
            line=None,
            get_signatures=lambda: [_fake_signature(["a", "b"], "f(a, b)")],
        )
        monkeypatch.setattr(inspect_module, "_restricted_signature", lambda _s: False)

        assert inspect_module._build_signature(name) == "f(a, b)"
