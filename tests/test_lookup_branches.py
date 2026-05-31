"""Branch-coverage tests for the unified lookup tool.

The existing ``test_lookup*`` suites exercise the happy paths against real
fixture projects.  Those paths are intentionally hard to push into their
error/fallback branches with valid fixtures, so this module drives the
exception and fallback branches in ``pyeye.mcp.lookup`` and
``pyeye.mcp.lookup_builders`` directly with a mocked analyzer.

These tests are platform-independent (no skips), so they raise coverage on
both POSIX and Windows CI — closing the Windows-only coverage gap that the
fixture-based suites leave on the new lookup modules.
"""

import ast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyeye.mcp import (
    lookup as lk,
    lookup_builders as lb,
)


def make_name(
    *,
    name: str = "X",
    line: int = 1,
    column: int = 0,
    full_name: str | None = "pkg.mod.X",
    type_: str = "class",
    module_path: str | None = "/proj/pkg/mod.py",
    docstring: str = "doc",
    is_definition: bool = True,
) -> MagicMock:
    """Build a MagicMock standing in for a Jedi ``Name`` object."""
    n = MagicMock()
    n.name = name
    n.line = line
    n.column = column
    n.full_name = full_name
    n.type = type_
    n.module_path = module_path
    n.is_definition.return_value = is_definition
    n.docstring.return_value = docstring
    return n


def make_analyzer() -> MagicMock:
    """Build a mock JediAnalyzer with async navigation methods."""
    analyzer = MagicMock()
    analyzer.project = MagicMock()
    analyzer._get_import_path_for_file.return_value = "pkg.mod"
    analyzer.find_subclasses = AsyncMock(return_value=[])
    analyzer.find_references = AsyncMock(return_value=[])
    analyzer.get_call_hierarchy = AsyncMock(return_value={"callers": [], "callees": []})
    analyzer.find_imports = AsyncMock(return_value=[])
    analyzer.find_symbol = AsyncMock(return_value=[])
    analyzer.get_module_info = AsyncMock(return_value={"error": "no"})
    analyzer._enrich_method = AsyncMock(return_value={"signature": "sig"})
    analyzer._enrich_attribute = AsyncMock(return_value={"name": "a"})
    analyzer._get_module_variables = AsyncMock(return_value=[])
    return analyzer


# --------------------------------------------------------------------------
# lookup_builders.py — small helpers
# --------------------------------------------------------------------------


def test_find_name_at_no_match_returns_none():
    """_find_name_at returns None when nothing matches (line 93)."""
    names = [make_name(name="other", line=5)]
    assert lb._find_name_at(names, "target", 1) is None


def test_module_ref_fallback_uses_import_path():
    """When the Script context yields no full_name, fall back to import path (51-52)."""
    analyzer = make_analyzer()
    script = MagicMock()
    script.get_context.return_value = MagicMock(full_name=None)
    with patch("pyeye.file_artifact_cache.get_script", return_value=script):
        ref = lb._module_ref_for_file(analyzer, "/proj/pkg/mod.py")
    assert ref["full_name"] == "pkg.mod"
    assert ref["name"] == "mod"


def test_module_ref_fallback_uses_stem_when_no_import_path():
    """When import-path lookup also fails, fall back to the file stem (53-55)."""
    analyzer = make_analyzer()
    analyzer._get_import_path_for_file.return_value = None
    with patch("pyeye.file_artifact_cache.get_script", side_effect=RuntimeError("boom")):
        ref = lb._module_ref_for_file(analyzer, "/proj/pkg/widget.py")
    assert ref["name"] == "widget"
    assert ref["full_name"] == "widget"


# --------------------------------------------------------------------------
# lookup_builders.py — base-class resolution via goto
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_bases_attribute_and_goto_fallbacks():
    """Cover dotted-base column math, goto-empty, and goto-raises branches."""
    src = "class C(mod.Base, Plain, Broken):\n    pass\n"
    tree = ast.parse(src)
    script = MagicMock()
    call_state = {"n": 0}

    def goto_side_effect(*_args):
        # First base (mod.Base, an Attribute) resolves; Plain returns nothing;
        # Broken raises — exercising all three branches.
        call_state["n"] += 1
        if call_state["n"] == 1:
            return [make_name(name="Base")]
        if call_state["n"] == 2:
            return []
        raise RuntimeError("goto failed")

    script.goto.side_effect = goto_side_effect
    bases = await lb._resolve_bases_via_goto(script, tree, "C", 1)
    names = [b["name"] for b in bases]
    assert "Base" in names  # resolved via goto
    assert "Plain" in names  # goto returned [] -> AST unparse fallback
    assert "Broken" in names  # goto raised -> AST unparse fallback


@pytest.mark.asyncio
async def test_resolve_bases_outer_exception_is_swallowed():
    """A malformed tree triggers the outer guard and returns [] (172-173)."""
    bases = await lb._resolve_bases_via_goto(MagicMock(), None, "C", 1)  # type: ignore[arg-type]
    assert bases == []


# --------------------------------------------------------------------------
# lookup_builders.py — class result
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_class_result_target_not_found():
    """When the class name isn't found in the file, return the empty stub (208)."""
    analyzer = make_analyzer()
    script = MagicMock()
    script.get_context.return_value = MagicMock(full_name="pkg.mod")
    script.get_names.return_value = []  # nothing matches target
    with (
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
        patch("pyeye.file_artifact_cache.get_ast", return_value=ast.parse("")),
    ):
        result = await lb._build_class_result(
            analyzer,
            {"file": "/proj/pkg/mod.py", "name": "Missing", "line": 1},
            limit=10,
        )
    assert result["type"] == "class"
    assert result["methods"] == []
    assert result["subclasses"] == {"total": 0, "items": []}


@pytest.mark.asyncio
async def test_build_class_result_member_and_relationship_exceptions():
    """Member enumeration, subclasses, and references all raise -> guarded (237-278)."""
    analyzer = make_analyzer()
    analyzer.find_subclasses = AsyncMock(side_effect=RuntimeError("subs"))
    analyzer.find_references = AsyncMock(side_effect=RuntimeError("refs"))
    target = make_name(name="C", line=1, type_="class")
    target.defined_names.side_effect = RuntimeError("members")
    script = MagicMock()
    script.get_context.return_value = MagicMock(full_name="pkg.mod")
    script.get_names.return_value = [target]
    with (
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
        patch("pyeye.file_artifact_cache.get_ast", return_value=ast.parse("")),
    ):
        result = await lb._build_class_result(
            analyzer,
            {"file": "/proj/pkg/mod.py", "name": "C", "line": 1, "column": 0},
            limit=10,
        )
    # Despite every relationship call raising, a well-formed stub comes back.
    assert result["subclasses"] == {"total": 0, "items": []}
    assert result["references"] == {"total": 0, "items": []}


@pytest.mark.asyncio
async def test_build_class_result_attribute_member_enrichment():
    """A statement member triggers the read_text bridge + _enrich_attribute."""
    analyzer = make_analyzer()
    target = make_name(name="C", line=1, type_="class")
    method_dn = make_name(name="m", type_="function")
    attr_dn = make_name(name="a", type_="statement")
    target.defined_names.return_value = [method_dn, attr_dn]
    script = MagicMock()
    script.get_context.return_value = MagicMock(full_name="pkg.mod")
    script.get_names.return_value = [target]
    # read_text on a non-existent path raises -> caught by the member guard (237-238).
    with (
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
        patch("pyeye.file_artifact_cache.get_ast", return_value=ast.parse("")),
    ):
        result = await lb._build_class_result(
            analyzer,
            {"file": "/nonexistent/pkg/mod.py", "name": "C", "line": 1, "column": 0},
            limit=10,
        )
    assert result["type"] == "class"


# --------------------------------------------------------------------------
# lookup_builders.py — function result
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_function_result_with_callers_and_callees():
    """Populate caller/callee lists from the hierarchy (covers item loops)."""
    analyzer = make_analyzer()
    analyzer.get_call_hierarchy = AsyncMock(
        return_value={
            "callers": [{"name": "c1", "full_name": "m.c1", "file": "m.py", "line": 3}],
            "callees": [{"name": "e1", "full_name": "m.e1", "file": "m.py", "line": 9}],
        }
    )
    analyzer.find_references = AsyncMock(
        return_value=[{"name": "r1", "full_name": "m.r1", "file": "m.py", "line": 4}]
    )
    target = make_name(name="fn", line=2, type_="function")
    script = MagicMock()
    script.get_names.return_value = [target]
    with patch("pyeye.file_artifact_cache.get_script", return_value=script):
        result = await lb._build_function_result(
            analyzer,
            {"file": "/proj/m.py", "name": "fn", "line": 2, "column": 0, "type": "function"},
            limit=10,
        )
    assert result["callers"]["total"] == 1
    assert result["callees"]["total"] == 1
    assert result["references"]["total"] == 1


@pytest.mark.asyncio
async def test_build_function_result_all_paths_raise():
    """Enrichment, hierarchy, and references all raise -> guarded (323-377)."""
    analyzer = make_analyzer()
    analyzer._enrich_method = AsyncMock(side_effect=RuntimeError("enrich"))
    analyzer.get_call_hierarchy = AsyncMock(side_effect=RuntimeError("hier"))
    analyzer.find_references = AsyncMock(side_effect=RuntimeError("refs"))
    target = make_name(name="fn", line=2, type_="function")
    script = MagicMock()
    script.get_names.return_value = [target]
    with patch("pyeye.file_artifact_cache.get_script", return_value=script):
        result = await lb._build_function_result(
            analyzer,
            {"file": "/proj/m.py", "name": "fn", "line": 2, "column": 0},
            limit=10,
        )
    assert result["signature"] is None
    assert result["callers"] == {"total": 0, "items": []}


# --------------------------------------------------------------------------
# lookup_builders.py — module result
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_module_result_exception_paths():
    """Docstring, variables, and imported_by guards all fire (427-508)."""
    analyzer = make_analyzer()
    analyzer._get_module_variables = AsyncMock(side_effect=RuntimeError("vars"))
    analyzer.find_imports = AsyncMock(side_effect=RuntimeError("imports"))
    cls = make_name(name="C", type_="class", line=1)
    fn = make_name(name="f", type_="function", line=5)
    imp = make_name(name="os", type_="module", line=1, is_definition=True)
    script = MagicMock()
    script.get_names.return_value = [cls, fn, imp]
    with (
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
        patch("pyeye.file_artifact_cache.get_ast", side_effect=RuntimeError("ast")),
    ):
        result = await lb._build_module_result(
            analyzer,
            {"file": "/nonexistent/pkg/mod.py", "name": "mod", "full_name": "pkg.mod"},
            limit=10,
        )
    assert result["type"] == "module"
    assert result["classes"]["total"] == 1
    assert result["functions"]["total"] == 1
    assert result["variables"] == {"total": 0, "items": []}


# --------------------------------------------------------------------------
# lookup_builders.py — basic result + dispatcher
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_basic_result_docstring_exception():
    """A failing name lookup is swallowed in the basic builder (536-537)."""
    analyzer = make_analyzer()
    with patch("pyeye.file_artifact_cache.get_script", side_effect=RuntimeError("script")):
        result = await lb._build_basic_result(
            analyzer,
            {"file": "/proj/m.py", "name": "thing", "line": 3, "type": "variable"},
        )
    assert result["type"] == "variable"
    assert result["docstring"] is None


@pytest.mark.asyncio
async def test_assemble_response_passthrough_when_no_marker():
    """A terminal response (no _resolved_via) is returned unchanged (552)."""
    terminal = {"found": False, "identifier": "Nope"}
    out = await lb.assemble_response(make_analyzer(), terminal, limit=10)
    assert out is terminal


@pytest.mark.asyncio
async def test_assemble_response_dispatches_basic_type():
    """An unknown resolved type routes to the basic builder."""
    analyzer = make_analyzer()
    with patch("pyeye.file_artifact_cache.get_script", side_effect=RuntimeError("x")):
        out = await lb.assemble_response(
            analyzer,
            {"_resolved_via": "bare_name", "type": "variable", "name": "v", "file": None},
            limit=10,
        )
    assert out["type"] == "variable"
    assert "_resolved_via" not in out


@pytest.mark.asyncio
async def test_assemble_response_outer_exception_falls_back():
    """A builder raising (missing 'file' key) yields the stripped stub (564-568)."""
    analyzer = make_analyzer()
    resolution = {"_resolved_via": "bare_name", "type": "class", "name": "C"}
    out = await lb.assemble_response(analyzer, resolution, limit=10)
    assert out == {"type": "class", "name": "C"}
    assert "_resolved_via" not in out


# --------------------------------------------------------------------------
# lookup.py — coordinate resolution
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_coordinates_missing_file():
    """A non-existent file short-circuits to a not-found stub (118)."""
    result = await lk._resolve_coordinates("/no/such/file.py", 1, 0, ".")
    assert result["found"] is False
    assert result["searched"]["indexed"] is False


@pytest.mark.asyncio
async def test_resolve_coordinates_goto_fallback(tmp_path):
    """infer() empty -> goto() resolves the definition (158-168)."""
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    analyzer = make_analyzer()
    script = MagicMock()
    script.infer.return_value = []
    script.goto.return_value = [make_name(name="x", type_="statement", line=1)]
    with (
        patch("pyeye.mcp.server.get_analyzer", return_value=analyzer),
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
    ):
        result = await lk._resolve_coordinates(str(f), 1, 0, ".")
    assert result["_resolved_via"] == "coordinates"
    assert result["name"] == "x"


@pytest.mark.asyncio
async def test_resolve_coordinates_nothing_found(tmp_path):
    """infer() and goto() both empty -> not-found with indexed=True (169-180)."""
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    analyzer = make_analyzer()
    script = MagicMock()
    script.infer.return_value = []
    script.goto.return_value = []
    with (
        patch("pyeye.mcp.server.get_analyzer", return_value=analyzer),
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
    ):
        result = await lk._resolve_coordinates(str(f), 1, 0, ".")
    assert result["found"] is False
    assert result["searched"]["indexed"] is True


@pytest.mark.asyncio
async def test_resolve_coordinates_outer_exception(tmp_path):
    """An analyzer failure is caught and returns a not-found stub (181-194)."""
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    with patch("pyeye.mcp.server.get_analyzer", side_effect=RuntimeError("boom")):
        result = await lk._resolve_coordinates(str(f), 1, 0, ".")
    assert result["found"] is False
    assert result["searched"]["indexed"] is False


# --------------------------------------------------------------------------
# lookup.py — file-path resolution
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_file_path_non_integer_line_suffix():
    """A non-integer ':suffix' is treated as part of the path (288-289)."""
    result = await lk._resolve_file_path("does_not_exist.py:abc", ".")
    assert result["found"] is False


@pytest.mark.asyncio
async def test_resolve_file_path_line_match_by_name(tmp_path):
    """A name on the requested line resolves directly (346-355)."""
    f = tmp_path / "m.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    analyzer = make_analyzer()
    script = MagicMock()
    script.get_names.return_value = [make_name(name="foo", line=1, type_="function")]
    with (
        patch("pyeye.mcp.server.get_analyzer", return_value=analyzer),
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
    ):
        result = await lk._resolve_file_path(f"{f}:1", str(tmp_path))
    assert result["_resolved_via"] == "file_path"
    assert result["name"] == "foo"


@pytest.mark.asyncio
async def test_resolve_file_path_line_infer_fallback(tmp_path):
    """No name on the line -> infer() at column 0 resolves it (328-345)."""
    f = tmp_path / "m.py"
    f.write_text("value = compute()\n", encoding="utf-8")
    analyzer = make_analyzer()
    script = MagicMock()
    script.get_names.return_value = []  # nothing on the line
    script.infer.return_value = [make_name(name="value", type_="statement", line=1)]
    with (
        patch("pyeye.mcp.server.get_analyzer", return_value=analyzer),
        patch("pyeye.file_artifact_cache.get_script", return_value=script),
    ):
        result = await lk._resolve_file_path(f"{f}:1", str(tmp_path))
    assert result["_resolved_via"] == "file_path"
    assert result["name"] == "value"


@pytest.mark.asyncio
async def test_resolve_file_path_outer_exception(tmp_path):
    """An analyzer failure after the existence check is guarded (386-388)."""
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    with patch("pyeye.mcp.server.get_analyzer", side_effect=RuntimeError("boom")):
        result = await lk._resolve_file_path(f"{f}:1", str(tmp_path))
    assert result["found"] is False


# --------------------------------------------------------------------------
# lookup.py — dotted-path resolution + ambiguous items
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_dotted_path_ambiguous_full_name():
    """Multiple full-name matches -> ambiguous + _build_ambiguous_items (446-454, 512-532)."""
    analyzer = make_analyzer()
    analyzer.find_symbol = AsyncMock(
        return_value=[
            {"name": "X", "full_name": "pkg.mod.X", "file": "a.py", "line": 1, "type": "class"},
            {"name": "X", "full_name": "pkg.mod.X", "file": "b.py", "line": 2, "type": "class"},
        ]
    )
    with patch("pyeye.mcp.server.get_analyzer", return_value=analyzer):
        result = await lk._resolve_dotted_path("pkg.mod.X", ".", limit=10)
    assert result["ambiguous"] is True
    assert result["matches"]["total"] == 2
    assert result["matches"]["items"][0]["context"]["full_name"] == "pkg.mod"


@pytest.mark.asyncio
async def test_resolve_dotted_path_bare_symbol_fallback_single():
    """Full-name search misses, bare-name search yields one match (460-470)."""
    analyzer = make_analyzer()

    async def find_symbol(query):
        if query == "pkg.mod.Thing":
            return [{"name": "Thing", "full_name": "other.Thing", "file": "o.py", "line": 1}]
        return [
            {
                "name": "Thing",
                "full_name": "pkg.mod.Thing",
                "file": "m.py",
                "line": 7,
                "type": "class",
            }
        ]

    analyzer.find_symbol = AsyncMock(side_effect=find_symbol)
    with patch("pyeye.mcp.server.get_analyzer", return_value=analyzer):
        result = await lk._resolve_dotted_path("pkg.mod.Thing", ".", limit=10)
    assert result["_resolved_via"] == "dotted_path"
    assert result["full_name"] == "pkg.mod.Thing"


@pytest.mark.asyncio
async def test_resolve_dotted_path_bare_symbol_fallback_ambiguous():
    """Bare-name fallback returns multiple full-name matches -> ambiguous (471-478)."""
    analyzer = make_analyzer()

    async def find_symbol(query):
        if query == "pkg.mod.Thing":
            return []
        return [
            {"name": "Thing", "full_name": "pkg.mod.Thing", "file": "a.py", "line": 1},
            {"name": "Thing", "full_name": "pkg.mod.Thing", "file": "b.py", "line": 2},
        ]

    analyzer.find_symbol = AsyncMock(side_effect=find_symbol)
    with patch("pyeye.mcp.server.get_analyzer", return_value=analyzer):
        result = await lk._resolve_dotted_path("pkg.mod.Thing", ".", limit=10)
    assert result["ambiguous"] is True
    assert result["matches"]["total"] == 2


@pytest.mark.asyncio
async def test_resolve_dotted_path_outer_exception():
    """An analyzer failure is caught and returns a not-found stub (494-507)."""
    with patch("pyeye.mcp.server.get_analyzer", side_effect=RuntimeError("boom")):
        result = await lk._resolve_dotted_path("pkg.mod.X", ".", limit=10)
    assert result["found"] is False
    assert result["searched"]["indexed"] is False
