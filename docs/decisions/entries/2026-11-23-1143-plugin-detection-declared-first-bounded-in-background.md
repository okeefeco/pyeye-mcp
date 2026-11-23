---
date: "2026-11-23"
title: "Plugin detection reads declared dependencies first, bounds its scan, and runs after serving starts (#1143)"
issues: [1143, 1124, 770, 659, 517, 637]
anchors: ["pyeye.plugins.detection.declared_dependencies", "pyeye.plugins.detection.declares", "pyeye.plugins.detection.scan_for_imports", "pyeye.plugins.detection.SCAN_ENTRY_LIMIT", "pyeye.plugins.base.AnalyzerPlugin.detection", "pyeye.plugins.pydantic.PydanticPlugin.detection", "pyeye.plugins.flask.FlaskPlugin.detection", "pyeye.async_utils.filtered_walk", "pyeye.mcp.server.prepare_plugins", "pyeye.mcp.server.detect_plugins", "pyeye.mcp.server.commit_plugins", "pyeye.mcp.server.plugin_detection", "pyeye.mcp.server.redetect_plugins", "pyeye.mcp.server.initialize_plugins", "pyeye.mcp.list_changed.ToolsChangedNotifier", "pyeye.mcp.__main__.serve_detecting_plugins", "tests/test_plugin_detection_startup.py"]
status: "active"
amends: ["2026-11-16-659-configure-packages-re-detects-frameworks-add-only.md", "2026-11-20-770-configure-packages-announces-new-tools.md", "2026-11-16-517-every-whole-tree-scan-goes-through-filtered-rglob.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — Plugin detection reads declared dependencies first, bounds its scan, and runs after serving starts (#1143)

**Friction:** `main()` ran `initialize_plugins(".")` before the stdio loop. `PydanticPlugin.detect()` walked the whole tree for an import and only then read the manifests, and `filtered_rglob` listed the whole tree before it returned. Started in `/tmp` (461k files) the server served nothing for 73 s and didn't notice a closed stdin (#1124's EOF exit was delayed, not lost).

**Decision:** The maintainer ruled (2026-11-23) to keep detection: plugin tools stay listed only when their framework is detected. Three changes:

- **Declared dependencies first.** `declared_dependencies` reads the root's `pyproject.toml` (PEP 621 dependencies and extras, PEP 735 groups, uv dev-dependencies, Poetry dependencies and groups), `requirements*.txt`, `requirements/*.txt`, `Pipfile`, `uv.lock` and `poetry.lock`. Names are matched after PEP 503 normalisation, as `<framework>` or `<framework>-*`, no longer as a substring of the file. Lock files list transitive dependencies too, so a framework pulled in by another package is detected: listing a few extra tools is the cheap error.
- **A bounded fallback scan.** `scan_for_imports` walks lazily through `filtered_walk` (the `filtered_rglob` exclusions, yielded per directory) and stops after `SCAN_ENTRY_LIMIT` (20,000) directory entries. Stopping there is `not_determined`, never `not_detected` (absence vs zero). A detector that raises is `not_determined` too (#637: a bug, not "framework absent"). `plugin_detection()` records each plugin's outcome, `pending` until detection is committed. A not-determined framework's tools aren't listed, but they still run by name (#665).
- **Detection after serving starts.** `main()` calls `prepare_plugins` (no walk), then `serve_detecting_plugins` runs `detect_plugins` on a daemon thread while stdio serves. `commit_plugins` registers the detected plugins' tools on the event loop, and `ToolsChangedNotifier` announces them. The notifier is server middleware: it remembers the client's connection from `notifications/initialized` on and sends on the negotiated channel (#770's `channel_for`). If no client has spoken yet, it sends on the client's next message. A detection still running when stdin closes is abandoned with the process.
- `commit_plugins` holds `_plugin_lock` and skips a plugin class already active. Startup's background commit and a `configure_packages` re-detection (`redetect_plugins`, now `detect_plugins` + `commit_plugins`) can both find a framework, and it activates once (#659's add-only rule). `initialize_plugins` remains the synchronous path for tests and callers.
- Rejected: always listing plugin tools (a surface change, ruled out), and using pyeye's own import graph to detect (the same walk plus parsing, so slower on a cold start).

**Anchor:** `pyeye.plugins.detection`, `PydanticPlugin.detection`, `FlaskPlugin.detection`, `pyeye.mcp.server.prepare_plugins` / `detect_plugins` / `commit_plugins`, `pyeye.mcp.list_changed.ToolsChangedNotifier`, `pyeye.mcp.__main__.serve_detecting_plugins`; #1143.

**Applies-to:**

- every plugin detector: `PydanticPlugin.detection` and `FlaskPlugin.detection` (declared first, bounded scan). `DjangoPlugin.detect` is untouched: it reads requirements files and globs the root only, so it never walks (measured 0.01 s on `/tmp` in #1143). It gets `not_detected` / `detected` from the base `detection()`;
- every activation path: startup (`prepare_plugins` + `serve_detecting_plugins`), `initialize_plugins`, and `redetect_plugins` (`configure_packages`), all through `detect_plugins` → `commit_plugins`;
- every tools-changed announcement: in a request, `announces_new_tools` (#770); outside one, `ToolsChangedNotifier`;
- the whole-tree scan rule (#517): `scan_for_imports` walks through `filtered_walk`, which carries `filtered_rglob`'s exclusions; `filtered_rglob` is now built on it.

**Verify:** gold. `uv run pytest tests/test_plugin_detection_startup.py tests/test_plugin_redetection.py tests/test_tools_list_changed.py tests/integration/test_nested_worktree_exclusion.py` passes. It checks that:

- each of 13 manifest forms detects Pydantic and Flask with the walk patched to fail;
- only a requirement's name counts (comments, options and other names don't);
- a scan stopped at the bound is `not_determined`, a complete one `not_detected`, and the plugins honour the bound;
- the server records `pending`, then each outcome, and a failing detector is `not_determined`;
- a legacy client lists tools while detection is blocked, then gets exactly one `tools/list_changed` and sees the new tools;
- serving ends without waiting for a blocked detection;
- nothing detected announces nothing;
- a modern client gets the event on its listen stream;
- a second commit of the same framework activates it once.
