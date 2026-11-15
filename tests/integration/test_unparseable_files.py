"""Regression: project-wide scans disclose the files they couldn't parse (#729).

#703 made a source whose OWN file doesn't parse report ``unparseable``.  The
project-wide reverse scans still skipped any other file that didn't parse, and
said nothing: a subclass or an importer in such a file vanished from
``expand(..., "subclasses")`` / ``expand(..., "imported_by")``, which still
answered a confident list.  Those two edges now carry ``unparseable_files``,
mirroring ``unresolved_importers`` (#668): POSIX paths, ``[]`` when every file
parsed, absent on every other edge; per node in ``trace``, present iff the edge
was walked.  A bare-name ``resolve`` miss names the count in ``detail``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.resolve import resolve
from pyeye.mcp.operations.trace import trace
from tests.conformance.response_linter import lint_response

# A SyntaxError on every Python version, so the test doesn't depend on which
# new syntax the running interpreter happens to lack.
_BROKEN = (
    "from pkg.base import Base\n"
    "import pkg.mod\n"
    "\n"
    "class Broken(Base):\n"
    "    value = = 1\n"
)


def _project(root: Path, *, broken: bool) -> JediAnalyzer:
    files = {
        "pkg/__init__.py": "",
        "pkg/base.py": "class Base:\n    pass\n",
        "pkg/mod.py": "X = 1\n",
        "pkg/good.py": (
            "from pkg.base import Base\nimport pkg.mod\n\n\nclass Good(Base):\n    pass\n"
        ),
    }
    if broken:
        files["pkg/broken.py"] = _BROKEN
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(root))


def _broken_posix(root: Path) -> str:
    return (root / "pkg" / "broken.py").resolve().as_posix()


async def _expand(handle: str, edge: str, analyzer: JediAnalyzer) -> dict:
    result = dict(await expand(handle, edge, analyzer))
    lint_response(result, "expand")
    return result


@pytest.mark.asyncio
async def test_subclasses_discloses_the_unparseable_file(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, broken=True)
    result = await _expand("pkg.base.Base", "subclasses", analyzer)
    assert [s["handle"] for s in result["stubs"]] == ["pkg.good.Good"]
    assert result["unparseable_files"] == [_broken_posix(tmp_path)]


@pytest.mark.asyncio
async def test_imported_by_discloses_the_unparseable_file(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, broken=True)
    result = await _expand("pkg.mod", "imported_by", analyzer)
    assert [s["handle"] for s in result["stubs"]] == ["pkg.good"]
    assert result["unparseable_files"] == [_broken_posix(tmp_path)]
    assert result["unresolved_importers"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handle", "edge"), [("pkg.base.Base", "subclasses"), ("pkg.mod", "imported_by")]
)
async def test_clean_project_reports_an_empty_list(tmp_path: Path, handle: str, edge: str) -> None:
    analyzer = _project(tmp_path, broken=False)
    result = await _expand(handle, edge, analyzer)
    assert result["unparseable_files"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handle", "edge"),
    [("pkg.good", "members"), ("pkg.good", "imports"), ("pkg.good.Good", "superclasses")],
)
async def test_other_edges_never_carry_the_field(tmp_path: Path, handle: str, edge: str) -> None:
    analyzer = _project(tmp_path, broken=True)
    result = await _expand(handle, edge, analyzer)
    assert "unparseable_files" not in result


@pytest.mark.asyncio
async def test_trace_carries_it_per_node(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, broken=True)
    walked = dict(await trace(["pkg.base.Base"], ["subclasses"], analyzer, max_depth=1))
    lint_response(walked, "trace")
    # Every node whose subclasses scan ran reports it: the root, and Good (walked
    # at the depth frontier, its new adjacents cut).
    broken = [_broken_posix(tmp_path)]
    assert walked["unparseable_files"] == {"pkg.base.Base": broken, "pkg.good.Good": broken}

    not_walked = dict(await trace(["pkg.base.Base"], ["superclasses"], analyzer, max_depth=1))
    assert "unparseable_files" not in not_walked


@pytest.mark.asyncio
async def test_trace_omits_clean_nodes(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, broken=False)
    walked = dict(await trace(["pkg.base.Base"], ["subclasses"], analyzer, max_depth=1))
    lint_response(walked, "trace")
    assert walked["unparseable_files"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Broken", "nonexistent_name_xyz"])
async def test_bare_name_miss_names_the_unparseable_count(tmp_path: Path, name: str) -> None:
    analyzer = _project(tmp_path, broken=True)
    result = dict(await resolve(name, analyzer))
    lint_response(result, "resolve")
    assert result["found"] is False and result["reason"] == "unresolved"
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert "1 project file" in result["detail"]
    assert f"Python {version}" in result["detail"]


@pytest.mark.asyncio
async def test_bare_name_miss_in_a_clean_project_keeps_the_default_detail(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, broken=False)
    result = dict(await resolve("nonexistent_name_xyz", analyzer))
    assert result["found"] is False
    assert "can't be parsed" not in result["detail"]
