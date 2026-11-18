---
date: "2026-11-18"
title: "Config entries the path check refuses are disclosed in an always-present `rejected_paths` (#898)"
issues: [898, 856, 594, 842, 568]
anchors: ["pyeye.config.ProjectConfig.rejected_paths", "pyeye.config.REJECTED_PATH", "pyeye.plugins.base.AnalyzerPlugin.set_rejected_paths", "pyeye.plugins.base.AnalyzerPlugin.describe_scope", "pyeye.mcp.server._plugin_tool", "pyeye.mcp.server.configure_packages", "tests/test_rejected_config_disclosure.py"]
status: "amended"
amends: ["2026-11-15-594-plugin-tools-take-an-opt-in-envelope-that-reports-searched.md", "2026-11-18-856-every-caller-path-is-checked-in-its-final-form.md"]
supersedes: []
amended_by: ["2026-11-19-953-unsaved-configure-packages-calls-accumulate-in-a-session-overlay.md"]
superseded_by: []
---

## 2026-11-18 — Config entries the path check refuses are disclosed in an always-present `rejected_paths` (#898)

**Friction:** Under #856, a `.pyeye.json` package, namespace or standalone entry that fails the path check is skipped with a logged warning. It then drops out of the configured scopes, so it never reached `unsearched_scopes` (#842). Results silently left out a package the user had configured: unknown written as absent (#568).

**Decision:** approved by the maintainer as proposed (via coordinator-3, 2026-11-18). It ships in v2.2.0 as `added` and is additive, so `no-breaking` stays 0.

- **One source:** `ProjectConfig.rejected_paths()` reports every refused entry as `{scope, path, reason: "rejected_path", detail}`.
  - `scope` is `packages`, `namespace:<name>` or `standalone`.
  - `path` is the entry as written.
  - `detail` is the validator's message.
- **Same checks as the getters:** the report uses the getters' own checks, so what is skipped and what is disclosed can't drift apart.
  - `_path_refusal` serves namespace and standalone entries.
  - `_checked_package_dirs` serves package entries and the namespace directories that `get_package_paths` reads.
  - A test pins that the two sets are equal.
  - A glob with any refused match is skipped whole and reported once. Before, the matches checked ahead of the refusal were kept.
- **The plugin envelope:** it gains `rejected_paths` between `unsearched_scopes` and `results`.
  - The key is present whenever the check completed; `[]` is a measured "none refused".
  - **Never `[]` for an unfinished check** (coordinator's addition at the merge, 2026-11-19). When the check can't complete, the response errors or omits the key.
    - A config source that failed to load is recorded in `ProjectConfig.load_errors`, and `rejected_paths()` returns `None`. A malformed `.pyeye.json` was logged and treated as empty, so `[]` would have vouched for entries nobody saw.
    - A plugin's value starts as `None`. `_apply_plugin_paths` clears it before recomputing, so a check that raises leaves "not measured", never the previous list.
    - The envelope and `configure_packages` include the key only when it is not `None`.
    - A check that raises part-way is a tool error, never a partial list.
  - The list comes from `AnalyzerPlugin.rejected_paths`, which `_apply_plugin_paths` sets from the config.
  - `describe_scope` puts every scope with a rejected entry in `unsearched_scopes`, never in `searched`, whatever scope was asked for.
- **`configure_packages`:** it returns the same `rejected_paths`, present on the same terms.
- **Missing and rejected stay distinct:** a `package:` path that merely doesn't exist stays an unsearched scope with no `rejected_paths` record (#842).
- **Rejected alternative:** encoding the reason inside `unsearched_scopes` (e.g. `"namespace:ns (rejected_path)"`). That would change the type of an existing field. A separate key is additive and carries the detail.

**Anchor:** maintainer approval of 2026-11-18 (via coordinator-3); `pyeye.config.ProjectConfig.rejected_paths`; `pyeye.plugins.base.AnalyzerPlugin.describe_scope`; `pyeye.mcp.server._plugin_tool`; `pyeye.mcp.server.configure_packages`; #898, #856, #594, #842, #568.
**Applies-to:**

- the source: `pyeye.config.ProjectConfig.rejected_paths`, `pyeye.config.ProjectConfig._path_refusal`, `pyeye.config.ProjectConfig._checked_package_dirs`;
- the plugins: `pyeye.plugins.base.AnalyzerPlugin.set_rejected_paths`, `pyeye.plugins.base.AnalyzerPlugin.describe_scope`, `pyeye.mcp.server._apply_plugin_paths`;
- the responses: `pyeye.mcp.server._plugin_tool` (the envelope), `pyeye.mcp.server.configure_packages`.

**Verify:** gold. `uv run pytest tests/test_rejected_config_disclosure.py tests/test_plugin_envelope.py` passes on POSIX. It checks:

- the key order and the `[]` for a clean config;
- refused namespace, standalone, package, ancestor ("/") and glob entries are disclosed with a reason, and their scopes are unsearched;
- the good entries are still searched;
- a missing `package:` is unsearched but not rejected;
- `configure_packages` reports the same list;
- the getters skip exactly the entries that are disclosed.
