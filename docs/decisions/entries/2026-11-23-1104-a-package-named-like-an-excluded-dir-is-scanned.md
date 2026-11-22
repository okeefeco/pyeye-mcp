---
date: "2026-11-23"
title: "The scan excludes venvs by pyvenv.cfg and excluded names only when not a package, with one rule for scan, watcher and scope (#1104)"
issues: [1104, 517, 507, 738, 1092]
anchors: ["pyeye.project_layout.excluded_scan_dir", "pyeye.project_layout.is_package_dir", "pyeye.async_utils.filtered_rglob", "pyeye.cache.CodebaseWatcher._is_ignored", "pyeye.scope._has_build_artifact_segment", "tests/test_scan_excluded_package_dirs.py"]
status: "active"
amends: ["2026-11-16-517-every-whole-tree-scan-goes-through-filtered-rglob.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — The scan excludes venvs by pyvenv.cfg and excluded names only when not a package, with one rule for scan, watcher and scope (#1104)

**Friction:** `filtered_rglob`, the one whole-tree scan (#517), pruned every directory NAMED in `constants.EXCLUDED_DIRS`, even a package. On Poetry 2.5.2 that silently dropped 22 modules (`poetry/utils/env/`, `poetry/console/commands/env/`) from `imported_by`, `subclasses`, the plugins and `iter_module_files`: a measured-empty answer for something never measured. #1092's coverage check found it. The same name-only rule lived in two more places:

- a hand-copied list in the file watcher. Fixing the scan alone would have indexed `poetry/utils/env/` but never invalidated its caches;
- scope classification, for a top-level `build`/`dist`.

**Decision** (the maintainer's ruling, via designer, 2026-11-23, Q1–Q4 as proposed):

- **Q1, the package rule:** a directory named in `EXCLUDED_DIRS` (or `*.egg-info`) is still scanned when it holds `__init__.py` or `__init__.pyi`. A PEP 420 namespace package with such a name stays excluded, because a name alone can't tell it from setuptools' `build/lib`. That limit is stated in the scan edges' ceilings (`literal_subclassing`, `static_imports` for `imported_by`), not left silent.
- **Q2, venvs by marker:** any directory holding `pyvenv.cfg` is pruned, whatever its name (`.direnv/python-3.12`, `myvenv`). The venv rule beats the package rule. The scan checks each directory against its own listing as it enters it, so this costs no extra lookup.
- **Q3, one rule:** `pyeye.project_layout.excluded_scan_dir` (with `is_package_dir`) is the rule for the scan and the watcher. The two name lists are merged into `constants.EXCLUDED_DIRS`, which gains the watcher's `.svn`, `.idea` and `.vscode`.
- **Q4, scope:** a top-level `build`/`dist` that is a package (`is_package_dir`) is project, not build output. Scope keeps its case-folded name match (`Build/`, `DIST/`); only the package test is shared.

**Anchor:** `pyeye.project_layout.excluded_scan_dir`, `is_package_dir`; `pyeye.async_utils.filtered_rglob`; `pyeye.cache.CodebaseWatcher._is_ignored`; `pyeye.scope._has_build_artifact_segment`; #1104.

**Applies-to:**

- `pyeye.project_layout.excluded_scan_dir`, `excluded_name` and `is_package_dir`, and `pyeye.constants.EXCLUDED_DIRS`;
- `pyeye.async_utils.filtered_rglob` and every whole-tree scan through it (#517);
- `pyeye.cache.CodebaseWatcher._is_ignored`;
- `pyeye.scope._has_build_artifact_segment`;
- the ceilings `literal_subclassing` and `static_imports` in `pyeye.mcp.operations.edges.CEILING_MEANINGS`, and `docs/architecture/caching.md`.

**Verify:** gold. `uv run pytest tests/test_scan_excluded_package_dirs.py` passes. It covers:

- packages named `env`, `build`, `dist` and `venv` (with `__init__.py` or `__init__.pyi`) scanned by `filtered_rglob`, `iter_module_files`, `imported_by` and `subclasses`, and watched;
- a venv named `env` and venvs of any name pruned and unwatched, and a venv beating the package rule;
- `build/lib` and a namespace package named `build` still excluded;
- a top-level `build`/`dist` package classified project, and a plain `build` dir still external;
- both ceilings stating the limit.

Partial: on the pinned django scenario (`cd385e6b8c`), `iter_module_files` lists the same 2,922 files before and after, with a median of 5.07 s before and 5.13 s after over 5 runs, inside the runs' spread. This isn't in CI.
