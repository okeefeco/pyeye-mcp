"""Plugin tools take a per-call ``project_path`` (#665).

Every plugin tool gains an optional ``project_path``. Omitted, the tool answers
about the project it was registered for, exactly as before. Given, it answers
about that project, with a plugin built from that project's own config:

- its package, namespace and standalone paths, and its ``scope_defaults``;
- run even when the project's framework wasn't auto-detected (the #665 decision,
  D1(a)): the scan really ran there, so ``[]`` is a measured empty;
- cached in ``ProjectManager`` beside the project's analyzer, and dropped with it;
- never mixed with another project's state, whatever the call order.

A ``project_path`` that doesn't exist is an MCP tool error, as on the core tools.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pyeye.config import ProjectConfig
from pyeye.mcp import server as server_module
from pyeye.mcp.server import _plugin_tool, get_project_manager, register_plugin_tools
from pyeye.path_utils import path_to_key
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.scope_utils import SmartScopeResolver

_MODEL = "from pydantic import BaseModel\n\n\nclass {name}(BaseModel):\n    x: int\n"


def _write_project(root: Path, model: str, extra: Path | None = None, **config: Any) -> Path:
    (root / "app").mkdir(parents=True)
    (root / "app" / "models.py").write_text(_MODEL.format(name=model), encoding="utf-8")
    data: dict[str, Any] = dict(config)
    if extra is not None:
        data["packages"] = [extra.as_posix()]
    (root / ".pyeye.json").write_text(json.dumps(data), encoding="utf-8")
    return root


@pytest.fixture
def projects(tmp_path: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Project A (the registered one), project B with its own extra package, and a plain C."""
    extra_b = tmp_path / "extra_b"
    (extra_b / "pkg").mkdir(parents=True)
    (extra_b / "pkg" / "models.py").write_text(_MODEL.format(name="ExtraB"), encoding="utf-8")
    a = _write_project(tmp_path / "a", "ModelA")
    b = _write_project(
        tmp_path / "b",
        "ModelB",
        extra=extra_b,
        scope_defaults={"methods": {"find_pydantic_models": "all"}},
    )
    c = tmp_path / "c"
    (c / "lib").mkdir(parents=True)
    (c / "lib" / "util.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    yield a, b, c
    manager = get_project_manager()
    for root in (a, b, c):
        manager.invalidate_analyzer(root.as_posix())


def _server_for(root: Path) -> MCPServer:
    """Register the Pydantic plugin for *root*, as initialize_plugins would."""
    config = ProjectConfig(root.as_posix())
    plugin = PydanticPlugin(root.as_posix())
    plugin.set_additional_paths([Path(p) for p in config.get_package_paths()])
    server = MCPServer("t")
    register_plugin_tools(server, [plugin], SmartScopeResolver(config))
    return server


async def _names(server: MCPServer, **args: Any) -> list[str]:
    result = await server.call_tool("find_pydantic_models", args)
    return sorted(json.loads(c.text)["name"] for c in result.content)


async def _files(server: MCPServer, **args: Any) -> list[str]:
    result = await server.call_tool("find_pydantic_models", args)
    return [json.loads(c.text)["file"] for c in result.content]


class TestSelection:
    @pytest.mark.asyncio
    async def test_default_is_the_registered_project(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        a, _b, _c = projects
        assert await _names(_server_for(a)) == ["ModelA"]

    @pytest.mark.asyncio
    async def test_project_path_answers_about_that_project(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        a, b, _c = projects
        server = _server_for(a)
        files = await _files(server, project_path=b.as_posix(), scope="main")
        assert files and all(f.startswith(b.as_posix() + "/") for f in files)
        assert await _names(server, project_path=b.as_posix(), scope="main") == ["ModelB"]

    @pytest.mark.asyncio
    async def test_scope_defaults_come_from_the_target_project(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        """B's config defaults find_pydantic_models to "all", so its package is searched."""
        a, b, _c = projects
        server = _server_for(a)
        assert await _names(server, project_path=b.as_posix()) == ["ExtraB", "ModelB"]
        assert await _names(server) == ["ModelA"]  # A has no such default

    @pytest.mark.asyncio
    async def test_undetected_framework_still_runs_and_is_measured_empty(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        """D1(a): C has no Pydantic at all; the scan runs there and finds none."""
        a, _b, c = projects
        assert await _names(_server_for(a), project_path=c.as_posix()) == []

    @pytest.mark.asyncio
    async def test_model_lookup_uses_the_target_project(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        a, b, _c = projects
        server = _server_for(a)
        result = await server.call_tool(
            "get_model_schema", {"model_name": "ModelB", "project_path": b.as_posix()}
        )
        payload = json.loads(result.content[0].text)
        assert payload["found"] is True
        missing = await server.call_tool("get_model_schema", {"model_name": "ModelB"})
        assert json.loads(missing.content[0].text)["found"] is False

    @pytest.mark.asyncio
    async def test_envelope_describes_the_target_project(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        a, b, _c = projects
        result = await _server_for(a).call_tool(
            "find_pydantic_models", {"project_path": b.as_posix(), "envelope": True}
        )
        payload = json.loads(result.content[0].text)
        assert payload["scope"] is None or payload["scope"] == "all"
        assert sorted(r["name"] for r in payload["results"]) == ["ExtraB", "ModelB"]
        assert any(s.startswith("package") or s == "all" for s in payload["searched"])


class TestNoLeak:
    @pytest.mark.asyncio
    async def test_alternating_calls_never_mix_projects(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        a, b, _c = projects
        server = _server_for(a)
        for _ in range(2):
            assert await _names(server, scope="all") == ["ModelA"]
            assert await _names(server, project_path=b.as_posix(), scope="all") == [
                "ExtraB",
                "ModelB",
            ]
            assert await _names(server, project_path=a.as_posix(), scope="all") == ["ModelA"]


class TestCache:
    @pytest.mark.asyncio
    async def test_one_context_per_project_dropped_with_the_analyzer(
        self, projects: tuple[Path, Path, Path]
    ) -> None:
        a, b, _c = projects
        server = _server_for(a)
        manager = get_project_manager()
        await _names(server, project_path=b.as_posix())
        await _names(server, project_path=b.as_posix())
        # Only b's contexts: another test's project may have its own (#1061).
        b_key = path_to_key(b)
        keys = [k for k in manager._plugin_contexts if k[1] is PydanticPlugin and k[0] == b_key]
        assert len(keys) == 1
        manager.invalidate_analyzer(b.as_posix())
        assert not [k for k in manager._plugin_contexts if k[1] is PydanticPlugin and k[0] == b_key]

    @pytest.mark.asyncio
    async def test_a_reconfigured_project_is_rebuilt_from_its_new_config(
        self, projects: tuple[Path, Path, Path], tmp_path: Path
    ) -> None:
        a, b, _c = projects
        server = _server_for(a)
        assert "ExtraB" in await _names(server, project_path=b.as_posix(), scope="all")
        more = tmp_path / "more_b"
        (more / "pkg2").mkdir(parents=True)
        (more / "pkg2" / "models.py").write_text(_MODEL.format(name="MoreB"), encoding="utf-8")
        await server_module.configure_packages(
            packages=[more.as_posix()], save=True, project_path=b.as_posix()
        )
        assert "MoreB" in await _names(server, project_path=b.as_posix(), scope="all")


class TestErrors:
    @pytest.mark.asyncio
    async def test_missing_project_is_a_tool_error(
        self, projects: tuple[Path, Path, Path], tmp_path: Path
    ) -> None:
        a, _b, _c = projects
        with pytest.raises(ToolError, match="ProjectNotFoundError"):
            await _server_for(a).call_tool(
                "find_pydantic_models", {"project_path": (tmp_path / "nope").as_posix()}
            )

    def test_a_tool_declaring_project_path_is_rejected(self, tmp_path: Path) -> None:
        def clash(scope: str = "main", project_path: str = ".") -> list[Any]:  # noqa: ARG001
            return []

        with pytest.raises(TypeError, match="project_path"):
            _plugin_tool("x", clash, PydanticPlugin(tmp_path.as_posix()), None)

    def test_description_says_how_project_path_behaves(self, tmp_path: Path) -> None:
        server = _server_for(tmp_path)
        raw = server._tool_manager._tools["find_pydantic_models"].description or ""
        description = " ".join(raw.split())
        assert "even if its framework wasn't auto-detected" in description
        assert "an empty result means the scan found none" in description
