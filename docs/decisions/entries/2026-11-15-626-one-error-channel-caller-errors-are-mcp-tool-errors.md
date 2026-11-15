---
date: "2026-11-15"
title: "One error channel: a call that couldn't run is an MCP tool error, a lookup miss is a response (#626)"
issues: [626, 629]
anchors: ["pyeye.mcp.tool_errors.tool_errors", "pyeye.mcp.tool_errors.CALLER_ERRORS", "pyeye.mcp.server.register_plugin_tools"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — One error channel: a call that couldn't run is an MCP tool error, a lookup miss is a response (#626)

**Friction:** pyeye's caller-side failures reached the MCP SDK as unexpected exceptions. These were a bad argument (`line=0`), a `project_path` that doesn't exist, an unusable config, and an unreadable file (`ValidationError` / `ProjectNotFoundError` / `ConfigurationError` / `FileAccessError`). The SDK logged each one with a traceback and sent the client only "Error executing tool X". The agent got no hint what to fix, and the log couldn't tell a typo from a pyeye bug.

**Decision:** pyeye answers in two channels.

- **A lookup that ran is a response:** found, not-found (`{found: false, <echo>, reason, detail}`, slice A) or unsupported. A miss never raises.
- **A call that couldn't run is an MCP tool error** (`is_error`) whose message names the error type, the problem and the offending parameter. `tool_errors` turns exactly `CALLER_ERRORS` into the SDK's `ToolError` (raised `from` the original).
- **Anything else is a genuine bug** and passes through unchanged. It stays a loud, logged crash.
- `tool_errors` is applied **outermost**, directly under `@mcp.tool()`, so argument validation runs inside it. The core tools are `@mcp.tool()` / `@tool_errors` / `@validate_mcp_inputs` / `@metrics.measure` / `@track_mcp_operation` / `@on_jedi_worker`, and the plugin tools are `tool_errors(on_jedi_worker(_plugin_tool(...)))`.
- **Rejected:** folding caller errors into `found: false`. A typo'd `project_path` is not a lookup that ran and found nothing. Reporting it as not-found would hide the mistake behind the absence-vs-zero invariant.

**Anchor:** `pyeye.mcp.tool_errors` (`tool_errors`, `CALLER_ERRORS`, `tool_error_message`); `pyeye.mcp.server` (the core tool decorators, `register_plugin_tools`); #626 slice C.
**Applies-to:** every tool registered on the MCP server: the six primitives, `configure_packages`, and every plugin tool added by `register_plugin_tools`. The exceptions are `get_performance_metrics` and `get_connection_diagnostics`, deliberately unwrapped (`NOT_WRAPPED` in `tests/test_tool_errors.py`): they take no user lookup input and raise no caller error. A new tool must be wrapped, or added to that `NOT_WRAPPED` set with a reason.
**Verify:** gold. `uv run pytest tests/test_tool_errors.py`:

- `test_every_registered_tool_reports_caller_errors` sweeps every registered tool for the wrapper marker;
- outermost placement is checked on the core and the plugin tools;
- the real `mcp.call_tool` path is checked: an invalid argument is a tool error naming it, a missing project is a tool error on all six primitives, a genuine bug is still a crash, and a lookup miss is still a response.
