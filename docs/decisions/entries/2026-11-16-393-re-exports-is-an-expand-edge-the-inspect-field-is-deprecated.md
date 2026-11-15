---
date: "2026-11-16"
title: "re_exports is an expand edge to the re-exporting module; the inspect field is deprecated, cached and kept (#393)"
issues: [393, 712, 729, 749, 704]
anchors: ["pyeye.mcp.operations.edges.resolve_re_exports", "pyeye.mcp.operations.edges.EdgeResult", "pyeye.canonicalization.re_export_scan", "pyeye.canonicalization.invalidate_re_exports"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — re_exports is an expand edge to the re-exporting module; the inspect field is deprecated, cached and kept (#393)

**Friction:** `inspect` computed `re_exports` eagerly: a whole-package AST scan on every node, the cost the old TODO(perf) flagged. It was the only relationship that wasn't an edge, so `trace` couldn't walk it. And the field had no way to say "incomplete": when a package file didn't parse, #704 left it absent.

**Decision:**

- **An edge, `expand(handle, "re_exports")`.** It applies to every kind except `module`, because a module is re-exported as itself. Like the other reverse scans, it is not counted in `edge_counts`.
- **The stub is the re-exporting MODULE, plus `bindings`.** A re-export path such as `pkg.api.X` is an alias of the symbol, not a handle of its own: resolving it canonicalises back to the definition. The module is a real handle. A module can bind the symbol under several names, and adjacents are deduplicated by handle, so `bindings` is a sorted LIST. This is the one place an edge stub carries an edge-specific field (`EdgeResult.stub_extras`).
- **"Public" is #712's definition**, from one scan shared by the edge and the field.
- **#729's shape for parse gaps.** The edge sets `unparseable_files` (`[]` when clean) and still lists every re-export found in the files that parsed. On `trace`, the edge joins the `{handle: [files]}` map. Only `SyntaxError` counts as unparseable (#704).
- **Ceiling `package_reexports` (#417).** The scan covers import bindings written in source in the public modules of the symbol's own package. Re-exports from other packages, and names a module's `__getattr__` provides lazily, are outside it.
- **The field: user option A.** Keep `inspect.re_exports` eager, deprecate it for removal in v3.0 (tracker #749), and serve it from the same cache, so a repeat call is free and the field and the edge never disagree. It stays absent on a parse gap, as before.
- **Cache.** The key is (project root, layout key, handle), bounded LRU, cleared per project by the file watcher and by `configure_packages`.
- Rejected: dropping the field now. v2.x removes nothing (#629).
- Rejected: a stub per re-export path. Those paths aren't handles, and `expand` on such a stub would land back on the source symbol.

**Anchor:** `edges.resolve_re_exports`; `edges.EdgeResult.stub_extras`; `canonicalization.re_export_scan` / `ReExportScan` / `invalidate_re_exports`; response linter E.8 / T.11; #393, #712, #729, #749.
**Applies-to:**

- the field: `inspect.inspect` (`re_exports`, deprecated), via `canonicalization.collect_re_exports`;
- the edge: `edges.resolve_re_exports`, `EDGE_APPLIES_TO["re_exports"]`, `expand.expand_resolved` (stub extras), `trace.trace` (`unparseable_files` map);
- the cache: `canonicalization.re_export_scan`, invalidated in `ProjectManager._on_files_changed` and `server.configure_packages`;
- the docs: the `expand` tool description in `pyeye.mcp.server` and the python-explore skill's edge table;
- the conformance linter rules E.8 and T.11.

**Verify:** gold. `uv run pytest tests/test_re_exports_edge.py tests/test_edge_applicability.py tests/test_python_explore_skill_conformance.py tests/conformance/` passes.
