---
date: "2026-11-23"
title: "The dogfooding adoption metrics are retired; #943's stubs stay until v3 (#1139)"
issues: [1139, 943, 749, 469, 879, 1130, 1140]
anchors: ["scripts/unified_metrics.py", "docs/UNIFIED_METRICS.md", "pyeye.unified_metrics.get_unified_collector", "tests/unit/utils/test_unified_metrics_deprecated.py", ".pre-commit-config.yaml"]
status: "active"
amends: ["2026-11-18-943-the-server-stops-writing-unified-metrics-documented-surfaces-are-deprecated-stubs.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — The dogfooding adoption metrics are retired; #943's stubs stay until v3 (#1139)

**Friction:** The adoption metrics didn't measure adoption.

- The monitoring wasn't installed on the dev box, so `mcp-report` reported nothing there.
- The grep count treated every search as a failure to use pyeye (#1138 narrowed it). `dogfooding_metrics.py`'s `mcp_ratio` couldn't see MCP calls at all (#879).
- Long-lived sessions ran stale pyeye servers, so "adoption" didn't exercise current code.
- The bugs found on 2026-11-23 came from external-codebase trials and coverage checks, not from metrics.
- The architecture rethink (#469) never reached a decision.

**Decision:** The maintainer ruled (2026-11-23) to retire them. Dogfooding continues as verification on real codebases (`pyeye-verify`, #1140) and as everyday use.

- **Removed (repository dev tooling, never in the wheel):**
  - `scripts/claude_hooks/`: the tracking hooks, `mcp_analytics`, `merge_hooks` and `setup_mcp_monitoring.sh`;
  - `scripts/dogfooding_metrics.py` and its `start-metrics-session` post-checkout hook;
  - the grep-tracking wrappers and setup scripts (`grep_tracker.sh`, `setup_grep_tracking.sh`, `mcp_wrapper.sh`, `setup_aliases.sh`, `setup_dogfooding.sh`);
  - `docs/DOGFOODING_INTEGRATION.md`, `docs/DOGFOODING_SETUP.md` and `docs/METRICS_BASELINE.md`, with their registry entries;
  - the tests of all of these.
- **Kept: #943's deprecated stubs.** `scripts/unified_metrics.py` and `docs/UNIFIED_METRICS.md` are documented 2.x surfaces, removed in v3 (#749), so `changelog.py no-breaking` stays 0. They no longer point at `mcp-report` or `scripts/claude_hooks/`. `pyeye.unified_metrics` is untouched.
- **Kept:** the `click` dev dependency, which the Flask plugin tests import directly.
- The installers wrote outside the repository: `~/.local/bin` grep wrappers that `exec` the deleted `grep_tracker.sh`, hook entries in `~/.claude/settings.json`, and `~/.claude/mcp_monitoring/`. The `1139.removed.md` fragment tells contributors how to undo each one. Nothing is uninstalled automatically.
- #1130's unreleased fragment loses its `mcp-report` bullet, since that tooling never ships.

**Anchor:** #1139; `scripts/unified_metrics.py`, `docs/UNIFIED_METRICS.md`, `.pre-commit-config.yaml`.

**Applies-to:**

- every adoption-metrics surface in the repository, all removed: the files listed above, the `start-metrics-session` pre-commit hook, and their `docs/facts/docs.toml` entries;
- the surfaces that stay: #943's stubs (`scripts/unified_metrics.py`, `docs/UNIFIED_METRICS.md`, `pyeye.unified_metrics.get_unified_collector`) until #749;
- the Claude instructions: the root `CLAUDE.md` "Dogfooding Metrics Tracking" section (removed) and `.claude/instructions/03-mcp-dogfooding.md` "Measuring Success" (now points at verification).

**Verify:** gold.

- `git ls-files scripts/claude_hooks scripts/dogfooding_metrics.py scripts/grep_tracker.sh scripts/setup_grep_tracking.sh scripts/mcp_wrapper.sh scripts/setup_aliases.sh scripts/setup_dogfooding.sh docs/DOGFOODING_INTEGRATION.md docs/DOGFOODING_SETUP.md docs/METRICS_BASELINE.md` prints nothing.
- `git grep -nE 'mcp-report|mcp-logs|claude_hooks|dogfooding_metrics' -- ':!CHANGELOG.md' ':!docs/audits' ':!docs/decisions' ':!docs/superpowers'` finds only the notes that record the retirement: `changes/1139.removed.md` and `docs/UNIFIED_METRICS.md`'s "Where MCP usage is measured now".
- `uv run pytest tests/unit/utils/test_unified_metrics_deprecated.py` passes, so the stubs still warn and exit 0.
- `python scripts/changelog.py no-breaking` prints 0.
