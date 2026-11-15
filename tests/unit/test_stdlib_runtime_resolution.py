"""Standard-library symbols resolve to their runtime definition (#544).

``collections.abc.Mapping`` was an honest not-found: typeshed declares it as a
re-export of ``typing.Mapping``, the reverse of the runtime. The resolver now
asks the running interpreter for stdlib symbols, so every tool reports the
runtime's own handle, located in the runtime definition's source.
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
    def test_resolve_handle_names_the_runtime_class(
        self, leaf: str, analyzer: JediAnalyzer
    ) -> None:
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
        # ``typing.Mapping`` is an alias instance at runtime, not a class: the
        # runtime rule does not apply, and it is not rewritten to the ABC.
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
    async def test_imports_edge_names_the_imported_runtime_class(
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
    async def test_member_and_superclass_handles_use_the_runtime_owner(
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
        # count == expand (#599) holds for a runtime-renamed class
        assert node["edge_counts"]["members"] == len(members["stubs"])
        assert node["edge_counts"]["superclasses"] == len(supers["stubs"])

    @pytest.mark.asyncio
    async def test_enclosing_scope_of_a_member_is_the_runtime_class(
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
