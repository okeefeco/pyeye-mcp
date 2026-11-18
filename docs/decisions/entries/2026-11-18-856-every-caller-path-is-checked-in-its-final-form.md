---
date: "2026-11-18"
title: "Every caller-supplied path is checked in the form the tool finally uses (#856)"
issues: [856, 852, 842, 843, 568, 714, 717]
anchors: ["pyeye.validation.PathValidator.validate_final", "pyeye.validation.PathValidator.check_forms", "pyeye.validation.validate_mcp_inputs", "pyeye.mcp.operations.resolve._resolve_identifier", "pyeye.scope_utils.package_scope_path", "pyeye.config.ProjectConfig.get_namespaces", "pyeye.config.ProjectConfig.get_standalone_paths", "tests/test_final_form_path_checks.py"]
status: "active"
amends: ["2026-11-18-842-relative-caller-paths-anchor-on-project-path-missing-package-is-unsearched.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — Every caller-supplied path is checked in the form the tool finally uses (#856)

**Friction:** The independent review of #852 found five inputs that skipped the path check on the path the tool actually reads. None was new in #852.

- **(A)** A relative `file` or `project_path` without `..` was checked only as written, never anchored or resolved. `resolve_at(file="etc/passwd", project_path="/")` passed, and so did a path through a symlink inside the project pointing at `/etc`.
- **(B)** `resolve`'s file forms (`f.py`, `f.py:42`) were never checked, so `resolve("/etc/hosts")` reached Jedi.
- **(C)** A plugin `scope="package:<path>"` was never checked.
- **(D)** `configure_packages`' `namespaces` paths and `standalone_dirs` were never checked.
- **(E)** Namespace and standalone paths from the config reached analysis unchecked. Only a duplicate copy of the namespace paths, in `get_package_paths`, was ever validated.

**Decision:** built on the maintainer's rulings of 2026-11-18, given via the designer. This entry is their record; they are not in a design doc.

- **The rulings:**
  - **Q1:** a relative path that reaches a restricted location, through a symlink inside the project or plainly (`etc/x` with `project_path="/"`), is **refused**. Today it is accepted.
  - **Q2:** a restricted `resolve` file form (`/etc/hosts`, `../../etc/passwd:1`) is a **ToolError** (`Invalid identifier …`), not a not-found. Reporting not-found for a forbidden path would write unknown as absent (#568).
  - **Q3:** a restricted `package:<path>` scope is a **ToolError** (`Invalid scope …`). `unsearched_scopes` stays for paths that merely don't exist (#842).
  - **Q4:** a refused **config** entry (`.pyeye.json` namespaces, `standalone.dirs`) is **skipped with a warning**, never an error, so a bad config never breaks every call. Telling the caller which entries were skipped is a separate follow-up, **#898**, outside #856.
  - **Release classification:** a security fix, **not breaking**. Fragment `856.security.md`; `scripts/changelog.py no-breaking` stays 0.

- **One check, final form:** `PathValidator.validate_final(path, root)` anchors a relative path on the root where the tool will anchor it (`path_utils.anchor`), `..` or not, and checks both forms through the one deny-list (`_check_targets`, shared with `validate_path`):
  - the **lexical** form (symlinks kept, so macOS `/etc` → `/private/etc` is still caught);
  - the **resolved** form (symlinks followed, so an in-project symlink to `/etc` is caught).

  It returns the caller's spelling (#714/#717). A project under a symlinked root (macOS `/tmp` → `/private/tmp`) passes. `check_forms` now anchors every relative path whenever a root is known.
- **Wired at every entry point:**
  - `validate_mcp_inputs`: `file`/`file_path`/`path`, the `packages`/`standalone_dirs` lists and the `namespaces` values on the call's `project_path`, and `project_path` itself on the cwd.
  - `resolve`'s file forms, in `_resolve_identifier`.
  - `scope_utils.package_scope_path`, so the search and the #842 envelope share it.
  - `ProjectConfig.get_namespaces` and `get_standalone_paths`.
- **Scope:** it is still "a sanity check, not a sandbox", and the deny-list stays POSIX-only (#867).

**Anchor:** maintainer rulings of 2026-11-18 (via the designer); `pyeye.validation.PathValidator.validate_final` / `check_forms` / `_check_targets`; `pyeye.validation.validate_mcp_inputs`; `pyeye.mcp.operations.resolve._resolve_identifier`; `pyeye.scope_utils.package_scope_path`; `pyeye.config.ProjectConfig.get_namespaces` / `get_standalone_paths`; `SECURITY.md`; `tests/test_final_form_path_checks.py`; #856, #852, #842, #568, #898.
**Applies-to:**

- the check: `pyeye.validation.PathValidator.validate_final`, `pyeye.validation.PathValidator.check_forms`;
- its callers: `pyeye.validation.validate_mcp_inputs`, `pyeye.mcp.operations.resolve._resolve_identifier`, `pyeye.scope_utils.package_scope_path`, `pyeye.config.ProjectConfig.get_namespaces`, `pyeye.config.ProjectConfig.get_standalone_paths`.

**Verify:** gold. `uv run pytest tests/test_final_form_path_checks.py` passes on POSIX. It checks:

- every input in (A)–(E) is refused, as a ToolError for tool arguments, or skipped with a warning for config entries;
- ordinary relative paths, file forms and `package:` scopes pass;
- a project under a symlinked root passes.

The same tests fail on main before this change.
