---
date: "2026-11-07"
title: "Local env setup uses `uv sync --frozen`, not bare `uv sync` (#573)"
issues: [573, 479, 481]
anchors: ["test_local_uv_sync_is_frozen", "tests/test_local_uv_sync_frozen.py", "setup.sh"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-07 — Local env setup uses `uv sync --frozen`, not bare `uv sync` (#573)

**Friction:** The lockfile-authoritative policy pinned the hooks (`uv run --frozen`, #479) and CI (`uv sync --locked`, #481), but local setup (setup.sh, CONTRIBUTING/TROUBLESHOOTING/Sphinx docs, `.claude/instructions`) still prescribed bare `uv sync`, which may re-resolve and rewrite `uv.lock`. That is the mirror failure mode of #479, left open on the one path every contributor and Claude session runs. Bare `uv sync` also invited the mistaken `--all-extras`, a no-op here because there are no extras (see the 2026-06-18 entry).
**Decision:** Local setup is `uv sync --frozen` (`--frozen --group docs` for docs builds): install exactly from the lock, never block, never rewrite it, so it works offline and behind a mirror. CI stays `--locked`, keeping the existing frozen-local / locked-CI split; drift is still caught there, and locally via `uv lock --check`. Rejected: `--locked` locally (needs re-resolution, so behind a mirror it can fail on a lock that is actually fine); `--all-extras` (no extras exist). This amends the 2026-06-18 entry's "bare `uv sync` is the canonical install".
**Anchor:** `test_local_uv_sync_is_frozen` in `tests/test_local_uv_sync_frozen.py`; `setup.sh`; CONTRIBUTING.md "Dependency lockfile policy"; #573, #479, #481.
**Verify:** gold — `uv run pytest tests/test_local_uv_sync_frozen.py` passes. `test_local_uv_sync_is_frozen` fails on any `uv sync` in setup.sh, CONTRIBUTING.md, DOCUMENTATION.md, docs/TROUBLESHOOTING.md, docs/RELEASE.md, docs/source/*.rst or .claude/instructions/*.md that lacks `--frozen`/`--locked`, unless the prose forbids it as "bare `uv sync`". `test_matcher` pins what counts as bare (flagged: `uv sync`, `uv sync --group docs`) versus pinned or forbidden-in-prose (accepted). The mirror claim is unverifiable in-repo (needs a mirror).
