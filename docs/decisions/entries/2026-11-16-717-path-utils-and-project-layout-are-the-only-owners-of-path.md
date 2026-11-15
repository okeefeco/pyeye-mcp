---
date: "2026-11-16"
title: "path_utils and project_layout are the only owners of path normalisation and comparison, enforced by a ratchet (#717)"
issues: [717, 714, 710, 715, 689]
anchors: ["scripts/check_cross_platform_paths.py", "pyeye.path_utils", "pyeye.project_layout", "tests/test_path_ownership.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — path_utils and project_layout are the only owners of path normalisation and comparison, enforced by a ratchet (#717)

**Friction:** Three path bugs turned up in one afternoon: #710 (macOS/Windows red on a symlinked tmp), #714 (an invented `__main__.X` handle under a symlinked root) and #715 (a macOS watcher flake). They came from code that normalised or compared paths its own way, so two copies of one comparison disagreed about symlinks. `path_utils` existed, but production code used only `dedupe_paths`. The audit found 52 inline sites: 41 `.resolve()`, 10 `relative_to`, 1 `os.path`. The old regex checker was commented out of pre-commit because it had too many false positives, so nothing enforced the rules.
**Decision:**

- Outside `pyeye.path_utils` and `pyeye.project_layout`, `src/pyeye` code does not normalise or compare paths. It calls `relative_within` (containment), `paths_equal` (equality) or `normalize_path` (resolved form).
- `scripts/check_cross_platform_paths.py` is rewritten as an AST checker with four narrow rules: zero-argument `.resolve()`; `os.path.realpath`/`abspath`/`normpath`/`samefile`; `.relative_to` / `.is_relative_to`; and `str(<path-like>)` in a comparison, `startswith`/`endswith` or a key. The f-string rule is dropped and log messages are allowed.
- The checker is a blocking ratchet, under the #689 rules. `BASELINE` holds `(file::qualname, rule) -> count` and is exact both ways: a count above the baseline fails, and a count below it or a key that has gone also fails until the entry is lowered or deleted. It runs as pre-commit `path-ownership` and as `tests/test_path_ownership.py`.
- The 52 existing sites are baselined. Follow-up PRs move them through `path_utils`, and the baseline shrinks to empty.

Rejected: fixing every site in one PR, which is too large and mixes risky behaviour changes with mechanical ones; keeping the regex checker, whose false positives are why it was turned off.
**Anchor:** `scripts/check_cross_platform_paths.py` (`BASELINE`, `ratchet`); `pyeye.path_utils.relative_within`, `paths_equal`, `normalize_path`; `tests/test_path_ownership.py`; #717.
**Applies-to:** every module under `src/pyeye` except `path_utils.py` and `project_layout.py`. Today's sites are the 52 `BASELINE` entries across `project_manager`, `analyzers/jedi_analyzer`, `scope`, `validation`, `mcp/operations/typeref`, `config`, `mcp/server`, `file_artifact_cache`, `analyzers/project_graph`, `resolver`, `plugins/handles`, `plugins/base`, `namespace_resolver` and `mcp/operations/resolve`.
**Verify:** gold: `uv run python scripts/check_cross_platform_paths.py` exits 0 with "0 new, 0 stale", and `uv run pytest tests/test_path_ownership.py` passes. The rules are syntactic (AST); a path compared through another route, for example a helper that returns `str(p)` and is compared by its caller, isn't caught.
