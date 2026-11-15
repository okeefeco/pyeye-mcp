"""Analyzed code using Python 3.14-only syntax is measured on a 3.14 server (#543).

The module is written at test time, not checked in as a fixture, because black,
ruff and mypy on older interpreters cannot parse 3.14 syntax. On an older server
interpreter the same module currently outlines as measured-empty; that is #703.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline

pytestmark = pytest.mark.skipif(sys.version_info < (3, 14), reason="3.14 syntax (#543)")

_MODULES = {
    # PEP 750 template strings
    "tstr": (
        "from string.templatelib import Template\n\n\n"
        "def render(name: str) -> Template:\n"
        '    return t"hello {name}"\n\n\n'
        "def after() -> int:\n"
        "    return 3\n"
    ),
    # PEP 758 unparenthesised except
    "exc": (
        "def guard() -> int:\n"
        "    try:\n"
        "        return 1\n"
        "    except ValueError, TypeError:\n"
        "        return 0\n\n\n"
        "def after() -> int:\n"
        "    return 3\n"
    ),
}


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    pkg = tmp_path / "p314"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name, source in _MODULES.items():
        (pkg / f"{name}.py").write_text(source, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("tstr", ["p314.tstr.render", "p314.tstr.after"]),
        ("exc", ["p314.exc.guard", "p314.exc.after"]),
    ],
)
async def test_outline_sees_definitions_around_new_syntax(
    analyzer: JediAnalyzer, module: str, expected: list[str]
) -> None:
    tree = await outline(f"p314.{module}", analyzer)
    assert tree["found"] is True
    handles = [c["node"]["handle"] for c in tree["children"]]
    assert set(expected) <= set(handles), handles


@pytest.mark.asyncio
async def test_template_return_type_resolves(analyzer: JediAnalyzer) -> None:
    node = await inspect("p314.tstr.render", analyzer)
    assert node["found"] is True
    assert node["return_type"]["handle"] == "string.templatelib.Template"
