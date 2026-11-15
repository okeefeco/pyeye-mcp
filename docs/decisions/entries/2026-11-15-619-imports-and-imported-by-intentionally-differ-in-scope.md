---
date: "2026-11-15"
title: "`imports` and `imported_by` intentionally differ in scope (#619)"
issues: [619, 360, 625]
anchors: ["JediAnalyzer.find_importers", "ast.walk", "pyeye._module_scope.iter_module_scope_imports", "expand", "pyeye.mcp.server"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — `imports` and `imported_by` intentionally differ in scope (#619)

**Friction:** #619 found that `imported_by` (`find_importers`, an `ast.walk` over the whole file) counts imports inside functions and class bodies, while `imports` (`resolve_imports`) counts only module-scope bindings (#360). So A→B in `imports` and B←A in `imported_by` didn't match. Making `imported_by` use the #360 walk would have mirrored them exactly, but it would contradict the imported_by design spec ("including conditional/nested ones") and drop real dependents. Lazy imports inside functions are the usual way to break import cycles. #619's other two bullets (a root-package project named importers `b` instead of `rootpkg.b`; importers in additional packages were dropped) were fixed by #625's shared file↔module mapper and are already pinned in `tests/test_project_layout.py`.

**Decision:** Keep the difference and document it. The two edges answer different questions. `imports` answers "what names does this module bind at module scope", so a function-body import (a local) isn't one. `imported_by` answers "who depends on this module", and a lazy import is a dependency. What holds is the forward direction only: if `imports(M)` shows project module `B`, then `M ∈ imported_by(B)`. The reverse fails by design for function- and class-body importers. It also fails for symbol stubs, because `imports` reports a re-exported name at its canonical definition site rather than the module it came through. Rejected: switching `imported_by` to the module-scope walk, which under-reports fan-in and changes a documented guarantee. Also rejected: adding function-body imports to `imports`, which breaks the #360 members/imports partition.

**Anchor:** `JediAnalyzer.find_importers` (whole-file `ast.walk`) vs `pyeye._module_scope.iter_module_scope_imports` (#360); the `expand` tool description in `pyeye.mcp.server`; `skills/python-explore/SKILL.md` edge table; `docs/superpowers/specs/2026-06-10-imported-by-edge-design.md` ceiling; #619, #360, #625.

**Amended 2026-11-15 (#668):** `imported_by` must also never *drop* a dependent. A file that imports the target but has no module name (a path part that isn't a Python identifier: `my-script.py`, `tools-dir/x.py`) can't be a stub, so it used to vanish silently, a confident under-count of fan-in. It is now listed in `unresolved_importers` (POSIX paths; `[]` when every importer is named), on `expand` and per node on `trace`, mirroring `unresolved_imports` on `imports` (#494). The file↔module mapper (`project_layout.module_name_for_file`) returns `None` for such files rather than inventing a name, and no longer treats `root/../other/x.py` as under `root`. A relative import from an unnamed file can't be anchored, so only its absolute imports count. The root cause #668 reported (unnormalised `..` in configured namespace paths) is fixed once, in `ProjectConfig` (#676).

**Applies-to:** both edges: `edges.resolve_imported_by` → `JediAnalyzer.find_importers`, and `edges.resolve_imports`.

**Verify:** gold. `uv run pytest tests/test_imports_imported_by.py` passes:

- the forward property over every `_SWEEP_CORPORA` fixture and over a project with every import form (plain, aliased, `from pkg import mod`, `from pkg.sub import mod`, relative, `TYPE_CHECKING`, try/except shim);
- the asymmetry is pinned: a function-body importer (`app.lazy`) and a class-body importer (`app.class_body`) are in `imported_by` of their target but don't show it in their own `imports`.
- #668: `tests/unit/mcp/operations/test_unresolved_importers.py` (expand, trace, find_importers, other edges never carry the field), the mapper cases in `tests/test_project_layout.py`, and linter rules E.6/T.10.
