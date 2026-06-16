# Decision Log

Contract/invariant-significant, friction-driven decisions. Each entry is a small verifiable fact: Friction · Decision · Anchor (stable ref) · Verify (checkable or honestly-labelled). Newest on top. Maintained via the `decision-log` skill.

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
