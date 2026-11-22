"""A ``@classmethod`` shows its declared signature, ``cls`` included (#1128).

Jedi infers a classmethod's ``def`` as an instance of ``builtins.classmethod``
(the descriptor). typeshed's ``classmethod`` has no call signature, so
``get_signatures()`` is ``[]`` and ``inspect`` / ``outline`` showed no
signature at all, while a staticmethod and a plain method in the same class
had one. The declared signature is rendered from the source AST, showing
``cls`` the way a plain method shows ``self``.

``@property`` infers ``builtins.property`` and deliberately stays unsigned:
a property is read, not called.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline

# The package re-exports the ``inspect`` function under the module's name.
inspect_module = importlib.import_module("pyeye.mcp.operations.inspect")

_KINDS = """\
from abc import ABC, abstractmethod


class Kinds:
    @classmethod
    def make(cls, a: int = 1) -> int:
        return a

    @classmethod
    def bare(cls):
        return cls

    @staticmethod
    def helper(a, b=2):
        return a

    def plain(self, a: int = 1) -> int:
        return a

    @property
    def prop(self) -> int:
        return 1


class Base(ABC):
    @classmethod
    @abstractmethod
    def build(cls, x: str, /, *, strict: bool = False) -> "Base":
        ...
"""

# Defaults render without spaces (``a: int=1``), as Jedi renders them for a
# plain method, so a classmethod and its siblings read the same way.
_CLASSMETHODS = {
    "pkg.kinds.Kinds.make": "make(cls, a: int=1) -> int",
    "pkg.kinds.Kinds.bare": "bare(cls)",
    "pkg.kinds.Base.build": "build(cls, x: str, /, *, strict: bool=False) -> 'Base'",
}


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "kinds.py").write_text(_KINDS, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


class TestAClassmethodHasASignature:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("handle", sorted(_CLASSMETHODS))
    async def test_inspect(self, analyzer: JediAnalyzer, handle: str) -> None:
        node = await inspect(handle, analyzer)

        assert node["signature"] == _CLASSMETHODS[handle]

    @pytest.mark.asyncio
    async def test_outline(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("pkg.kinds.Kinds", analyzer)

        shown = {c["node"]["handle"]: c["node"].get("signature") for c in tree["children"]}
        assert shown["pkg.kinds.Kinds.make"] == _CLASSMETHODS["pkg.kinds.Kinds.make"]
        assert shown["pkg.kinds.Kinds.bare"] == _CLASSMETHODS["pkg.kinds.Kinds.bare"]

    @pytest.mark.asyncio
    async def test_outline_of_an_abstract_classmethod(self, analyzer: JediAnalyzer) -> None:
        tree = await outline("pkg.kinds.Base", analyzer)

        shown = {c["node"]["handle"]: c["node"].get("signature") for c in tree["children"]}
        assert shown["pkg.kinds.Base.build"] == _CLASSMETHODS["pkg.kinds.Base.build"]


class TestSiblingsAreUnchanged:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handle", "shown"),
        [
            ("pkg.kinds.Kinds.helper", "helper(a, b=2)"),
            ("pkg.kinds.Kinds.plain", "plain(self, a: int=1) -> int"),
        ],
    )
    async def test_staticmethod_and_plain_method(
        self, analyzer: JediAnalyzer, handle: str, shown: str
    ) -> None:
        assert (await inspect(handle, analyzer))["signature"] == shown

    @pytest.mark.asyncio
    async def test_a_property_stays_unsigned(self, analyzer: JediAnalyzer) -> None:
        """Deliberate: a property is read, not called (#1128's decision entry)."""
        node = await inspect("pkg.kinds.Kinds.prop", analyzer)

        assert "signature" not in node


class TestTheClassmethodBranch:
    def test_a_classmethod_with_no_source_is_omitted(self) -> None:
        """No ``def`` to render from (a C extension): omitted, never ``""``."""
        descriptor = SimpleNamespace(full_name="builtins.classmethod")
        name = SimpleNamespace(
            name="make",
            module_path=None,
            line=None,
            get_signatures=lambda: [],
            infer=lambda: [descriptor],
        )

        assert inspect_module._build_signature(name) is None

    def test_an_unsigned_non_classmethod_is_still_omitted(self) -> None:
        """The branch keys on ``builtins.classmethod`` only (a property isn't one)."""
        descriptor = SimpleNamespace(full_name="builtins.property")
        name = SimpleNamespace(
            name="prop",
            module_path="/nonexistent/kinds.py",
            line=3,
            get_signatures=lambda: [],
            infer=lambda: [descriptor],
        )

        assert inspect_module._build_signature(name) is None
