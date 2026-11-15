---
date: "2026-06-23"
title: "uv lockfile is authoritative everywhere; pinned per context (#481, follows #479)"
issues: [481, 479]
anchors: ["tests/test_ci_uv_pinned.py::test_ci_uv_sync_is_locked", "tests/test_precommit_hook_config.py::test_all_uv_run_entries_are_frozen"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-23 — uv lockfile is authoritative everywhere; pinned per context (#481, follows #479)

**Friction:** Behind a PyPI mirror, bare `uv run` in pre-commit re-resolved and rewrote `uv.lock`, tripping pre-commit's framework-level "files were modified by this hook" check and failing `git checkout`/`commit` (#479). The deeper issue: nothing guaranteed every environment built from the *exact* locked config — bare `uv run`/`uv sync` may silently re-resolve (a mirror rewrite, or CI drifting from a stale lock), so "use the exact config" could quietly degrade.
**Decision:** Make the lockfile authoritative everywhere, pinned per context by how strict the no-deviation must be. **Hooks** use `uv run --frozen` (use the lock as-is; never block, never rewrite — fresh-clone friendly) (#479). **CI** pins `uv sync --locked` on its setup steps (assert `uv.lock == pyproject.toml`, fail on drift); subsequent `uv run` runs against the just-verified env. Resolution happens only via a deliberate `uv lock`/`uv add`. The `--frozen`-for-hooks vs `--locked`-for-CI split is intentional: hooks must never block local work, while the CI gate must fail loudly on drift (`--frozen` in CI would silently run a stale lock and hide it). A workflow-level `UV_LOCKED=1` env var was tried first (one declaration, can't-erode) but **reverted**: `UV_LOCKED` is mutually exclusive with `--frozen`, and CI's `pre-commit` job runs the `--frozen` hooks, so uv aborted with `UV_LOCKED cannot be used with --frozen` (PR #482 CI; an empty per-job override does NOT clear it — uv treats the var as present). A `--locked` *flag* on the standalone `uv sync` never shares an environment with the `--frozen` hook runs, so they can't collide. Rejected: `--frozen` in CI (hides drift); workflow-level `UV_LOCKED` (collides with the hooks).
**Anchor:** `uv sync --locked` in `.github/workflows/{ci,release,build-deploy-docs}.yml`; `uv run --frozen` entries in `.pre-commit-config.yaml`; guard tests `tests/test_ci_uv_pinned.py::test_ci_uv_sync_is_locked` and `tests/test_precommit_hook_config.py::test_all_uv_run_entries_are_frozen`; CONTRIBUTING.md "Dependency lockfile policy"; #481, #479.
**Verify:** gold — `test_ci_uv_sync_is_locked` asserts every `uv sync` in a workflow carries `--locked`; `test_all_uv_run_entries_are_frozen` asserts no pre-commit hook entry uses a bare `uv run`. Behavioral (proven locally): with a dependency added to `pyproject.toml` but `uv.lock` left unchanged, `uv sync --locked` fails with "The lockfile at `uv.lock` needs to be updated, but `--locked` was provided"; `uv run --frozen python scripts/refresh_version.py` on a fresh clone leaves `uv.lock` unchanged; and `UV_LOCKED=1 uv run --frozen …` aborts (the collision that forced the flag-over-env choice).
