---
date: "2026-06-18"
title: "Dev/docs deps are PEP 735 dependency-groups; bare `uv sync` is the canonical install"
issues: [414]
anchors: ["pyproject.toml", "dev", "docs", "setup.sh"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-18 — Dev/docs deps are PEP 735 dependency-groups; bare `uv sync` is the canonical install

**Friction:** The repo was nominally a `uv` project (tracked `uv.lock`, "this is a uv project — NOT uv pip install" in the instructions) but every install site used `uv pip install --system` / `uv venv`, which **bypasses the lockfile** — CI re-resolved deps each run and `uv.lock` was never enforced. `dev` was also a published `[project.optional-dependencies]` extra, exposing dev tooling as `pip install pyeye-mcp[dev]`. (#414, follow-up to #413.)
**Decision:** Make `uv sync` (lock-driven) the single install path everywhere — CI (`ci.yml`, `release.yml`, `build-deploy-docs.yml`), `setup.sh`, and the human docs — with test/type/security/build steps invoked via `uv run`. Move `dev` and a new `docs` set from extras to PEP 735 `[dependency-groups]`. `dev` is uv's **default group**, so bare `uv sync` installs main + dev (what CI/pre-commit/contributors need); docs is opt-in via `uv sync --group docs`. There are intentionally **no extras**. Rejected: keep `dev`/`docs` as extras synced via `--all-extras` (keeps dev tooling in published metadata and the lock-bypass `uv pip` habit alive). Consequence: `pip install -e ".[dev]"` / `uv pip install -e ".[dev]"` no longer work — the documented install is `uv sync`.
**Anchor:** #414 ; `pyproject.toml` `[dependency-groups]` (`dev`, `docs`) ; `.github/workflows/{ci,release,build-deploy-docs}.yml` ; `setup.sh`
**Verify:** gold — (1) no lock-bypassing installs remain: `grep -rE "uv pip|uv venv|--system" .github/workflows setup.sh CONTRIBUTING.md docs/RELEASE.md docs/TROUBLESHOOTING.md` returns nothing; (2) `[project.optional-dependencies]` is absent from `pyproject.toml` (no extras); (3) bare `uv sync` then `uv run python -c "import pytest, mypy"` succeeds (dev is a default group); (4) `uv sync --all-extras` installs no extras (none defined) while dev remains present.
