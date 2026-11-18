---
date: "2026-11-18"
title: "The path deny-list is anchored patterns only, matched ignoring case (#939)"
issues: [939, 909, 856, 867]
anchors: ["pyeye.validation.PathValidator.RESTRICTED_TARGETS", "pyeye.validation.PathValidator._check_spelling", "pyeye.validation.PathValidator._check_targets", "pyeye.validation.PathValidator.check_forms", "tests/test_anchored_deny_list.py"]
status: "active"
amends: ["2026-11-18-856-every-caller-path-is-checked-in-its-final-form.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — The path deny-list is anchored patterns only, matched ignoring case (#939)

**Friction:** a spelling check (`RESTRICTED_COMPONENTS`) refused any path containing `/etc/`, `/root/`, `/proc/`, `/sys/` or `/dev/` anywhere, ignoring case, and two unanchored target patterns (`/etc/`, `/root/`) did the same on the checked forms. A project under `~/dev` or `~/Dev` could not be analysed at all: every call failed with "suspicious component: /dev/". So were `/srv/etc/lib`, `/home/u/root/proj` and a project's own `etc/` or `sys/` package. It was inconsistent too: `outline("etc.settings")` worked while `resolve_at(file="etc/settings.py")` was refused. It has been present since the original validator (v2.1.0 has it). Found in the #909 diagnosis.

**Decision:** approved by the user for v2.1.1 (via coordinator-3), as #909's Q1. #909's question of extending the list is separate and with the designer.

- **Removed:** `RESTRICTED_COMPONENTS` and the unanchored `/etc/` and `/root/` patterns. A directory name inside a path proves nothing about where the path leads.
- **Still caught:** since #856 every caller path is checked in its anchored final form, both lexical and resolved, and that is enough to catch every route to a system directory.
  - A climb (`../…/etc`), a relative path from `project_path="/"`, and a symlink into `/etc` all land on an anchored pattern.
  - `check_forms` now anchors a relative path given without a root on the cwd, where the OS would resolve it. Before, such a path was checked "as written only", and with only anchored patterns left it would never match.
- **Symlink then `..` (bypass review of #949):** `check_forms` resolved the LEXICAL form, collapsing `..` before following symlinks. So `project_path="proj/l_tmp/../etc/…"` (with `l_tmp` -> `/tmp`) was checked as `<cwd>/proj/etc/…` and passed, and the tool, which resolves the caller's spelling through the OS, then read `/etc`. The removed substring check only masked the deeper forms; `proj/l_tmp/../etc` itself already passed before. `check_forms` now resolves the RAW join, as `_final_forms` has since the #856 review. So every caller that hands its spelling on downstream (`project_path`, `file`/`path`, the list parameters, through `validate_path`) is checked where the OS will put it. Fragment `939.security.md`.
- **Case is ignored** in the anchored match, so a case-insensitive macOS volume can't reach `/etc` as `/ETC`. The cost, refusing a Linux directory literally named `/ETC`, is negligible.
- **Audited every caller** of `validate_path` / `check_forms` / `validate_final` / `validate_scan_root`. Each gets an anchored final form:
  - `validate_mcp_inputs`: `project_path` is anchored on the cwd, and `file`/`path`/list items on the call's `project_path`;
  - `resolve`'s file forms (`validate_final` on the project);
  - `scope_utils`, `ProjectConfig` and `_check_new_config_paths` (`validate_scan_root` on the project);
  - `ProjectConfig._process_*`'s `validate_path` calls, which get paths already made absolute.
- **Unchanged:** `_RESTRICTED_DIRS` and its ancestors are as #856 derived them. `DANGEROUS_NAMES` stays warn-only. Windows stays out of scope (#867): the patterns never match a drive-letter path, as before for the anchored ones.
- **The docs fact follows:** `security.path_checks` no longer lists a "naming one of these directories" rule, and says the patterns are anchored and matched ignoring case.
- **Release:** `fixed`. The change only accepts paths that were wrongly refused; nothing sensitive that was refused before is now accepted.

**Anchor:** user approval of 2026-11-18 (via coordinator-3); `pyeye.validation.PathValidator.RESTRICTED_TARGETS`, `_check_spelling`, `_check_targets`, `check_forms`; `pyeye.docs_facts.extractors.security`; `SECURITY.md`; #939, #909, #856.
**Applies-to:**

- the deny-list and its checks: `pyeye.validation.PathValidator.RESTRICTED_TARGETS`, `pyeye.validation.PathValidator._check_spelling`, `pyeye.validation.PathValidator._check_targets`, `pyeye.validation.PathValidator.check_forms`;
- the fact: `pyeye.docs_facts.extractors.security._path_checks`.

**Verify:** gold. `uv run pytest tests/test_anchored_deny_list.py` passes on POSIX. It checks:

- projects under `dev`, `Dev`, `srv/etc/lib`, `home/u/root` and `work/SYS`, with their own `etc/` and `sys/` packages, work through `resolve`, `resolve_at`, `outline`, `configure_packages` and a plugin `package:` scope;
- a climb, `etc/passwd` from `project_path="/"`, a symlink into `/etc`, `/ETC/passwd`, the simulated macOS `/private/etc` forms, and a root-less relative path from `/` are all refused;
- a symlink then `..` (`l_tmp/../etc`, `l_tmp/../proc/self`) is refused as a relative or absolute `project_path`, a `resolve` file form, a `resolve_at` file and each `configure_packages` list.

29 of its 33 tests fail on main before this change; the 4 that pass are refusals main already made.
