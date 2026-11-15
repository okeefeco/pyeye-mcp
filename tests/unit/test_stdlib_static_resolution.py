"""Stdlib names: public handles for private definitions (#544), and the
platform decision point for ``os.path`` (#329). All static; identical on every OS.

``collections.abc.Mapping`` was an honest not-found: typeshed declares it as a
re-export of ``typing.Mapping``, the reverse of the real source. The resolver
follows the real ``.py`` chain to ``class Mapping`` in ``_collections_abc.py``
and names it by the public module, ``collections.abc.Mapping``, in every tool.
"""

from __future__ import annotations

import datetime
import json
import pathlib
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from pyeye.resolver import Resolved, resolve_handle

_ABCS = ["Mapping", "Sequence", "Iterable", "Iterator", "MutableMapping", "Awaitable", "Callable"]


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(Path(__file__).parent))


class TestCollectionsAbc:
    @pytest.mark.parametrize("leaf", _ABCS)
    def test_resolve_handle_names_the_public_class(self, leaf: str, analyzer: JediAnalyzer) -> None:
        result = resolve_handle(f"collections.abc.{leaf}", analyzer)

        assert isinstance(result, Resolved), result
        assert result.handle == f"collections.abc.{leaf}"
        assert result.kind == "class"
        assert result.scope == "external"
        assert Path(str(result.anchor.module_path)).name == "_collections_abc.py"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identifier", ["collections.abc.Mapping", "_collections_abc.Mapping"])
    async def test_resolve_and_inspect_agree(self, identifier: str, analyzer: JediAnalyzer) -> None:
        resolved = await resolve(identifier, analyzer)
        node = await inspect(identifier, analyzer)

        assert resolved["found"] is True, resolved
        assert node["found"] is True, node
        assert resolved["handle"] == node["handle"] == "collections.abc.Mapping"
        assert resolved["kind"] == node["kind"] == "class"
        assert resolved["location"]["file"].endswith("_collections_abc.py")
        assert node["location"] == resolved["location"]

    def test_member_follows_its_owner_class(self, analyzer: JediAnalyzer) -> None:
        result = resolve_handle("collections.abc.Mapping.get", analyzer)

        assert isinstance(result, Resolved), result
        assert result.handle == "collections.abc.Mapping.get"
        assert result.kind == "method"

    def test_canonical_handle_is_idempotent(self, analyzer: JediAnalyzer) -> None:
        first = resolve_handle("collections.abc.Mapping", analyzer)
        assert isinstance(first, Resolved)
        again = resolve_handle(first.handle, analyzer)
        assert isinstance(again, Resolved)
        assert again.handle == first.handle


class TestUnchangedStdlib:
    """Names the resolver already placed keep their handles."""

    @pytest.mark.parametrize(
        ("identifier", "expected"),
        [
            ("json.loads", "json.loads"),
            ("json.JSONDecoder", f"{json.JSONDecoder.__module__}.JSONDecoder"),
            ("pathlib.Path", f"{pathlib.Path.__module__}.Path"),
            ("datetime.datetime", f"{datetime.datetime.__module__}.datetime"),
            ("asyncio.Queue", "asyncio.queues.Queue"),
        ],
    )
    def test_handle(self, identifier: str, expected: str, analyzer: JediAnalyzer) -> None:
        result = resolve_handle(identifier, analyzer)

        assert isinstance(result, Resolved), result
        assert result.handle == expected

    def test_typing_alias_is_not_turned_into_a_different_object(
        self, analyzer: JediAnalyzer
    ) -> None:
        # ``typing.Mapping`` is defined in ``typing`` (a public module): the #544
        # exception does not apply, and it is never rewritten to the ABC.
        result = resolve_handle("typing.Mapping", analyzer)

        assert not isinstance(result, Resolved) or result.handle == "typing.Mapping"


_IMPORTER = """\
import os.path
from collections.abc import Iterable, Mapping
from json import JSONDecoder


def f(p: str, m: Mapping, items: Iterable[int]) -> str:
    return os.path.join(p, "x")
"""


@pytest.fixture
def importer(tmp_path: Path) -> JediAnalyzer:
    (tmp_path / "importer.py").write_text(_IMPORTER)
    return JediAnalyzer(str(tmp_path))


class TestToolsAgreeOnStdlibHandles:
    """Every tool emits the handle ``resolve`` reports (#544, #614)."""

    @pytest.mark.asyncio
    async def test_imports_edge_names_the_imported_public_class(
        self, importer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.expand import expand

        result = await expand("importer", "imports", importer)
        handles = {s["handle"] for s in result["stubs"]}

        assert {"collections.abc.Mapping", "collections.abc.Iterable"} <= handles
        assert not {h for h in handles if h.startswith("typing.")}
        assert f"{json.JSONDecoder.__module__}.JSONDecoder" in handles
        for handle in handles:
            resolved = resolve_handle(handle, importer)
            assert isinstance(resolved, Resolved) and resolved.handle == handle, handle

    @pytest.mark.asyncio
    async def test_parameter_typeref_round_trips(self, importer: JediAnalyzer) -> None:
        node = await inspect("importer.f", importer)
        types = {p["name"]: p["type"] for p in node["parameters"]}

        assert types["m"]["handle"] == "collections.abc.Mapping"
        assert types["items"]["handle"] == "collections.abc.Iterable"
        resolved = resolve_handle(types["m"]["handle"], importer)
        assert isinstance(resolved, Resolved) and resolved.handle == "collections.abc.Mapping"

    @pytest.mark.asyncio
    async def test_member_and_superclass_handles_use_the_public_owner(
        self, analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.expand import expand

        members = await expand("collections.abc.Mapping", "members", analyzer)
        supers = await expand("collections.abc.Mapping", "superclasses", analyzer)
        node = await inspect("collections.abc.Mapping", analyzer)

        member_handles = [s["handle"] for s in members["stubs"]]
        assert "collections.abc.Mapping.get" in member_handles
        assert all(h.startswith("collections.abc.Mapping.") for h in member_handles)
        assert [s["handle"] for s in supers["stubs"]] == ["collections.abc.Collection"]
        assert node["superclasses"] == ["collections.abc.Collection"]
        # count == expand (#599) holds for a publicly-renamed class
        assert node["edge_counts"]["members"] == len(members["stubs"])
        assert node["edge_counts"]["superclasses"] == len(supers["stubs"])

    @pytest.mark.asyncio
    async def test_enclosing_scope_of_a_member_is_the_public_class(
        self, analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.expand import expand

        result = await expand("collections.abc.Mapping.get", "enclosing_scope", analyzer)

        assert [s["handle"] for s in result["stubs"]] == ["collections.abc.Mapping"]


class TestProjectShadowingAStdlibName:
    """A project package that shares a stdlib name is never renamed (#544 guard)."""

    @pytest.mark.asyncio
    async def test_project_json_is_untouched(self, tmp_path: Path) -> None:
        from pyeye.mcp.operations.expand import expand

        pkg = tmp_path / "json"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "class JSONDecoder:\n    def decode(self):\n        pass\n"
        )
        analyzer = JediAnalyzer(str(tmp_path))

        resolved = resolve_handle("json.JSONDecoder", analyzer)
        members = await expand("json.JSONDecoder", "members", analyzer)

        assert isinstance(resolved, Resolved)
        assert resolved.handle == "json.JSONDecoder"
        assert resolved.scope == "project"
        assert [s["handle"] for s in members["stubs"]] == ["json.JSONDecoder.decode"]


class TestOsPathDecisionPoint:
    """``os.path`` names are located at the ``sys.platform`` branch (#329).

    Neither ``ntpath.py`` nor ``posixpath.py``: the typeshed ``os/path.pyi``
    block that selects between them, the same on every OS.
    """

    @staticmethod
    def _assert_decision_point(file: str, line_start: int) -> None:
        assert file.endswith("stdlib/os/path.pyi"), file
        assert Path(file).read_text().splitlines()[line_start - 1].startswith("if sys.platform")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("identifier", "kind"), [("os.path.join", "function"), ("os.path", "module")]
    )
    async def test_resolve_and_inspect(
        self, identifier: str, kind: str, analyzer: JediAnalyzer
    ) -> None:
        resolved = await resolve(identifier, analyzer)
        node = await inspect(identifier, analyzer)

        assert resolved["found"] is True and node["found"] is True
        assert resolved["handle"] == node["handle"] == identifier
        assert resolved["kind"] == node["kind"] == kind
        self._assert_decision_point(
            resolved["location"]["file"], resolved["location"]["line_start"]
        )
        assert node["location"] == resolved["location"]

    @pytest.mark.asyncio
    async def test_callee_stub_is_at_the_decision_point(self, importer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.expand import expand

        resolved = await resolve("os.path.join", importer)
        callees = await expand("importer.f", "callees", importer)
        stub = next(s for s in callees["stubs"] if s["handle"] == "os.path.join")

        assert stub["line_start"] == resolved["location"]["line_start"]
        assert stub["line_end"] == resolved["location"]["line_end"]
        assert stub["kind"] == "function"
