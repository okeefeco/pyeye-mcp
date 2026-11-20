"""Re-detect frameworks after ``configure_packages`` adds a package (#659).

Framework plugins were detected once at startup, against the project root
only, so a framework used only in a configured package never activated, not
even after a restart.  Detection now covers the root and every configured
package and namespace path, at startup and again after ``configure_packages``
on the startup project.  Newly activated plugins' tools are registered at
runtime (add-only: nothing is ever unregistered or renamed), and any client can
call them by name; ``activated_plugins`` names what appeared.  The
tools-changed event is #770's (``tests/test_tools_list_changed.py``).
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from pyeye.plugins.base import AnalyzerPlugin

server = importlib.import_module("pyeye.mcp.server")

_FLASK_APP = "from flask import Flask\n\napp = Flask(__name__)\n\n\n@app.route('/hi')\ndef hi():\n    return 'hi'\n"


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> MCPServer:
    """A fresh MCP server and empty active-plugin list, restored afterwards."""
    fresh = MCPServer("test-redetect")
    monkeypatch.setattr(server, "mcp", fresh)
    saved = list(server._plugins)
    server._plugins.clear()
    yield fresh
    server._plugins.clear()
    server._plugins.extend(saved)


def _tools(srv: MCPServer) -> set[str]:
    return set(srv._tool_manager._tools)


@pytest.fixture
def startup_and_lib(tmp_path: Path) -> tuple[Path, Path]:
    """A startup project with no Flask, and a separate package that uses it."""
    # Not siblings: ProjectConfig auto-discovers sibling packages, and the point
    # here is a package that only configure_packages brings in.
    root = tmp_path / "projects" / "app"
    root.mkdir(parents=True)
    (root / "main.py").write_text("X = 1\n", encoding="utf-8")
    lib = tmp_path / "vendor" / "libs" / "weblib"
    lib.mkdir(parents=True)
    (lib / "app.py").write_text(_FLASK_APP, encoding="utf-8")
    return root, lib


async def test_a_framework_only_in_an_added_package_activates(
    isolated: MCPServer, startup_and_lib: tuple[Path, Path]
) -> None:
    root, lib = startup_and_lib
    server.initialize_plugins(root.as_posix())
    assert "find_flask_routes" not in _tools(isolated)

    result = await server.configure_packages(
        packages=[lib.as_posix()], save=False, project_path=root.as_posix()
    )

    assert result["activated_plugins"] == ["Flask"]
    assert "find_flask_routes" in _tools(isolated)
    # Callable by name, whether or not the client re-lists its tools.
    routes = await isolated.call_tool("find_flask_routes", {})
    assert routes is not None


async def test_a_second_identical_call_activates_nothing(
    isolated: MCPServer, startup_and_lib: tuple[Path, Path]
) -> None:
    root, lib = startup_and_lib
    server.initialize_plugins(root.as_posix())
    await server.configure_packages(
        packages=[lib.as_posix()], save=False, project_path=root.as_posix()
    )
    before = _tools(isolated)

    again = await server.configure_packages(
        packages=[lib.as_posix()], save=False, project_path=root.as_posix()
    )

    assert again["activated_plugins"] == []
    assert _tools(isolated) == before


async def test_redetection_is_add_only(
    isolated: MCPServer, startup_and_lib: tuple[Path, Path]
) -> None:
    """Re-detection never unregisters or renames a tool (a removal under v2.x)."""
    root, lib = startup_and_lib
    (root / "models.py").write_text(
        "from pydantic import BaseModel\n\n\nclass M(BaseModel):\n    x: int\n", encoding="utf-8"
    )
    server.initialize_plugins(root.as_posix())
    before = _tools(isolated)
    assert "find_pydantic_models" in before

    await server.configure_packages(
        packages=[lib.as_posix()], save=False, project_path=root.as_posix()
    )

    after = _tools(isolated)
    assert before <= after
    assert after - before >= {"find_flask_routes"}


async def test_a_non_startup_project_is_not_redetected(
    isolated: MCPServer, startup_and_lib: tuple[Path, Path], tmp_path: Path
) -> None:
    root, lib = startup_and_lib
    server.initialize_plugins(root.as_posix())
    other = tmp_path / "other"
    other.mkdir()

    result = await server.configure_packages(
        packages=[lib.as_posix()], save=False, project_path=other.as_posix()
    )

    assert "activated_plugins" not in result
    assert "find_flask_routes" not in _tools(isolated)


async def test_startup_detection_sees_configured_packages(
    isolated: MCPServer, startup_and_lib: tuple[Path, Path]
) -> None:
    """A restart gives the same answer as re-detection: packages from .pyeye.json count."""
    root, lib = startup_and_lib
    (root / ".pyeye.json").write_text(f'{{"packages": ["{lib.as_posix()}"]}}', encoding="utf-8")

    server.initialize_plugins(root.as_posix())

    assert "find_flask_routes" in _tools(isolated)


@pytest.mark.usefixtures("isolated")
async def test_a_detect_failure_is_logged_and_skipped(
    startup_and_lib: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Broken(AnalyzerPlugin):
        def name(self) -> str:
            return "broken"

        def detect(self) -> bool:
            raise RuntimeError("detector bug")

        def register_tools(self) -> dict[str, Any]:
            return {}

    root, lib = startup_and_lib
    monkeypatch.setattr(server, "_PLUGIN_CLASSES", (Broken, *server._PLUGIN_CLASSES))
    server.initialize_plugins(root.as_posix())

    with caplog.at_level(logging.ERROR, logger=server.logger.name):
        result = await server.configure_packages(
            packages=[lib.as_posix()], save=False, project_path=root.as_posix()
        )

    assert result["activated_plugins"] == ["Flask"]
    assert any("Broken" in r.getMessage() for r in caplog.records)


def test_register_plugin_tools_skips_names_already_registered() -> None:
    """The second, runtime call registers only new names and still rejects real duplicates."""

    class Two(AnalyzerPlugin):
        def name(self) -> str:
            return "two"

        def detect(self) -> bool:
            return True

        def register_tools(self) -> dict[str, Any]:
            async def a(scope: str = "main") -> list[Any]:
                return [scope]

            return {"tool_a": a}

    fresh = MCPServer("t")
    first = Two(".")
    assert server.register_plugin_tools(fresh, [first]) == ["tool_a"]
    second = Two(".")
    assert server.register_plugin_tools(fresh, [second], already_registered={"tool_a"}) == []
    with pytest.raises(ValueError, match="already registered"):
        server.register_plugin_tools(fresh, [first, second])
