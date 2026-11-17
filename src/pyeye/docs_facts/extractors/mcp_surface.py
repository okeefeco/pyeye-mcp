"""MCP surface facts: every tool, and every parameter with its type and default.

Read from live registrations, never from a hand-kept list:

- core tools from the module-level server;
- admin tools (opt-in via ``PYEYE_ENABLE_PERFORMANCE_METRICS``) registered on a
  fresh server, so the result doesn't depend on the environment;
- plugin tools from every plugin class, registered on a fresh server the way
  the server registers them for a detected framework.

Importing the server starts no worker, watcher or thread; it does only the
module-level registration.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ...scope_utils import SmartScopeResolver
from ..facts import Bindable, Fact, code, code_list, table, view

PREFIXES = ("tool", "tools")


def _schema_type(schema: dict[str, Any]) -> str:
    """Render a JSON-schema fragment as a short Python-like type."""
    if "anyOf" in schema:
        return " | ".join(_schema_type(s) for s in schema["anyOf"])
    kind = schema.get("type")
    if kind == "array":
        return f"list[{_schema_type(schema.get('items', {}))}]"
    if kind == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"dict[str, {_schema_type(extra)}]"
        return "dict"
    names = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}
    if kind == "null":
        return "None"
    return names.get(str(kind), "any")


async def _list_tools(server: Any) -> list[Any]:
    return list(await server.list_tools())


#: Where an omitted plugin ``scope`` comes from (#559): the resolver, not the schema.
SCOPE_DEFAULT_SOURCE = (
    "scope_defaults.methods.<tool>, then scope_defaults.global, then the built-in default"
)


def _default_cell(value: dict[str, Any]) -> str:
    if value["required"]:
        return "required"
    shown = code(json.dumps(value.get("default")))
    if "effective_default" in value:
        effective = code(json.dumps(value["effective_default"]))
        shown += f" (omitted: {effective} unless `scope_defaults` overrides it)"
    return shown


def _tool_facts(
    tools: list[Any],
    group: str,
    plugin: str | None,
    scope_default: Callable[[str], Any] | None = None,
) -> Iterator[Bindable]:
    tool_facts: list[Fact] = []
    for tool in sorted(tools, key=lambda t: t.name):
        schema = tool.input_schema
        required = set(schema.get("required", []))
        params: list[Fact] = []
        for pname, pschema in schema.get("properties", {}).items():
            value: dict[str, Any] = {
                "type": _schema_type(pschema),
                "required": pname in required,
            }
            if "default" in pschema:
                value["default"] = pschema["default"]
            if pname == "scope" and scope_default is not None:
                value["effective_default"] = scope_default(tool.name)
                value["effective_default_source"] = SCOPE_DEFAULT_SOURCE
            shown = "required" if value["required"] else json.dumps(value.get("default"))
            params.append(Fact(f"tool.{tool.name}.param.{pname}", value, f"{code(pname)}: {shown}"))
        yield from params
        tool_value: dict[str, Any] = {"group": group, "params": [p.id for p in params]}
        if plugin is not None:
            tool_value["plugin"] = plugin
        tool_fact = Fact(f"tool.{tool.name}", tool_value, code(tool.name))
        tool_facts.append(tool_fact)
        yield tool_fact
        rows = [
            [
                code(p.id.rsplit(".", 1)[1]),
                code(p.value["type"]),
                _default_cell(p.value),
            ]
            for p in params
        ]
        yield view(
            f"tool.{tool.name}.params",
            params,
            table(["Parameter", "Type", "Default"], rows),
        )
    if tool_facts:
        key = f"tools.{group}" if plugin is None else f"tools.plugin.{plugin}"
        yield view(key, tool_facts, code_list(f.id.split(".", 1)[1] for f in tool_facts))


def extract(root: Path) -> Iterator[Bindable]:  # noqa: ARG001 - live registration, no files
    """Yield a fact per tool and per parameter, plus the group views."""
    from mcp.server.mcpserver import MCPServer

    from ...mcp import server as srv

    admin_server = MCPServer("docs-facts-admin")
    for admin_tool in srv.ADMIN_TOOLS:
        admin_server.tool()(admin_tool)
    admin_names = {t.name for t in asyncio.run(_list_tools(admin_server))}
    core = [t for t in asyncio.run(_list_tools(srv.mcp)) if t.name not in admin_names]
    yield from _tool_facts(core, "core", None)
    yield from _tool_facts(asyncio.run(_list_tools(admin_server)), "admin", None)

    # A resolver with no project config: the built-in defaults, registered the way
    # initialize_plugins registers them (which always passes a resolver).
    resolver = SmartScopeResolver()
    for plugin_class in srv._PLUGIN_CLASSES:
        plugin = plugin_class(".")
        plugin_server = MCPServer(f"docs-facts-{plugin.name()}")
        srv.register_plugin_tools(plugin_server, [plugin], resolver)
        tools = asyncio.run(_list_tools(plugin_server))
        yield from _tool_facts(tools, "plugin", plugin.name().lower(), resolver.plugin_tool_default)
