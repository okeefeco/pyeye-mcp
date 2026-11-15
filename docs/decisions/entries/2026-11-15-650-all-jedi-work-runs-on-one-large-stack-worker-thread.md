---
date: "2026-11-15"
title: "All Jedi work runs on one large-stack worker thread (#650)"
issues: [650]
anchors: ["pyeye.mcp.jedi_worker.on_jedi_worker", "run_on_jedi_worker", "WORKER_STACK_SIZE", "pyeye.mcp.server.register_plugin_tools", "pyeye.mcp.__main__", "shutdown"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — All Jedi work runs on one large-stack worker thread (#650)

**Friction:** Jedi's `goto(follow_imports=True)` recurses about 1,500 frames in some stdlib modules (`io.py` → `_io`, `weakref.py` → `_weakref`). Python raises `RecursionError` first on Linux, macOS and 3.12+, and the per-goto handling reports an unresolved import. On Windows with CPython 3.11, the 1 MB main-thread C stack overflows first and the server process dies. `trace` reached it already, and #623 slice 2 would expose it through `expand("io", "imports")` too.
**Decision:** every MCP tool that touches Jedi or the analyzers runs on ONE dedicated thread created with a 64 MiB stack (`pyeye.mcp.jedi_worker`). On that thread the recursion limit always fires before the C stack runs out.

- The thread runs its own asyncio loop, and whole tool coroutines run there (`run_coroutine_threadsafe` + `wrap_future`). The operations await globbing and `to_thread` work and create loop-bound locks, so running only the sync Jedi calls there would split one operation across two loops.
- Operations still interleave at their awaits exactly as they did on the main loop. Only one thread ever calls Jedi.
- The decorator `@on_jedi_worker` sits innermost under the validation and metrics decorators, so those still measure the whole call. A nested hop runs in place; cancellation reaches the worker task at its next await.
- Rejected: raising the recursion limit, which makes the C-stack overflow *more* likely; special-casing the `_io`/`_weakref` stubs, which is whack-a-mole; per-call threads, which would race Jedi, since Jedi isn't thread-safe.

**Anchor:** `pyeye.mcp.jedi_worker.on_jedi_worker`, `run_on_jedi_worker`, `WORKER_STACK_SIZE`; `pyeye.mcp.server.register_plugin_tools`; `pyeye.mcp.__main__` cleanup (`shutdown`); #650.
**Applies-to:** every MCP tool registered on the server:

- the core tools `resolve`, `resolve_at`, `inspect`, `outline`, `expand`, `trace`;
- `configure_packages` (it invalidates analyzers, so it is serialised with in-flight analysis);
- every plugin tool, wrapped at registration.

Deliberately off the worker: `get_performance_metrics` and `get_connection_diagnostics`, which don't touch Jedi. Not covered: code that calls `pyeye.mcp.operations.*` directly, such as library use and tests, runs on the caller's thread. Use `run_on_jedi_worker` there when it walks stdlib internals. The existing `asyncio.to_thread` uses (globbing, the AST name-index build) run no Jedi.
**Verify:** gold. `uv run pytest tests/test_jedi_worker.py` passes:

- every tool registered on `pyeye.mcp.server.mcp` except the two metrics tools carries the worker marker, and plugin tools are wrapped at registration;
- tool bodies, including `get_analyzer`, run on the worker thread;
- the thread is created with `WORKER_STACK_SIZE`, and the process-wide `threading.stack_size()` is restored;
- `resolve_imports` on stdlib `io` returns on the worker with `_io.UnsupportedOperation` unresolved, and `trace` into `io` through the tool layer returns;
- a `RecursionError` escaping a tool reaches the SDK as a tool error, and the worker keeps serving.

The Windows/3.11 crash itself is only exercised on that CI job.
