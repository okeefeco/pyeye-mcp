"""Integration tests: _search_all_scopes on the AST name-index (#457, Task 3).

These exercise the real ``JediAnalyzer._search_all_scopes`` over temp projects.
The completeness test reproduces the #457 bug directly: with >30 modules defining
the same name, ``jedi.Project.search``'s 30-parsed-file cap drops definitions;
the AST index must return every one.
"""

from pathlib import Path

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer


def _w(p: Path, src: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src)
    return p


@pytest.mark.asyncio
async def test_returns_every_definition_past_the_30_file_cap(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    for i in range(40):
        _w(proj / f"m{i}.py", "class Field:\n    pass\n")
    project_graph.invalidate()
    analyzer = JediAnalyzer(str(proj))

    results = await analyzer._search_all_scopes("Field")

    assert len({r.module_path.as_posix() for r in results}) == 40


@pytest.mark.asyncio
async def test_dedups_by_name_path_line(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _w(proj / "a.py", "class Widget:\n    pass\n")
    project_graph.invalidate()
    analyzer = JediAnalyzer(str(proj))

    results = await analyzer._search_all_scopes("Widget")

    assert len(results) == 1
    assert results[0].full_name == "a.Widget"
    assert results[0].type == "class"


@pytest.mark.asyncio
async def test_import_only_name_returns_empty(tmp_path: Path) -> None:
    # The AST index yields definitions, not import bindings: a name that is only
    # imported (never defined in the project) resolves to nothing.
    proj = tmp_path / "proj"
    _w(proj / "a.py", "from os import getcwd\n\nx = getcwd()\n")
    project_graph.invalidate()
    analyzer = JediAnalyzer(str(proj))

    assert await analyzer._search_all_scopes("getcwd") == []


@pytest.mark.asyncio
async def test_scope_applied_at_lookup_not_build(tmp_path: Path) -> None:
    # Cross-scope-poisoning regression: querying "main" first must not narrow the
    # project-keyed cache so that a later "all" misses an additional-path def.
    main = tmp_path / "main"
    extra = tmp_path / "extra"
    _w(main / "a.py", "class Shared:\n    pass\n")
    _w(extra / "b.py", "class OnlyExtra:\n    pass\n")
    project_graph.invalidate()
    analyzer = JediAnalyzer(str(main))
    analyzer.additional_paths = [extra]

    main_only = await analyzer._search_all_scopes("OnlyExtra", scope="main")
    assert main_only == []  # not defined in the main project

    all_scope = await analyzer._search_all_scopes("OnlyExtra", scope="all")
    assert len(all_scope) == 1  # still found under "all" — not poisoned
