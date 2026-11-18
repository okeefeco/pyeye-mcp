---
date: "2026-11-18"
title: "Namespace globs expand to sorted matches through the one helper packages use (#872)"
issues: [872, 856, 842, 419, 668, 830]
anchors: ["pyeye.config.ProjectConfig._expand_glob", "pyeye.config.ProjectConfig._checked_package_dirs", "pyeye.config.ProjectConfig.get_namespaces", "pyeye.plugins.base.AnalyzerPlugin.describe_scope", "tests/test_namespace_globs.py"]
status: "active"
amends: ["2026-11-18-856-every-caller-path-is-checked-in-its-final-form.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — Namespace globs expand to sorted matches through the one helper packages use (#872)

**Friction:** `get_namespaces()` only normalised each entry (#668). A glob such as `"co": ["~/repos/co-*"]` therefore mapped the namespace to the literal pattern, a directory that doesn't exist, and `namespace:co` searched nothing. The same entry's matches still reached the analysis as plain packages, because `_process_namespace_paths` did glob for `get_package_paths`. Two code paths read one entry and disagreed, and every documented namespace glob silently configured nothing (found by the #830 docs review).

**Decision:** the coordinator's calls of 2026-11-18, on the diagnosis reported before building.

- **One expansion:** `ProjectConfig._expand_glob` is the only place a config entry becomes directories. The package paths (via `_checked_package_dirs`) and `get_namespaces` both use it, so they can't disagree again.
- **Sorted matches:** a namespace's order is its precedence (first portion wins, #419), and `glob` returns filesystem order. Package matches are sorted too, which changes the order of `get_package_paths` and of Jedi's added paths, deterministically.
- **`*` only:** a literal `?` or `[` in a path keeps its meaning. `configure_packages`' check (`_config_entry_targets`, #856) still treats `*?[` as glob. Checking more entries by their matches is only stricter; both sites say so in a comment.
- **A refused match skips the whole entry**, with a warning (#856). Before, the matches checked ahead of the refused one were kept, unannounced.
- **A glob that matches nothing:** the namespace stays configured with no directories, so `namespace:<name>` is reported in `unsearched_scopes`, never silently absent (#842). `describe_scope` treats a configured scope with no directories as unsearched; it used to count it as vacuously all searched.
- **The saved config keeps the pattern;** only the in-memory map expands.
- **Docs:** the #830 guard that banned namespace globs now bans only `?` and `[`. DOCUMENTATION.md shows one namespace glob again and explains the order. The other examples stay explicit.
- **Release:** `fixed` (872.fixed.md). Config now does what the docs describe; per #629 that is a correction, not a break.

**Anchor:** `pyeye.config.ProjectConfig._expand_glob`, `_checked_package_dirs`, `get_namespaces`, `_namespace_dirs`; `pyeye.plugins.base.AnalyzerPlugin.describe_scope`; `pyeye.mcp.server._config_entry_targets`; #872, #856, #842, #419, #668, #830.
**Applies-to:**

- the expansion: `pyeye.config.ProjectConfig._expand_glob`, `pyeye.config.ProjectConfig._checked_package_dirs`;
- its callers: `pyeye.config.ProjectConfig._process_package_path`, `pyeye.config.ProjectConfig._process_namespace_paths`, `pyeye.config.ProjectConfig.get_namespaces`, `pyeye.config.ProjectConfig._namespace_dirs`;
- the empty-scope rule: `pyeye.plugins.base.AnalyzerPlugin.describe_scope`;
- the wider check, by design: `pyeye.mcp.server._config_entry_targets`.

**Verify:** gold. `uv run pytest tests/test_namespace_globs.py tests/integration/test_scope_configuration.py` passes. It checks:

- a glob expands to its matches, sorted, for namespaces and packages;
- namespaces and package paths agree;
- explicit, relative and `?`/`[` literal entries are unchanged;
- a no-match glob leaves the namespace configured and unsearched;
- a refused match skips the whole entry (POSIX);
- `namespace:co` from a glob finds the matches' models end to end.

8 of the new file's 10 tests fail on main before this change. The other two are the unchanged-entry controls.
