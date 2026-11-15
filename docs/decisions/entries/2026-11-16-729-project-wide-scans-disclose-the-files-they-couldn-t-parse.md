---
date: "2026-11-16"
title: "Project-wide scans disclose the files they couldn't parse: unparseable_files on subclasses and imported_by (#729)"
issues: [729, 703, 668, 704, 435]
anchors: ["pyeye.analyzers.jedi_analyzer._parse_or_record", "pyeye.analyzers.project_graph.ClassGraph", "pyeye.analyzers.project_graph.ImportGraph", "pyeye.analyzers.project_graph.get_index_unparseable", "pyeye.mcp.operations.edges.EdgeResult", "pyeye.mcp.operations.resolve._unparseable_note"]
status: "active"
amends: ["2026-11-16-703-a-parse-failure-is-unsupported-or-omitted-never-measured-empty.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Project-wide scans disclose the files they couldn't parse: unparseable_files on subclasses and imported_by (#729)

**Friction:** #703 made a source whose *own* file doesn't parse report `unparseable`. It left a residue: the project-wide AST scans skipped any *other* file that didn't parse, and said nothing.

- A subclass defined in a file using newer syntax than the server's interpreter vanished from `expand(Base, "subclasses")`, which still answered a confident list.
- An importer in such a file vanished from `imported_by`.
- A definition there was invisible to bare-name `resolve`, whose miss read as "no such name".

**Decision:**

- **Record, never drop.** Each project-wide build records the files that raise `SyntaxError` when parsed (the same mapping as #703's `parse_own_source`), as POSIX paths, on the cached artefact: `ClassGraph.unparseable`, `ImportGraph.unparseable`, and the name index's unparseable list. Any other exception keeps its existing handling, and is never relabelled as a parse gap (#704). The one helper for the class and import scans is `jedi_analyzer._parse_or_record`.
- **`unparseable_files` on the reverse scans**, mirroring #668's `unresolved_importers` exactly, so #435's completeness envelope inherits one pattern:
  - on `expand`, a flat POSIX list for `subclasses` and `imported_by` only: `[]` when every file parsed, absent on every other edge;
  - on `trace`, a `{handle: [file, ...]}` map, present iff `subclasses` or `imported_by` was walked on some node, with zero-loss nodes omitted. A node walked on both edges gets the union.
- **Bare-name `resolve`: `detail` only.** On a miss, `detail` names the count of unparseable project files, one example, and the server's Python version. A field on every bare-name result is left to #435's envelope.
- Rejected: folding these files into `unresolved_importers`. That field means "an importer with no module name", which is a fact about a file the scan did read. A second field keeps the meanings apart.
- Rejected: a new not-found reason for `resolve`. The miss is still `unresolved`; only its explanation changes.
- Fragment category `Fixed`: the response contract was already "never silently incomplete", so this is an addition, and v2.x-safe.

**Anchor:** `pyeye.analyzers.jedi_analyzer._parse_or_record`; `project_graph.ClassGraph` / `ImportGraph` / `get_index_unparseable`; `edges.EdgeResult.unparseable_files`; `resolve._unparseable_note`; response linter E.8 / T.11; #729, #703, #668, #704, #435.
**Applies-to:**

- the builders: `JediAnalyzer._class_inventory` / `_build_class_graph` (the `subclasses` edge and `find_subclasses`), `JediAnalyzer._build_import_graph` / `find_importers` (`imported_by`), and `project_graph._build_indices` (the bare-name name and member indices);
- the edges: `edges.resolve_subclasses` and `edges.resolve_imported_by`, through `EdgeResult.unparseable_files`;
- the surfaces: `expand.expand_resolved`, `trace.trace` (`_record_hop_losses`), `resolve._resolve_bare_name` / `resolve.resolve` (the miss `detail`), the `expand` / `trace` tool descriptions in `pyeye.mcp.server`, and the python-explore skill's honesty fields;
- the conformance linter rules E.8 and T.11.

**Verify:** gold. `uv run pytest tests/integration/test_unparseable_files.py tests/unit/analyzers/test_parse_or_record.py tests/unit/analyzers/test_project_graph.py tests/conformance/test_linter_adversarial_expand.py tests/conformance/test_linter_adversarial_trace.py` passes:

- a project with a file that is a `SyntaxError` on every Python: `expand(Base, "subclasses")` and `expand(mod, "imported_by")` still list the parseable adjacents and list that file in `unparseable_files`;
- a clean project gives `[]`, and `members` / `imports` / `superclasses` never carry the field;
- `trace` carries it per walked node, and absent when neither edge was walked;
- a bare-name miss names the count and the server's Python version, and a clean project keeps the default `detail`;
- `_parse_or_record` maps only `SyntaxError`, and any other failure propagates;
- the index's unparseable list is cached and invalidated with the index;
- E.8 / T.11 reject the field elsewhere and malformed values.
