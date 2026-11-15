---
date: "2026-11-16"
title: "imported_by reads a cached reverse import graph, built once per project, layout, scope and generation (#397)"
issues: [397, 668, 619, 436, 343]
anchors: ["pyeye.analyzers.project_graph.get_import_graph", "pyeye.analyzers.project_graph.ImportGraph", "pyeye.analyzers.jedi_analyzer.JediAnalyzer.find_importers", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._build_import_graph", "tests/unit/analyzers/test_import_graph_cache.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — imported_by reads a cached reverse import graph, built once per project, layout, scope and generation (#397)

**Friction:** `expand(module, "imported_by")` re-scanned every project file for each target: it read each file's text, applied a pre-filter, then ran the authoritative AST check. On the pyeye repo (470 files) every query cost about 1.5 s, and every `imported_by` hop of a `trace` paid it again. The answer for every target comes from the same per-file facts, so the scan was redone for nothing.

**Decision:**

- **Where it lives:** `find_importers` reads an `ImportGraph` from `pyeye.analyzers.project_graph.get_import_graph`. That's the same store, key `(root, layout_key, scope)`, generation pinning, `invalidate` and per-key single-flight as the class graph (#397 slice 1's entry). The store holds both graphs, keyed by kind.
- **The graph inverts the old AST match exactly.** For each file it registers every dotted prefix of each `import` and of each resolved `from` clause, plus `<resolved>.<name>` for each `from <pkg> import <name>` (#436). That is exactly the old `alias == T or startswith(T + ".")` and `resolved == T or startswith(T + ".")` match, so a lookup is a dict read.
  - Relative imports resolve against the importer's module (#343).
  - A file with no module name registers only its absolute imports, and is reported as unnamed (#668).
  - Imports anywhere in the file count, function bodies included (#619's deliberate asymmetry with `imports`).
  - Entries keep POSIX-sorted file order, one per file, so ordering and "first occurrence wins" are unchanged. The target's own file is skipped at lookup.
- **The text pre-filter is gone.** It only saved parses in front of the authoritative AST check, and a target-independent graph can't use a target-specific filter.
- **Cost trade:** the cold build parses every file, so the first query in a generation costs about 1.2–1.9× the old single scan. Every later query is a lookup. It breaks even at the second query.
- **Contents:** strings, `Path`s and `None` only, never AST objects.
- **Rejected:**
  - Caching answers per target: the shared scan is the cost, not the per-target lookup.
  - Keeping a pre-filtered per-target scan with only the parse cached: still O(project) text reads per query.

**Anchor:** `pyeye.analyzers.project_graph.get_import_graph` / `ImportGraph`; `JediAnalyzer.find_importers` / `_build_import_graph`; `tests/unit/analyzers/test_import_graph_cache.py`; #397, #668, #619, #436, #343.

**Applies-to:**

- The `imported_by` edge (`pyeye.mcp.operations.edges.resolve_imported_by`), and through it `trace(follow=["imported_by"])`, via `JediAnalyzer.find_importers`.
- Any future reader of reverse imports must read this graph through `get_import_graph` rather than scanning files.
- `imports` is a forward edge over the module's own file and stays as it is.

**Verify:** gold — `uv run pytest tests/unit/analyzers/test_import_graph_cache.py` passes. It checks:

- **Equivalence:** the graph's `Importers` equal a verbatim copy of the old scan (pre-filter + AST) for every module of #619's import-forms corpus and #668's unnamed corpus, and for 13 modules of the pyeye repo, including the busiest.
- **#668:** `unresolved_importers` lists both unnamed importers, cold and warm.
- **#619:** function- and class-body imports count for `imported_by`, not `imports`, cold and warm.
- **Lifecycle:** one build for four queries; an added importer appears only after `invalidate`; a module never reports itself; the class and import graphs are separate entries and both are dropped by `invalidate`.
- **Compactness and timing:** no AST objects; a warm lookup stays under a `PerformanceThresholds` bound.
