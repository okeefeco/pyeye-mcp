---
date: "2026-11-20"
title: "A save writes only the project's explicit config; discovered packages are reported, never saved (#1038)"
issues: [1038, 1035, 953]
anchors: ["pyeye.config.ProjectConfig.save_config", "pyeye.config.ProjectConfig.add_explicit", "pyeye.config.ProjectConfig.discovered", "pyeye.mcp.server.configure_packages", "tests/test_config_save_explicit.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A save writes only the project's explicit config; discovered packages are reported, never saved (#1038)

**Friction:** found while diagnosing #1035. `configure_packages(save=True)` added the call's entries to `ProjectConfig.config` and `save_config` dumped that whole dict. But it is the MERGED view of every layer:

- the global config;
- the project file;
- `.pyeye.override.json`;
- derived packages (sibling discovery, the `src/` layout, `[tool.pyright] extraPaths`, build-backend layouts);
- the unsaved overlay.

So a save copied the user's global defaults and the local override into the project's (usually committed) `.pyeye.json`. It also froze re-derived packages as absolute paths: once `packages` is non-empty, auto-discovery never runs again, so a sibling guess became permanent config. Nothing in the response said which packages pyeye had added on its own.

**Decision:** the coordinator's ruling (#1038), independent of #1035's discovery-rule question.

- **What a save writes:** `ProjectConfig` keeps the project config file's own pyeye section as a separate layer (`_project_layer`; for `pyproject.toml`, its `[tool.pyeye]` table). Explicit additions go into both that layer and the merged view, through one method, `add_explicit`: a `configure_packages` call's entries and the session's unsaved overlay (#953). `save_config` writes the layer, never the merged view. #953's rule is unchanged: a save persists the overlay with the call's own entries.
- **What is never written:** a derived package, the global config, the override file.
- **Reported:** `configure_packages` returns an always-present `discovered`, each derived package as `{"path", "reason"}`, with `reason` one of `sibling`, `src_layout`, `pyright_extra_paths` or `build_backend_layout`. `path` is resolved POSIX, the form `packages` uses; `[]` when none were added. They are still analysed: each is also in `packages`. It is a new path-carrying key, so `tests/test_mcp_path_boundary.py`'s walker checks its paths. `configure_packages` isn't respelled into the caller's spelling (#717 respells file locations; `packages` isn't either), so neither is `discovered`.
- **Deterministic siblings:** sibling discovery is sorted. Its order is Jedi's root order (#858), and `iterdir` order varies by filesystem.
- **Kept:** a save still writes `.pyeye.json`, even for a project whose config is in `pyproject.toml` or YAML, and the project's own section carries over into it. That's the existing behaviour minus the leaks.
- **Rejected:** stripping derived entries from the merged view at save time. A derived path can also be written in the project file, and the global and override layers aren't marked in the merged dict, so subtraction can't tell them apart. A separate layer can.

**Anchor:** `pyeye.config.ProjectConfig.save_config` / `add_explicit` / `discovered` / `_load_from_file` (`project_file`) / `_discover_sibling_packages`; `pyeye.mcp.server.configure_packages`; #1038, #1035, #953.

**Applies-to:** `pyeye.config.ProjectConfig.save_config`, `pyeye.config.ProjectConfig.add_explicit`, `pyeye.config.ProjectConfig.discovered`, `pyeye.config.ProjectConfig._apply_unsaved`, `pyeye.config.ProjectConfig._load_from_file`, `pyeye.config.ProjectConfig._discover_sibling_packages`, `pyeye.config.ProjectConfig._discover_src_layout`, `pyeye.config.ProjectConfig._read_pyright_extra_paths`, `pyeye.config.ProjectConfig._add_detected_paths`, `pyeye.mcp.server.configure_packages`.

**Verify:** gold. `uv run pytest tests/test_config_save_explicit.py tests/test_unsaved_config_overlay.py tests/unit/core/test_config.py` passes. It checks:

- a save writes no sibling, `src/`, pyright or build-backend package, nothing from the global config, and nothing from the override file;
- the project file's other keys and a `pyproject.toml` `[tool.pyeye]` section carry over;
- unsaved entries are still written;
- `discovered` lists each kind with its reason, is `[]` once packages are configured, and is a subset of `packages`.
