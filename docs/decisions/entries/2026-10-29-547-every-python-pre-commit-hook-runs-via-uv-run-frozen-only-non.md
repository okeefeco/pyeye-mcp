---
date: "2026-10-29"
title: "Every Python pre-commit hook runs via `uv run --frozen`; only non-Python hooks stay remote (#547, extends #413)"
issues: [547, 413, 548, 529, 481]
anchors: ["python3", "pyproject.toml"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-10-29 — Every Python pre-commit hook runs via `uv run --frozen`; only non-Python hooks stay remote (#547, extends #413)

**Friction:** #413 single-sourced only black/ruff/mypy. detect-secrets, bandit, pydocstyle, commitizen and the `pre-commit-hooks` file checks stayed remote repos pinning their own `rev:` in separate envs. Dependabot has no `pre-commit` ecosystem, so those revs were never bumped and drifted from `uv.lock`: the commit hook ran bandit 1.8.6 while CI's `security` job ran 1.9.4 (a finding could pass locally and fail in CI, or the reverse), and commitizen 3.13.0 against a locked 4.19.3. The separate envs also depended on `default_language_version`; its `python3.12` pin broke CI's pre-commit job (exit 3, no interpreter) the moment that job moved to 3.13 (#529).
**Decision:** All Python tool hooks are `repo: local` with `uv run --frozen` entries, so `uv.lock` is their only version source (same binary as CI and `uv run <tool>`). Each mirrors its upstream manifest at the previously pinned rev (entry, types/files, args, stages, `require_serial`); commitizen's default args (`--allow-abort --commit-msg-file`) are inlined because local hooks don't inherit them. `pre-commit-hooks` joins the dev group at the rev already in use (4.5.0, so no behavior change) and Dependabot's dev-tooling group. Only non-Python hooks (markdownlint, Node) may stay remote. `default_language_version` is `python3`, never a minor. Rejected again, as in #413: adding a `pre-commit` Dependabot ecosystem (keeps two pins that diverge between PRs).
**Anchor:** #547 / PR #548 ; #529 (`python3`) ; `.pre-commit-config.yaml` `repo: local` hooks ; `pyproject.toml` dev group `pre-commit-hooks` ; guard tests `tests/test_precommit_hook_config.py::{test_only_non_python_hooks_use_remote_repos, test_python_tool_hooks_run_through_uv, test_hook_python_is_not_pinned_to_a_minor_version}` ; extends the 2026-06-18 (#413) and 2026-06-23 (#481) entries.
**Verify:** gold [needs synced env: `uv sync`] — the three guard tests pass; `grep -E '^\s*- repo: https' .pre-commit-config.yaml` lists only `igorshubovych/markdownlint-cli`; `uv run --frozen bandit --version` and `uv run --frozen cz version` report the `uv.lock` versions. Behavior parity at conversion time (one-off, not re-runnable from the repo): the old and new configs gave identical pass/fail on 25 checks over deliberately bad files plus a good and a bad commit message.
