"""``UNPARSEABLE_FILE_EDGES`` is exactly the edges that report ``unparseable_files`` (#874).

The docstrings and tool descriptions name the set through this one constant (and
the ``edges.unparseable`` fact built from it), so it must match what ``expand``
actually returns: present (even ``[]``) for these edges, absent for every other.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pyeye.mcp.operations.edges import EDGE_RESOLVERS, UNPARSEABLE_FILE_EDGES

#: A handle each implemented edge applies to, in the fixture project below.
_HANDLES = {
    "members": "pkg.mod.A",
    "callees": "pkg.mod.make",
    "imported_by": "pkg.mod",
    "subclasses": "pkg.mod.A",
    "superclasses": "pkg.mod.B",
    "imports": "pkg.mod",
    "enclosing_scope": "pkg.mod.A.meth",
    "submodules": "pkg",
    "re_exports": "pkg.mod.A",
}


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("unparseable_edges")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from pkg.mod import A\n")
    (pkg / "mod.py").write_text(
        "import os\n\n"
        "class A:\n"
        "    def meth(self):\n"
        "        return os.sep\n\n"
        "class B(A):\n"
        "    pass\n\n"
        "def make():\n"
        "    return A()\n"
    )
    (root / "user.py").write_text("from pkg import mod\n")
    return root


def _expand(project: Path, handle: str, edge: str) -> Any:
    from pyeye.mcp.server import mcp

    result = asyncio.run(
        mcp.call_tool(
            "expand", {"handle": handle, "edge": edge, "project_path": project.as_posix()}
        )
    )
    assert not result.is_error, result.content
    return result.structured_content


def test_every_implemented_edge_has_a_probe() -> None:
    assert set(_HANDLES) == set(EDGE_RESOLVERS)


def test_the_set_names_only_implemented_edges() -> None:
    assert set(EDGE_RESOLVERS) >= UNPARSEABLE_FILE_EDGES


@pytest.mark.parametrize("edge", sorted(_HANDLES))
def test_unparseable_files_is_present_exactly_for_the_set(project: Path, edge: str) -> None:
    response = _expand(project, _HANDLES[edge], edge)
    assert response["found"] is True and "stubs" in response, response
    assert ("unparseable_files" in response) == (edge in UNPARSEABLE_FILE_EDGES), response
