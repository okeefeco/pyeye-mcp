---
date: "2026-11-20"
title: "configure_packages announces the tools it adds; pyeye advertises tools.listChanged (#770)"
issues: [770, 659, 629]
anchors: ["pyeye.mcp.list_changed.announces_new_tools", "pyeye.mcp.list_changed.channel_for", "pyeye.mcp.list_changed.run_stdio", "pyeye.mcp.list_changed.initialization_options", "tests/test_tools_list_changed.py"]
status: "active"
amends: ["2026-11-16-659-configure-packages-re-detects-frameworks-add-only.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — configure_packages announces the tools it adds; pyeye advertises tools.listChanged (#770)

**Friction:** #659 lets `configure_packages` activate a framework plugin and register its tools at runtime. Nothing told a client, so one that caches `tools/list` didn't show them until it re-listed. #659 deferred the notification: pyeye advertised `listChanged: false` on the handshake, so sending it would have been off-spec.

**Decision** (coordinator-3, 2026-11-20, as #770 proposed; checked against mcp 2.3.0):

- **Advertise `tools.listChanged: true`.** The SDK's `MCPServer.run_stdio_async` passes no notification options. `pyeye.mcp.list_changed.run_stdio` repeats its three lines with `NotificationOptions(tools_changed=True)`, and `__main__` runs it. It reaches the SDK's `_lowlevel_server`, as the SDK's own path does. If an upgrade removes it, `run_stdio` warns and falls back to `run_stdio_async`: tools are still added, only not announced. 2026-07-28+ clients derive the flag from `subscriptions/listen` being served, which is unchanged.
- **One event per activating call,** on the negotiated channel (`channel_for`). On 2026-07-28+ it's `Context.notify_tools_changed()`, onto the `subscriptions/listen` bus. On every earlier version it's `session.send_tool_list_changed()`. Never both. It's sent only when the result's `activated_plugins` is non-empty. A call that raises sends nothing, and a failed send is logged, never fails the tool.
- **`announces_new_tools` sits outermost**, above `tool_errors`. `configure_packages` is already async to the SDK (`@on_jedi_worker` returns an async wrapper), but its body runs on the Jedi worker, where a `Context` can't be used. The decorator takes an injected `Context` (by annotation, hidden from the input schema), removes it before the call goes down the chain, and awaits the event on the server's loop.

**Anchor:** `pyeye.mcp.list_changed.announces_new_tools`, `channel_for`, `run_stdio`, `initialization_options`; #770.

**Applies-to:**

- the stdio entry point: `pyeye.mcp.__main__.main` through `pyeye.mcp.list_changed.run_stdio`;
- `pyeye.mcp.server.configure_packages` (decorated) and `pyeye.mcp.server.redetect_plugins` (its docstring);
- the `configure_packages` description, `docs/api/README.md` and `docs/architecture/plugin-system.md`.

**Verify:** gold. `uv run pytest tests/test_tools_list_changed.py` passes. It covers:

- the channel for every known version;
- `listChanged: true` in the options and over real JSON-RPC streams on a handshake;
- the fallback when `_lowlevel_server` is missing;
- exactly one notification for an activation on a handshake client, and none for a call that activates nothing or fails;
- a `subscriptions/listen` event for a 2026-07-28 client;
- the input schema without the context, a client that ignores the event still calling the new tool, and the decorator above the worker hop.

Partial: real clients' handling of the event (re-listing) is theirs, and isn't tested here.
