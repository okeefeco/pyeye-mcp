---
date: "2026-11-15"
title: "parso's in-memory parse cache is never garbage-collected (#684)"
issues: [684, 457, 650]
anchors: ["pyeye._parso_cache.disable_parso_cache_gc", "pyeye.__init__", "parso.cache._CACHED_SIZE_TRIGGER", "jedi.parser_utils.get_parso_cache_node"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — parso's in-memory parse cache is never garbage-collected (#684)

**Friction:** `asyncio.Queue`, `asyncio.queues.Queue` and `json.JSONDecoder` came back unresolved from `resolve`, `inspect` and canonicalization, but only in some full runs: every CI job, a fresh clone, and never an older worktree. The cause is parso, not pyeye's `file_artifact_cache`.

- Once `parso.cache.parser_cache` holds `_CACHED_SIZE_TRIGGER` (600) files, every insert first drops each entry whose `last_used` is more than 10 minutes old.
- parso 0.8.7 initialises `last_used` to the FILE's mtime, not the parse time. An old-mtime stdlib or typeshed file is dropped at the next insert after its own.
- Jedi still holds that module, and `jedi.parser_utils.get_parso_cache_node` raises `KeyError`. The resolver's `except Exception` reported it as "unresolved".
- A fresh checkout keeps 600+ recent-mtime project files in the cache, so a real project hits this in normal use.

**Decision:** pyeye sets `parso.cache._CACHED_SIZE_TRIGGER = sys.maxsize` ONCE, in `pyeye._parso_cache.disable_parso_cache_gc`, called from `pyeye/__init__.py`.

- Package import runs it before any pyeye module touches Jedi.
- The setting is module-global, so it covers the Jedi worker thread (#650).
- Correctness must not depend on cache size, the invariant #457 set for the name index.
- Trade-off: the cache is keyed by path and replaced on an mtime change, so memory is bounded by the distinct files Jedi parses, not by a count cap. That came to about 0.35 MB per resident file, measured on 3,000 site-packages files (about 1,050 MB vs about 345 MB with the GC).
- Rejected: resetting `last_used` to the parse time. A Script left in `file_artifact_cache` for more than 10 minutes would still lose its modules. Also rejected: catching the `KeyError` and re-parsing, because a new tree's nodes don't match the ones Jedi's context holds.
- Constraints: `pyproject.toml` requires only `jedi>=0.19.0`. parso is transitive; jedi 0.20.1 requires `parso>=0.8.7,<0.9`, and `uv.lock` pins 0.8.7. A parso 0.9 needs this re-checked.

**Anchor:** `pyeye._parso_cache.disable_parso_cache_gc`; the call in `pyeye/__init__.py`; parso private `parso.cache._CACHED_SIZE_TRIGGER`; `jedi.parser_utils.get_parso_cache_node`; #684.
**Applies-to:**

- the setup site, `pyeye._parso_cache.disable_parso_cache_gc` and its call in `pyeye/__init__.py`;
- the guard tests in `tests/unit/test_parso_cache_gc.py`;
- every Jedi consumer in the process, which inherits the policy: `pyeye.resolver`, `pyeye.file_artifact_cache`, the operations and the plugins.

**Verify:** gold. `uv run pytest tests/unit/test_parso_cache_gc.py` passes:

- `parso.cache` still has `_CACHED_SIZE_TRIGGER` and `parser_cache`, so a parso rename fails here;
- importing `pyeye` sets the trigger to at least `sys.maxsize`;
- with the real cache held over 600 fresh entries and the stdlib files evicted, `resolve_handle`, `resolve` and `inspect` still place `asyncio.Queue`, `asyncio.queues.Queue` and `json.JSONDecoder` as classes, and `outline("pathlib.Path")` keeps its nested containers `truncated: "external"`.

Without the call, 11 of those 13 tests fail.
