"""Plugin tools honour ``scope_defaults`` when the caller passes no scope (#559).

Before this, every plugin method hard-coded ``scope="main"`` and never consulted
the configured defaults, so ``"scope_defaults": {"methods": {...}}`` or
``"global"`` did nothing: a namespace project's ``find_pydantic_models`` silently
searched only the main repo.

Now, for a plugin tool called without ``scope``:

1. ``scope_defaults.methods.<tool name>`` (keyed on the MCP tool name, e.g.
   ``find_pydantic_models``), else
2. ``scope_defaults.global``, else
3. ``"main"`` (unchanged built-in default).

An explicit ``scope`` argument always wins. Keys that aren't plugin tool names,
such as the old method names (``find_models`` is ambiguous between Django and
Pydantic), are reported as ignored rather than guessed at.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer

from pyeye.config import ProjectConfig
from pyeye.mcp.server import all_plugin_tool_names, register_plugin_tools
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.scope_utils import SmartScopeResolver

_MODEL = "from pydantic import BaseModel\n\n\nclass {name}(BaseModel):\n    x: int\n"


@pytest.fixture
def project(tmp_path: Path):
    """A main project plus a 'shared' namespace repo, each with one model."""
    main = tmp_path / "main"
    (main / "app").mkdir(parents=True)
    (main / "app" / "models.py").write_text(_MODEL.format(name="MainModel"))
    shared = tmp_path / "shared"
    (shared / "lib").mkdir(parents=True)
    (shared / "lib" / "models.py").write_text(_MODEL.format(name="SharedModel"))
    return main, shared


def _server(
    main: Path, shared: Path, scope_defaults: dict | None, aliases: dict | None = None
) -> MCPServer:
    config_data: dict = {"namespaces": {"shared": [shared.as_posix()]}}
    if scope_defaults is not None:
        config_data["scope_defaults"] = scope_defaults
    if aliases is not None:
        config_data["scope_aliases"] = aliases
    (main / ".pyeye.json").write_text(json.dumps(config_data))

    config = ProjectConfig(str(main))
    plugin = PydanticPlugin(str(main))
    plugin.set_namespace_paths(config.get_namespaces())
    server = MCPServer("test")
    register_plugin_tools(server, [plugin], SmartScopeResolver(config))
    return server


async def _model_names(server: MCPServer, args: dict | None = None) -> set[str]:
    result = await server.call_tool("find_pydantic_models", args or {})
    return {json.loads(item.text)["name"] for item in result.content}


class TestResolution:
    async def test_no_config_defaults_to_main(self, project):
        assert await _model_names(_server(*project, None)) == {"MainModel"}

    async def test_tool_name_key_applies(self, project):
        server = _server(*project, {"methods": {"find_pydantic_models": "all"}})
        assert await _model_names(server) == {"MainModel", "SharedModel"}

    async def test_global_applies_when_no_tool_key(self, project):
        server = _server(*project, {"global": "namespace:shared"})
        assert await _model_names(server) == {"SharedModel"}

    async def test_tool_key_beats_global(self, project):
        server = _server(*project, {"global": "all", "methods": {"find_pydantic_models": "main"}})
        assert await _model_names(server) == {"MainModel"}

    async def test_explicit_scope_beats_config(self, project):
        server = _server(*project, {"methods": {"find_pydantic_models": "all"}})
        assert await _model_names(server, {"scope": "main"}) == {"MainModel"}

    async def test_alias_as_default_is_expanded(self, project):
        """Plugins don't know aliases; unexpanded, one searched nothing."""
        server = _server(
            *project,
            {"methods": {"find_pydantic_models": "everything"}},
            {"everything": ["main", "namespace:shared"]},
        )
        assert await _model_names(server) == {"MainModel", "SharedModel"}

    async def test_explicit_alias_is_expanded(self, project):
        server = _server(*project, None, {"libs": "namespace:shared"})
        assert await _model_names(server, {"scope": "libs"}) == {"SharedModel"}

    async def test_legacy_method_name_key_is_not_applied(self, project):
        """``find_models`` was never a tool name; it must not silently apply."""
        server = _server(*project, {"methods": {"find_models": "all"}})
        assert await _model_names(server) == {"MainModel"}


class TestToolSchema:
    async def test_scope_is_optional_with_null_default(self, project):
        server = _server(*project, None)
        tools = {t.name: t for t in await server.list_tools()}
        prop = tools["find_pydantic_models"].input_schema["properties"]["scope"]
        assert prop.get("default") is None
        assert "scope" not in tools["find_pydantic_models"].input_schema.get("required", [])

    async def test_other_parameters_are_unchanged(self, project):
        server = _server(*project, None)
        tools = {t.name: t for t in await server.list_tools()}
        assert tools["get_model_schema"].input_schema["required"] == ["model_name"]

    async def test_description_states_the_default_source(self, project):
        server = _server(*project, None)
        tools = {t.name: t for t in await server.list_tools()}
        assert "scope_defaults" in tools["find_pydantic_models"].description


class TestResolverApi:
    def test_plugin_tool_default_order(self, tmp_path):
        (tmp_path / ".pyeye.json").write_text(
            json.dumps(
                {"scope_defaults": {"global": "all", "methods": {"find_flask_routes": "main"}}}
            )
        )
        resolver = SmartScopeResolver(ProjectConfig(str(tmp_path)))
        assert resolver.plugin_tool_default("find_flask_routes") == "main"
        assert resolver.plugin_tool_default("find_flask_views") == "all"
        assert SmartScopeResolver(None).plugin_tool_default("find_flask_views") == "main"

    def test_ignored_method_keys_names_non_tool_keys(self, tmp_path):
        (tmp_path / ".pyeye.json").write_text(
            json.dumps(
                {
                    "scope_defaults": {
                        "methods": {
                            "find_models": "all",
                            "find_pydantic_models": "all",
                            "list_modules": "main",
                        }
                    }
                }
            )
        )
        resolver = SmartScopeResolver(ProjectConfig(str(tmp_path)))
        assert resolver.ignored_method_keys(all_plugin_tool_names(str(tmp_path))) == [
            "find_models",
            "list_modules",
        ]

    def test_builtin_table_has_no_plugin_method_names(self):
        """Plugin defaults now come from the tool-name lookup, not this table."""
        stale = {"find_routes", "find_models", "find_views", "find_blueprints", "find_templates"}
        assert not stale & set(SmartScopeResolver.SMART_DEFAULTS)


def test_all_plugin_tool_names_covers_every_plugin(tmp_path):
    names = all_plugin_tool_names(str(tmp_path))
    assert {"find_pydantic_models", "find_flask_routes", "find_django_models"} <= names


_ROOT = Path(__file__).resolve().parents[1]
_METHODS_BLOCK = re.compile(r'"methods"\s*:\s*\{(?P<body>[^}]*)\}')
_TOML_METHODS = re.compile(
    r"^\[tool\.pyeye\.scope_defaults\.methods\]\n(?P<body>(?:[^\[\n].*\n?)*)", re.M
)


def _documented_method_keys() -> dict[str, list[str]]:
    """``scope_defaults.methods`` keys in the docs' and examples' config snippets."""
    keys: dict[str, list[str]] = {}
    files = [
        *(_ROOT / "examples" / "configurations").glob("*.json"),
        *(_ROOT / "docs").glob("*.md"),
        *(_ROOT / "docs" / "source").rglob("*.rst"),
        _ROOT / "README.md",
        _ROOT / "DOCUMENTATION.md",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        bodies = [m["body"] for m in _METHODS_BLOCK.finditer(text)]
        bodies += [m["body"] for m in _TOML_METHODS.finditer(text)]
        for body in bodies:
            for key in re.findall(r'^\s*"?([A-Za-z_]\w*)"?\s*[:=]', body, re.M):
                keys.setdefault(key, []).append(path.relative_to(_ROOT).as_posix())
    return keys


def test_documented_method_keys_are_plugin_tool_names(tmp_path):
    """Every documented scope_defaults.methods key must be a tool it applies to."""
    tools = all_plugin_tool_names(str(tmp_path))
    documented = _documented_method_keys()
    assert documented, "found no documented scope_defaults.methods keys; parser broken?"
    bad = {key: sorted(set(where)) for key, where in documented.items() if key not in tools}
    assert not bad, f"scope_defaults.methods keys that aren't plugin tool names: {bad}"


class TestStartupPath:
    """``initialize_plugins`` wires the resolver in and reports ignored keys."""

    async def test_initialize_plugins_applies_defaults_and_warns(
        self, project, monkeypatch, caplog
    ):
        import logging

        import pyeye.mcp.server as srv

        main, shared = project
        (main / ".pyeye.json").write_text(
            json.dumps(
                {
                    "namespaces": {"shared": [shared.as_posix()]},
                    "scope_defaults": {
                        "methods": {"find_pydantic_models": "all", "find_models": "all"}
                    },
                }
            )
        )
        fresh = MCPServer("startup-test")
        monkeypatch.setattr(srv, "mcp", fresh)
        monkeypatch.setattr(srv, "_plugins", [])

        with caplog.at_level(logging.WARNING, logger="pyeye.mcp.server"):
            srv.initialize_plugins(str(main))

        assert "find_pydantic_models" in {t.name for t in await fresh.list_tools()}
        assert await _model_names(fresh) == {"MainModel", "SharedModel"}
        warnings = [r.getMessage() for r in caplog.records if "scope_defaults" in r.getMessage()]
        assert len(warnings) == 1
        # Only the non-tool key is listed; the valid tool-name key isn't.
        assert "plugin tool names: find_models." in warnings[0]
