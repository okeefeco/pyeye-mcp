---
date: "2026-11-16"
title: "parso's parse cache is bounded; eviction is made harmless by recovering in Jedi's two readers (#713)"
issues: [713, 684, 706]
anchors: ["pyeye._parso_cache.apply_parso_cache_policy", "pyeye._parso_cache._install_recovery", "pyeye._parso_cache._set_cache_item_lru", "pyeye.settings.PerformanceSettings.parso_cache_max_entries", "jedi.inference.filters.get_parso_cache_node", "jedi.parser_utils.get_cached_code_lines", "parso.cache._set_cache_item", "tests/unit/test_parso_cache_gc.py"]
status: "amended"
amends: ["2026-11-15-684-parso-s-in-memory-parse-cache-is-never-garbage-collected.md"]
supersedes: []
amended_by: ["2026-11-16-713-cached-jedi-scripts-have-their-own-cap-it-is-what-bounds.md", "2026-11-16-783-a-jedi-filter-uses-parso-s-cache-node-only-when-it-is-its-own-tree.md"]
superseded_by: []
---

## 2026-11-16 — parso's parse cache is bounded; eviction is made harmless by recovering in Jedi's two readers (#713)

**Friction:** #706 fixed #684 by never evicting from `parso.cache.parser_cache`, which left it unbounded at about 0.35–0.45 MB per resident parse tree: +1,049 MB for 3,000 files. #706 rejected recovering from a missing entry by re-parsing, because new nodes wouldn't match the ones Jedi's context holds. That rejection is right, but recovery doesn't need a re-parse. Jedi reads an entry back in exactly two places, and neither needs the cached node itself:

- `_AbstractUsedNamesFilter` (`jedi.inference.filters`) uses it **only** as the key of a weak memo of definition names. `_get_definition_names` already computes the same names, from the module's own tree, when the key is `None`.
- `get_cached_code_lines` (bound by name in five Jedi modules) uses only its source lines.

**Decision:**

- **Recovery:** `pyeye._parso_cache._install_recovery` rebinds both readers.
  - A missing entry gives the filter `None`. That's an identical answer from Jedi's own nodes, with no memo.
  - Missing code lines are re-read and split exactly as parso does (`python_bytes_to_unicode` + `split_lines(keepends=True)`).
  - Nothing is re-parsed.
- **Bound:** `parso.cache._set_cache_item` is replaced by an LRU (`_set_cache_item_lru`).
  - It stamps `last_used` with the **parse time**, not the file mtime (the #684 bug). parso already refreshes `last_used` on a hit.
  - Over `PYEYE_PARSO_CACHE_MAX_ENTRIES` (default 600), it evicts least-recently-used entries down to 90% of the cap.
  - `_CACHED_SIZE_TRIGGER` stays `sys.maxsize`, so parso's own GC never runs.
- **One place, as in #706:** `apply_parso_cache_policy`, called from `pyeye/__init__.py`. It's idempotent: wrappers are marked and never double-wrapped.
  - The LRU is installed at once.
  - **Importing pyeye must not import Jedi** (#623's layering keeps modules such as `pyeye.project_layout` Jedi-free at import time). So recovery is installed at once only if Jedi is already imported. Otherwise a one-shot `sys.meta_path` finder (`_RecoverAfterJediImport`) installs it as soon as `import jedi` finishes, before anything can use Jedi. `import jedi` loads every module recovery patches.
- **Measured:**
  - Under a policy where every insert evicts every entry, the full suite passes with recovery (3,649 passed); without it, #706's 5 resolution files fail 110 tests.
  - #706's 13 resolution tests pass under a forced bound of ONE entry, and all 10 of those fail when recovery is disabled.
  - W1 (#706's workload): +1,049 MB → +349 MB at a cap of 600.
- **Limit:** trees that a cached `jedi.Script` still uses stay alive however small the cap. In realistic pyeye use, the Script store is the other half of the bound (#713, PR 2).
- **Rejected:**
  - Re-parsing a missing entry (#706's reason stands).
  - Resetting `last_used` alone (a Script idle for over 10 minutes still lost its modules).
  - A finite trigger without recovery (fails past the limit, i.e. #684 again).

**Anchor:** `pyeye._parso_cache.apply_parso_cache_policy` / `_install_recovery` / `_set_cache_item_lru`; `PerformanceSettings.parso_cache_max_entries`; Jedi's `jedi.inference.filters.get_parso_cache_node` and the five `get_cached_code_lines` bindings; parso's `parso.cache._set_cache_item`; `tests/unit/test_parso_cache_gc.py`; #713, #684, #706.

**Applies-to:**

- the setup site, `pyeye._parso_cache.apply_parso_cache_policy` and its call in `pyeye/__init__.py`;
- the pinned internals and their guard tests in `tests/unit/test_parso_cache_gc.py` (`TestPinnedInternals`);
- every Jedi consumer in the process, which inherits the policy: `pyeye.resolver`, `pyeye.file_artifact_cache`, the operations and the plugins.
- A Jedi or parso upgrade must re-check `_CODE_LINES_MODULES` / `_FILTER_MODULE` against the new sources. The constraints recorded in #706's entry still hold (`jedi>=0.19.0`; jedi 0.20.1 → `parso>=0.8.7,<0.9`).

**Verify:** gold — `uv run pytest tests/unit/test_parso_cache_gc.py` passes. It checks:

- every patched internal exists and is wrapped;
- `_get_definition_names(None, …)` equals the memoised answer;
- missing code lines are re-read identically;
- the LRU stamps the parse time, evicts the least recently used first and never exceeds its cap;
- #706's 13 resolution tests pass under both the over-the-cap filler and a bound of one entry. With recovery disabled, the bound-of-one cases fail.
