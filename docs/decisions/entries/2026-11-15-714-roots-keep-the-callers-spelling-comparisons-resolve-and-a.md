---
date: "2026-11-15"
title: "Roots keep the caller's spelling, comparisons resolve, and a project handle's module comes from the mapper (#714)"
issues: [714, 603, 668, 625]
anchors: ["pyeye.path_utils.relative_within", "pyeye.project_layout.module_name_for_file", "pyeye.resolver._canonical_of", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.__init__"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — Roots keep the caller's spelling, comparisons resolve, and a project handle's module comes from the mapper (#714)

**Friction:** When the project root is reached through a symlink (every macOS temp dir, `/var` → `/private/var`), `resolve("MyClass")` returned `found: true` with the invented handle `__main__.MyClass`. #603 keeps `project_path` in the caller's spelling so `location.file` matches the caller's paths. But the config branch of `JediAnalyzer.__init__` stored in-project roots resolved, the file → module mapper compared paths lexically, and the resolver trusted Jedi's `full_name`. Jedi names a file it can't place on its roots `__main__`, or `src.pkg.mod` in a src layout.
**Decision:**

- **Spelling:** roots and `location.file` keep the caller's spelling (#603 stands). A root inside the project is re-expressed under `project_path`'s spelling in both the config and no-config branches.
- **Comparison:** every root/file containment check goes through `path_utils.relative_within`. It tries the path as spelled, then resolved, and never counts a `..` result as inside (#668). No call site does its own inline `.resolve()` comparison.
- **Handles:** a definition whose file the mapper can name takes its handle's module part from the mapper (`module_name_for_file`), followed by Jedi's qualname. A definition the mapper can't name is `None`, so not found. A `__main__.*` name is never a handle. Jedi's `full_name` stands only outside the mapper's roots (stdlib, site-packages).

Rejected: resolving `project_path` (that undoes #603: callers' own paths would stop matching `location.file`); filtering out only `__main__.*` names (that still returns `src.pkg.mod.X`).
**Anchor:** `pyeye.path_utils.relative_within`; `pyeye.project_layout.module_name_for_file`; `pyeye.resolver._canonical_of`; the root setup in `JediAnalyzer.__init__`; #714, #603, #668.
**Applies-to:** comparison: `project_layout.module_name_for_file` (project, additional, `MODULE_LOOKUP` and namespace roots) and the in-project root setup in `JediAnalyzer.__init__`. Handles: `resolver._canonical_of`, reached from `_place_definition` and `_follow_alias` (so `resolve`, `resolve_at`, `inspect`, `outline`, `expand` and `trace`). Not yet moved: other path comparisons outside `path_utils` / `project_layout` (e.g. `JediAnalyzer._is_subpath`, `_search_all_scopes`' scope filter). #717 makes `path_utils` / `project_layout` their only owners.
**Verify:** PARTIAL — gold: `uv run pytest tests/test_symlinked_root.py` passes, covering every operation on a symlinked root with and without config, `location.file` in the link spelling, the `..` guard, and `_canonical_of` never returning `__main__.*`. Unverifiable until #717's checker: that no other module compares paths outside `path_utils` / `project_layout`.
