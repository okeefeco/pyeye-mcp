"""A re-export collapses to its definition site, however it was imported (#857).

For ``from .thing import CloneThing`` in ``clonepkg/__init__.py``, Jedi names the
import binding ``clonepkg.CloneThing``, so step 4 matched the BINDING and kept
it: ``resolve("clonepkg.CloneThing")`` answered ``clonepkg.CloneThing`` at the
import line, although ``inspect("clonepkg.thing.CloneThing")`` lists that very
path among its ``re_exports``. The documented contract is that a re-export
collapses to its definition (``django.db.models.Model`` -> ``…base.Model``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.resolver import Resolved, resolve_handle

THING = "class CloneThing:\n    size = 1\n\n\ndef helper() -> int:\n    return 1\n"

#: ``__init__.py`` bodies that re-export from ``thing``.
INITS = {
    "relative": "from .thing import CloneThing, helper\n",
    "absolute": "from clonepkg.thing import CloneThing, helper\n",
    "relative_alias": "from .thing import CloneThing as CloneThing, helper as helper\n",
}


def _analyzer(tmp_path: Path, init: str) -> JediAnalyzer:
    pkg = tmp_path / "clonepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(init, encoding="utf-8")
    (pkg / "thing.py").write_text(THING, encoding="utf-8")
    (pkg / "own.py").write_text("class Own:\n    pass\n", encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix())


@pytest.mark.parametrize("form", sorted(INITS))
@pytest.mark.parametrize(
    ("request_path", "handle"),
    [
        ("clonepkg.CloneThing", "clonepkg.thing.CloneThing"),
        ("clonepkg.helper", "clonepkg.thing.helper"),
    ],
)
def test_a_re_export_collapses_to_the_definition(
    tmp_path: Path, form: str, request_path: str, handle: str
) -> None:
    result = resolve_handle(request_path, _analyzer(tmp_path, INITS[form]))

    assert isinstance(result, Resolved), result
    assert result.handle == handle
    assert Path(result.anchor.module_path).name == "thing.py"


def test_a_definition_in_the_package_itself_stays(tmp_path: Path) -> None:
    """A real definition in ``__init__.py`` is not a re-export."""
    analyzer = _analyzer(tmp_path, "class Local:\n    pass\n")

    result = resolve_handle("clonepkg.Local", analyzer)

    assert isinstance(result, Resolved)
    assert result.handle == "clonepkg.Local"
    assert Path(result.anchor.module_path).name == "__init__.py"


def test_the_definition_path_itself_is_unchanged(tmp_path: Path) -> None:
    result = resolve_handle("clonepkg.thing.CloneThing", _analyzer(tmp_path, INITS["relative"]))

    assert isinstance(result, Resolved)
    assert result.handle == "clonepkg.thing.CloneThing"


def test_the_tools_agree(tmp_path: Path) -> None:
    import asyncio

    from pyeye.mcp.server import mcp

    _analyzer(tmp_path, INITS["relative"])
    p = tmp_path.as_posix()

    async def call(tool: str, **args: str) -> dict:
        result = await mcp.call_tool(tool, {**args, "project_path": p})
        assert not result.is_error, result.content
        return result.structured_content  # type: ignore[return-value]

    resolved = asyncio.run(call("resolve", identifier="clonepkg.CloneThing"))
    inspected = asyncio.run(call("inspect", handle="clonepkg.CloneThing"))
    definition = asyncio.run(call("inspect", handle="clonepkg.thing.CloneThing"))

    assert resolved["handle"] == inspected["handle"] == "clonepkg.thing.CloneThing"
    assert "clonepkg.CloneThing" in definition["re_exports"]
