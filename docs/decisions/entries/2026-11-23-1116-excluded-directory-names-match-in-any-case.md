---
date: "2026-11-23"
title: "Excluded directory names match in any case, through one name predicate shared by scan and scope (#1116)"
issues: [1116, 1104]
anchors: ["pyeye.project_layout.dir_name_matches", "pyeye.project_layout.excluded_name", "pyeye.scope._has_build_artifact_segment", "tests/test_scan_case_insensitive_dirs.py"]
status: "active"
amends: ["2026-11-23-1104-a-package-named-like-an-excluded-dir-is-scanned.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — Excluded directory names match in any case, through one name predicate shared by scan and scope (#1116)

**Friction:** after #1104, scope classification case-folded directory names (`Build/`, `DIST/`), but the scan's excluded-directory match (`excluded_scan_dir` over `constants.EXCLUDED_DIRS`) was exact. The two still used separate name predicates, and on case-insensitive filesystems (macOS, Windows) a `Build/` or `Env/` tree was scanned.

**Decision** (the maintainer's ruling, via designer, 2026-11-23):

- **One name predicate:** `pyeye.project_layout.dir_name_matches(name, names)` is the directory-name match for exclusion. It's case-insensitive, and a `*.suffix` entry matches by suffix (`*.egg-info`). The scan uses it as `excluded_name` over `EXCLUDED_DIRS`. Scope uses it over its own build-artifact sets: `build`/`dist` at the top level, and `.tox`, `__pycache__` and `*.egg-info` anywhere.
- **A widening:** `Build/`, `DIST/`, `Env/`, `.VENV/` and the like, with no `__init__`, are now pruned by the scan and ignored by the watcher. Scope's `*.egg-info` match also became case-insensitive.
- **Unchanged:** #1104's package rule still wins (a directory holding `__init__.py(i)` is scanned whatever its name), and `pyvenv.cfg` still prunes. Only directory exclusion folds case; module, class and handle names stay case-sensitive.

**Anchor:** `pyeye.project_layout.dir_name_matches`, `excluded_name`; `pyeye.scope._has_build_artifact_segment`; #1116.

**Applies-to:**

- `pyeye.project_layout.dir_name_matches`, `excluded_name` and `excluded_scan_dir`, and through them `pyeye.async_utils.filtered_rglob` and `pyeye.cache.CodebaseWatcher._is_ignored`;
- `pyeye.scope._has_build_artifact_segment`;
- `docs/architecture/caching.md`.

**Verify:** gold. `uv run pytest tests/test_scan_case_insensitive_dirs.py tests/unit/handle/test_scope.py` passes. It covers:

- excluded names in any case, other names not matched, and suffix patterns;
- scope calling the same predicate;
- cased excluded dirs pruned by the scan and ignored by the watcher;
- the package rule still winning and `pyvenv.cfg` still pruning;
- module names keeping their case;
- scope's existing case-folding tests unchanged.
