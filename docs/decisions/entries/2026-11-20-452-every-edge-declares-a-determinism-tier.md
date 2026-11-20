---
date: "2026-11-20"
title: "Every edge declares a determinism tier, and one registry-driven test holds it to that tier (#452)"
issues: [452, 419, 445, 1057, 449]
anchors: ["pyeye.mcp.operations.edges.EDGE_DETERMINISM", "pyeye.mcp.operations.edges.DETERMINISM_MEANINGS", "tests/test_edge_determinism.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-20-1057-subclasses-and-superclasses-resolve-a-base-one-way.md"]
superseded_by: []
---

## 2026-11-20 — Every edge declares a determinism tier, and one registry-driven test holds it to that tier (#452)

**Friction:**

- The static-edge determinism invariant (`docs/architecture/resolution.md`) held for `imported_by` and `subclasses` only through each edge's own regression test. A new edge could re-derive its adjacents through Jedi (the #445 pattern) and no test would notice.
- The issue's two tiers (`ast` / `forward-goto`) didn't fit: `imports` is AST-enumerated but goto-resolved, and only its external targets flip between processes (#419).
- Measured before building (fresh processes, `PYTHONHASHSEED` varied): every edge was stable on `cross_tool` and on django, but django's class graph had 1336 or 1337 keys per run. That was `threading.local`'s stdlib try/except shim, and it reached `subclasses` output (#1057). A five-file fixture showed a *project* shim flipping `subclasses` too, even across a rebuild in one process.

**Decision:** the plan approved by coordinator-3, 2026-11-20.

- **Four tiers**, one per edge in `edges.EDGE_DETERMINISM` beside `EDGE_RESOLVERS`, each with its guarantee in `edges.DETERMINISM_MEANINGS`:
  - `filesystem` (`submodules`) and `ast` (`imported_by`, `re_exports`): no Jedi; fully stable.
  - `jedi_local` (`members`, `enclosing_scope`): Jedi on the source's own file; fully stable.
  - `goto` (`imports`, `callees`, `superclasses`, `subclasses`): project-scope adjacents stable; an external target behind a shim may differ (#419), declared rather than hidden.
- **Stated where agents read it.** The `goto` caveat, and the #1057 gap until it is fixed, are in the meanings. The meanings are rendered into the `expand` and `trace` descriptions (`<<fact:determinism.table:tiers>>`), the python-explore skill, `resolution.md` and the edges reference page (`determinism.table`), and each edge fact carries `determinism`.
- **One test, driven by the registry** (`tests/test_edge_determinism.py`, fixture `determinism_traps`):
  - every edge has a tier;
  - every edge repeats after all caches and indices are dropped;
  - `filesystem`/`ast` resolvers give the same adjacents with Jedi's lookups raising;
  - two fresh processes (seeds 0 and 1) agree on each tier's guaranteed part;
  - `subclasses` and `superclasses` agree.
  It runs in about 25 s; django stays a recorded scenario probe, not CI.
- **#1057's cases.** The project-shim symmetry failure is reliable, so it is a strict xfail. The stdlib-shim case agrees in some processes, so a strict xfail would pass by chance; it and the two shim bases are in `_KNOWN_1057`, skipped by the rebuild and cross-process checks. Fixing #1057 (ruled option A, 2026-11-20: a shim base is unresolved, the child is in neither list) turns the xfail green and empties the set.

**Anchor:** `pyeye.mcp.operations.edges.EDGE_DETERMINISM` / `DETERMINISM_MEANINGS`; `pyeye.docs_facts.extractors.edges.extract_code`; `pyeye.docs_facts.describe._render_tiers`; `tests/test_edge_determinism.py`; #452, #419, #445, #1057.

**Applies-to:**

- the registry: `pyeye.mcp.operations.edges.EDGE_DETERMINISM`, `pyeye.mcp.operations.edges.DETERMINISM_MEANINGS`;
- the facts and descriptions: `pyeye.docs_facts.extractors.edges.extract_code`, `pyeye.docs_facts.describe._render_tiers`, `pyeye.docs_facts.pages.edges_page`, `pyeye.mcp.server.expand`, `pyeye.mcp.server.trace`.

**Verify:** gold. `uv run pytest tests/test_edge_determinism.py` passes with exactly one xfail (`ShimChild`). Setting any `filesystem`/`ast` tier on a Jedi-using edge (e.g. `members` to `ast`) fails `test_filesystem_and_ast_edges_need_no_jedi` with `_JediCalled`. `uv run python scripts/docs_facts.py check` passes.
