---
date: "2026-11-18"
title: "The server stops writing unified metrics; its documented surfaces become deprecated stubs (#943)"
issues: [943, 917, 914, 628, 749]
anchors: ["pyeye.unified_metrics.get_unified_collector", "pyeye.metrics_hook.track_mcp_operation", "pyeye.settings.DEPRECATED_ENV_VARS", "pyeye.settings.PerformanceSettings._get_str_env", "scripts/unified_metrics.py", "docs/UNIFIED_METRICS.md", "tests/unit/utils/test_unified_metrics_deprecated.py", "tests/test_mcp_shutdown_cleanup.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-23-1139-retire-the-dogfooding-adoption-metrics.md"]
superseded_by: []
---

## 2026-11-18 — The server stops writing unified metrics; its documented surfaces become deprecated stubs (#943)

**Friction:** The unified metrics store was write-only in practice.

- Every MCP tool call paid a locked whole-file rewrite of `~/.pyeye/metrics/active_sessions.json`. That was about 2 ms after #917's prototype fix, and it grew with every call without it: 11.2 ms at 4,000 calls in one session, and 1.29 MB on dev01 (#914).
- Its only shipped reader, `scripts/unified_metrics.py`, failed on import for every command (a relative import loaded by path). Its `dashboard` called a missing method and its `cleanup` was a stub.
- Nothing outside tests called `record_grep_operation` or `update_cache_stats`, and nothing set `PYEYE_PARENT_SESSION`. So the grep, cache, "adoption" and subagent data were always empty.
- `mcp-report` and `mcp-logs` read the Claude Code hooks' own files, not this store.

**Decision:** This is the maintainer ruling of 2026-11-18, given via the designer, per #628 option (a). This entry is its record.

- **The server stops writing.** No session is opened at start-up or ended at shutdown, and `track_mcp_operation` no longer records calls. It still feeds connection diagnostics and the error tracker, which `get_connection_diagnostics` and the shutdown summary read.
- **Documented surfaces become deprecated stubs (warn plus no-op).** `pyeye.unified_metrics.get_unified_collector()` emits a `DeprecationWarning` (`stacklevel=2`) and returns a collector that accepts the old calls and records nothing; it writes no files. `scripts/unified_metrics.py` prints a deprecation notice and exits 0. `docs/UNIFIED_METRICS.md` becomes a deprecation note and keeps its `DocEntry`. "Raise a `DeprecationWarning`" means *emit* it (coordinator's reading of the ruling), so existing callers don't crash.
- **The released environment variables become deprecated no-ops.** `PYEYE_ISSUE` and `PYEYE_PARENT_SESSION` go in `DEPRECATED_ENV_VARS` ("accepted and ignored; nothing records sessions any more"). `settings.py` loads them through a new `_get_str_env`, so they stay documented, on lines marked deprecated (#628).
- **Internals and the unreleased variable are deleted.** That covers the store implementation and its tests; the server, `__main__` and `metrics_hook` wiring; the test-suite redirect; and `PYEYE_METRICS_DIR`, which #918 added after v2.1.0 and which was never released. The `security.metrics_inputs` and `security.writes.metrics` facts go too, and `security.write_sites` shrinks.
- **Release classification:** patch-compatible (v2.1.1). Fragments are `943.removed.md` (the write side effect, the fewer write sites, and that the old files can be deleted) and `943.deprecated.md`. `scripts/changelog.py no-breaking` stays 0. Users' existing files are left on disk and documented as deletable.
- **Full removal** of the stubs and the two variables is tracked under #749.
- #917's bounded-timing fix and #914's store fixes are superseded. Neither has an entry to amend.

**Applies-to:**

- the deprecated stubs: `pyeye.unified_metrics.get_unified_collector`, `scripts/unified_metrics.py`, `docs/UNIFIED_METRICS.md`;
- the deprecated settings: `pyeye.settings.DEPRECATED_ENV_VARS`, `pyeye.settings.PerformanceSettings._get_str_env`, and the env extractor's `_KINDS` in `pyeye.docs_facts.extractors.env`;
- what no longer records: `pyeye.metrics_hook.track_mcp_operation`, `pyeye.mcp.__main__.cleanup`, `pyeye.mcp.__main__.main`;
- the security facts: `pyeye.docs_facts.extractors.security.extract`.

**Verify:** gold. `uv run pytest tests/unit/utils/test_unified_metrics_deprecated.py tests/test_mcp_shutdown_cleanup.py tests/test_docs_facts_security.py` passes. It checks that:

- `get_unified_collector` warns;
- its collector accepts every old call, returns empty results and writes nothing under a temporary HOME;
- the script exits 0 with a deprecation notice for every old subcommand;
- both variables are in `DEPRECATED_ENV_VARS`;
- a real `python -m pyeye.mcp` start and stop under a temporary HOME creates no `~/.pyeye/metrics`;
- the server and `__main__` no longer wire the store;
- `security.write_sites` names no `pyeye.unified_metrics` site, and the two metrics facts are gone.

`uv run python scripts/docs_facts.py check` passes, with both variables marked deprecated in `docs/reference/env-vars.md`.
