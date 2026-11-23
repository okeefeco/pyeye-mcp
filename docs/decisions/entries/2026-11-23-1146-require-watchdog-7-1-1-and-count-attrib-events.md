---
date: "2026-11-23"
title: "Require watchdog 7.1.1, which fixes its Windows reader; a metadata-only change invalidates (#1146)"
issues: [1146, 807, 613, 804]
anchors: ["pyeye.cache.CodebaseWatcher.on_attrib", "pyproject.toml watchdog pin", ".github/dependabot.yml", "tests.test_mcp_signal_shutdown.test_the_watcher_threads_are_daemons"]
status: "active"
amends: ["2026-11-17-807-stay-on-watchdog-6-until-its-windows-reader-is-fixed.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — Require watchdog 7.1.1, which fixes its Windows reader; a metadata-only change invalidates (#1146)

**Friction:** #807 capped watchdog below 7. 7.0-7.1.0's Windows reader starved event delivery under steady activity (gorakhargosh/watchdog#1469), and its non-daemon reader thread hung interpreter exit (gorakhargosh/watchdog#1470). 7.1.1 (2026-11-21) ships both fixes. Its `winapi.py` creates the reader with `threading.Thread(..., daemon=True)`, and `get_events` collects for `timeout` from the first buffer instead of waiting for a quiet `timeout`. #807's entry said to revisit the cap then, starting from #804's diff.

**Decision:** assigned by coordinator-3 (2026-11-23).

- **The pin** is `watchdog>=7.1.1,<8`. The floor is the first release with both Windows fixes. The cap is the next major, which may change event semantics again, as 7.0 did. `uv.lock` moves only watchdog, 6.0.0 → 7.1.1. Dependabot's watchdog semver-major ignore is removed. This amends #807's pin and ignore; #807's leak guard stays, because a leaked observer still holds an inotify instance or a directory handle.
- **Metadata-only changes count** (#804's #613 handler): watchdog 7 moved touch / `os.utime` / chmod from `on_modified` to `on_attrib`, so `CodebaseWatcher.on_attrib` treats a file's attrib event as `on_modified` does. A directory's attrib event is ignored, like a directory "modified". Kept because a touch is how a user forces a re-index, the artifact caches key on mtime, and the catch-up sweep (#738) already treats a newer mtime as a change. The cost is a spurious invalidation on chmod.
- **Windows is checked, not assumed:** `test_the_watcher_threads_are_daemons` is no longer skipped on Windows, so CI's Windows legs check #1470's fix. `serve_then_clean_up` still cleans up before `atexit` (#1124), which costs nothing.
- **Rejected:** keeping `<7`. 6.x gets no Windows fixes upstream, and #1469/#1470 were the only reasons for the cap.

**Anchor:** `pyeye.cache.CodebaseWatcher.on_attrib`; `pyproject.toml` (`watchdog>=7.1.1,<8`); `.github/dependabot.yml`; `tests.test_mcp_signal_shutdown.test_the_watcher_threads_are_daemons`; #1146, #807, #804.

**Applies-to:**

- the pin: the `watchdog` requirement in `pyproject.toml` and its specifier and version in `uv.lock`; the `uv` ecosystem entry in `.github/dependabot.yml` (no watchdog ignore);
- the handler: `pyeye.cache.CodebaseWatcher.on_attrib`, beside `on_modified`, `on_created`, `on_deleted` and `on_moved`;
- the Windows checks: `tests.test_mcp_signal_shutdown.test_the_watcher_threads_are_daemons` (every OS) and `tests/test_watcher_invalidation.py`'s real-observer tests on CI's Windows legs.

**Verify:** gold. `uv run pytest tests/test_watcher_invalidation.py tests/test_mcp_signal_shutdown.py tests/test_no_leaked_observers.py` passes on every CI leg:

- a file attrib event reaches the callback, directly and through `dispatch`;
- directory, non-Python and ignored attrib events don't;
- with a real observer and the sweeps disabled, an mtime-only `os.utime` is delivered;
- the watcher's threads are daemons, Windows included.

`grep '"watchdog>=7.1.1,<8"' pyproject.toml` matches. [Windows half needs CI's Windows legs.]
