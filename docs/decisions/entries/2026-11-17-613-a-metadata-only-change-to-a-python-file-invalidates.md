---
date: "2026-11-17"
title: "A metadata-only change to a Python file invalidates, as a content change does (#613)"
issues: [613, 617, 738]
anchors: ["pyeye.cache.CodebaseWatcher.on_attrib", "pyeye.cache.CodebaseWatcher.on_modified"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — A metadata-only change to a Python file invalidates, as a content change does (#613)

**Friction:** watchdog 7 moved metadata-only changes (touch, `os.utime`, chmod) from `on_modified` to a new `on_attrib`. `CodebaseWatcher` had no `on_attrib`, so after the upgrade a `touch` of a `.py` file would silently stop invalidating anything.

**Decision:**

- `CodebaseWatcher.on_attrib` treats a file's attrib event exactly like `on_modified`: a `.py` file outside the ignored directories is queued and the debounce restarted.
- A directory's attrib event is ignored, like a directory "modified" event: it adds or removes no module.
- Kept rather than dropped because `touch` is how a user forces a re-index, the artifact caches key on mtime, and the catch-up sweep (#738) already treats a newer mtime as a change. Ignoring attrib would make the watcher disagree with the sweep.
- The cost is a spurious invalidation on chmod, which is rare and only costs a re-parse.
- `watchdog>=7.1` is the floor, because the handler relies on watchdog 7's event split.

**Anchor:** `pyeye.cache.CodebaseWatcher.on_attrib`, `pyeye.cache.CodebaseWatcher.on_modified`; #613.
**Applies-to:**

- the handler: `pyeye.cache.CodebaseWatcher.on_attrib` (beside `on_modified`, `on_created`, `on_deleted`, `on_moved`);
- the dependency floor in `pyproject.toml` (`watchdog>=7.1`);
- the tests in `tests/test_watcher_invalidation.py` (`TestWatcherEvents` attrib tests, `TestRealObserver.test_touching_an_existing_file_is_delivered`).

**Verify:** gold. `uv run pytest tests/test_watcher_invalidation.py -k "attrib or metadata or touching"` passes: a file attrib event reaches the callback (directly and through `dispatch`), directory / non-Python / ignored attrib events do not, and with a real observer and the sweeps disabled an mtime-only `os.utime` of an existing file is delivered.
