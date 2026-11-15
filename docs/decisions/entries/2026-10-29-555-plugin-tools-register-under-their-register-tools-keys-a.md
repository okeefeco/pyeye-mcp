---
date: "2026-10-29"
title: "Plugin tools register under their `register_tools()` keys; a duplicate name fails startup (#555)"
issues: [555]
anchors: ["pyeye.mcp.server.register_plugin_tools", "initialize_plugins", "tests/test_plugin_tool_names_conformance.py::TestPluginToolNames", "EXPECTED_PLUGIN_TOOLS"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-10-29 — Plugin tools register under their `register_tools()` keys; a duplicate name fails startup (#555)

**Friction:** `initialize_plugins` registered `mcp.tool()(tool_func)`, which names a tool after `tool_func.__name__` and throws away the declared key. The method names collide across plugins, and the SDK keeps the first tool on a collision, logging only a warning. So with Pydantic, Django and Flask all detected, Django's `find_models` / `find_views` / `find_templates` were never exposed, and the documented `find_django_*` / `find_flask_*` / `find_pydantic_models` names did not exist.
**Decision:** The keys are the tool names (`mcp.tool(name=key)`). They were always the declared intent, and they're collision-free; the method names are not. This renames 6 Flask tools, 1 Pydantic tool and all 5 Django tools for clients, which ships in 2.0 (#470) alongside the other tool-surface breaks. Registration raises `ValueError` on a duplicate and runs outside the per-plugin "optional, log and continue" handler, so the bug class can't recur silently. Rejected: keeping the method names and renaming only Django's methods. That breaks fewer clients but leaves ambiguous names (`find_models` — which framework?) and makes the declared keys meaningless.
**Anchor:** #555 ; `pyeye.mcp.server.register_plugin_tools` / `initialize_plugins` ; `tests/test_plugin_tool_names_conformance.py::TestPluginToolNames` (`EXPECTED_PLUGIN_TOOLS`) ; CHANGELOG "Framework plugin tools register under their declared names (#555)".
**Verify:** gold — `uv run pytest tests/test_plugin_tool_names_conformance.py` passes: registering all three plugins on a fresh `MCPServer` yields exactly the 20 keys in `EXPECTED_PLUGIN_TOOLS`, each dispatching to its own plugin's method; registering two `FlaskPlugin`s raises `ValueError`. PARTIAL residue: `scope_defaults.methods` entries for plugin methods are unaffected by the rename but were never applied to plugins at all; that's tracked separately in #559, not verified here.
