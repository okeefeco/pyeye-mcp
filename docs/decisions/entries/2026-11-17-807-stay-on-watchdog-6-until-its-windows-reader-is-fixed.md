---
date: "2026-11-17"
title: "Stay on watchdog 6.x until its Windows reader is fixed; real observers never outlive a test (#807)"
issues: [807, 613, 617]
anchors: ["pyproject.toml watchdog pin", ".github/dependabot.yml watchdog ignore", "tests.conftest.pytest_sessionfinish", "tests.utils.watchers.live_observers"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-23-1146-require-watchdog-7-1-1-and-count-attrib-events.md"]
superseded_by: []
---

## 2026-11-17 — Stay on watchdog 6.x until its Windows reader is fixed; real observers never outlive a test (#807)

**Friction:** the 6.0 → 7.1 upgrade (#613, tried in #804) failed every Windows CI leg. watchdog 7's rewritten Windows reader (`watchdog/observers/winapi.py`, `DirectoryChangeReader`) has two problems:

- `get_events(timeout)` keeps draining until its queue has been quiet for `timeout` (1.0 s by default). Changes arriving less than 1 s apart, even into ignored directories, hold back every event until they stop (gorakhargosh/watchdog#1469).
- `BaseThread.start()` runs `on_thread_start()` in the caller's thread, and the reader's `threading.Thread` is created there with no daemon flag. Started from the main thread, it is non-daemon. One observer that is never stopped blocks interpreter shutdown, and that happens before `atexit` runs, so the server's atexit `cleanup_all()` can't help (gorakhargosh/watchdog#1470). Two module-scoped test fixtures leaked real observers, so pytest never exited.

**Decision:**

- Pin `watchdog>=3.0.0,<7` in `pyproject.toml`, so users don't install 7.x either, and make Dependabot ignore watchdog semver-major updates. Minor and patch 6.x updates still arrive.
- Rejected: staying on 7.x with workarounds (a shorter emitter timeout only narrows the starvation, and the exit hang needs either every observer stopped before shutdown or patching watchdog's internals), and a platform-conditional dependency (a forked lock and two event models to test).
- Both problems are reported upstream: gorakhargosh/watchdog#1469 and gorakhargosh/watchdog#1470.
- Test hygiene, valid on 6.x too: a module- or session-scoped fixture is set up before the autouse inert-Observer patch, so a `ProjectManager` it creates starts a REAL watcher and must `cleanup_all()` on teardown. `pytest_sessionfinish` fails the run if any real observer is still alive.
- Revisit the pin when gorakhargosh/watchdog#1469 and #1470 are fixed. The #804 diff (an `on_attrib` handler, needed because 7.0 moved touch/chmod to attrib events) is the starting point.

**Anchor:** `pyproject.toml` (`watchdog>=3.0.0,<7`); `.github/dependabot.yml` (`ignore: watchdog semver-major`); `tests.conftest.pytest_sessionfinish`; `tests.utils.watchers.live_observers`; #807, #804, #613.
**Applies-to:**

- the pin: the `watchdog` requirement in `pyproject.toml` and its specifier in `uv.lock`;
- the Dependabot ignore: the `uv` ecosystem entry in `.github/dependabot.yml`;
- the leak guard: `tests/conftest.py` (`pytest_sessionfinish`), `tests/utils/watchers.py`, `tests/test_no_leaked_observers.py`, and the module-scoped fixtures in `tests/unit/mcp/operations/test_goto_policy.py` and `tests/integration/test_multirepo_namespace_scenario.py`.

**Verify:** gold. `uv run pytest tests/test_no_leaked_observers.py` passes: a real observer started by a `real_watcher` test is reported by `live_observers()` until `cleanup_all()`, and the inert observer is never reported. A full run ends with no "watchdog observer(s) still running" error and exit 0. `grep 'watchdog>=3.0.0,<7' pyproject.toml` matches.
