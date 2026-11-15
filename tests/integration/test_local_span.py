"""Regression: a local or class-body attribute ends on its own line (#693).

Every tool reads spans from ``_jedi_location.get_end_line``.  Before #693 a
name that merely sat inside a ``def``/``class`` reported that block's end as
its ``line_end``; ``resolve``, ``inspect`` and edge stubs now agree on the
documented contract (non-definitions end where they start).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve

_M = """\
class Config:
    name = "x"
    port: int = 8080

    def load(self):
        data = {}
        return data
"""


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "m.py").write_text(_M, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handle", "line"),
    [
        ("pkg.m.Config.name", 2),
        ("pkg.m.Config.port", 3),
        ("pkg.m.Config.load.data", 6),
    ],
)
async def test_resolve_and_inspect_end_on_the_names_line(
    analyzer: JediAnalyzer, handle: str, line: int
) -> None:
    resolved = await resolve(handle, analyzer)
    assert resolved["found"] is True, resolved
    assert (resolved["location"]["line_start"], resolved["location"]["line_end"]) == (line, line)
    inspected = await inspect(handle, analyzer)
    assert inspected["found"] is True
    assert (inspected["location"]["line_start"], inspected["location"]["line_end"]) == (line, line)


@pytest.mark.asyncio
async def test_member_stubs_agree(analyzer: JediAnalyzer) -> None:
    expanded = await expand("pkg.m.Config", "members", analyzer)
    spans = {s["handle"]: (s["line_start"], s["line_end"]) for s in expanded["stubs"]}
    assert spans["pkg.m.Config.name"] == (2, 2)
    assert spans["pkg.m.Config.port"] == (3, 3)
    # The method spans exactly its block, lines 5-7 (#709).
    assert spans["pkg.m.Config.load"] == (5, 7)
