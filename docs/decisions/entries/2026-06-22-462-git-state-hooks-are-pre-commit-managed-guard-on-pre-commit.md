---
date: "2026-06-22"
title: "git-state hooks are pre-commit-managed; guard on PRE_COMMIT_CHECKOUT_TYPE (#462)"
issues: [462]
anchors: ["scripts.refresh_version.should_run", "scripts.dogfooding_metrics._extract_issue", "default_install_hook_types"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-24-1182-anchors-that-drifted-are-carried-to-their-current-sites.md"]
superseded_by: []
---

## 2026-06-22 — git-state hooks are pre-commit-managed; guard on PRE_COMMIT_CHECKOUT_TYPE (#462)

**Friction:** Two things broke that should have been the same fix. (1) The `setuptools_scm` version file (`src/pyeye/_version.py`, gitignored, written only at install time) drifted after a plain `git pull` — `pyeye://about` reported `dev342` while HEAD was `dev416`. (2) The dogfooding metrics auto-start lived in an *uncommitted* `.git/hooks/post-checkout` that called bare `python scripts/dogfooding_metrics.py` — so it ran on exactly one machine, and that script imports `click` + `pyeye`, so a bare interpreter would have failed (silently swallowed by `2>/dev/null || true`). A contributor-wide concern was wired to one developer's disk.
**Decision:** Move both into pre-commit `local` hooks and add `post-merge` + `post-checkout` to `default_install_hook_types` so a bare `pre-commit install` wires them for everyone (committed, reproducible — the "documentation that can't lie" principle). Both invoke via `uv run` (the version regen needs `setuptools_scm`; the metrics script needs `click`+`pyeye`). The file-vs-branch guard reads **`PRE_COMMIT_CHECKOUT_TYPE`** (`"0"`=file checkout → skip), NOT git's positional `$3` — verified in pre-commit's source that it consumes git's args and re-exports them as env vars, so a hand-rolled `$3` guard would never fire under pre-commit. Both hooks are failure-tolerant (always exit 0) so a refresh/metrics hiccup can never block a pull or checkout. Rejected: a committed `.githooks/` + `core.hooksPath` (duplicates the mechanism pre-commit already owns here) and bare `python` like the stdlib-only `decision-log-nudge` (these scripts need the venv).
**Anchor:** `scripts.refresh_version.should_run` / `.main`; `scripts.dogfooding_metrics._extract_issue` / `._current_branch` / `start-on-checkout` command; `refresh-version-file` + `start-metrics-session` hooks and `default_install_hook_types` in `.pre-commit-config.yaml`; #462.
**Verify:** gold — `tests/test_precommit_hook_config.py` asserts `default_install_hook_types` contains `post-merge`/`post-checkout` and the two hooks' `stages`; `tests/test_refresh_version.py` asserts `should_run()` is False iff `PRE_COMMIT_CHECKOUT_TYPE=="0"` and `main()` shells out only when allowed and swallows failures; `tests/test_dogfooding_checkout.py` asserts branch→issue parsing and the same checkout-type guard on the `start-on-checkout` command. PARTIAL residue: that pre-commit actually exports `PRE_COMMIT_CHECKOUT_TYPE` (vs passing `$3`) is confirmed by reading pre-commit 4.3.0 `commands/run.py`/`hook_impl.py`, not pinned by a test in this repo.
