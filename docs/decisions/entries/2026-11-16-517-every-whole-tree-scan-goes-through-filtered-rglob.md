---
date: "2026-11-16"
title: "Every whole-tree project scan goes through `filtered_rglob` (#517)"
issues: [517, 507, 690]
anchors: ["pyeye.async_utils.filtered_rglob", "rglob_async", "pyeye.plugins.pydantic.PydanticPlugin.detect", "pyeye.plugins.flask.FlaskPlugin.detect", "get_framework_components", "pyeye.plugins.django.DjangoPlugin.find_migrations", "pyeye.canonicalization._scan_package_for_handle"]
status: "active"
amends: ["2026-08-09-507-the-project-scan-excludes-nested-git-worktrees-not.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Every whole-tree project scan goes through `filtered_rglob` (#517)

**Friction:** #507's exclusion rule (nested linked worktrees, `EXCLUDED_DIRS`, `*.egg-info`) lived inside `rglob_async`, so it bound only that function's callers. The framework plugins and the canonicalization re-export scan called `Path.rglob` / `Path.glob("**/…")` directly.

- They reported a second copy of every `models.py`, `views.py`, migration and template directory from `.claude/worktrees/…`.
- They read `.venv`, so Pydantic could be "detected" from installed packages.

**Decision:** the rule has ONE home, the sync `pyeye.async_utils.filtered_rglob(pattern, path)`.

- `rglob_async` is that on a worker thread.
- Every whole-tree scan calls it: Pydantic and Flask detection, the Flask and Django component maps, Django migrations, and `canonicalization._scan_package_for_handle`. The last one's root is the project root when the project is itself a package.
- Submodules stay included (git's `commondir` marker, as in #507).
- Recursive scans of a known subtree are not project scans and are allow-listed with their reason: `.venv/lib` searched for `site-packages`, and a found `templates/` directory.

**Anchor:** `pyeye.async_utils.filtered_rglob`, `rglob_async`; the plugin scans named above; #517, #507.
**Applies-to:**

- `pyeye.async_utils.filtered_rglob` and `rglob_async`;
- the plugin scans `PydanticPlugin.detect`, `FlaskPlugin.detect`, `FlaskPlugin.get_framework_components`, `DjangoPlugin.get_framework_components` and `DjangoPlugin.find_migrations`;
- `pyeye.canonicalization._scan_package_for_handle`;
- the structural guard `tests/integration/test_nested_worktree_exclusion.py::test_every_whole_tree_scan_goes_through_filtered_rglob`, with its `_SUBTREE_SCANS` allowlist.

**Verify:** gold. `uv run pytest tests/integration/test_nested_worktree_exclusion.py` passes:

- against real `git worktree add` / `git submodule add` output, the plugins report only the main tree and the submodule;
- the guard finds no `.rglob(` / `glob("**…")` in `src/pyeye` outside `filtered_rglob` and the allowlist.
