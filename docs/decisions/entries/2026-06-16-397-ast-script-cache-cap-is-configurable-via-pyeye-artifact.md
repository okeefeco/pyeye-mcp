---
date: "2026-06-16"
title: "AST/Script cache cap is configurable via `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`"
issues: [397]
anchors: ["Settings.artifact_cache_max_entries", "FileArtifactCache.__init__"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-16 — AST/Script cache cap is configurable via `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`

**Friction:** The `file_artifact_cache` combined AST+Script LRU cap was hardcoded at 500. On large repos (hundreds of files / 10k+ classes) the working set exceeds it, so a repeated scan (e.g. `expand` `subclasses`) evicts its own entries mid-scan and the next identical call re-parses from disk — the cache silently stops helping. Reproduced: same call twice → same cost, with eviction count climbing.
**Decision:** Add `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` (default 500, min 1, max 1_000_000). `FileArtifactCache(ast_max_entries=None)` falls back to `settings.artifact_cache_max_entries`; an explicit constructor arg always wins (test isolation / targeted tuning). Rejected: hardcoded constant; auto-sizing to project file count (deferred — wants the eviction signal observed in the field first).
**Anchor:** `Settings.artifact_cache_max_entries` ; `FileArtifactCache.__init__` ; commit `0d7933d` ; #397
**Verify:** gold — `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=7 python -c "from pyeye import file_artifact_cache as f; assert f.FileArtifactCache()._ast_max_entries==7"`; covered by `tests/test_artifact_cache_configurable.py` (default-vs-explicit precedence) and `tests/unit/core/test_settings.py` (default/env/clamp).
