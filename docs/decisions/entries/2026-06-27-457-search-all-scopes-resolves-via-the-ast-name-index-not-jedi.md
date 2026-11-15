---
date: "2026-06-27"
title: "`_search_all_scopes` resolves via the AST name-index, not `jedi.Project.search` (#457)"
issues: [457, 450, 397]
anchors: ["JediAnalyzer._search_all_scopes", "pyeye.analyzers.project_graph.get_name_index", "resolve._resolve_bare_name", "fb9cbe4"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-27 — `_search_all_scopes` resolves via the AST name-index, not `jedi.Project.search` (#457)

**Friction:** `jedi.Project.search(name, all_scopes=True)` silently truncates at Jedi's internal 30-parsed-file cap (`_PARSED_FILE_LIMIT`), so high-frequency names lose real definitions: on django, `resolve("Field")` returned a single false-confident hit instead of the project's three `Field` classes (#457). Raising the cap only moves the cliff — the project-wide reverse-search shape is the same disease #405 already cured for `find_subclasses`.
**Decision:** `_search_all_scopes` now looks names up in a whole-project, non-evicting, invalidate-and-rebuild AST name→definitions index (`project_graph`), built once via `extract_definitions` and filtered to the requested scope **at lookup, never at build** (a scope-keyed build would poison the project-keyed cache). The index holds modules (incl. `__init__.py` = regular packages), top-level classes/functions/statements, and nested classes; methods/attributes are reached via the parent (`_enclosed_definitions`, pure AST), never indexed by bare name. Index module names carry the root-package prefix when the project root is a package (`_index_module_name`, matching Jedi's `full_name`), while `_get_import_path_for_file` stays prefix-free for `find_reexports`. Consequence: `resolve._resolve_bare_name` no longer early-returns on empty `find_symbol` matches, so PEP 420 namespace-package anchoring (#444) still fires when the index yields nothing (a namespace package has no file to index). Determinism over Jedi reverse search (#449). **Scope:** `_search_all_scopes` only — `inspect`/`canonicalization`/`search_all_projects` still call `project.search` for other paths (separate, out of scope).
**Anchor:** `JediAnalyzer._search_all_scopes` ; `pyeye.analyzers.project_graph.get_name_index` ; `resolve._resolve_bare_name` ; commits `4341b47`/`fb9cbe4` ; #457 (closes #450, seeds #397)
**Verify:** gold — `tests/test_search_all_scopes_index.py::test_returns_every_definition_past_the_30_file_cap` (40 modules → 40 defs, was 30 on `main`); `tests/test_resolve_completeness_457.py` (`resolve` ambiguous with all N, not truncated); django dogfood: `resolve("Field")` → the 3 canonical `Field`s + a nested one, `resolve("django.forms.fields.Field")` → real line 84.
