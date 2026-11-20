---
date: "2026-11-20"
title: "A cached Jedi script's all-scope names are read once and reused (#1044)"
issues: [1044, 713, 1024]
anchors: ["pyeye.file_artifact_cache.FileArtifactCache.get_all_scope_names", "pyeye.file_artifact_cache.get_all_scope_names", "pyeye.resolver._place_definition", "pyeye.resolver._anchor_at_stdlib_definition", "pyeye.mcp.operations.edges._class_members", "tests/test_all_scope_names_cached.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A cached Jedi script's all-scope names are read once and reused (#1044)

**Friction:** #1024's django round trip, `resolve_at` then `resolve` for each function-local class, was OOM-killed at a 2 GB cap after about 1,400 pairs, and again at 3 GB. The script cap (#713) bounded the number of Jedi inference states, but not their size. A census found each state's `module_cache` held one module, while its `memoize_cache` grew from 27k entries in total at 200 pairs to 627k at 1,200, with one state holding 251k. On one file the cause showed in plain Jedi: every `Script.get_names(all_scopes=True, definitions=True, references=False)` on the same Script adds one `CachedMetaClass` entry (a `ClassValue`) per class that is defined inside a method and has an assignment in its body. Those entries are keyed on contexts rebuilt each call, so they're never hit again. pyeye made that call per request, on long-lived cached Scripts, at three sites.

**Decision:** approved by coordinator-3 (2026-11-20).

- **Read once per cached Script.** `file_artifact_cache.get_all_scope_names(path, project)` makes the call once per cached Script and returns the same tuple for that Script's lifetime. A tuple can't be mutated by the callers that share it. The names are held in a `WeakKeyDictionary` keyed by the Script, so an evicted or invalidated Script frees them with no bookkeeping in the eviction paths. A new file version gets a new Script, and so new names. Like every Jedi call, it runs on the Jedi worker thread.
- **The three callers use it:** `pyeye.resolver._place_definition` (definition placement), `pyeye.resolver._anchor_at_stdlib_definition` (the anchor lookup) and `pyeye.mcp.operations.edges._class_members` (members). A fitness test fails if any other code calls `get_names` with `all_scopes` anything but `False`.
- **Upstream:** a minimal plain-Jedi repro (Jedi 0.20.1) was written up for the user to decide whether to report it; nothing was filed.
- **Measured on dev01** (django `cd385e6b8c`, 2 GB cap):

  | measure | before | after |
  |---|---|---|
  | #1024's round trip | OOM after ~1,400 pairs | all 2,267 pairs, ending at 419 MB |
  | RSS at 1,200 pairs | 1,646 MB | 280 MB |
  | memoised entries at 1,200 pairs | 626,543 | 11,018 |
  | time for 1,200 pairs | 287.8 s | 74.6 s |
  | 3,000-call `resolve_at` sweep, final RSS | 391 MB | 383 MB |
  | 3,000-call `resolve_at` sweep, time | 105.1 s | 66.7 s |

**Anchor:** `pyeye.file_artifact_cache.get_all_scope_names`; `tests/test_all_scope_names_cached.py`; #1044.

**Applies-to:**

- `pyeye.file_artifact_cache.FileArtifactCache.get_all_scope_names` and `pyeye.file_artifact_cache.get_all_scope_names`;
- its callers: `pyeye.resolver._place_definition`, `pyeye.resolver._anchor_at_stdlib_definition` and `pyeye.mcp.operations.edges._class_members`;
- every future reader of a cached Script's all-scope names (the fitness test);
- `docs/architecture/caching.md` (the parsed-file cache paragraph).

**Verify:** gold — `uv run pytest tests/test_all_scope_names_cached.py` passes. It checks:

- one Script gives back the same tuple;
- reading it again doesn't grow the inference state;
- plain Jedi does grow (the bug is real);
- an edited file gets new names;
- an evicted or invalidated Script's names are freed;
- repeated round trips on one file keep the state flat;
- no other code reads all-scope names directly.
