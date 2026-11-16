---
date: "2026-11-16"
title: "Plugin tools take a per-call project_path, served by per-project plugins that run undetected (#665)"
issues: [665, 659, 627, 629]
anchors: ["pyeye.mcp.server._plugin_tool", "pyeye.mcp.server._plugin_context_for", "pyeye.mcp.server._build_plugin_context", "pyeye.mcp.server.reapply_plugin_paths", "pyeye.mcp.server.PLUGIN_PROJECT_PATH_NOTE", "pyeye.project_manager.ProjectManager.get_plugin_context", "tests/test_plugin_project_path.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Plugin tools take a per-call project_path, served by per-project plugins that run undetected (#665)

**Friction:** Framework plugin tools were bound to the project the server started in. Every core tool takes `project_path`, but a client working across several projects couldn't ask `find_pydantic_models` about any other project.

**Decision:** every plugin tool gains a keyword `project_path: str | None = None`.

- **`None`** (omitted) is the project the plugin was registered for, so the default call is unchanged. The startup project keeps its registered instance and resolver.
- **Another project** gets its own plugin context (instance plus `SmartScopeResolver`), built by `_build_plugin_context` from **that project's own** `ProjectConfig`: its packages, namespaces, standalone paths and `scope_defaults`. Nothing is shared with the startup project or with another project.
- **Undetected frameworks still run** (decision D1(a), approved by coordinator-2). The per-call plugin is not gated on `detect()`. Detection only decides which tools are registered at startup, and #659 re-detects after `configure_packages`. The scan really runs over that project, so `[]` is a measured empty, never a refusal based on a heuristic. The tool description and the skill say so.
- **Cache:** the contexts live in `ProjectManager.get_plugin_context`, keyed `(path_to_key(project), class)`. They're dropped with the project's analyzer (`invalidate_analyzer`, LRU eviction). So `configure_packages` on a project rebuilds its per-call plugins from the new config, and `reapply_plugin_paths` updates the startup instances in place, comparing with `paths_equal`, not `==`.
- **Missing project:** `get_analyzer(project_path)` runs first, so a `project_path` that doesn't exist is the core tools' `ProjectNotFoundError` tool error, not a scan of nothing.
- **Description and conflicts:** `PLUGIN_PROJECT_PATH_NOTE` is appended to every plugin tool's description. A plugin method that already declares `project_path` is a `TypeError` at registration, as with `envelope`.
- **Rejected:**
  - (b) "framework not detected" as a tool error: a heuristic false negative would become a refusal;
  - (c) registering every plugin's tools always: it changes the tool list.

**Anchor:** `pyeye.mcp.server` (`_plugin_tool`, `_plugin_context_for`, `_build_plugin_context`, `_PluginContext`, `reapply_plugin_paths`, `PLUGIN_PROJECT_PATH_NOTE`); `pyeye.project_manager.ProjectManager` (`get_plugin_context`, `_drop_plugin_contexts`, called from `_cleanup_project` and `invalidate_analyzer`); `skills/python-explore/SKILL.md`; #665.
**Applies-to:** every plugin tool registered through `register_plugin_tools`: those of `PydanticPlugin`, `DjangoPlugin` and `FlaskPlugin`, at startup and at runtime (#659). Each passes through `_plugin_tool`, so a new plugin gets `project_path` with no extra code. #659's re-detection stays startup-only by design: a per-call project isn't re-detected, because its tools run undetected anyway.
**Verify:** gold. `uv run pytest tests/test_plugin_project_path.py` covers:

- the default's selection, and selection of another project;
- `scope_defaults` from the target project;
- an undetected framework measured empty;
- a model lookup and the envelope against the target;
- alternating calls never mixing projects;
- one cached context per project, dropped with the analyzer;
- a reconfigured project rebuilt from its new config;
- a missing project as a tool error;
- a conflicting declaration rejected;
- the description note.

`tests/test_plugin_tool_names_conformance.py` checks every registered plugin tool's description ends with the note.
