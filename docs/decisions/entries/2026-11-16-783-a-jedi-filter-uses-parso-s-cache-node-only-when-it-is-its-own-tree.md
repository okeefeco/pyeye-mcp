---
date: "2026-11-16"
title: "A Jedi filter uses parso's cache node only when it is its own tree: recovery covers a missing AND a mismatched entry (#783)"
issues: [783, 713, 774, 764]
anchors: ["pyeye._parso_cache._install_own_tree_guard", "pyeye._parso_cache._install_recovery", "jedi.inference.filters._AbstractUsedNamesFilter", "tests/unit/test_parso_cache_node_identity.py"]
status: "active"
amends: ["2026-11-16-713-parso-s-parse-cache-is-bounded-eviction-is-made-harmless-by.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — A Jedi filter uses parso's cache node only when it is its own tree: recovery covers a missing AND a mismatched entry (#783)

**Friction:** #713 made eviction harmless only for a **missing** entry. `jedi.inference.filters._AbstractUsedNamesFilter` takes parso's cache entry **by path** and keys two things on it: its definition-name memo, and `get_cached_parent_scope`. Its `_used_names`, however, come from the module's **own** tree. Once the LRU evicted a file and a Script under another project re-parsed it, the path named a new tree. A Script that was still cached (#764's cap keeps up to 200) then read the other parse's names and rejected them all as unreachable, so `goto` answered `[]`. That is a silent "unresolved", the outcome #713's bound promised never to bring back. #774's CI hit it on 3.13: `Premium(Widget)`'s base came back unresolved, depending on test order.

**Decision:**

- **An identity guard on the filter.** `_parso_cache._install_own_tree_guard` wraps `_AbstractUsedNamesFilter.__init__` once, marked and idempotent, installed with the rest of recovery (so the lazy Jedi-import hook covers it). After the original `__init__`, a present entry whose `.node` isn't `self._node_context.get_root_context().tree_node` becomes `None`. The filter then computes without its memo: the identical answer of #713's eviction path.
- **`node_or_none` stays.** A missing entry raises `KeyError` inside the original `__init__`, before the guard runs. The two cover missing and mismatched respectively.
- **One wrap covers every reader.** All 7 subclasses (`ParserTreeFilter`, `ClassFilter`, `GlobalNameFilter`, `_FunctionExecutionFilter`, `StubFilter`, `MixedParserTreeFilter`, `FixtureFilter`) reach it through `super().__init__`, and no other Jedi module takes the node by path. Both facts are pinned by tests.
- **No guard for `get_cached_code_lines`.** It reads only `.lines`, and its five callers read them right after parsing or loading the module.
- Rejected: evicting `file_artifact_cache` Scripts when parso evicts a path. That misses a long-lived Script whose inference loaded *another* module's tree.
- Rejected, as the fix: unbounded caps (#706's stopgap shape). Correctness is restored with the bound kept.
- Out of scope: parso's diff parser updates a cached module in place when file content changes. Identity is kept then, and it is triggered by edits, not by the caps.

**Anchor:** `pyeye._parso_cache._install_own_tree_guard` / `_install_recovery`; `jedi.inference.filters._AbstractUsedNamesFilter`; #783, #713, #774, #764.
**Applies-to:**

- the guard: `pyeye._parso_cache._install_own_tree_guard`, called from `_install_recovery` (so from `apply_parso_cache_policy` and `_RecoverAfterJediImport`);
- the pins: `tests/unit/test_parso_cache_node_identity.py` (`TestPinnedFilterInternals`) and the install-order probe in `tests/unit/test_parso_cache_gc.py`;
- every Jedi consumer in the process, which inherits it: `pyeye.resolver`, `pyeye.file_artifact_cache`, the operations and the plugins.
- A Jedi or parso upgrade must re-run the pins. They fail if the filter's `__init__` signature, its `_parso_cache_node` / `_node_context` attributes, `_NodeCacheItem.node`, the set of callers that take the node by path, or a subclass's `super().__init__` changes.

**Verify:** gold. `uv run pytest tests/unit/test_parso_cache_node_identity.py tests/unit/test_parso_cache_gc.py` passes. The regression runs #774's sequence with the default caps, and its red check (the guard unwrapped) reproduces `['Widget']`.
