---
date: "2026-11-16"
title: "Jedi's own subprocess directory is never on pyeye's sys.path (#722)"
issues: [722, 623, 457]
anchors: ["pyeye._jedi_project.make_project", "pyeye._jedi_project.is_jedi_private_path", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.__init__", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.set_namespace_paths"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-19-993-the-project-environment-is-discovered-and-read-statically.md"]
superseded_by: []
---

## 2026-11-16 — Jedi's own subprocess directory is never on pyeye's sys.path (#722)

**Friction:** `resolve("__init__")` and `resolve("functions")` returned found top-level modules anchored on Jedi's private `jedi/inference/compiled/subprocess/__init__.py` and `functions.py`.

- Jedi's `SameEnvironment.get_sys_path()` returns its inference subprocess's `sys.path`. That process runs `jedi/inference/compiled/subprocess/__main__.py`, so `sys.path[0]` is Jedi's own script directory.
- It's the first entry of the base path. So a same-named module reachable only through `added_sys_path` (a configured package) was shadowed in `goto` and `infer`: `import functions` from the project landed in Jedi.
- The project root and a `src/` directory were not affected, because Jedi's `smart_sys_path` puts them ahead of the base path.

**Decision:** pyeye builds every `jedi.Project` through `pyeye._jedi_project.make_project`. It passes Jedi an explicit base `sys_path`: the environment's, in its original order, minus every entry under Jedi's own package directory (`is_jedi_private_path`).

- An explicit `sys_path` replaces only Jedi's *base* path (`Project._get_base_sys_path`). `smart_sys_path` (the project root, discovered parent dirs, buildout paths) and `added_sys_path` still apply on top, unchanged; this was checked against jedi 0.20.1's `Project._get_sys_path`.
- The fix is at the source, so every consumer (`resolve`, `inspect`, edges, typerefs, plugins) stops seeing the leaked modules at once.
- If the environment's path can't be read, the project keeps Jedi's default base path, so analysis never fails because of the filter.
- Rejected: refusing placements under Jedi's directory in `resolver._external` alone. That fixes `resolve("__init__")` but leaves the shadowing in `goto`/`infer`, and so in the `imports` edge and typerefs.
- Rejected: subclassing `jedi.Project` to filter `_get_base_sys_path`, which overrides a private method; `sys_path=` is public API.

**Anchor:** `pyeye._jedi_project.make_project` / `is_jedi_private_path`; the `JediAnalyzer.__init__` and `set_namespace_paths` call sites; jedi's `Project._get_base_sys_path` / `_get_sys_path`; #722.
**Applies-to:**

- the helper, `pyeye._jedi_project.make_project` and `is_jedi_private_path`;
- the `jedi.Project` construction sites, all routed through it: `JediAnalyzer.__init__` (formerly two `jedi.Project` calls, with and without `added_sys_path`) and `JediAnalyzer.set_namespace_paths` (rebuild with namespace roots);
- every Jedi consumer that uses `analyzer.project`, which inherits the filtered path.

**Verify:** gold. `uv run pytest tests/unit/test_jedi_project.py tests/integration/test_jedi_private_sys_path.py tests/integration/test_multirepo_namespace_scenario.py` passes:

- the base path equals the environment's minus Jedi's directory, in order, and Jedi's directory was there to drop;
- the project root and `added_sys_path` still resolve imports;
- a configured package's `functions` isn't shadowed by Jedi's;
- `resolve` and `inspect` of `functions` and `__init__` are not-found, and `__main__` never lands in Jedi's files;
- `functions` at the project root and in a `src/` layout resolve to the project's file, from `resolve`, `resolve_at` and the `imports` edge;
- `__future__`, `os`, `functools` and `jedi` still resolve as external;
- the #667 multi-repo namespace scenario passes unchanged.

Without the filter, 4 of those tests fail.
