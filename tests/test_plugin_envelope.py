"""Opt-in ``envelope=true`` on plugin tools reports what was searched (#594).

A plugin tool returns a bare list, which a client receives as one content item per
result. An empty result is zero items, and nothing says which scope was searched, so
"these are all the models" can't be told from "these are the main repo's models".

With ``envelope=true`` every plugin tool returns::

    {"scope": ..., "searched": [...], "unsearched_scopes": [...], "results": ...}

The default (``envelope`` omitted or false) must stay byte-for-byte what it was:
making the envelope the default is a breaking change, deferred to #644.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from pyeye.config import ProjectConfig
from pyeye.mcp.server import register_plugin_tools
from pyeye.plugins.base import AnalyzerPlugin
from pyeye.plugins.django import DjangoPlugin
from pyeye.plugins.flask import FlaskPlugin
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.scope_utils import SmartScopeResolver

_MODEL = "from pydantic import BaseModel\n\n\nclass {name}(BaseModel):\n    x: int\n"

PLUGIN_CLASSES: tuple[type[AnalyzerPlugin], ...] = (PydanticPlugin, DjangoPlugin, FlaskPlugin)

# Tools whose signature needs more than scope.
EXTRA_ARGS: dict[str, dict[str, Any]] = {
    "get_model_schema": {"model_name": "MainModel"},
    "trace_model_inheritance": {"model_name": "MainModel"},
}

FLASK_APP = """
from flask import Flask, Blueprint, render_template

app = Flask(__name__)
bp = Blueprint('bp', __name__, url_prefix='/bp')


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.errorhandler(404)
def missing(e):
    return 'x', 404
"""


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A main project, a 'shared' namespace repo and an extra package, each with code."""
    main = tmp_path / "main"
    (main / "app").mkdir(parents=True)
    (main / "app" / "models.py").write_text(_MODEL.format(name="MainModel"))
    (main / "app.py").write_text(FLASK_APP)
    blog = main / "blog"
    blog.mkdir()
    (blog / "models.py").write_text(
        "from django.db import models\n\n\nclass Post(models.Model):\n    pass\n"
    )
    shared = tmp_path / "shared"
    (shared / "lib").mkdir(parents=True)
    (shared / "lib" / "models.py").write_text(_MODEL.format(name="SharedModel"))
    extra = tmp_path / "extra"
    (extra / "pkg").mkdir(parents=True)
    (extra / "pkg" / "models.py").write_text(_MODEL.format(name="ExtraModel"))
    return main, shared, extra


def _config(main: Path, shared: Path, extra: Path | None, **more: Any) -> ProjectConfig:
    data: dict[str, Any] = {"namespaces": {"shared": [shared.as_posix()]}, **more}
    if extra is not None:
        data["packages"] = [extra.as_posix()]
    (main / ".pyeye.json").write_text(json.dumps(data))
    return ProjectConfig(str(main))


def _plugins(main: Path, config: ProjectConfig) -> list[AnalyzerPlugin]:
    plugins = []
    for cls in PLUGIN_CLASSES:
        plugin = cls(str(main))
        plugin.set_additional_paths([Path(p) for p in config.get_package_paths()])
        plugin.set_namespace_paths(config.get_namespaces())
        plugins.append(plugin)
    return plugins


def _wrapped_server(plugins: list[AnalyzerPlugin], config: ProjectConfig) -> MCPServer:
    server = MCPServer("wrapped")
    register_plugin_tools(server, plugins, SmartScopeResolver(config))
    return server


def _raw_server(plugins: list[AnalyzerPlugin]) -> MCPServer:
    """Plugin methods registered directly: the pre-#594 wire format."""
    server = MCPServer("raw")
    for plugin in plugins:
        for name, func in plugin.register_tools().items():
            server.tool(name=name)(func)
    return server


def _all_tool_names() -> list[str]:
    names: list[str] = []
    for cls in PLUGIN_CLASSES:
        names.extend(cls(".").register_tools())
    return names


ALL_TOOLS = _all_tool_names()


#: Keys #627 adds: per-record handles, scope and location (slice A), and the
#: model lookups' ``found`` discriminator (slice B). The pins below strip them, so
#: they still prove the pre-#594 output is otherwise unchanged.
_ADDED_BY_627 = frozenset({"location", "scope", "handle", "unresolved", "found"})


def _strip_627(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_627(v) for k, v in value.items() if k not in _ADDED_BY_627}
    if isinstance(value, list):
        return [_strip_627(v) for v in value]
    return value


def _dump(result: Any) -> Any:
    content = []
    for c in result.content:
        item = c.model_dump()
        item["text"] = _strip_627(json.loads(item["text"]))
        content.append(item)
    return (
        content,
        _strip_627(getattr(result, "structured_content", None)),
        result.is_error,
    )


async def _envelope(server: MCPServer, tool: str, **args: Any) -> dict[str, Any]:
    result = await server.call_tool(tool, {**EXTRA_ARGS.get(tool, {}), **args, "envelope": True})
    assert not result.is_error, result.content
    assert len(result.content) == 1
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, dict)
    return payload


def test_every_plugin_tool_is_covered() -> None:
    assert len(ALL_TOOLS) == len(set(ALL_TOOLS)) == 20


class TestSchema:
    @pytest.mark.parametrize("tool", ALL_TOOLS)
    async def test_envelope_is_an_optional_boolean_defaulting_false(
        self, project: tuple[Path, Path, Path], tool: str
    ) -> None:
        main, shared, extra = project
        config = _config(main, shared, extra)
        tools = {
            t.name: t for t in await _wrapped_server(_plugins(main, config), config).list_tools()
        }

        schema = tools[tool].input_schema
        assert schema["properties"]["envelope"]["type"] == "boolean"
        assert schema["properties"]["envelope"]["default"] is False
        assert "envelope" not in schema.get("required", [])


class TestDefaultIsUnchanged:
    """Without ``envelope``, the wire output equals the plugin method registered raw."""

    @pytest.mark.parametrize("envelope_arg", [{}, {"envelope": False}])
    @pytest.mark.parametrize("tool", ALL_TOOLS)
    async def test_byte_for_byte(
        self, project: tuple[Path, Path, Path], tool: str, envelope_arg: dict[str, Any]
    ) -> None:
        main, shared, extra = project
        config = _config(main, shared, extra)
        plugins = _plugins(main, config)
        args = {**EXTRA_ARGS.get(tool, {}), "scope": "all"}

        wrapped = await _wrapped_server(plugins, config).call_tool(tool, {**args, **envelope_arg})
        raw = await _raw_server(plugins).call_tool(tool, args)

        assert _dump(wrapped) == _dump(raw)

    async def test_bare_list_is_one_item_per_result(self, project: tuple[Path, Path, Path]) -> None:
        main, shared, extra = project
        config = _config(main, shared, extra)
        result = await _wrapped_server(_plugins(main, config), config).call_tool(
            "find_pydantic_models", {"scope": "all"}
        )
        names = sorted(json.loads(c.text)["name"] for c in result.content)
        assert names == ["ExtraModel", "MainModel", "SharedModel"]


class TestEnvelopeShape:
    @pytest.mark.parametrize("tool", ALL_TOOLS)
    async def test_keys_and_results_match_the_bare_answer(
        self, project: tuple[Path, Path, Path], tool: str
    ) -> None:
        main, shared, extra = project
        config = _config(main, shared, extra)
        plugins = _plugins(main, config)
        method = next(p.register_tools()[tool] for p in plugins if tool in p.register_tools())

        payload = await _envelope(_wrapped_server(plugins, config), tool, scope="main")

        assert list(payload) == ["scope", "searched", "unsearched_scopes", "results"]
        expected = await method(**EXTRA_ARGS.get(tool, {}), scope="main")
        assert _strip_627(payload["results"]) == json.loads(json.dumps(expected))

    async def test_empty_results_are_present_not_absent(self, tmp_path: Path) -> None:
        # A subdirectory, so ProjectConfig's sibling auto-discovery sees no other
        # test's directories as packages.
        root = tmp_path / "empty"
        root.mkdir()
        config = ProjectConfig(str(root))
        server = _wrapped_server(_plugins(root, config), config)

        payload = await _envelope(server, "find_flask_routes")

        assert payload == {
            "scope": "main",
            "searched": ["main"],
            "unsearched_scopes": [],
            "results": [],
        }


class TestScopeReporting:
    async def _payload(
        self, project: tuple[Path, Path, Path], with_packages: bool = True, **args: Any
    ) -> dict[str, Any]:
        main, shared, extra = project
        config = _config(main, shared, extra if with_packages else None, **args.pop("config", {}))
        return await _envelope(
            _wrapped_server(_plugins(main, config), config), "find_pydantic_models", **args
        )

    async def test_main_lists_configured_scopes_it_skipped(
        self, project: tuple[Path, Path, Path]
    ) -> None:
        payload = await self._payload(project, scope="main")

        assert payload["scope"] == "main"
        assert payload["searched"] == ["main"]
        assert payload["unsearched_scopes"] == ["packages", "namespace:shared"]
        assert [r["name"] for r in payload["results"]] == ["MainModel"]

    async def test_all_skips_nothing(self, project: tuple[Path, Path, Path]) -> None:
        payload = await self._payload(project, scope="all")

        assert payload["searched"] == ["main", "packages", "namespace:shared"]
        assert payload["unsearched_scopes"] == []
        assert sorted(r["name"] for r in payload["results"]) == [
            "ExtraModel",
            "MainModel",
            "SharedModel",
        ]

    async def test_list_scope(self, project: tuple[Path, Path, Path]) -> None:
        payload = await self._payload(project, scope=["main", "namespace:shared"])

        assert payload["scope"] == ["main", "namespace:shared"]
        assert payload["searched"] == ["main", "namespace:shared"]
        assert payload["unsearched_scopes"] == ["packages"]

    async def test_without_packages_configured(self, project: tuple[Path, Path, Path]) -> None:
        payload = await self._payload(project, with_packages=False, scope="main")

        assert payload["unsearched_scopes"] == ["namespace:shared"]

    async def test_unknown_namespace_searches_nothing(
        self, project: tuple[Path, Path, Path]
    ) -> None:
        payload = await self._payload(project, scope="namespace:nope")

        assert payload["searched"] == []
        assert payload["unsearched_scopes"] == ["main", "packages", "namespace:shared"]
        assert payload["results"] == []

    async def test_single_package_path(self, project: tuple[Path, Path, Path]) -> None:
        extra = project[2]
        payload = await self._payload(project, scope=f"package:{extra.as_posix()}")

        # Coverage is by path: `extra` is the only configured package, so naming it
        # covers `packages` too.
        assert payload["searched"] == ["packages", f"package:{extra.as_posix()}"]
        assert payload["unsearched_scopes"] == ["main", "namespace:shared"]

    async def test_one_of_several_packages_leaves_packages_unsearched(
        self, project: tuple[Path, Path, Path], tmp_path: Path
    ) -> None:
        second = tmp_path / "second"
        second.mkdir()
        extra = project[2]
        payload = await self._payload(
            project,
            with_packages=False,
            scope=f"package:{extra.as_posix()}",
            config={"packages": [extra.as_posix(), second.as_posix()]},
        )

        assert payload["searched"] == [f"package:{extra.as_posix()}"]
        assert payload["unsearched_scopes"] == ["main", "packages", "namespace:shared"]

    async def test_packages_scope_reports_what_it_actually_reads(
        self, project: tuple[Path, Path, Path]
    ) -> None:
        # `packages` searches the configured packages only (#690). It used to also
        # search main and the namespaces, which initialize_plugins mixed into
        # additional_paths (#594); the envelope still reports exactly what it read.
        payload = await self._payload(project, scope="packages")

        assert payload["searched"] == ["packages"]
        assert payload["unsearched_scopes"] == ["main", "namespace:shared"]

    async def test_alias_reports_the_requested_name_and_the_expansion(
        self, project: tuple[Path, Path, Path]
    ) -> None:
        payload = await self._payload(
            project, scope="everything", config={"scope_aliases": {"everything": "all"}}
        )

        assert payload["scope"] == "everything"
        assert payload["searched"] == ["main", "packages", "namespace:shared"]
        assert payload["unsearched_scopes"] == []

    async def test_defaulted_scope_is_reported(self, project: tuple[Path, Path, Path]) -> None:
        payload = await self._payload(
            project, config={"scope_defaults": {"methods": {"find_pydantic_models": "all"}}}
        )

        assert payload["scope"] == "all"
        assert payload["unsearched_scopes"] == []


class TestWithoutResolver:
    async def test_envelope_works_when_registered_without_scope_defaults(
        self, project: tuple[Path, Path, Path]
    ) -> None:
        main, shared, extra = project
        config = _config(main, shared, extra)
        server = MCPServer("no-resolver")
        register_plugin_tools(server, _plugins(main, config))

        payload = await _envelope(server, "find_pydantic_models")

        assert payload["scope"] == "main"
        assert payload["unsearched_scopes"] == ["packages", "namespace:shared"]


def test_skill_tells_agents_to_pass_envelope() -> None:
    skill = Path(__file__).resolve().parent.parent / "skills" / "python-explore" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")

    assert "envelope=true" in text
    assert "unsearched_scopes" in text


class TestWrapperGuards:
    def test_tool_without_scope_is_rejected(self, tmp_path: Path) -> None:
        from pyeye.mcp.server import _plugin_tool

        async def no_scope() -> list[str]:
            return []

        with pytest.raises(TypeError, match="no 'scope'"):
            _plugin_tool("x", no_scope, FlaskPlugin(str(tmp_path)), None)

    def test_tool_declaring_envelope_is_rejected(self, tmp_path: Path) -> None:
        from pyeye.mcp.server import _plugin_tool

        async def clash(scope: str = "main", envelope: bool = False) -> list[str]:  # noqa: ARG001
            return []

        with pytest.raises(TypeError, match="already declares 'envelope'"):
            _plugin_tool("x", clash, FlaskPlugin(str(tmp_path)), None)
