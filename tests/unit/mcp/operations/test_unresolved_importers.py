"""``imported_by`` never silently drops an importer it can't name (#668).

A file whose path has no module name (a ``my-script.py``, a file under a
``tools-dir/`` directory) can still ``import pkg.target``. It is a real
dependent, but it has no handle, so it can't be a stub. It used to be dropped
without a trace, which made ``imported_by`` a confident under-count. It is now
listed in ``unresolved_importers``, the way ``imports`` lists the targets it
couldn't resolve in ``unresolved_imports`` (#494).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.trace import trace


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def project(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "proj"
    _write(root / "pkg" / "__init__.py", "")
    target = _write(root / "pkg" / "target.py", "def f():\n    return 1\n")
    _write(root / "pkg" / "named.py", "import pkg.target\n")
    return {
        "root": root,
        "target": target,
        # absolute imports from files that have no module name
        "script": _write(root / "my-script.py", "import pkg.target\n"),
        "tool": _write(root / "tools-dir" / "use_target.py", "from pkg import target\n"),
        # a relative import from an unnamed file can't be anchored: not counted
        "relative": _write(root / "tools-dir" / "rel.py", "from . import target\n"),
    }


@pytest.fixture
def analyzer(project: dict[str, Path]) -> JediAnalyzer:
    return JediAnalyzer(str(project["root"]))


async def test_find_importers_separates_unnamed_files(
    analyzer: JediAnalyzer, project: dict[str, Path]
) -> None:
    result = await analyzer.find_importers("pkg.target", project["target"])
    assert [module for module, _ in result.named] == ["pkg.named"]
    assert result.unnamed == sorted([project["script"], project["tool"]], key=Path.as_posix)


async def test_expand_lists_unnamed_importers(
    analyzer: JediAnalyzer, project: dict[str, Path]
) -> None:
    result = await expand("pkg.target", "imported_by", analyzer)
    assert [s["handle"] for s in result["stubs"]] == ["pkg.named"]
    assert result["unresolved_importers"] == sorted(
        p.as_posix() for p in (project["script"], project["tool"])
    )


async def test_expand_reports_empty_when_every_importer_is_named(analyzer: JediAnalyzer) -> None:
    """Measured and complete is ``[]``, not an absent key."""
    result = await expand("pkg.named", "imported_by", analyzer)
    assert result["unresolved_importers"] == []


@pytest.mark.parametrize("edge", ["imports", "members", "submodules"])
async def test_other_edges_never_carry_the_field(analyzer: JediAnalyzer, edge: str) -> None:
    result = await expand("pkg.target", edge, analyzer)
    assert "unresolved_importers" not in result


async def test_trace_maps_unnamed_importers_per_node(
    analyzer: JediAnalyzer, project: dict[str, Path]
) -> None:
    result = await trace("pkg.target", ["imported_by"], analyzer, max_depth=1)
    assert result["unresolved_importers"] == {
        "pkg.target": sorted(p.as_posix() for p in (project["script"], project["tool"]))
    }


async def test_trace_without_imported_by_omits_the_field(analyzer: JediAnalyzer) -> None:
    result = await trace("pkg", ["members"], analyzer, max_depth=1)
    assert "unresolved_importers" not in result
