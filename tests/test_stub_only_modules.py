"""A project module that exists only as a ``.pyi`` stub has a handle everywhere (#933).

The maintainer's ruling (option A):

1. A project stub-only module (``pkg/stubonly.pyi``, no ``stubonly.py``) gets a
   handle across the whole surface, located at the ``.pyi``. A ``.py`` beside a
   stub still wins (#885).
3. A stub's own imports don't count in ``imported_by``, and its ceiling says so.
4. An in-project ``foo-stubs/`` package gets no handles and isn't enumerated.
5. A body edge (``callees``) on a stub declaration is ``unsupported``, reason
   ``stub_declaration``: a stub has no bodies to read. That holds for an
   external stub (typeshed) too.

2. The marker is a documented flag (the maintainer's ruling, via designer):
   ``stub: true`` on every node whose definition site is a ``.pyi``, absent
   for source. Whether a file is a stub is always measured, so its absence is
   a measured "no". The conformance linter's Check D enforces it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from pyeye.mcp.server import mcp
from pyeye.project_layout import declaration_kind, mark_stub
from tests.conformance.response_linter import lint_response

FIXTURE = Path(__file__).parent / "fixtures" / "stub_only"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The ``stub_only`` corpus, plus a stub/source pair and a ``-stubs`` dir.

    The corpus's ``pkg.declared`` stub imports and subclasses ``pkg.base``.
    """
    root = tmp_path / "proj"
    shutil.copytree(FIXTURE, root)
    pkg = root / "pkg"
    (pkg / "mixed.py").write_text("def g(x):\n    return x\n", encoding="utf-8")
    (pkg / "mixed.pyi").write_text("def g(x: int) -> int: ...\n", encoding="utf-8")
    vendored = root / "foo-stubs"
    vendored.mkdir()
    (vendored / "__init__.pyi").write_text("X: int\n", encoding="utf-8")
    (vendored / "util.pyi").write_text("def helper() -> int: ...\n", encoding="utf-8")
    return root


async def _call(tool: str, project: Path, **args: Any) -> dict[str, Any]:
    result = await mcp.call_tool(tool, {**args, "project_path": project.as_posix()})
    assert not result.is_error, result.content
    response: dict[str, Any] = result.structured_content  # type: ignore[assignment]
    return response


def _stub_handles(response: dict[str, Any]) -> list[str]:
    return [s["handle"] for s in response["stubs"]]


class TestHandles:
    """(1) The stub-only module resolves, inspects, outlines and expands, at its ``.pyi``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("dotted", "kind", "line"),
        [
            ("pkg.stubonly", "module", 1),
            ("pkg.stubonly.S", "class", 3),
            ("pkg.stubonly.f", "function", 6),
        ],
    )
    async def test_dotted_resolve_and_inspect(
        self, project: Path, dotted: str, kind: str, line: int
    ) -> None:
        resolved = await _call("resolve", project, identifier=dotted)
        inspected = await _call("inspect", project, handle=dotted)

        for response in (resolved, inspected):
            assert response["found"] is True, response
            assert (response["handle"], response["kind"], response["scope"]) == (
                dotted,
                kind,
                "project",
            )
            assert response["location"]["file"] == (project / "pkg" / "stubonly.pyi").as_posix()
            assert response["location"]["line_start"] == line

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool", "args", "handle"),
        [
            ("resolve", {"identifier": "pkg/stubonly.pyi"}, "pkg.stubonly"),
            ("resolve", {"identifier": "pkg/stubonly.pyi:3"}, "pkg.stubonly.S"),
            ("resolve_at", {"file": "pkg/stubonly.pyi", "line": 3, "column": 6}, "pkg.stubonly.S"),
        ],
    )
    async def test_every_file_form_resolves(
        self, project: Path, tool: str, args: dict[str, Any], handle: str
    ) -> None:
        found = await _call(tool, project, **args)

        assert found["found"] is True and found["handle"] == handle, found
        assert found["location"]["file"] == (project / "pkg" / "stubonly.pyi").as_posix()

    @pytest.mark.asyncio
    async def test_outline_and_members(self, project: Path) -> None:
        outline = await _call("outline", project, handle="pkg.stubonly")
        members = await _call("expand", project, handle="pkg.stubonly", edge="members")

        assert outline["found"] is True
        assert [c["node"]["handle"] for c in outline["children"]] == [
            "pkg.stubonly.S",
            "pkg.stubonly.f",
        ]
        assert sorted(_stub_handles(members)) == ["pkg.stubonly.S", "pkg.stubonly.f"]

    @pytest.mark.asyncio
    async def test_it_is_a_submodule_of_its_package(self, project: Path) -> None:
        submodules = await _call("expand", project, handle="pkg", edge="submodules")

        assert _stub_handles(submodules) == [
            "pkg.base",
            "pkg.declared",
            "pkg.mixed",
            "pkg.stubonly",
        ]

    @pytest.mark.asyncio
    async def test_a_stub_class_is_a_subclass_of_its_project_base(self, project: Path) -> None:
        """``superclasses`` and ``subclasses`` agree for a class declared in a stub."""
        supers = await _call("expand", project, handle="pkg.declared.Sub", edge="superclasses")
        subs = await _call("expand", project, handle="pkg.base.Base", edge="subclasses")

        assert _stub_handles(supers) == ["pkg.base.Base"]
        assert _stub_handles(subs) == ["pkg.declared.Sub"]

    @pytest.mark.asyncio
    async def test_a_bare_name_finds_it(self, project: Path) -> None:
        found = await _call("resolve", project, identifier="Sub")

        assert found["found"] is True and found["handle"] == "pkg.declared.Sub"

    @pytest.mark.asyncio
    async def test_a_stub_beside_its_source_still_lands_on_the_source(self, project: Path) -> None:
        """#885 unchanged: the ``.py`` wins, in the dotted and the file forms."""
        for identifier in ("pkg.mixed", "pkg/mixed.pyi"):
            found = await _call("resolve", project, identifier=identifier)
            assert found["handle"] == "pkg.mixed"
            assert found["location"]["file"] == (project / "pkg" / "mixed.py").as_posix()

    @pytest.mark.asyncio
    async def test_the_importers_imports_resolve_into_the_stub(self, project: Path) -> None:
        imports = await _call("expand", project, handle="app", edge="imports")

        assert {"pkg.stubonly.S", "pkg.stubonly.f"} <= set(_stub_handles(imports))


class TestImportedBy:
    """(3) A stub's imports are declarations, not runtime dependencies."""

    @pytest.mark.asyncio
    async def test_a_stub_importer_is_not_counted(self, project: Path) -> None:
        importers = await _call("expand", project, handle="pkg.base", edge="imported_by")

        assert "pkg.declared" not in _stub_handles(importers)
        assert importers["unresolved_importers"] == []

    @pytest.mark.asyncio
    async def test_the_stubs_own_imports_still_list(self, project: Path) -> None:
        """The forward ``imports`` edge reads the stub's own statements, as written."""
        imports = await _call("expand", project, handle="pkg.declared", edge="imports")

        assert "pkg.base.Base" in _stub_handles(imports)

    @pytest.mark.asyncio
    async def test_the_ceiling_says_so(self, project: Path) -> None:
        from pyeye.mcp.operations.edges import CEILING_MEANINGS, EDGE_CEILINGS

        importers = await _call("expand", project, handle="pkg.base", edge="imported_by")

        assert importers["ceiling"] == EDGE_CEILINGS["imported_by"]
        assert ".pyi" in CEILING_MEANINGS[EDGE_CEILINGS["imported_by"]]


class TestVendoredStubsPackage:
    """(4) An in-project ``foo-stubs/`` is someone else's type information: no handles."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identifier", ["foo-stubs/util.pyi", "foo-stubs/__init__.pyi"])
    async def test_its_files_have_no_handle(self, project: Path, identifier: str) -> None:
        miss = await _call("resolve", project, identifier=identifier)

        assert miss["found"] is False

    @pytest.mark.asyncio
    async def test_it_is_not_enumerated(self, project: Path) -> None:
        found = await _call("resolve", project, identifier="helper")

        assert found["found"] is False

    def test_the_mapper_names_none_of_it(self, project: Path) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.project_layout import iter_module_files, module_name_for_file

        analyzer = JediAnalyzer(project.as_posix())

        assert module_name_for_file(analyzer, project / "foo-stubs" / "util.pyi") is None
        listed = {p.relative_to(project).as_posix() for p in iter_module_files(project)}
        assert not any(p.startswith("foo-stubs/") for p in listed)
        assert {"pkg/stubonly.pyi", "pkg/declared.pyi", "pkg/mixed.py"} <= listed
        assert "pkg/mixed.pyi" not in listed  # a stub beside its source isn't a module file


class TestModuleFiles:
    """The scans list ``.py`` and stub-only ``.pyi`` in one walk (#933)."""

    @pytest.mark.asyncio
    async def test_one_listing_for_both_suffixes(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer

        analyzer = JediAnalyzer(project.as_posix())
        patterns: list[Any] = []
        real = analyzer.get_project_files

        async def counting(pattern: Any = "*.py", *args: Any, **kwargs: Any) -> list[Path]:
            patterns.append(pattern)
            return await real(pattern, *args, **kwargs)

        monkeypatch.setattr(analyzer, "get_project_files", counting)
        files = await analyzer.get_module_files(scope="main")

        assert patterns == [("*.py", "*.pyi")]
        listed = {f.relative_to(project).as_posix() for f in files}
        assert {"pkg/stubonly.pyi", "pkg/mixed.py", "app.py"} <= listed
        assert "pkg/mixed.pyi" not in listed and not any(p.startswith("foo-stubs/") for p in listed)


class TestBodyEdges:
    """(5) A stub has no bodies: ``callees`` on its declarations is refused, never ``[]``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle", ["pkg.stubonly.f", "pkg.stubonly.S.m", "pkg.declared.Sub.run"]
    )
    async def test_callees_on_a_project_stub_declaration(self, project: Path, handle: str) -> None:
        refused = await _call("expand", project, handle=handle, edge="callees")

        assert refused["unsupported"] is True and refused["reason"] == "stub_declaration", refused
        assert "stub" in refused["detail"]
        assert "stubs" not in refused

    @pytest.mark.asyncio
    async def test_callees_on_an_external_stub_declaration(self, project: Path) -> None:
        refused = await _call("expand", project, handle="math.sqrt", edge="callees")

        assert refused["reason"] == "stub_declaration", refused

    @pytest.mark.asyncio
    async def test_trace_reports_it_as_unsupported(self, project: Path) -> None:
        graph = await _call("trace", project, start="pkg.stubonly.f", follow=["callees"])

        assert [u["reason"] for u in graph["unsupported_edges"]] == ["stub_declaration"]

    @pytest.mark.asyncio
    async def test_callees_on_source_still_measure(self, project: Path) -> None:
        measured = await _call("expand", project, handle="app.use", edge="callees")

        assert "unsupported" not in measured
        assert "pkg.stubonly.f" in _stub_handles(measured)


class TestStubFlag:
    """(2) ``stub: true`` on every node declared in a ``.pyi``; absent for source."""

    @pytest.mark.asyncio
    async def test_resolve_and_inspect(self, project: Path) -> None:
        for tool, args in (
            ("resolve", {"identifier": "pkg.stubonly.S"}),
            ("inspect", {"handle": "pkg.stubonly.S"}),
            ("resolve_at", {"file": "pkg/stubonly.pyi", "line": 3, "column": 6}),
        ):
            response = await _call(tool, project, **args)
            lint_response(response, tool)
            assert response["stub"] is True, (tool, response)
        source = await _call("resolve", project, identifier="pkg.base.Base")
        assert "stub" not in source

    @pytest.mark.asyncio
    async def test_a_stub_beside_its_source_is_located_at_the_source(self, project: Path) -> None:
        assert "stub" not in await _call("resolve", project, identifier="pkg/mixed.pyi")

    @pytest.mark.asyncio
    async def test_edge_stubs_outline_and_trace_nodes(self, project: Path) -> None:
        imports = await _call("expand", project, handle="app", edge="imports")
        outline = await _call("outline", project, handle="pkg.stubonly")
        graph = await _call("trace", project, start="app", follow=["imports"], max_depth=1)
        lint_response(imports, "expand")
        lint_response(outline, "outline")
        lint_response(graph, "trace")

        flags = {s["handle"]: s.get("stub") for s in imports["stubs"]}
        assert flags["pkg.stubonly.S"] is True and flags["pkg.stubonly.f"] is True
        assert outline["node"]["stub"] is True
        assert all(c["node"]["stub"] is True for c in outline["children"])
        assert graph["nodes"]["pkg.stubonly.S"]["stub"] is True
        assert "stub" not in graph["nodes"]["app"]

    @pytest.mark.asyncio
    async def test_a_submodule_stub_and_a_subclass_stub(self, project: Path) -> None:
        """Sentinel-built stubs (directory scans, the class graph) carry it too."""
        submodules = await _call("expand", project, handle="pkg", edge="submodules")
        subclasses = await _call("expand", project, handle="pkg.base.Base", edge="subclasses")

        flags = {s["handle"]: s.get("stub") for s in submodules["stubs"]}
        assert flags == {
            "pkg.base": None,
            "pkg.declared": True,
            "pkg.mixed": None,
            "pkg.stubonly": True,
        }
        assert subclasses["stubs"][0]["stub"] is True

    @pytest.mark.asyncio
    async def test_ambiguous_candidates_are_flagged_one_by_one(self, project: Path) -> None:
        (project / "pkg" / "other.py").write_text("class S:\n    pass\n", encoding="utf-8")

        found = await _call("resolve", project, identifier="S")

        lint_response(found, "resolve")
        flags = {c["handle"]: c.get("stub") for c in found["candidates"]}
        assert flags == {"pkg.other.S": None, "pkg.stubonly.S": True}

    @pytest.mark.asyncio
    async def test_an_external_typeshed_declaration(self, project: Path) -> None:
        found = await _call("resolve", project, identifier="math.sqrt")

        assert found["location"]["file"].endswith(".pyi"), found
        assert found["stub"] is True

    def test_mark_stub_sets_and_clears(self) -> None:
        node: dict[str, Any] = {"handle": "h", "scope": "project"}

        assert mark_stub(node, "/p/m.pyi")["stub"] is True
        assert "stub" not in mark_stub(node, "/p/m.py")
        assert "stub" not in mark_stub(node, None)


class TestDeclarationKind:
    """The flag's one predicate (#933)."""

    @pytest.mark.parametrize(
        ("file", "expected"),
        [
            ("/p/pkg/stubonly.pyi", "stub"),
            ("/usr/lib/typeshed/stdlib/math.pyi", "stub"),
            ("/p/pkg/mod.py", "source"),
            ("/p/pkg/__init__.py", "source"),
            ("C:/p/pkg/mod.PYI", "stub"),
        ],
    )
    def test_from_the_definition_file(self, file: str, expected: str) -> None:
        assert declaration_kind(file) == expected
