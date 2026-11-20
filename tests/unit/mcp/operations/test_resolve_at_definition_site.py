"""resolve_at on a definition answers with that definition, never one goto wanders to (#1024).

Found by #1024's django round-trip: at ``class Meta`` inside a ``ModelForm``
subclass, Jedi's ``goto`` returned the base class's ``Meta`` in another file,
so ``resolve_at`` named a different class than the one under the cursor. A
position on a definition's own name resolves to that definition.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.resolve import resolve, resolve_at

SRC = (
    "class Base:\n"  # 1
    "    class Meta:\n"  # 2   app.m.Base.Meta
    "        kind = 'base'\n"  # 3
    "\n"  # 4
    "class Child(Base):\n"  # 5
    "    class Meta:\n"  # 6   app.m.Child.Meta (shadows Base.Meta)
    "        kind = 'child'\n"  # 7
    "\n"  # 8
    "def build():\n"  # 9
    "    class Local(Base):\n"  # 10  app.m.build.Local
    "        class Meta:\n"  # 11  app.m.build.Local.Meta
    "            kind = 'local'\n"  # 12
    "    return Local\n"  # 13
    "\n"  # 14
    "class Runner:\n"  # 15
    "    def run(self):\n"  # 16  app.m.Runner.run
    "        pass\n"  # 17
    "\n"  # 18
    "class Faster(Runner):\n"  # 19
    "    def run(self):\n"  # 20  app.m.Faster.run (overrides Runner.run)
    "        return Runner()\n"  # 21
)


@pytest.fixture
def project(tmp_path: Path) -> tuple[JediAnalyzer, str]:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/__init__.py").write_text("", encoding="utf-8")
    module = tmp_path / "app/m.py"
    module.write_text(SRC, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix()), module.as_posix()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("line", "column", "handle"),
    [
        (2, 10, "app.m.Base.Meta"),
        (6, 10, "app.m.Child.Meta"),
        (11, 14, "app.m.build.Local.Meta"),
        (16, 8, "app.m.Runner.run"),
        (20, 8, "app.m.Faster.run"),
    ],
)
async def test_a_definition_resolves_to_itself(
    project: tuple[JediAnalyzer, str], line: int, column: int, handle: str
) -> None:
    analyzer, module = project

    by_position: dict[str, Any] = dict(await resolve_at(module, line, column, analyzer))
    by_name: dict[str, Any] = dict(await resolve(handle, analyzer))

    assert by_position["found"] is True and by_position["handle"] == handle, by_position
    assert by_position["location"]["line_start"] == line
    assert by_name["found"] is True and by_name["location"]["line_start"] == line, by_name


@pytest.mark.asyncio
async def test_a_use_still_goes_to_its_definition(project: tuple[JediAnalyzer, str]) -> None:
    """Only a definition's own name is answered in place; a use still follows goto."""
    analyzer, module = project

    result: dict[str, Any] = dict(await resolve_at(module, 21, 15, analyzer))  # `Runner()`

    assert result["found"] is True and result["handle"] == "app.m.Runner", result
    assert result["location"]["line_start"] == 15
