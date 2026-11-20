---
date: "2026-11-21"
title: "A standalone script is named from its directory, unless another module owns the name (#1041)"
issues: [1041, 625, 690, 714, 993, 1042]
anchors: ["pyeye.project_layout.RootsBoundary", "pyeye.project_layout.module_name_for_file", "pyeye.project_layout.file_for_module", "pyeye.project_layout.standalone_shadow", "pyeye.mcp.operations.resolve._resolve_at_position", "pyeye.mcp.operations.resolve._unplaced_miss", "tests/test_standalone_module_names.py"]
status: "active"
amends: ["2026-11-15-625-one-project-roots-policy-and-one-file-module-mapper-both.md", "2026-11-16-690-one-scope-to-paths-resolver-standalone-dirs-are-project.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-21 — A standalone script is named from its directory, unless another module owns the name (#1041)

**Friction:** a `standalone.dirs` directory was searched (`RootsBoundary.SCOPE` includes it, #690) but was not a naming root (`MODULE_LOOKUP` was source roots, project, additional paths). So `module_name_for_file` gave `None` for a script outside the project, plugins dropped its records, and Jedi, with the directory on no `sys.path` root, named its definitions `__main__.*`. Sibling-directory guessing had hidden this until #1035 removed it; #1042 pinned it as a strict xfail.

**Decision:** the maintainer's ruling, via designer (2026-11-21), on the proposal in #1041, with a widened shadowing rule.

- **A script's name is its path relative to its standalone directory, dotted** (`tool`, `sub.deep`), as Python imports it with that directory on `sys.path`.
- **Standalone directories come LAST in `MODULE_LOOKUP`**, through the one mapper (#625): `module_name_for_file` and `file_for_module` both. A standalone directory inside the project, or under a source root, keeps the name it had (`bin.run`): the earlier root names it first.
- **Not on Jedi's `sys_path`.** That would make every script importable by its stem for project code, and could shadow real imports. Instead, a `__main__.*` name from Jedi takes its module from the mapper: `resolver.handle_for_anchor` (#714) for the edges, and `resolve._resolve_at_position` for `resolve_at` and the `file:line` form.
- **No handle is ever shared (the widened rule).** A script is named only if NO earlier root, standard-library module or module in the project's environment owns its name (`project_layout.standalone_shadow`):
  - the standard library: `sys.stdlib_module_names`;
  - an earlier root: a source root, the project, a package, or a configured or discovered namespace package. An earlier standalone directory wins by the root order, and `module_name_for_file` names a script only if its name leads back to it;
  - the environment: the project's environment (#993, `analyzer.environment.site_paths`), read statically, never executed: a package directory, a `.py`/`.pyi` module or a compiled extension at the top of a site directory. Each site directory's names are cached by its mtime (`_site_tops`), so a large `site-packages` isn't listed on every check and an install is still seen.
  - `file_for_module` never answers a name from a standalone directory when one of these owns it, so `resolve("json")` stays the standard library's.
- **A shadowed script stays searched but unnamed.** `resolve_at` on it answers an honest `unresolved` that names what shadows it (`scripts/json.py is shadowed by the standard library module json`). A script on no root at all says so.
- Additive: a name that was `None` gets a value; nothing named before changes.

**Amends #625:** `MODULE_LOOKUP` gains `standalone_paths`, last. **Amends #690:** standalone directories are project scope AND, now, naming roots.

**Anchor:** `pyeye.project_layout.RootsBoundary` / `module_name_for_file` / `file_for_module` / `standalone_shadow`; `pyeye.mcp.operations.resolve._resolve_at_position`; #1041.

**Applies-to:**

- `pyeye.project_layout.RootsBoundary` (the `MODULE_LOOKUP` subset), `pyeye.project_layout.module_name_for_file`, `pyeye.project_layout.file_for_module`, `pyeye.project_layout.standalone_shadow`, and every consumer of the mapper (resolve, inspect, the edges, the plugin records);
- `pyeye.mcp.operations.resolve._resolve_at_position` and `pyeye.mcp.operations.resolve._unplaced_miss`.

**Verify:** gold. `uv run pytest tests/test_standalone_module_names.py tests/test_rejected_config_disclosure.py` passes. It checks:

- a script outside the project is named from its directory (`tool`, `sub.deep`);
- its handle round-trips through `resolve`, `resolve_at` (where Jedi says `__main__`), the `file:line` form and `inspect`;
- a standalone directory inside the project keeps its name;
- a script shadowed by an earlier standalone directory, by a project package, by the standard library (`json.py`) or by an environment module gets no name, and `resolve_at` says what shadows it;
- `json` still resolves to the standard library;
- the plugins find a standalone script's models (#1042's standalone half, no longer an xfail).
