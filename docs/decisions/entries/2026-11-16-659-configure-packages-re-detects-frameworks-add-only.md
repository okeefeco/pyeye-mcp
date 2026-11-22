---
date: "2026-11-16"
title: "configure_packages re-detects frameworks on the startup project; runtime tool registration is add-only (#659)"
issues: [659, 665, 618, 637, 770]
anchors: ["pyeye.mcp.server.redetect_plugins", "pyeye.mcp.server._activate_if_detected", "pyeye.mcp.server._detection_roots", "pyeye.mcp.server.register_plugin_tools", "pyeye.mcp.server.configure_packages", "pyeye.mcp.server.initialize_plugins"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-20-770-configure-packages-announces-new-tools.md", "2026-11-23-1143-plugin-detection-declared-first-bounded-in-background.md"]
superseded_by: []
---

## 2026-11-16 — configure_packages re-detects frameworks on the startup project; runtime tool registration is add-only (#659)

**Friction:** framework plugins were detected once, at startup, by running each plugin's `detect()` against the project root only. A framework used only in a configured package (Flask in a vendored web library, say) never activated. That held even after a restart, despite #618 giving active plugins the new paths.

**Decision:**

- **One detection rule**, `_activate_if_detected`, at startup and at runtime: a plugin activates when its framework is detected at the project root **or** in any configured package or namespace directory (`_detection_roots`). A detector failure is logged with its traceback and the plugin is skipped (#637's contract).
- **Re-detection after `configure_packages`, on the startup project only** (`redetect_plugins`). Plugin tools are registered once per name and are bound to the project the server started in until #665 adds a per-call `project_path`. Each plugin class not yet active is re-detected against the new layout, and only the new plugins' tools are registered, through the same decorator stack as at startup (#627/#752).
- **Add-only at runtime:** `register_plugin_tools(..., already_registered=...)` skips names already registered. Nothing is unregistered or renamed, which would be a removal under v2.x. A framework that later disappears keeps its tools until restart.
- **`activated_plugins`** on the `configure_packages` result: the newly activated plugin names. `[]` when none; present whenever re-detection ran; absent for any other project. Additive field.
- **No `tools/list_changed`.** Under the handshake-era protocol pyeye advertises `listChanged: false`, so sending it would be off-spec. The 2026-07-28 route needs a `Context`-injecting async wrapper around a worker-bound sync tool. Both are deferred to #770. The new tools are **callable by name** regardless of whether the client re-lists, which the `configure_packages` docstring and the python-explore skill say.
- Split with #665 (worker-3): `_plugins` stays the startup project's active set, `_startup_root` is a `Path` compared with `paths_equal`, and #665 replaces the path re-apply loop with `reapply_plugin_paths`, keeping the re-detect call after it.
- Rejected: re-detecting every configured project, because the tools are bound to the startup one; unregistering tools whose framework disappeared, because that's a removal.

**Anchor:** `pyeye.mcp.server.redetect_plugins` / `_activate_if_detected` / `_detection_roots` / `register_plugin_tools(already_registered=)` / `configure_packages` / `initialize_plugins`; #659, #665, #618, #637, #770.
**Applies-to:**

- startup detection, `pyeye.mcp.server.initialize_plugins`, through `_activate_if_detected` / `_detection_roots`;
- runtime re-detection and registration: `pyeye.mcp.server.redetect_plugins` and `register_plugin_tools`'s `already_registered`;
- the `configure_packages` tool and its `activated_plugins` field;
- the python-explore skill's framework-plugin section.

**Verify:** gold. `uv run pytest tests/test_plugin_redetection.py` passes:

- a framework only in an added package activates, its tools are registered and callable by name, and `activated_plugins == ["Flask"]`;
- an identical second call activates nothing and registers nothing;
- re-detection is add-only (the tool set only grows);
- a non-startup project isn't re-detected (field absent);
- startup detection sees `.pyeye.json` packages;
- a detector failure is logged and skipped;
- `register_plugin_tools` skips already-registered names and still rejects a real duplicate.

With root-only detection, 4 of those 7 fail.
