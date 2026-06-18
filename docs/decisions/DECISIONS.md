# Decision Log

Contract/invariant-significant, friction-driven decisions. Each entry is a small verifiable fact: Friction · Decision · Anchor (stable ref) · Verify (checkable or honestly-labelled). Newest on top. Maintained via the `decision-log` skill.

## 2026-06-18 — Dev/docs deps are PEP 735 dependency-groups; bare `uv sync` is the canonical install

**Friction:** The repo was nominally a `uv` project (tracked `uv.lock`, "this is a uv project — NOT uv pip install" in the instructions) but every install site used `uv pip install --system` / `uv venv`, which **bypasses the lockfile** — CI re-resolved deps each run and `uv.lock` was never enforced. `dev` was also a published `[project.optional-dependencies]` extra, exposing dev tooling as `pip install pyeye-mcp[dev]`. (#414, follow-up to #413.)
**Decision:** Make `uv sync` (lock-driven) the single install path everywhere — CI (`ci.yml`, `release.yml`, `build-deploy-docs.yml`), `setup.sh`, and the human docs — with test/type/security/build steps invoked via `uv run`. Move `dev` and a new `docs` set from extras to PEP 735 `[dependency-groups]`. `dev` is uv's **default group**, so bare `uv sync` installs main + dev (what CI/pre-commit/contributors need); docs is opt-in via `uv sync --group docs`. There are intentionally **no extras**. Rejected: keep `dev`/`docs` as extras synced via `--all-extras` (keeps dev tooling in published metadata and the lock-bypass `uv pip` habit alive). Consequence: `pip install -e ".[dev]"` / `uv pip install -e ".[dev]"` no longer work — the documented install is `uv sync`.
**Anchor:** #414 ; `pyproject.toml` `[dependency-groups]` (`dev`, `docs`) ; `.github/workflows/{ci,release,build-deploy-docs}.yml` ; `setup.sh`
**Verify:** gold — (1) no lock-bypassing installs remain: `grep -rE "uv pip|uv venv|--system" .github/workflows setup.sh CONTRIBUTING.md docs/RELEASE.md docs/TROUBLESHOOTING.md` returns nothing; (2) `[project.optional-dependencies]` is absent from `pyproject.toml` (no extras); (3) bare `uv sync` then `uv run python -c "import pytest, mypy"` succeeds (dev is a default group); (4) `uv sync --all-extras` installs no extras (none defined) while dev remains present.

## 2026-06-18 — Dev-tool versions (black/ruff/mypy) single-sourced in pyproject; pre-commit runs them via `uv run`

**Friction:** black/ruff/mypy were pinned in two places — the `pyproject.toml` dev group AND `.pre-commit-config.yaml` hook `rev:`s — which drifted (e.g. mypy `v1.17.1` vs `2.1.0`, ruff `v0.12.10` vs `0.15.17`). Dependabot bumps only `pyproject.toml`, never the pre-commit revs, so `uv run mypy` (CI `type-check` job + local dev) and the pre-commit `mypy` hook ran *different* versions, and the drift recurred on every dev-tooling bump. Surfaced while validating the dev-dependencies dependabot PR (#327).
**Decision:** Convert the black/ruff/mypy pre-commit hooks to a single `repo: local` block that invokes `uv run <tool>`, making the `pyproject.toml` dev pin the one source for pre-commit, CI, and local dev (literally the same binary — drift impossible). mypy's type-stub `additional_dependencies` moved into the pyproject dev group. Rejected: (a) bump the pre-commit `rev:`s to match + add a `pre-commit` dependabot ecosystem — keeps two pins that still transiently diverge between dependabot PRs; (b) one-time manual rev sync — drift just recurs. Tradeoff accepted: hooks now require a synced uv env, so the CI `pre-commit` job runs `uv sync --all-extras` first (and contributors must `uv sync`).
**Anchor:** #413 ; `.pre-commit-config.yaml` `repo: local` black/ruff/mypy hooks ; `pyproject.toml` `[project.optional-dependencies].dev` pins ; `.github/workflows/ci.yml` `pre-commit` job
**Verify:** gold [needs synced env: `uv sync --all-extras`] — (1) no second pin can exist: `grep -E "psf/black|ruff-pre-commit|mirrors-mypy" .pre-commit-config.yaml` returns nothing (the hooks are `repo: local`); (2) the tools resolve to the pyproject pins: `uv run ruff --version` == `0.15.17`, `uv run mypy --version` reports `2.1.0`, `uv run black --version` reports `26.5.1` — the same binaries the pre-commit hooks invoke.

## 2026-06-16 — AST/Script cache cap is configurable via `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`

**Friction:** The `file_artifact_cache` combined AST+Script LRU cap was hardcoded at 500. On large repos (hundreds of files / 10k+ classes) the working set exceeds it, so a repeated scan (e.g. `expand` `subclasses`) evicts its own entries mid-scan and the next identical call re-parses from disk — the cache silently stops helping. Reproduced: same call twice → same cost, with eviction count climbing.
**Decision:** Add `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` (default 500, min 1, max 1_000_000). `FileArtifactCache(ast_max_entries=None)` falls back to `settings.artifact_cache_max_entries`; an explicit constructor arg always wins (test isolation / targeted tuning). Rejected: hardcoded constant; auto-sizing to project file count (deferred — wants the eviction signal observed in the field first).
**Anchor:** `Settings.artifact_cache_max_entries` ; `FileArtifactCache.__init__` ; commit `0d7933d` ; #397
**Verify:** gold — `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=7 python -c "from pyeye import file_artifact_cache as f; assert f.FileArtifactCache()._ast_max_entries==7"`; covered by `tests/test_artifact_cache_configurable.py` (default-vs-explicit precedence) and `tests/unit/core/test_settings.py` (default/env/clamp).

## 2026-06-16 — AST/Script cache stats surfaced in the performance report

**Friction:** The `file_artifact_cache` (AST/Script) cache — the one that actually accelerates navigation — was wired to no report. `get_performance_metrics` surfaced only the result/scoped cache, so a healthy run and a cap-thrashing run reported *identically* (both `1 hit, 1 miss`); the eviction signal that distinguishes them was invisible. Root cause: four disconnected `CacheMetrics` objects, only one of them reported.
**Decision:** Surface `file_artifact_cache.stats()` as a distinct top-level `artifact_cache` section in `MetricsCollector.get_performance_report()` and as `pyeye_artifact_cache_{hits,misses,evictions}` Prometheus series. Kept *separate* from the existing `cache` block (not merged) so the metric fragmentation stays visible rather than hidden.
**Anchor:** `MetricsCollector.get_performance_report` ; `MetricsCollector.export_prometheus` ; commit `e9e47d5` ; #397
**Verify:** gold — `tests/test_artifact_cache_metrics_surface.py` asserts the report exposes `artifact_cache` reflecting real hits/misses/evictions, and that an over-cap run (evictions>0) is now distinguishable from an under-cap run (evictions==0) — the exact blind spot this closes.

## 2026-06-13 — decision-log ships in the pyeye plugin, not ~/.claude/skills

**Friction:** A loose `~/.claude/skills/` file is unmanaged — not versioned, lost on a machine move, not shareable — and it split the work across two homes (user dir + repo).
**Decision:** Bundle the skill in the pyeye plugin's `skills/` (alongside `python-explore`) so it ships, versions, and reinstalls with pyeye while staying globally available. Keep the pyeye-dependency *soft* — `Verify` tiers allow grep / import-linter / tests / human, not just pyeye. Rejected: loose user-level skill.
**Anchor:** `skills/decision-log/SKILL.md` ; `.claude-plugin/plugin.json` ; this session
**Verify:** gold — `test -f skills/decision-log/SKILL.md && ! test -e ~/.claude/skills/decision-log` (skill present in plugin, no shadow copy).

## 2026-06-13 — decision-log fires at the commit checkpoint, not ambient AI vigilance

**Friction:** An ambient "agent watches for significant changes and pipes up" trigger decays — the agent is heads-down on the task and catches the moment inconsistently (the same reason "always do X" instructions lapse).
**Decision:** Anchor the trigger to the commit — a deterministic pause with the diff already on the table — via the `smart-commit` agent, plus on-demand ("log this decision"). Rejected: always-on agent vigilance.
**Anchor:** `skills/decision-log/SKILL.md` ("When This Fires") ; `.claude/agents/smart-commit.md`
**Verify:** PARTIAL — `grep -q "commit checkpoint" skills/decision-log/SKILL.md` and a decision-note step exists in `.claude/agents/smart-commit.md` confirm the documented trigger. Whether it *actually* fires reliably is behavioural — human-observed over time [unverifiable mechanically].

## 2026-06-13 — decisions captured as an append-only log, not one ADR file per decision

**Friction:** Per-file ADRs (`NNNN-slug.md`) are ceremony that rots; the goal is the lowest friction that still yields retrievable, verifiable facts (avoid the ADR graveyard).
**Decision:** A single append-only `docs/decisions/DECISIONS.md`, newest on top, one short entry per distinct decision (Friction · Decision · Anchor · Verify). Rejected: one ADR file per decision; commit-trailer-only (buried in git history).
**Anchor:** `docs/decisions/DECISIONS.md` ; `skills/decision-log/SKILL.md` ("File Convention")
**Verify:** gold — `head -1 docs/decisions/DECISIONS.md` equals `# Decision Log`; entries are `##` headings carrying the four bold fields Friction/Decision/Anchor/Verify.
