---
date: "2026-11-16"
title: "The resolved class graph is cached per project, layout, scope and generation, and dropped whole on any change (#397)"
issues: [397, 617, 618, 713]
anchors: ["pyeye.analyzers.project_graph.get_class_graph", "pyeye.analyzers.project_graph.ClassGraph", "pyeye.analyzers.project_graph.invalidate", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.find_subclasses", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._build_class_graph", "tests/unit/analyzers/test_class_graph_cache.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — The resolved class graph is cached per project, layout, scope and generation, and dropped whole on any change (#397)

**Friction:** `expand(handle, "subclasses")`, and every hop of `trace(follow=["subclasses"])`, rebuilt the project's resolved class graph from scratch and then discarded it. The build is AST-first base resolution with Jedi `goto` fallbacks. The work is identical whatever class is asked about. On the pyeye repo (471 files), 11 queries took about 16 s, ten of them pure rebuilds. On Django-sized projects one build takes minutes, so a multi-hop trace was unusable. The obvious alternative is an incrementally patched index (#397's Option C). It needs a populated cross-file dependency cascade, which doesn't exist (#397's comments). Patching a live index wrongly would ship stale edges, breaking absence-vs-zero.

**Decision:**

- **Where it lives:** `find_subclasses` (FQN input) reads a `ClassGraph` from `pyeye.analyzers.project_graph.get_class_graph`, the store that already holds the name index. The graph holds every class's facts (name, file, line span, column) and its children bucketed under each base's definition-site key. It also holds the AST import, define and star tables, so a query target is keyed exactly as bases were.
- **Key:** `(normalised root, layout_key, scope)`.
  - `layout_key` follows #618: module names and base resolution depend on the layout.
  - **Scope is in the key** rather than filtered at lookup. Which modules' import tables are in the build decides which bases resolve, so a wider build filtered later could change answers.
- **Lifecycle:** the name index's (#617).
  - Snapshot `project_graph.generation` before listing files, and cache the build only if the generation is unchanged. A raced build is returned, not cached.
  - `project_graph.invalidate` drops every class graph of the project. It is already called by the watcher (`_on_files_changed`, on every layout root), project eviction and `configure_packages`.
  - **Coarse:** any change drops the whole graph. A dropped graph is rebuilt, never reported empty.
- **Threading:** builds are single-flight under a per-key lock, not the store lock, so a long build doesn't block other projects' lookups. The build runs on the caller's thread, because it calls Jedi, which must stay on the Jedi worker.
- **Contents:** strings and ints only, never AST nodes or Jedi/parso objects. A cached graph pins neither the AST LRU nor parso's unbounded parse cache (#713). One build per generation instead of one per query also means fewer Jedi Scripts, which reduces #713's growth.
- **Not changed:** the simple-name (ambiguous) path has no production caller and stays uncached.
- **Rejected:**
  - Caching answers per target (Option A): the cost is the shared build, not the per-target lookup.
  - Incremental per-file patching (Option C): there's no dependency cascade to drive it, and stale-edge risk.
  - Building whole-project and filtering scope at lookup: answers could change.

**Anchor:** `pyeye.analyzers.project_graph.get_class_graph` / `ClassGraph` / `invalidate`; `JediAnalyzer.find_subclasses` / `_build_class_graph` / `_direct_children`; `tests/unit/analyzers/test_class_graph_cache.py`; #397, #617, #618, #713.

**Applies-to:**

- The `subclasses` edge (`pyeye.mcp.operations.edges.resolve_subclasses`), and through it `trace(follow=["subclasses"])`, via `JediAnalyzer.find_subclasses` with a FQN.
- Any future reader of the class graph, such as #664's Pydantic model discovery or #726's `edge_counts` count, must read it through `get_class_graph` and never build its own copy.
- The `imported_by` import graph (#397 slice 2) must follow the same key and lifecycle.

**Verify:** gold — `uv run pytest tests/unit/analyzers/test_class_graph_cache.py` passes. It checks:

- **Built once per generation:** `_build_class_graph` is called once for three queries.
- **Same answer, warm or cold:** for every class in the four subclasses fixtures, the edge's stubs (handle, line span, order) after a fresh build equal the warm answer.
- **Invalidation:** after `invalidate`, an added subclass appears. Invalidating another project keeps this graph.
- **Raced build:** a build during which `invalidate` lands is returned but not cached.
- **Keying:** separate graphs per layout and scope; root spellings share one.
- **Compactness:** no `ast.AST` (or anything but str, int, Path and containers) in a built graph.
- **Timing:** warm `find_subclasses` stays under a `PerformanceThresholds` bound.
