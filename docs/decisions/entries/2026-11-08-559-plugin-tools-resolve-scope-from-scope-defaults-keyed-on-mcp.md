---
date: "2026-11-08"
title: "Plugin tools resolve `scope` from `scope_defaults`, keyed on MCP tool names (#559)"
issues: [559, 594, 555]
anchors: ["pyeye.mcp.server.register_plugin_tools", "_with_scope_default", "SmartScopeResolver.plugin_tool_default", "ignored_method_keys", "tests/test_plugin_scope_defaults.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-08 — Plugin tools resolve `scope` from `scope_defaults`, keyed on MCP tool names (#559)

**Friction:** `scope_defaults` had no effect on any 2.x tool. Plugin methods hard-coded `scope="main"`, and the resolver's only call path (`get_project_files(method_name=…)` via `find_subclasses`) was reached with an explicit scope. So a namespace project's `find_pydantic_models` silently searched only the main repo, while the docs told users to configure it, with method-name keys (`find_models`, ambiguous between Django and Pydantic since #555) that couldn't match any tool. An AI agent can pass `scope=` per call, but in a split codebase it has no way to know it should; the project config does.
**Decision:** Make it work for the plugin tools rather than remove it. `register_plugin_tools` wraps each tool that has a `scope` parameter. The MCP schema's `scope` becomes `Scope | None = None`, and an omitted scope resolves `scope_defaults.methods.<MCP tool name>` → `scope_defaults.global` → `"main"`. An explicit scope wins, and `scope_aliases` are expanded either way (unexpanded, an alias searched nothing). Keys are tool names; any other key is logged as ignored, never guessed (`find_models` could be Django's or Pydantic's). Rejected: removing `scope_defaults` (honest, but loses correct-by-default completeness for namespace projects); keeping method-name keys (ambiguous after #555); editing about 20 plugin signatures instead of one wrapper. Deferred to 3.0 (#594): results reporting the scope searched and the scopes skipped, which changes every plugin tool's response shape from a list to an object.
**Anchor:** `pyeye.mcp.server.register_plugin_tools` / `_with_scope_default`; `SmartScopeResolver.plugin_tool_default` / `ignored_method_keys`; `tests/test_plugin_scope_defaults.py`; #559, #594, #555.
**Verify:** gold — `uv run pytest tests/test_plugin_scope_defaults.py` passes. It covers no config → `main`; the tool key, `global` and precedence; an explicit scope winning; aliases expanded both as a default and explicitly; the legacy key `find_models` not applied; the schema's `scope` default being `null`; `initialize_plugins` applying defaults and warning only on non-tool keys; and every `scope_defaults.methods` key in `docs/`, `examples/configurations/`, README and DOCUMENTATION being a real plugin tool name.
