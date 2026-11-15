---
date: "2026-11-16"
title: "A watcher start is followed by two catch-up sweeps; filtered_rglob prunes (#738)"
issues: [738, 715, 617, 517, 731]
anchors: ["pyeye.project_manager.ProjectManager._watch", "_schedule_catchup", "_catch_up", "_cancel_catchup", "CATCHUP_SWEEP_OFFSETS", "CATCHUP_MTIME_MARGIN_NS", "pyeye.async_utils.filtered_rglob"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — A watcher start is followed by two catch-up sweeps; filtered_rglob prunes (#738)

**Friction:** watchdog's `Observer.start()` returns before the emitter listens. On macOS, FSEvents snapshots the tree and only then starts its stream; on Windows the directory handle is opened on the emitter thread. A `.py` change made in that window was never delivered, so the caches kept the stale view (#715 hit it in the test suite).

**Decision:**

- `ProjectManager._watch` takes `started_ns` before `start()` and schedules two daemon-timer catch-up sweeps, at the watcher debounce + 0.5 s and + 5 s (`CATCHUP_SWEEP_OFFSETS`).
- Each sweep re-stats the root's `.py` files through `filtered_rglob` and invalidates those whose mtime is at or after the previous cutoff, exactly as a delivered batch would. The cutoff is the previous sweep's start (or `started_ns`) minus 2 s (`CATCHUP_MTIME_MARGIN_NS`), for coarse-mtime filesystems (#731).
- Two sweeps, because watchdog has no ready signal: the second catches a change made after the first sweep but before a slow emitter listened. Measuring each platform's start latency was rejected, since a margin tuned on CI says nothing about a loaded laptop.
- "Dirty once live" was rejected: inferring liveness needs a probe write into the user's tree or a first event that may never come.
- Sweeps run on timer threads, never on a tool call's path, and are cancelled on unwatch and cleanup.
- `filtered_rglob` prunes excluded directories during the walk instead of filtering after. The file set is identical, and it takes 27 ms instead of 0.9 s on pyeye, which keeps the sweep cheap.

**Anchor:** `pyeye.project_manager.ProjectManager._watch`, `_schedule_catchup`, `_catch_up`, `_cancel_catchup`, `CATCHUP_SWEEP_OFFSETS`, `CATCHUP_MTIME_MARGIN_NS`; `pyeye.async_utils.filtered_rglob`; #738, #715.
**Applies-to:**

- the sweep: `pyeye.project_manager.ProjectManager._watch`, `_schedule_catchup`, `_catch_up`, and the cancellation in `_unwatch_project` / `cleanup_all`;
- the walk: `pyeye.async_utils.filtered_rglob`, and so every project scan through it (`rglob_async`, the plugins, canonicalization, the sweep);
- the tests `tests/test_watcher_catchup_sweep.py` and `tests/test_filtered_rglob_prunes.py`.

**Verify:** gold. `uv run pytest tests/test_watcher_catchup_sweep.py tests/test_filtered_rglob_prunes.py` passes:

- with a watcher that never delivers, a file written right after start is picked up, and the control without sweeps is not;
- unchanged files and `.venv` files trigger nothing;
- cleanup cancels pending sweeps;
- a real observer delivers a file written immediately after start with no probe handshake;
- `filtered_rglob` returns the same paths as walk-then-filter for every caller pattern, and never enters a pruned directory.
