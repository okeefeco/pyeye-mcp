---
date: "2026-11-15"
title: "An analyzer built without config detects `src/` with the same rule as `ProjectConfig` (#625)"
issues: [625, 614, 618]
anchors: ["pyeye.project_layout.detect_src_layout", "ProjectConfig._discover_src_layout", "JediAnalyzer.__init__"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — An analyzer built without config detects `src/` with the same rule as `ProjectConfig` (#625)

**Friction:** `src/` detection lived only in `ProjectConfig` auto-discovery. A `JediAnalyzer` built without a config passed no `added_sys_path` to Jedi and had no source roots. On a src-layout project its tools named everything `src.<pkg>…`: `resolve("mypackage")` gave `src.mypackage`, dotted handles weren't found, and inspect and resolve disagreed. #614's cross-tool test recorded this as "bare"-mode gaps. Because caches are shared and keyed on the project path (#618), a bare analyzer's `src.`-named results also leaked into a configured analyzer created later in the same process.
**Decision:** one rule, `pyeye.project_layout.detect_src_layout` (a `src/` directory holding at least one regular package), used by both `ProjectConfig._discover_src_layout` and the `JediAnalyzer.__init__` no-config branch. So both analyzers hand Jedi the same `added_sys_path` and get the same `source_roots`. Rejected: building a full `ProjectConfig` inside a config-less analyzer. That would also pull in sibling and virtualenv discovery and the user's global config, making a bare analyzer depend on whatever surrounds it. Only `src/` is shared. The bare analyzer's src root keeps `project_path`'s own unresolved spelling (#603), because files are enumerated under that spelling. A resolved root broke on Windows CI and through symlinks: every module fell back to the project root and was named `src.<pkg>…`. The cache leak itself is #618's; this change only removes it for src layouts. Separately, every path `JediAnalyzer` hands to `jedi.Project` (`added_sys_path`) is now an OS-native string (`_jedi_sys_path`). `connection_pool.ProjectConnectionPool` still passes `as_posix()` strings to the `jedi.Project` it builds. That is the same latent Windows bug; it was reported to the cache owner and not changed here. Jedi names a module by `str(module_path).startswith(entry)`, so forward-slash entries never matched on Windows, and Jedi-derived handles (`resolve`, `resolve_at`) kept a `src.` prefix there whatever our own roots said. That also clears #640's two Windows-only src_layout entries.
**Anchor:** `pyeye.project_layout.detect_src_layout`; `ProjectConfig._discover_src_layout`; `JediAnalyzer.__init__` (no-config branch); #625, #614, #618.
**Applies-to:** every way an analyzer's roots are derived from the project directory:

- `ProjectConfig` auto-discovery (`_discover_src_layout`);
- a `JediAnalyzer` built without config.

Build-backend layout detection (`_detect_source_layout`: setuptools, poetry, hatch, pdm) and sibling and virtualenv discovery remain config-only. So a bare analyzer on a project whose package root is declared only in `pyproject.toml` (not `src/`) still differs from a configured one.
**Verify:** gold. `uv run pytest tests/test_bare_src_layout.py tests/test_jedi_analyzer_sys_path.py` passes:

- `detect_src_layout` is positive only for `src/` holding a package;
- `ProjectConfig` adds the same `src` root;
- a bare analyzer on `added_sys_path_project` has `source_roots == added_sys_path == [<project>/src]`, the same as a configured one;
- `resolve` and `inspect` agree on `mypackage`, `mypackage.module` and `mypackage.module.my_function`, with no `src.` prefix.
- the same holds through a symlinked project path, and the root keeps the symlink's spelling (skipped where symlinks are unavailable).
- Jedi's own `transform_path_to_dotted` names `src/mypackage/module.py` `mypackage.module` from the analyzer's `project.added_sys_path`, bare and configured; this is the check that bites on Windows.
