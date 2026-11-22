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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...scope_utils import SmartScopeResolver
from .. import static_signatures as sig
from ..facts import Bindable, ExtractionError, Fact, code, code_list, table, view
from ..static import constant

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


@dataclass(frozen=True)
class _Param:
    """One input parameter, as the schema states it."""

    name: str
    type: str
    required: bool
    default: Any = None
    has_default: bool = False


#: A tool: its name and its parameters, in schema order.
_Tool = tuple[str, list[_Param]]


def _schema_tools(tools: list[Any]) -> list[_Tool]:
    """Records from live MCP tool objects (their input schemas)."""
    records = []
    for tool in tools:
        schema = tool.input_schema
        required = set(schema.get("required", []))
        records.append(
            (
                tool.name,
                [
                    _Param(
                        pname,
                        _schema_type(pschema),
                        pname in required,
                        pschema.get("default"),
                        "default" in pschema,
                    )
                    for pname, pschema in schema.get("properties", {}).items()
                ],
            )
        )
    return records


def _tool_facts(
    tools: list[_Tool],
    group: str,
    plugin: str | None,
    scope_default: Callable[[str], Any] | None = None,
) -> Iterator[Bindable]:
    tool_facts: list[Fact] = []
    for tool_name, tool_params in sorted(tools, key=lambda t: t[0]):
        params: list[Fact] = []
        for param in tool_params:
            value: dict[str, Any] = {"type": param.type, "required": param.required}
            if param.has_default:
                value["default"] = param.default
            if param.name == "scope" and scope_default is not None:
                value["effective_default"] = scope_default(tool_name)
                value["effective_default_source"] = SCOPE_DEFAULT_SOURCE
            shown = "required" if value["required"] else json.dumps(value.get("default"))
            params.append(
                Fact(f"tool.{tool_name}.param.{param.name}", value, f"{code(param.name)}: {shown}")
            )
        yield from params
        tool_value: dict[str, Any] = {"group": group, "params": [p.id for p in params]}
        if plugin is not None:
            tool_value["plugin"] = plugin
        tool_fact = Fact(f"tool.{tool_name}", tool_value, code(tool_name))
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
            f"tool.{tool_name}.params",
            params,
            table(["Parameter", "Type", "Default"], rows),
        )
    if tool_facts:
        key = f"tools.{group}" if plugin is None else f"tools.plugin.{plugin}"
        yield view(key, tool_facts, code_list(f.id.split(".", 1)[1] for f in tool_facts))


def _extract_imported(root: Path) -> Iterator[Bindable]:  # noqa: ARG001 - live registration
    """The import-based twin, kept until the static path matches it byte for byte (#1098)."""
    from mcp.server.mcpserver import MCPServer

    from ...mcp import server as srv

    admin_server = MCPServer("docs-facts-admin")
    for admin_tool in srv.ADMIN_TOOLS:
        admin_server.tool()(admin_tool)
    admin_names = {t.name for t in asyncio.run(_list_tools(admin_server))}
    core = [t for t in asyncio.run(_list_tools(srv.mcp)) if t.name not in admin_names]
    yield from _tool_facts(_schema_tools(core), "core", None)
    yield from _tool_facts(_schema_tools(asyncio.run(_list_tools(admin_server))), "admin", None)

    # A resolver with no project config: the built-in defaults, registered the way
    # initialize_plugins registers them (which always passes a resolver).
    resolver = SmartScopeResolver()
    for plugin_class in srv._PLUGIN_CLASSES:
        plugin = plugin_class(".")
        plugin_server = MCPServer(f"docs-facts-{plugin.name()}")
        srv.register_plugin_tools(plugin_server, [plugin], resolver)
        tools = asyncio.run(_list_tools(plugin_server))
        yield from _tool_facts(
            _schema_tools(tools), "plugin", plugin.name().lower(), resolver.plugin_tool_default
        )


# --- static: from the source, never importing it (#1098, ruling C19) ---------

_SERVER = "pyeye.mcp.server"
_SCOPE_UTILS = "pyeye.scope_utils"


def _static_params(root: Path, module: str, dotted: str) -> list[_Param]:
    return [
        _Param(
            p.name,
            sig.type_string(root, module, p.annotation),
            p.required,
            p.default,
            not p.required,
        )
        for p in sig.signature(root, module, dotted)
    ]


def _declared(root: Path, name: str) -> list[_Param]:
    return [
        _Param(pname, sig.type_string(root, _SERVER, ann), False, default, True)
        for pname, ann, default in sig.declared_params(root, _SERVER, name)
    ]


def _plugin_tools(root: Path, class_name: str) -> tuple[str, list[_Tool]]:
    """A plugin's lower-case name and its tools, as ``register_plugin_tools`` registers them.

    Each tool is the plugin method's own parameters, with ``scope`` replaced by
    :data:`~pyeye.mcp.server.PLUGIN_TOOL_SCOPE_PARAM` (the resolver is always
    given) and :data:`~pyeye.mcp.server.PLUGIN_TOOL_EXTRA_PARAMS` appended.
    """
    source = sig.imported_from(root, _SERVER, class_name)
    if source is None:
        raise ExtractionError(f"{_SERVER}: {class_name} isn't imported from a pyeye module")
    module, cls = source
    name = sig.returned_literal(root, module, f"{cls}.name")
    (scope,) = _declared(root, "PLUGIN_TOOL_SCOPE_PARAM")
    extras = _declared(root, "PLUGIN_TOOL_EXTRA_PARAMS")
    tools = []
    for tool_name, method in sig.returned_method_dict(root, module, f"{cls}.register_tools"):
        params = [
            scope if p.name == scope.name else p
            for p in _static_params(root, module, f"{cls}.{method}")
        ]
        tools.append((tool_name, [*params, *extras]))
    return str(name).lower(), tools


def extract(root: Path) -> Iterator[Bindable]:
    """Yield a fact per tool and per parameter, plus the group views.

    Read from the source: the ``@mcp.tool()`` functions in the server (the core
    tools), the ``ADMIN_TOOLS`` tuple (registered only when metrics are on), and
    each plugin in ``_PLUGIN_CLASSES`` through its ``register_tools()`` dict and
    the parameters ``register_plugin_tools`` adds. An omitted plugin ``scope``
    defaults, with no project config, to ``PLUGIN_FALLBACK_SCOPE``.
    """
    admin = sig.tuple_names(root, _SERVER, "ADMIN_TOOLS")
    core = [n for n in sig.decorated(root, _SERVER, "mcp.tool()") if n not in admin]
    yield from _tool_facts([(n, _static_params(root, _SERVER, n)) for n in core], "core", None)
    yield from _tool_facts([(n, _static_params(root, _SERVER, n)) for n in admin], "admin", None)

    fallback = constant(root, _SCOPE_UTILS, "PLUGIN_FALLBACK_SCOPE")
    for class_name in sig.tuple_names(root, _SERVER, "_PLUGIN_CLASSES"):
        name, tools = _plugin_tools(root, class_name)
        yield from _tool_facts(tools, "plugin", name, lambda _tool: fallback)
