---
date: "2026-11-18"
title: "Relative caller paths anchor on project_path; a missing package: path is listed in unsearched_scopes (#842, #843)"
issues: [842, 843, 594, 717, 714]
anchors: ["pyeye.path_utils.anchor", "pyeye.scope_utils.package_scope_path", "pyeye.scope_utils.resolve_scope_paths", "pyeye.plugins.base.AnalyzerPlugin.describe_scope", "pyeye.mcp.operations.resolve.resolve_at", "tests/test_relative_paths_project_path.py"]
status: "active"
amends: ["2026-11-15-594-plugin-tools-take-an-opt-in-envelope-that-reports-searched.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — Relative caller paths anchor on project_path; a missing package: path is listed in unsearched_scopes (#842, #843)

**Friction:** A relative path a caller passed was joined to the MCP server's working directory, not to the `project_path` the caller named. A multi-project server always runs elsewhere, so:

- `resolve_at(file="myapp/cache.py", project_path=P)` and `resolve("myapp/cache.py:25", project_path=P)` answered `file_not_found`. Their own detail said "absolute or relative to project_path" (#843, found while building #828's examples).
- `find_flask_routes(scope="package:src/lib", project_path=P)` searched `<cwd>/src/lib`, found nothing, and returned `[]`. The only sign was a log warning (#842). #594's envelope listed a missing `package:` path in neither `searched` nor `unsearched_scopes`, so the envelope couldn't flag it either. `describe_scope` repeated the cwd bug with its own `Path(...).exists()`.

**Decision:**

- **One anchoring rule** (`pyeye.path_utils.anchor`, the #717 owner):
  - an absolute path is used exactly as given;
  - a relative one is joined to the root and made absolute in the caller's spelling (lexical `..`, no symlink resolution, #714/#603);
  - `~` is not expanded: these are tool arguments, not config entries;
  - a Windows drive-relative path (`C:foo`) on the root's drive loses its drive and joins the root; on another drive it is a `ValueError` (`path_utils.drive_relative`), because it could only mean that drive's cwd.
- **The input validator no longer anchors.** `PathValidator.validate_path` (behind `validate_mcp_inputs`) made any relative path containing `..` absolute against the cwd, before a tool could anchor it. It now returns a relative path unchanged, so `file`, `project_path` and `configure_packages`' `packages` reach the tool as the caller wrote them.
  - **The deny-list is not loosened.** Its checks still run on the real target. An absolute path, or a relative one containing `..`, is resolved for the checks only, anchored where the tool will anchor it: on the call's `project_path` (`anchor_root`) for `file` and `packages`, and on the cwd for `project_path` itself.
  - **Two forms, either rejects.** The deny-list runs over the target's lexical form (anchored, `..` collapsed, symlinks kept) and its resolved form (`PathValidator.check_forms`). On macOS `/etc` is a symlink to `/private/etc`, so the resolved form alone never matched `^/etc/`. That made #852's first version fail its own tests there.
    - In base, absolute `/etc/x` and relative `…/etc/x` were rejected on every OS, macOS included, by the given-string substring check, so files had no extra macOS hole.
    - The directory itself (`/etc`, `../../etc`) passed on every OS in base.
  - **Slightly stricter than before.** The anchored resolved-target patterns (`^/etc/`, `^/root/`, `^/proc/`, `^/sys/`, `^/dev/`) now also test the path as a directory. The match-anywhere ones (`/etc/`, `/root/`) don't, so a project directory that merely ends in `etc` or `root` (`/home/u/repos/root`) still passes, as in 2.x. Before, `../../etc` resolved to `/etc` and slipped past `^/etc/` for lack of a trailing slash. It is still "a sanity check, not a sandbox" (SECURITY.md).
- **Where it applies.**
  - `resolve_at`'s `file` and `resolve`'s `path:line` and `path` forms anchor on the analyzer's project. The not-found echo keeps the caller's spelling.
  - `package:<path>` scopes anchor on `ScopeLayout.project_path`, through `scope_utils.package_scope_path`. That function is the one place this is decided; `resolve_scope_paths` (the search) and `describe_scope` (the envelope) both call it, so they can't disagree.
- **Envelope (amends #594's "appears in neither list").** A `package:<path>` scope whose directory doesn't exist is listed in `unsearched_scopes`, after the configured scopes, spelled as the caller gave it, once. An unknown scope and an unconfigured namespace still appear in neither list. The user approved this contract change (via coordinator-3, 2026-11-18).
- **Rejected:**
  - Resolving relative paths against the cwd and fixing only the message. The caller controls `project_path`, not the server's cwd.
  - Expanding `~`, which no caller of these arguments relies on and which would make the rule differ from the respelling in `respell_paths`.
  - A new envelope field for missing paths. `unsearched_scopes` already means "searched less than you asked; widen or fix it".

**Anchor:** `pyeye.path_utils.anchor`; `pyeye.scope_utils.package_scope_path` / `resolve_scope_paths`; `pyeye.plugins.base.AnalyzerPlugin.describe_scope`; `pyeye.mcp.operations.resolve.resolve_at` / `_resolve_identifier`; `tests/test_relative_paths_project_path.py`; #842, #843, #594, #717.
**Applies-to:**

- the rule: `pyeye.path_utils.anchor`, `pyeye.path_utils.drive_relative`;
- the validator: `pyeye.validation.PathValidator.validate_path`, `PathValidator.check_forms` and the `validate_mcp_inputs` wrapper that passes `anchor_root`;
- its callers: `pyeye.mcp.operations.resolve.resolve_at`, `pyeye.mcp.operations.resolve._resolve_identifier` (the `file_with_line` and `file_only` forms), `pyeye.scope_utils.package_scope_path`;
- the scope readers: `pyeye.scope_utils.resolve_scope_paths`, `pyeye.plugins.base.AnalyzerPlugin.describe_scope` (and through it the `envelope` of every plugin tool registered by `register_plugin_tools`).

**Verify:** gold. `uv run pytest tests/test_relative_paths_project_path.py tests/test_plugin_envelope.py` passes. Every test there runs with cwd set to an empty directory outside the project. It checks:

- relative `resolve_at`, relative `resolve` forms and relative `package:` scopes resolve inside the project;
- absolute paths are unchanged;
- a file or directory that exists only in the cwd is not found;
- a missing `package:` path is in `unsearched_scopes`, on the wire too.

`uv run python scripts/check_cross_platform_paths.py` reports 0 new sites.
