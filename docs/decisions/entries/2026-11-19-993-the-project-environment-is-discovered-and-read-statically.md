---
date: "2026-11-19"
title: "The project's Python environment is discovered by convention and read statically; Jedi runs only pyeye's interpreter (#993)"
issues: [993, 722, 858, 665, 618, 568, 856, 909]
anchors: ["pyeye.environment.discover", "pyeye.environment.site_paths", "pyeye.environment.not_found_note", "pyeye._jedi_project.make_project", "pyeye._jedi_project.own_environment", "tests/test_project_environment.py"]
status: "active"
amends: ["2026-11-16-722-jedi-s-own-subprocess-directory-is-never-on-pyeye-s-sys-path.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — The project's Python environment is discovered by convention and read statically; Jedi runs only pyeye's interpreter (#993)

**Friction:** found by the install-docs review (worker-5), verified live and extended in the diagnosis.

- **Isolated installs:** under the Claude Code plugin, `uvx` or `uv tool`, a `src/`-layout project couldn't resolve its own third-party packages.
- **Why:** `make_project` never gave Jedi an environment, so Jedi used its default (`VIRTUAL_ENV`, else pyeye's interpreter). And `ProjectConfig._auto_discover` added the venv's site-packages, as a configured *package*, only for a flat project with no `packages`.
- **Worse:** pyeye's OWN site-packages was on Jedi's base path, so a project's imports resolved against pyeye's dependencies. A project lacking pydantic still "resolved" `pydantic.BaseModel`, to pyeye's copy.
- **Flat projects:** the venv-as-package scanned all of site-packages under scope `all`, and was written into `.pyeye.json` on save.
- **Interpreter:** with `VIRTUAL_ENV` set, Jedi's helper ran THAT environment's interpreter, which SECURITY.md's "the server's own interpreter" didn't hold for.

**Decision:** the maintainer's ruling (via coordinator-3, 2026-11-19). It follows standard Python conventions, with ONE deliberate deviation.

- **Precedence** (`pyeye.environment.discover`):
  1. the config's `environment` (a path, or `false` to opt out), as pyright and VS Code take an explicit interpreter;
  2. an in-project venv: `.venv`, `venv` or `env` with a `pyvenv.cfg`, one level up for a root-is-package project;
  3. `VIRTUAL_ENV` then `CONDA_PREFIX`, unless it is pyeye's own `sys.prefix` (`uv run` sets it to pyeye's env under the plugin), so Poetry, Pipenv, Hatch and conda environments outside the project work;
  4. none.

  **The deviation:** an in-project venv ranks ABOVE an activated one. One server answers for many projects (#665), and the shell's activated environment would otherwise be applied to every project. This matches editors' workspace-venv preference.
- **Read statically, never run** (`site_paths`): the environment's `site-packages` (POSIX `lib/pythonX.Y`, preferring `pyvenv.cfg`'s version; Windows `Lib`), then the plain-path lines of its `.pth` files, as Python's `site` module computes them. A `.pth` line starting `import` is code; it is skipped, never executed. A repository can ship its own `.venv`, and pyeye never runs project code.
- **Jedi** (`make_project`):
  - it always runs pyeye's own interpreter: one cached `SameEnvironment` (`own_environment`), attached to every project, never Jedi's `VIRTUAL_ENV`-driven default;
  - its base path is that interpreter's standard library only (entries under `sys.base_prefix` with no site-packages segment, Jedi's own directory still excluded, #722), followed by the environment's site paths;
  - pyeye's own site-packages, and an editable pyeye source tree, are never on it, venv or not;
  - #858's `added_sys_path` roots apply on top, unchanged;
  - third-party paths are `external` by `scope.py`'s existing site-packages rule.
- **The venv is no longer a configured package:** `_discover_venv_packages` is removed. Flat projects' `packages` stop listing site-packages; plugin scans and saved configs stop including it.
- **Caches:** the environment's site paths join `layout_key` (#618), so a venv that appears or changes is another layout.
- **Path checks:** a configured `environment` is path-checked like other config entries (#856, #909). A refused one is skipped with a warning, and discovery continues.
- **Disclosure:**
  - `configure_packages` gains an always-present `environment: {path|null, source}`, with `source` one of "config" | "project" | "VIRTUAL_ENV" | "CONDA_PREFIX" | "none";
  - a once-per-project warning is logged when none is found;
  - `resolve`'s and `inspect`'s not-found `detail` gains a note when the name is third-party (not stdlib, not a project module) and no environment was found. Then "doesn't exist" and "couldn't see the venv" are distinguishable (#568).
- **Release:** `fixed` (`993.fixed.md`), `added` (`993.added.md`: the config and response keys), and `security` (`993.security.md`: Jedi no longer runs an activated environment's interpreter).

**Anchor:** maintainer ruling on #993 (via coordinator-3, 2026-11-19); `pyeye.environment`; `pyeye._jedi_project.make_project`, `own_environment`; `pyeye.config.ProjectConfig.get_environment_setting`; `pyeye.project_layout.layout_key`; #993, #722, #858, #665, #618, #568.
**Applies-to:**

- discovery and reading: `pyeye.environment.discover`, `pyeye.environment.site_paths`, `pyeye.environment.warn_once_if_none`, `pyeye.environment.not_found_note`, `pyeye.config.ProjectConfig.get_environment_setting`;
- Jedi: `pyeye._jedi_project.make_project`, `pyeye._jedi_project.own_environment`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer.__init__`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._refresh_jedi_project`;
- the layout and the responses: `pyeye.project_layout.layout_key`, `pyeye.mcp.server.configure_packages`, `pyeye.mcp.operations.resolve.resolve`, `pyeye.mcp.operations.inspect.inspect`;
- removed: `pyeye.config.ProjectConfig._auto_discover` no longer adds the venv.

**Verify:** gold. `uv run pytest tests/test_project_environment.py tests/unit/test_jedi_project.py` passes. It checks:

- the full precedence, including the deviation, `false`, a refused config path, and pyeye's own `sys.prefix` ignored;
- the POSIX and Windows layouts, `pyvenv.cfg` version preference, and `.pth` plain lines added with an import line NOT executed (a marker file stays absent);
- Jedi's environment is pyeye's own even with `VIRTUAL_ENV` set;
- `src/` and flat projects resolve a venv package as external;
- pyeye's own pydantic never resolves for a project lacking it;
- the venv is no longer a configured package, and the environment changes the layout key;
- `environment` is reported in `configure_packages`, the not-found note appears only for third-party misses with no environment, and the warning is logged once.

Tests that relied on pyeye's own site-packages now give their fixture an environment (`tests/utils/environment.py`: a `.venv` whose `.pth` names the run's `purelib`), which is the production path.
