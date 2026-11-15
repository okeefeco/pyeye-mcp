"""An internal failure is never reported as a fact about the user's code (#704).

#684's ``KeyError`` hid for days because broad ``except Exception`` blocks
turned it into ``unresolved``. The rule (#626 slice C, extended):

- **Single subject.** When the thing the caller asked about can't be computed
  (``resolve_handle``, definition placement, bare-name lookup, goto at a
  position), the exception propagates and the tool call is a loud crash.
- **Per item.** One bad file inside a multi-file scan doesn't sink the call: it
  is reported through the field's honest signal. ``re_exports`` has none, so the
  field is left ABSENT (unknown), never ``[]``.
- A genuine miss is still a response.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jedi
import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from pyeye import file_artifact_cache, resolver
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.resolver import NotFound, resolve_handle, resolve_name


class Boom(RuntimeError):
    """The injected internal failure."""


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise Boom("injected internal failure")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from pkg.mod import Thing\n")
    (pkg / "mod.py").write_text("class Thing:\n    pass\n")
    return tmp_path


@pytest.fixture
def analyzer(project: Path) -> JediAnalyzer:
    return JediAnalyzer(str(project))


class TestSingleSubjectFailuresPropagate:
    def test_resolve_handle_catch_all(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(resolver, "_resolve", _boom)
        with pytest.raises(Boom):
            resolve_handle("pkg.mod.Thing", analyzer)

    def test_definition_placement(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(file_artifact_cache, "get_script", _boom)
        with pytest.raises(Boom):
            resolve_handle("pkg.mod.Thing", analyzer)

    def test_external_synthetic_import(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # #684's path: Jedi raising inside inference of a valid external name.
        monkeypatch.setattr(jedi.Script, "infer", _boom)
        with pytest.raises(Boom):
            resolve_handle("json.loads", analyzer)

    def test_stdlib_public_definition_anchor(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(file_artifact_cache, "get_script", _boom)
        with pytest.raises(Boom):
            resolve_handle("collections.abc.Mapping", analyzer)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["find_symbol", "find_member_definitions"])
    async def test_bare_name_lookup(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch, method: str
    ) -> None:
        async def broken(*_args: Any, **_kwargs: Any) -> Any:
            raise Boom("injected")

        if method == "find_member_definitions":

            async def none(*_args: Any, **_kwargs: Any) -> list[Any]:
                return []

            monkeypatch.setattr(analyzer, "find_symbol", none)
        monkeypatch.setattr(analyzer, method, broken)
        with pytest.raises(Boom):
            await resolve_name("NoSuchName", analyzer)

    @pytest.mark.asyncio
    async def test_goto_at_position(
        self, project: Path, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jedi.Script, "goto", _boom)
        with pytest.raises(Boom):
            await resolve_at((project / "pkg" / "mod.py").as_posix(), 1, 6, analyzer)


class TestPerItemFailuresDontSinkTheCall:
    @pytest.mark.asyncio
    async def test_re_exports_left_absent_not_empty(
        self, analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bad file in the re-export scan: ``inspect`` still answers, ``re_exports`` is unknown."""
        from pyeye import canonicalization

        real = file_artifact_cache.get_script

        def flaky(path: Any, project: Any) -> Any:
            if Path(path).name == "__init__.py":
                raise Boom("one bad file")
            return real(path, project)

        monkeypatch.setattr(canonicalization.file_artifact_cache, "get_script", flaky)
        node = await inspect("pkg.mod.Thing", analyzer)

        assert node["found"] is True
        assert node["kind"] == "class"
        assert "re_exports" not in node  # unknown, never a false []

    @pytest.mark.asyncio
    async def test_re_exports_still_measured_when_nothing_fails(
        self, analyzer: JediAnalyzer
    ) -> None:
        node = await inspect("pkg.mod.Thing", analyzer)

        assert node["re_exports"] == ["pkg.Thing"]


class TestMissesAreStillResponses:
    def test_unknown_handle_is_not_found(self, analyzer: JediAnalyzer) -> None:
        assert isinstance(resolve_handle("pkg.mod.Nope", analyzer), NotFound)

    @pytest.mark.asyncio
    async def test_unknown_bare_name_is_not_found(self, analyzer: JediAnalyzer) -> None:
        result = await resolve("NoSuchNameAnywhere", analyzer)
        assert result["found"] is False


@pytest.mark.asyncio
async def test_an_injected_failure_is_a_tool_error_not_unresolved(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: the SDK reports a crash, never ``found: false``."""
    import importlib

    server = importlib.import_module("pyeye.mcp.server")
    monkeypatch.setattr(resolver, "_resolve", _boom)
    with pytest.raises(UnexpectedToolError):
        await server.mcp.call_tool(
            "resolve", {"identifier": "pkg.mod.Thing", "project_path": project.as_posix()}
        )


class TestResolveItem:
    """``resolve_item``: one bad item is that item's unknown, logged, never a sunk call."""

    def test_internal_failure_is_reported_as_an_internal_error(
        self,
        analyzer: JediAnalyzer,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from pyeye.resolver import resolve_item

        monkeypatch.setattr(resolver, "_resolve", _boom)
        with caplog.at_level("WARNING", logger="pyeye.resolver"):
            result = resolve_item("pkg.mod.Thing", analyzer)

        assert isinstance(result, NotFound)
        assert "internal error" in result.detail and "Boom" in result.detail
        assert any(
            "internal error resolving" in r.getMessage() and r.exc_info for r in caplog.records
        )

    def test_a_miss_is_still_a_plain_miss(self, analyzer: JediAnalyzer) -> None:
        from pyeye.resolver import resolve_item

        result = resolve_item("pkg.mod.Nope", analyzer)

        assert isinstance(result, NotFound)
        assert "internal error" not in result.detail

    @pytest.mark.asyncio
    async def test_trace_lists_a_failing_root_and_walks_the_rest(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye.mcp.operations.trace import trace

        analyzer = JediAnalyzer(str(project))
        real = resolver._resolve

        def flaky(path: str, an: Any, hops: int) -> Any:
            if path == "pkg.mod":
                raise Boom("one bad root")
            return real(path, an, hops)

        monkeypatch.setattr(resolver, "_resolve", flaky)
        result = await trace(["pkg.mod", "pkg.mod.Thing"], ["members"], analyzer)

        assert "pkg.mod" in result["unresolved_roots"]
        assert "pkg.mod.Thing" in result["nodes"]

    @pytest.mark.asyncio
    async def test_imports_edge_survives_one_failing_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye.mcp.operations.expand import expand

        (tmp_path / "m.py").write_text("from collections.abc import Mapping\nimport json\n")
        analyzer = JediAnalyzer(str(tmp_path))
        real = resolver._resolve

        def flaky(path: str, an: Any, hops: int) -> Any:
            if path == "collections.abc.Mapping":
                raise Boom("one bad import")
            return real(path, an, hops)

        monkeypatch.setattr(resolver, "_resolve", flaky)
        result = await expand("m", "imports", analyzer)

        assert result["found"] is True
        assert "json" in [s["handle"] for s in result["stubs"]]


class TestEdgeOwnFileLoads:
    """An edge loading its OWN file: internal failure → crash, never ``stubs: []`` (#704).

    A ``SyntaxError`` keeps today's answer here; #703 turns it into ``unparseable``.
    """

    EDGES = [
        ("pkg.mod.Thing", "members"),
        ("pkg.mod", "members"),
        ("pkg.mod.Thing.method", "callees"),
        ("pkg.mod.Thing", "superclasses"),
        ("pkg.mod", "imports"),
    ]

    @pytest.fixture
    def edge_project(self, tmp_path: Path) -> Path:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "mod.py").write_text(
            "import json\n\n\nclass Base:\n    pass\n\n\n"
            "class Thing(Base):\n    def method(self):\n        return json.dumps(1)\n"
        )
        return tmp_path

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("handle", "edge"), EDGES)
    async def test_internal_failure_propagates(
        self, edge_project: Path, monkeypatch: pytest.MonkeyPatch, handle: str, edge: str
    ) -> None:
        from pyeye.mcp.operations import edges
        from pyeye.mcp.operations.expand import expand

        analyzer = JediAnalyzer(str(edge_project))
        node = await expand(handle, edge, analyzer)  # resolves and warms caches
        assert node["found"] is True

        monkeypatch.setattr(edges.file_artifact_cache, "get_script", _boom)
        monkeypatch.setattr(edges.file_artifact_cache, "get_ast", _boom)
        with pytest.raises(Boom):
            await expand(handle, edge, analyzer)

    @pytest.mark.asyncio
    async def test_enclosing_scope_still_answers(self, edge_project: Path) -> None:
        """The narrowed catch (``AttributeError`` only) leaves normal answers alone."""
        from pyeye.mcp.operations.expand import expand

        result = await expand("pkg.mod.Thing", "enclosing_scope", JediAnalyzer(str(edge_project)))

        assert [s["handle"] for s in result["stubs"]] == ["pkg.mod"]
