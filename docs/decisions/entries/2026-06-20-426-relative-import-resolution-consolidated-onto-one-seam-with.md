---
date: "2026-06-20"
title: "relative-import resolution consolidated onto one seam with an explicit `is_package` bit"
issues: [426, 421, 424, 343, 405]
anchors: ["import_analyzer.resolve_relative_import", "JediAnalyzer._resolve_relative_import", "base_resolution.build_import_table", "build_star_sources"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-20 — relative-import resolution consolidated onto one seam with an explicit `is_package` bit

**Friction:** Two independent resolvers derived "resolve a relative import to absolute" and silently disagreed. The #421 module-level seam (`resolve_relative_import`) inferred package-ness from a `level == len(parts)` heuristic; `JediAnalyzer._resolve_relative_import` carried an explicit `importer_is_package` flag. The heuristic was wrong for nested-package `__init__` imports (e.g. `from . import X` in package `pkg.sub` resolved to `pkg`, not `pkg.sub`), so #405 `find_subclasses` under-resolved nested-package star/relative re-exports flowing through `build_import_table`/`build_star_sources`. The seam can't distinguish a module `pkg.sub` from a package `pkg.sub` by name — the explicit bit is load-bearing.
**Decision:** Collapse onto ONE implementation — port the explicit-flag algorithm (Python `importlib` semantics) into the seam as `resolve_relative_import(current_module, imported_module, level, is_package=False)`, replacing the heuristic; `JediAnalyzer._resolve_relative_import` becomes a thin delegate (signature + callers unchanged, so `imported_by`/#343 stays byte-identical); `build_import_table`/`build_star_sources` gain a 4th `is_package` callback arg threaded from `file.name == "__init__.py"`. Rejected: keep both resolvers + a divergence-documenting test (a test asserting they AGREE can't pass while they diverge, and leaves the seam bug live). Consequence — an intentional correctness change to #405: nested-package re-exports now resolve to the right module, and an above-top-level `from ..` correctly yields `None` instead of a garbage path (one fixture that encoded the invalid case was nested to make it valid).
**Anchor:** `import_analyzer.resolve_relative_import` + `JediAnalyzer._resolve_relative_import` + `base_resolution.build_import_table` / `build_star_sources`; #426 (refs #421, #424, #343, #405).
**Verify:** gold — `tests/unit/analyzers/test_relative_import_resolver.py` asserts both entry points return identical Python-correct results across module / nested-package-`__init__` / top-level-package / above-root vectors (e.g. `resolve_relative_import("pkg.sub", None, 1, is_package=True) == "pkg.sub" == JediAnalyzer._resolve_relative_import(1, None, "pkg.sub", True)`, and `resolve_relative_import("pkg.mod", None, 2) is None`); `test_base_resolution.py::test_build_star_sources_relative_in_nested_package` asserts a nested-package star source resolves to `pkg.sub.impl`.
