---
date: "2026-11-16"
title: "Cached jedi.Scripts have their own cap; it is what bounds parse-tree memory (#713)"
issues: [713]
anchors: ["pyeye.file_artifact_cache.FileArtifactCache", "pyeye.file_artifact_cache.FileArtifactCache._enforce_ast_cap", "pyeye.settings.PerformanceSettings.script_cache_max_entries", "tests/unit/core/test_script_cache_cap.py"]
status: "active"
amends: ["2026-11-16-713-parso-s-parse-cache-is-bounded-eviction-is-made-harmless-by.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Cached jedi.Scripts have their own cap; it is what bounds parse-tree memory (#713)

**Friction:** #713 PR 1 bounded parso's parse cache, but in realistic pyeye use that barely moved memory. Each `jedi.Script` cached in `file_artifact_cache` owns a Jedi inference state that keeps every module it inferred alive, parse trees included, whatever parso's cache holds. Scripts shared the combined AST/Script cap (default 2,000) with ASTs, so hundreds of them stayed resident. W2 (#713: a 1,167-file project with the #397 graphs) held 692 Scripts and 1,179 live parse trees, with parso capped at 600.

**Decision:**

- `FileArtifactCache` takes a `script_max_entries` cap, by default `settings.script_cache_max_entries` (env `PYEYE_SCRIPT_CACHE_MAX_ENTRIES`, **default 200**). `_enforce_ast_cap` evicts least-recently-used Scripts over it, then enforces the combined cap as before (ASTs evicted first). An evicted Script is rebuilt on demand.
- **Why 200**, from W2 with PR 1's parso cap of 600 (serial, memory-capped runs, repeated for timing):

  | Script cap | Scripts | live parse trees | live RSS | wall time (2 runs) |
  |---|---|---|---|---|
  | none (today) | 692 | 1,179 | +1,491 MB | 168 s / 157 s |
  | 400 | 400 | 714–716 | +1,348–1,355 MB | 230 s / 160 s |
  | **200** | 200 | 555–557 | +1,181–1,193 MB | 192 s / 163 s |
  | 100 | 100 | 554 | +1,098 MB | 188 s |

  - At 200, live trees reach parso's own bound (about 555 of 600), so a smaller cap frees little: 100 saves another ~95 MB for twice the Script rebuilds.
  - The cost at 200 is about 4% wall time, within run-to-run noise.
  - Answers, subclass and resolve counts and the #684 canaries are identical in every row.
- **Not changed:** the combined cap. The rest of the resident memory is mostly stdlib `ast` trees (1,161 resident at about 0.56 MB each), the existing `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` lever. Changing its default is a separate decision.
- **Rejected:**
  - Lowering the combined cap instead: it trades ASTs (cheap to rebuild) for Scripts (expensive), the wrong way round.
  - A default of 100: little saving, more rebuilds.

**Anchor:** `pyeye.file_artifact_cache.FileArtifactCache` / `_enforce_ast_cap`; `PerformanceSettings.script_cache_max_entries`; `tests/unit/core/test_script_cache_cap.py`; #713.

**Applies-to:**

- `pyeye.file_artifact_cache.FileArtifactCache`, and through `get_script` every caller that builds Jedi Scripts: the resolver, the analyzer, the operations and the plugins.
- `PerformanceSettings.script_cache_max_entries` and its README row.

**Verify:** gold — `uv run pytest tests/unit/core/test_script_cache_cap.py` passes. It checks:

- Scripts never exceed their cap, and the least recently used goes first;
- an evicted Script is rebuilt with the same answers;
- ASTs aren't limited by the Script cap, and the combined cap still applies;
- the setting's default and override, and an explicit argument wins.
