---
date: "2026-11-20"
title: "Packages beside a project come only from declarations, its environment or pyeye's config; neighbouring directories are never guessed (#1035)"
issues: [1035, 1038, 993, 933]
anchors: ["pyeye.declared_deps.declared_path_dependencies", "pyeye.declared_deps.not_found_note", "pyeye.config.ProjectConfig._add_declared_dependencies", "pyeye.config.ProjectConfig._auto_discover", "pyeye.environment.third_party_top", "tests/test_declared_path_deps.py"]
status: "active"
amends: ["2026-11-20-1038-a-save-writes-only-the-projects-explicit-config.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — Packages beside a project come only from declarations, its environment or pyeye's config; neighbouring directories are never guessed (#1035)

**Friction:** with no `packages` configured, `ProjectConfig._discover_sibling_packages` added every directory beside the project that had a top-level `*.py` or a `setup.py`. Each became an analyzer root: watched, swept twice at start-up, and searched as `scope: project` code.

- **Over-discovery:** a project in a shared `/tmp` had 562 watched roots, including every Claude session's scratchpad. That cost also amplified #933's double walk.
- **Under-discovery:** the case the feature exists for, a modern `pyproject.toml` repository with its package in a subdirectory, has neither a top-level `.py` nor a `setup.py`. It was missed.
- **Frozen:** a save wrote the guesses into `.pyeye.json` (fixed separately in #1038).

**Decision:** the user's ruling (A+, via coordinator-3, 2026-11-20). Sibling-directory guessing is removed. A package beside the project comes from one of three places.

1. **A path dependency the project's `pyproject.toml` declares,** read statically by `pyeye.declared_deps` on every load (whichever pyeye config file the project uses) and never saved.
   - **uv:** `[tool.uv.sources]` `path` entries (a table, or a list with markers) and `[tool.uv.workspace]` `members` minus `exclude`. A glob member matches only inside the workspace root: a `..` part matches nothing, and matches are tested on their resolved form, so a symlink can't lead out. A literal member path is a declaration and is kept wherever it is.
   - **Poetry:** `path` dependencies in `[tool.poetry.dependencies]`, `[tool.poetry.group.*.dependencies]` and `[tool.poetry.dev-dependencies]`.
   - **PEP 621 / PEP 735:** `name @ file:...` direct references in `[project] dependencies`, `[project.optional-dependencies]` and `[dependency-groups]`. Only PDM's `${PROJECT_ROOT}` and Hatch's `{root:uri}` are expanded, by plain substitution. Any other placeholder skips the entry, logged at debug, and a skipped entry isn't discovered.
   - **Not read:** `setup.py` (code), `setup.cfg`, `requirements*.txt`.
   - **What counts:** only an existing directory (not a wheel or sdist). Its import root is its `src/` for a src layout, else the directory.
   - **Path checks:** each is added as a derived package, so the packages path check applies (`validate_scan_root` and the deny-list). A refused one is in `rejected_paths`, not `discovered`. Its `path` there is the entry as declared: absolute, `..` collapsed, symlinks unresolved (`path_utils.absolute_path`, #717). That is `rejected_paths`' "as written" contract, so a declared `/etc` reads `/etc`, not macOS's `/private/etc`. `discovered` and `packages` report resolved forms, as before.
   - **Reported:** `discovered` reports each one, with reason `uv_source`, `uv_workspace`, `poetry_path` or `pep621_file_url`.
2. **The project's environment (#993).** An editable install that writes a plain path to a `.pth` already reaches Jedi. Per the empirical survey, that's every common backend with a `src/` layout, and flat layouts on hatchling, pdm-backend, flit, poetry-core and uv_build. Reading setuptools' flat-layout finder, and the `editables` finders, statically is a separate, security-reviewed change.
3. **pyeye's own config,** unchanged.

The `src/` layout check (`_auto_discover`) is kept: it is the project's own source root, not a guess about a neighbour.

**The not-found hint:** when a top-level name looks third-party (`environment.third_party_top`: not the standard library's, not a project module), `resolve` and `inspect` append a note suggesting a path dependency or `configure_packages`. It sits beside #993's no-environment note, and both use the same predicate.

**Amends #1038:** its `discovered` reason `sibling` no longer occurs. The declared-dependency reasons are added.

**Anchor:** `pyeye.declared_deps.declared_path_dependencies` / `not_found_note`; `pyeye.config.ProjectConfig._add_declared_dependencies` / `_auto_discover` / `discovered`; `pyeye.environment.third_party_top`; #1035, #1038, #993.

**Applies-to:** `pyeye.declared_deps.declared_path_dependencies`, `pyeye.declared_deps.not_found_note`, `pyeye.config.ProjectConfig._add_declared_dependencies`, `pyeye.config.ProjectConfig._auto_discover`, `pyeye.config.ProjectConfig.discovered`, `pyeye.environment.third_party_top`, `pyeye.environment.not_found_note`, `pyeye.mcp.operations.resolve.resolve`, `pyeye.mcp.operations.inspect.inspect`.

**Verify:** gold. `uv run pytest tests/test_declared_path_deps.py tests/test_config_save_explicit.py` passes. It checks:

- undeclared neighbours are not packages;
- each uv, Poetry and PEP 621 / PEP 735 form is read, and a src-layout dependency resolves to its `src/`;
- workspace `exclude` applies, a climbing or symlinked glob member is dropped, and a literal member is kept;
- both placeholders expand and an unknown one skips the entry;
- an archive or a missing directory is skipped;
- declarations are read beside an explicit `.pyeye.json` and never saved;
- a restricted declared path is refused into `rejected_paths`;
- an unresolved third-party import's detail suggests declaring it.
