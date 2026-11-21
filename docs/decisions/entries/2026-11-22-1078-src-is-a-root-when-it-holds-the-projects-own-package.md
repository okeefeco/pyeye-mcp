---
date: "2026-11-22"
title: "src/ is a source root when it holds the project's own package by its declared name, a namespace included (#1078)"
issues: [1078, 625, 1035, 444]
anchors: ["pyeye.project_layout.detect_src_layout", "pyeye.project_layout.read_pyproject", "pyeye.config.ProjectConfig", "tests/test_src_layout_project_name.py"]
status: "active"
amends: ["2026-11-15-625-one-project-roots-policy-and-one-file-module-mapper-both.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-22 — src/ is a source root when it holds the project's own package by its declared name, a namespace included (#1078)

**Friction:** the architecture-facts exploration trial ran pyeye on Poetry 2.5.2 with no `.pyeye.json`. `source_roots` was empty, `resolve("poetry")` was ambiguous with `src.poetry.poetry`, and every module was named `src.…`. Two causes:

- `detect_src_layout`, the one src rule shared by the analyzer and `ProjectConfig` (#625), required a REGULAR package under `src/`. Poetry's `src/poetry` is a PEP 420 namespace, shared with poetry-core.
- Poetry declares no `packages` or `from`, so `ProjectConfig`'s build-backend readers (setuptools `where`, Poetry `from`, Hatch `sources`, PDM `package-dir`) had nothing to read. Poetry relies on poetry-core's documented default: the project's own name, at `<name>` or `src/<name>`.

**Decision:** coordinator-3's ruling (2026-11-22), option A of the proposal on #1078.

- **The rule:** `src/` is a source root when it holds a regular package (unchanged) OR the project's own package by its declared name: `src/<name>`, where `<name>` is `[project].name` or `[tool.poetry].name`, normalised as PEP 503 does (lowercase, runs of `-_.` as `_`). That directory can be a package or a PEP 420 directory that passes `dir_shallow_qualifies` (#444).
  - poetry-core, hatchling, uv_build, pdm-backend and setuptools' src-layout discovery all look there by default, so this follows a declaration in effect, in line with #1035's "declared, not guessed".
  - `pyproject.toml` is read statically (`project_layout.read_pyproject`, moved there from `declared_deps`, which reuses it).
- **Rejected (option B):** taking any PEP 420-shaped directory under `src/` as evidence. It is a guess, and it would rename existing layouts: a `src/` of loose script directories (`src/tools/x.py`) would go from `src.tools.x` to `tools.x`. A name that matches no directory under `src/` changes nothing.
- **A declared `from` / `where` still wins.** `ProjectConfig` reads it first, and auto-discovery runs only when no packages were declared.
- One helper still serves both callers, so an analyzer built without config and a configured one name files the same way (#625).

**Amends #625:** the src-layout rule gains the project-name case.

**Anchor:** `pyeye.project_layout.detect_src_layout`; `pyeye.project_layout.read_pyproject`; #1078.

**Applies-to:**

- `pyeye.project_layout.detect_src_layout` and its callers: `ProjectConfig` auto-discovery (`_discover_src_layout`), the no-config branch of `JediAnalyzer.__init__`, and `pyeye.declared_deps` (a declared dependency's import root);
- `pyeye.project_layout.read_pyproject` (shared with `pyeye.declared_deps`);
- `README.md` (Auto-Detection of Source Layouts).

**Verify:** gold. `uv run pytest tests/test_src_layout_project_name.py` passes. It checks:

- the Poetry shape (a namespace named after the project) makes `src` a root, and both analyzers name `poetry.console.app`;
- names are normalised (`My-Package`, `my.package`, `MY_PKG`), and `[tool.poetry].name` counts;
- mixed regular and namespace packages;
- a name that matches no `src/` directory changes nothing (`src.tools.run`);
- a project-named directory with no Python content isn't enough;
- no `pyproject.toml` keeps the regular-package rule;
- a declared `from` wins over the default;
- a declared `from = "src"` with a namespace already worked (pinned);
- an unreadable `pyproject.toml` falls back to the old rule.
