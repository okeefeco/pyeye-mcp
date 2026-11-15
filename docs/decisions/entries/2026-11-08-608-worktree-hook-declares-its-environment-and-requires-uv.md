---
date: "2026-11-08"
title: "worktree-hook declares its environment and requires uv, instead of running on whatever `python3` exists (#608)"
issues: [608]
anchors: ["worktree_create", "worktree_remove", "worktree_create._load_yaml"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-08 — worktree-hook declares its environment and requires uv, instead of running on whatever `python3` exists (#608)

**Friction:** The hooks ran as bare `python3` and inherited whatever was installed. macOS's built-in python3 (3.9) can't import the scripts (3.10 `X | None` annotations), so creating or removing a worktree through the plugin failed; on Windows `python3` is often missing. "No dependencies required" was kept up with a hand-written YAML fallback parser, which silently dropped `branch_types` whenever scalar keys followed the list (as in the bundled config). That disabled nested naming and alias collapsing for anyone without PyYAML, unnoticed because the dev venv and many system Pythons have it.
**Decision:** Each script declares `requires-python = ">=3.10"` and its dependencies (PyYAML for create) in a PEP 723 header, and `hooks.json` runs it with `uv run --quiet --script`. uv provides a matching interpreter and a cached environment, with no `.venv` in the plugin dir and no install hook. The fallback parser is deleted, and the plugin requires uv (as the pyeye plugin already does); the first run needs network to fetch PyYAML. Rejected: a `uv`→`python3`→`python` launcher plus 3.9 compatibility plus fixing the fallback parser (three workarounds, each a less-tested path than the normal one); a plugin `pyproject.toml` + `uv.lock` run with `uv run --project` (pins versions, but puts a `.venv` in the plugin dir and needs a SessionStart sync step, too much for two scripts and one dependency).
**Anchor:** `plugins/worktree-hook/hooks/hooks.json` commands; the PEP 723 blocks of `worktree_create` / `worktree_remove`; `worktree_create._load_yaml`; `plugins/worktree-hook/tests/test_uv_script.py`; #608.
**Verify:** gold — `uv run pytest plugins/worktree-hook/tests/test_uv_script.py` passes. That checks: both headers declare `>=3.10`; create declares `pyyaml>=6`; every `hooks.json` command is exactly `uv run --quiet --script "${CLAUDE_PLUGIN_ROOT}/<script>"`; and running those commands end to end creates `feat/608-uv` (nested, so the YAML config loaded), prints only that path on stdout, then removes the worktree and its branch [the end-to-end test is skipped without uv on PATH, and its first run needs network to fetch PyYAML]. Plus `grep -c _parse_simple_yaml plugins/worktree-hook/worktree_create.py` prints 0.
