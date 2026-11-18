"""find_pydantic_models' envelope discloses classes it can't place (#921 part 2).

A class whose base is an expression (``make_base()``, a conditional) has no
static base, so nobody can say whether it's a model. It isn't reported as one;
the envelope lists it in ``unplaced_classes``, capped by ``max_unplaced`` under
the bounded-response contract (#435). ``results`` is never capped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

_SOURCE = """
from pydantic import BaseModel

def make_base():
    return BaseModel

class User(BaseModel):
    name: str

class Admin(User):
    level: int

class Dynamic(make_base()):
    x: int

class Either(BaseModel if True else object):
    y: int

class NotPydantic(make_base()[0]):
    pass

class Generic(list[int]):
    pass
"""


def _server(project: Path) -> Any:
    from mcp.server.mcpserver import MCPServer

    from pyeye.config import ProjectConfig
    from pyeye.mcp import server as srv
    from pyeye.scope_utils import SmartScopeResolver

    server = MCPServer("unplaced-test")
    plugins = [cls(project.as_posix()) for cls in srv._PLUGIN_CLASSES]
    srv.register_plugin_tools(
        server, plugins, SmartScopeResolver(ProjectConfig(project.as_posix()))
    )
    return server


def _call(project: Path, **args: Any) -> Any:
    server = _server(project)

    async def run() -> Any:
        return await server.call_tool(
            "find_pydantic_models", {**args, "project_path": project.as_posix()}
        )

    result = asyncio.run(run())
    return result


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "models.py").write_text(_SOURCE)
    return tmp_path


def _envelope(project: Path, **args: Any) -> dict[str, Any]:
    result = _call(project, envelope=True, **args)
    assert not result.is_error, result.content
    response = result.structured_content
    # A tool that may return a list is wrapped as {"result": ...} on the wire.
    return response["result"] if set(response) == {"result"} else response


def test_unplaced_classes_lists_every_dynamic_base_class(project: Path) -> None:
    envelope = _envelope(project)

    unplaced = [(e["name"], e["line"], e["base"]) for e in envelope["unplaced_classes"]]
    # Every class with an expression base, pydantic-looking or not; Generic's
    # subscripted base names a class, so it's placed.
    assert unplaced == [
        ("Dynamic", 13, "make_base()"),
        ("Either", 16, "BaseModel if True else object"),
        ("NotPydantic", 19, "make_base()[0]"),
    ]
    assert all(Path(e["file"]).name == "models.py" for e in envelope["unplaced_classes"])
    assert sorted(m["name"] for m in envelope["results"]) == ["Admin", "User"]
    assert "truncated" not in envelope  # leave out, never false (#435)


def test_the_key_is_present_and_empty_when_nothing_is_unplaced(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "from pydantic import BaseModel\nclass A(BaseModel):\n    x: int\n"
    )

    envelope = _envelope(tmp_path)

    assert envelope["unplaced_classes"] == []


def test_the_cap_cuts_only_unplaced_classes(project: Path) -> None:
    envelope = _envelope(project, max_unplaced=1)

    assert [e["name"] for e in envelope["unplaced_classes"]] == ["Dynamic"]
    assert envelope["truncated"] is True
    assert envelope["truncation_reasons"] == ["max_unplaced"]
    assert envelope["total"] == 3
    # results is never capped.
    assert sorted(m["name"] for m in envelope["results"]) == ["Admin", "User"]


def test_no_cap_lists_them_all(project: Path) -> None:
    envelope = _envelope(project, max_unplaced=None)

    assert len(envelope["unplaced_classes"]) == 3 and "truncated" not in envelope


def test_an_invalid_cap_is_a_tool_error(project: Path) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="max_unplaced must be a positive integer"):
        _call(project, envelope=True, max_unplaced=0)


def test_the_bare_list_is_unchanged(project: Path) -> None:
    result = _call(project)

    assert not result.is_error
    response = result.structured_content
    models = response["result"] if isinstance(response, dict) else response
    assert sorted(m["name"] for m in models) == ["Admin", "User"]


def test_the_description_says_results_is_never_capped() -> None:
    from pyeye.plugins.pydantic import PydanticPlugin

    doc = " ".join((PydanticPlugin.find_models.__doc__ or "").split())
    assert "unplaced_classes" in doc and "max_unplaced" in doc
    assert "``results`` is never capped" in doc
