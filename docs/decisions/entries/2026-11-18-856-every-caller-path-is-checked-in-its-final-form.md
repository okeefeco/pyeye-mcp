---
date: "2026-11-18"
title: "Every caller-supplied path is checked in the form the tool finally uses (#856)"
issues: [856, 852, 842, 843, 568, 714, 717]
anchors: ["pyeye.validation.PathValidator.validate_final", "pyeye.validation.PathValidator.check_forms", "pyeye.validation.validate_mcp_inputs", "pyeye.mcp.operations.resolve._resolve_identifier", "pyeye.scope_utils.package_scope_path", "pyeye.config.ProjectConfig.get_namespaces", "pyeye.config.ProjectConfig.get_standalone_paths", "pyeye.validation.PathValidator.validate_scan_root", "pyeye.validation.restricted_dir", "pyeye.async_utils.pruned_walk", "tests/test_final_form_path_checks.py"]
status: "amended"
amends: ["2026-11-18-842-relative-caller-paths-anchor-on-project-path-missing-package-is-unsearched.md"]
supersedes: []
amended_by: ["2026-11-18-872-namespace-globs-expand-to-sorted-matches-through-the-package-helper.md", "2026-11-18-898-rejected-config-entries-are-disclosed-in-rejected-paths.md", "2026-11-18-939-the-deny-list-is-anchored-patterns-only-matched-ignoring-case.md", "2026-11-19-909-deny-list-adds-boot-and-secrets-dirs-and-home-credential-stores.md"]
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
- **Hardening from the independent bypass review of #901:**
  - **Scopes:** a sub-namespace must be a dotted Python name, because `namespace:ns./etc` joined an absolute part onto the base. Every directory any scope produces (main, packages, namespaces, aliases, `package:`) goes through `validate_final` in `resolve_scope_paths`, so no scope spelling can skip it.
  - **macOS:** `^/private/etc/` (the resolved form of `/etc`) is an anchored pattern, so the directory itself is refused too. The unanchored `/etc/` and `/root/` patterns get no directory form, so a project dir that merely ends in `etc` or `root` still passes.
  - **Resolved form:** the resolved form is the RAW join resolved (`root/l_tmp/../etc` follows `l_tmp` first, as the OS does), not the lexically collapsed path.
  - **`configure_packages`:** each new entry is checked as the config will read it (`~` expanded, anchored, normalised), on the tool's normalised project path. A refused entry is an error, and nothing is changed or saved.
  - **Glob entries in `configure_packages`:** a glob is checked by every directory it matches, never in pattern form (`/e*` matched `/etc` at use). A glob containing `..` is refused outright, because whether it escapes depends on matches that exist only later. Whether namespace globs are expanded at all is #872, out of scope.
  - **Not fixed here:** TOCTOU symlink swaps.
- **Ancestor ruling (maintainer, 2026-11-18, via coordinator-3):** option (a) with two additions.
  - **Ancestor scan roots are refused.** A DIRECTORY-SCAN root (a plugin scope, a package, a namespace or a standalone dir) is refused when it is a restricted directory or an ANCESTOR of one: `/`, and `/private` on macOS. This covers the implicit scan too: with `project_path="/"`, scope `main` scans from `/`, so the scan is a ToolError. `PathValidator.validate_scan_root` is the check. It is wired into `resolve_scope_paths`, `package_scope_path`, the config's package, namespace and standalone entries (skipped with a warning), `configure_packages`, and the `packages`, `standalone_dirs` and `namespaces` tool inputs. `project_path` itself and single-file inputs are unchanged, as Q1 ruled.
  - **Ancestors are derived, not listed.** They come from the ANCHORED deny-list patterns (`^/etc/` → `/etc`, whose ancestor is `/`). The unanchored `/etc/` and `/root/` patterns match at any depth, so they name no directory and have no ancestors.
  - **Defence in depth: walks prune.** Every recursive walk goes through `async_utils.pruned_walk`. It prunes any directory whose RESOLVED form is restricted (`validation.restricted_dir`), so a route the input checks miss (a symlinked parent, a new scope form) still can't descend into one. The root is resolved once, and a directory below it is the root plus its relative path, because `os.walk` never follows a symlinked subdirectory. `filtered_rglob` (the project-scan choke point) is built on it. So is the new `pruned_rglob`, which applies no project exclusions and now serves the three walkers that bypassed `filtered_rglob`: venv `site-packages` discovery (`ProjectConfig._discover_venv_packages`) and the Django and Flask `find_templates`. Rerouting them through `filtered_rglob` would have hidden a venv's `site-packages`.
  - **What stays as it is.** One-level listings (namespace structure, layout detection, the submodule enumerator, sibling discovery, Flask's `find_config` depth-1 glob from #873) list a directory whose root was already checked. The recursive file watcher takes no prune hook, so it is covered only by the root check: `ProjectManager._watch` never starts on a restricted root or an ancestor of one (`validation.unwalkable_root`). `docs_facts.review.src_literals` walks this repository's own `src`, a trusted root, so it isn't routed either.
- **Scope:** it is still "a sanity check, not a sandbox", and the deny-list stays POSIX-only (#867).

**Anchor:** maintainer rulings of 2026-11-18 (via the designer); `pyeye.validation.PathValidator.validate_final` / `check_forms` / `_check_targets`; `pyeye.validation.validate_mcp_inputs`; `pyeye.mcp.operations.resolve._resolve_identifier`; `pyeye.scope_utils.package_scope_path`; `pyeye.config.ProjectConfig.get_namespaces` / `get_standalone_paths`; `SECURITY.md`; `tests/test_final_form_path_checks.py`; #856, #852, #842, #568, #898.
**Applies-to:**

- the check: `pyeye.validation.PathValidator.validate_final`, `pyeye.validation.PathValidator.check_forms`;
- its callers: `pyeye.validation.validate_mcp_inputs`, `pyeye.mcp.operations.resolve._resolve_identifier`, `pyeye.scope_utils.package_scope_path`, `pyeye.config.ProjectConfig.get_namespaces`, `pyeye.config.ProjectConfig.get_standalone_paths`;
- the scan-root check and its callers: `pyeye.validation.PathValidator.validate_scan_root`, `pyeye.scope_utils.resolve_scope_paths`, `pyeye.mcp.server._check_new_config_paths`;
- the walk prune and its walkers: `pyeye.validation.restricted_dir`, `pyeye.validation.unwalkable_root`, `pyeye.async_utils.pruned_walk`, `pyeye.async_utils.pruned_rglob`, `pyeye.async_utils.filtered_rglob`, `pyeye.config.ProjectConfig._discover_venv_packages`, `pyeye.plugins.django.DjangoPlugin.find_templates`, `pyeye.plugins.flask.FlaskPlugin.find_templates`, `pyeye.project_manager.ProjectManager._watch`.
- deliberately NOT routed through the prune: `pyeye.plugins.flask.FlaskPlugin.find_config` (a depth-1 glob under scope roots already checked) and `pyeye.docs_facts.review.src_literals` (walks this repository's own `src`, a trusted root).

**Verify:** gold. `uv run pytest tests/test_final_form_path_checks.py` passes on POSIX. It checks:

- every input in (A)–(E) is refused, as a ToolError for tool arguments, or skipped with a warning for config entries;
- ordinary relative paths, file forms and `package:` scopes pass;
- a project under a symlinked root passes;
- an ancestor scan root (`package:/`, a symlink to `/`, `namespaces ["/"]`, `project_path "/"` with scope `main`) is refused, while a single-file `resolve_at` with `project_path "/"` still works;
- a walk that reaches a restricted directory through a symlinked parent is pruned, and `pruned_rglob` finds exactly what `rglob` finds.

The same tests fail on main before this change.
