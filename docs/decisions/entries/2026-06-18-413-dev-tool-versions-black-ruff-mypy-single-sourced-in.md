---
date: "2026-06-18"
title: "Dev-tool versions (black/ruff/mypy) single-sourced in pyproject; pre-commit runs them via `uv run`"
issues: [413]
anchors: ["pyproject.toml"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-18 — Dev-tool versions (black/ruff/mypy) single-sourced in pyproject; pre-commit runs them via `uv run`

**Friction:** black/ruff/mypy were pinned in two places — the `pyproject.toml` dev group AND `.pre-commit-config.yaml` hook `rev:`s — which drifted (e.g. mypy `v1.17.1` vs `2.1.0`, ruff `v0.12.10` vs `0.15.17`). Dependabot bumps only `pyproject.toml`, never the pre-commit revs, so `uv run mypy` (CI `type-check` job + local dev) and the pre-commit `mypy` hook ran *different* versions, and the drift recurred on every dev-tooling bump. Surfaced while validating the dev-dependencies dependabot PR (#327).
**Decision:** Convert the black/ruff/mypy pre-commit hooks to a single `repo: local` block that invokes `uv run <tool>`, making the `pyproject.toml` dev pin the one source for pre-commit, CI, and local dev (literally the same binary — drift impossible). mypy's type-stub `additional_dependencies` moved into the pyproject dev group. Rejected: (a) bump the pre-commit `rev:`s to match + add a `pre-commit` dependabot ecosystem — keeps two pins that still transiently diverge between dependabot PRs; (b) one-time manual rev sync — drift just recurs. Tradeoff accepted: hooks now require a synced uv env, so the CI `pre-commit` job runs `uv sync --all-extras` first (and contributors must `uv sync`).
**Anchor:** #413 ; `.pre-commit-config.yaml` `repo: local` black/ruff/mypy hooks ; `pyproject.toml` `[project.optional-dependencies].dev` pins ; `.github/workflows/ci.yml` `pre-commit` job
**Verify:** gold [needs synced env: `uv sync --all-extras`] — (1) no second pin can exist: `grep -E "psf/black|ruff-pre-commit|mirrors-mypy" .pre-commit-config.yaml` returns nothing (the hooks are `repo: local`); (2) the tools resolve to the pyproject pins: `uv run ruff --version` == `0.15.17`, `uv run mypy --version` reports `2.1.0`, `uv run black --version` reports `26.5.1` — the same binaries the pre-commit hooks invoke.
