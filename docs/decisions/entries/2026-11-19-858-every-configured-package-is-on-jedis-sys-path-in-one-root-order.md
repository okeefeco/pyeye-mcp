---
date: "2026-11-19"
title: "Every configured package is on Jedi's sys_path, in one fixed root order (#858, #962)"
issues: [858, 962, 625, 814, 857, 419, 953]
anchors: ["pyeye.analyzers.jedi_analyzer.JediAnalyzer.set_additional_paths", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._jedi_roots", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._refresh_jedi_project", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.set_namespace_paths", "tests/test_configured_packages_on_jedi_path.py"]
status: "active"
amends: ["2026-11-15-625-one-project-roots-policy-and-one-file-module-mapper-both.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — Every configured package is on Jedi's sys_path, in one fixed root order (#858, #962)

**Friction:** #625's mapper treats additional paths as `sys.path` roots, but only some of them reached Jedi.

- **Which ones were missing:** a package read from a saved `.pyeye.json` reached Jedi, because `JediAnalyzer.__init__` puts config packages on its `sys_path`. One registered through `ProjectManager.register_project` → `set_additional_paths` (`configure_packages(save=False)`, the documented session-only mode) did not: `set_additional_paths` only stored the list for pyeye's own scope search.
- **What broke:** Jedi couldn't follow imports into such a package. `resolve_at` on an imported name gave no symbol, `imports` listed them as unresolved, callees into the package were unresolved call sites, and types from it had no handle. A package nested in the project was named from the project root (`.hidden.upstream.pkg`), so a relative import inside one under a dot-directory couldn't be followed: #858's original report, wrongly blamed on a Jedi naming limit.
- **The order quirk:** separately, `set_namespace_paths` merged the roots through a `set()`, so their order (which decides import precedence between roots, #419) was arbitrary (#962).

**Decision:** approved by the coordinator as a bug fix (`fixed`). Jedi's names converging on pyeye's mapper is the intended state, not a contract change.

- **One composition, one fixed order:** `JediAnalyzer._jedi_roots` composes Jedi's added roots in ONE order. First the constructor's roots (config packages or `src/`, kept as `_base_sys_path`), then the additional paths, then the namespace repo roots. Each root is resolved and existing, and the list is deduped in that order.
- **Built from the layout:** the list is computed from the layout every time, never merged from the previous list, so it doesn't depend on which setter ran last.
- **Both setters rebuild:** `set_additional_paths` and `set_namespace_paths` both call `_refresh_jedi_project`, which rebuilds the Jedi project only when the composed list changed. The project path itself and missing paths are left out.
- **Saved configs are unchanged:** the constructor's roots come first as before.
- **Kept independent of #953** (the `save=False` overlay, waiting on the maintainer), which will touch the same route.
- **Left alone, follow-up:** the compensation added by #814 and #857 for the name mismatch is untouched. Mainly that is `resolver._names_path`'s respelling through `handle_for_anchor`, and the name checks that rely on it. It is now a candidate for removal, because every configured route gives Jedi the package's own root.

**Anchor:** `pyeye.analyzers.jedi_analyzer.JediAnalyzer.set_additional_paths`, `_jedi_roots`, `_refresh_jedi_project`, `set_namespace_paths`; `pyeye.project_layout.module_name_for_file`; #858, #962, #625, #814, #857, #419.
**Applies-to:**

- the composition: `pyeye.analyzers.jedi_analyzer.JediAnalyzer._jedi_roots`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._refresh_jedi_project`;
- its callers: `pyeye.analyzers.jedi_analyzer.JediAnalyzer.__init__`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer.set_additional_paths`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer.set_namespace_paths`.

**Verify:** gold. `uv run pytest tests/test_configured_packages_on_jedi_path.py tests/test_resolve_nonidentifier_package_dirs.py` passes. It checks, for a `save=False` package outside the project or under `.hidden/`:

- `resolve_at`, the `imports` edge, callees into the package, parameter and return types, and a relative re-export all resolve;
- the roots come additional-then-namespace, are the same whichever setter ran last, are stable over repeated calls, and match the order handed to Jedi;
- the project itself and missing paths are left out;
- #814's dot-directory relative re-export, formerly a strict xfail, passes.
