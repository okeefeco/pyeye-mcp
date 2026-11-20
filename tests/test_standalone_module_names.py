"""A standalone script outside the project has a module name, and its handles round-trip (#1041).

Standalone directories were searched (``RootsBoundary.SCOPE``, #690) but were
not naming roots (``MODULE_LOOKUP``), so ``module_name_for_file`` gave ``None``
for a script outside the project and plugins dropped its symbols. Jedi, with
the directory on no ``sys.path`` root, names such a file ``__main__``.

Now a standalone directory is the LAST naming root: a script's module is its
path relative to that directory (``tool``, ``sub.deep``), as Python imports it
with the directory on ``sys.path``. A file another root already names keeps
that name, and a file shadowed by an earlier root gets no name rather than a
handle that resolves to the other file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.project_layout import module_name_for_file
from pyeye.project_manager import ProjectManager

#: Pins the tests that need #1041's implementation (pending designer's ruling);
#: strict, so each one fails loudly the moment it starts passing.
PENDING_1041 = pytest.mark.xfail(
    strict=True, reason="#1041: standalone dirs aren't naming roots yet"
)

TOOL = "class Tool:\n    pass\n\n\ndef helper():\n    return Tool()\n"  # Tool @1:6, helper @5:4


@pytest.fixture
def layout(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "m.py").write_text("class Main:\n    pass\n", encoding="utf-8")
    (root / "bin").mkdir()
    (root / "bin" / "run.py").write_text("class Run:\n    pass\n", encoding="utf-8")

    scripts = tmp_path / "scripts"  # outside the project
    (scripts / "sub").mkdir(parents=True)
    (scripts / "tool.py").write_text(TOOL, encoding="utf-8")
    (scripts / "sub" / "deep.py").write_text("class Deep:\n    pass\n", encoding="utf-8")
    (scripts / "app.py").write_text("class Shadowed:\n    pass\n", encoding="utf-8")
    more = tmp_path / "more"  # a second standalone dir, also with tool.py
    more.mkdir()
    (more / "tool.py").write_text("class Other:\n    pass\n", encoding="utf-8")

    (root / ".pyeye.json").write_text(
        json.dumps({"standalone": {"dirs": [scripts.as_posix(), more.as_posix(), "bin"]}}),
        encoding="utf-8",
    )
    return {"root": root, "scripts": scripts, "more": more}


@pytest.fixture
def analyzer(layout: dict[str, Path]):  # type: ignore[no-untyped-def]
    manager = ProjectManager(max_projects=4)
    yield manager.get_analyzer(layout["root"].as_posix())
    manager.cleanup_all()


@PENDING_1041
def test_a_standalone_script_is_named_from_its_directory(layout, analyzer) -> None:  # type: ignore[no-untyped-def]
    assert module_name_for_file(analyzer, layout["scripts"] / "tool.py") == "tool"
    assert module_name_for_file(analyzer, layout["scripts"] / "sub" / "deep.py") == "sub.deep"


@PENDING_1041
@pytest.mark.asyncio
async def test_its_handles_round_trip(layout, analyzer) -> None:  # type: ignore[no-untyped-def]
    tool = (layout["scripts"] / "tool.py").as_posix()

    by_name = await resolve("tool.Tool", analyzer)
    assert by_name["found"] is True
    assert Path(by_name["location"]["file"]).name == "tool.py"
    by_position = await resolve_at(tool, 1, 6, analyzer)  # Jedi says __main__.Tool
    assert by_position["found"] is True and by_position["handle"] == "tool.Tool"
    by_line = await resolve(f"{tool}:5", analyzer)
    assert by_line["found"] is True and by_line["handle"] == "tool.helper"
    node = await inspect("tool.Tool", analyzer)
    assert node["kind"] == "class" and node["scope"] == "project"


@pytest.mark.asyncio
async def test_a_standalone_dir_inside_the_project_keeps_its_name(layout, analyzer) -> None:  # type: ignore[no-untyped-def]
    run = layout["root"] / "bin" / "run.py"
    assert module_name_for_file(analyzer, run) == "bin.run"  # the project root wins
    result = await resolve_at(run.as_posix(), 1, 6, analyzer)
    assert result["found"] is True and result["handle"] == "bin.run.Run"


@PENDING_1041
@pytest.mark.asyncio
async def test_a_shadowed_script_gets_no_name(layout, analyzer) -> None:  # type: ignore[no-untyped-def]
    """``tool`` is scripts/tool.py; more/tool.py must never answer as it."""
    other = layout["more"] / "tool.py"
    assert module_name_for_file(analyzer, other) is None
    result = await resolve_at(other.as_posix(), 1, 6, analyzer)
    assert result["found"] is False and result["reason"] == "unresolved"
    assert "shadowed" in result["detail"]
    assert (layout["scripts"] / "tool.py").as_posix() in result["detail"]  # the earlier file


@pytest.mark.asyncio
async def test_a_script_named_like_a_project_package_is_shadowed(layout, analyzer) -> None:  # type: ignore[no-untyped-def]
    shadowed = layout["scripts"] / "app.py"
    assert module_name_for_file(analyzer, shadowed) is None
    assert (await resolve("app.m.Main", analyzer))["found"] is True  # the package still wins
