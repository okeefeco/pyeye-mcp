---
date: "2026-06-20"
title: "subclasses edge becomes single-hop (direct-only), conforming to the expand contract"
issues: [422]
anchors: ["resolve_subclasses", "SUBCLASSES_TRANSITIVE_HINT", "pyeye.mcp.operations.edges"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-20 — subclasses edge becomes single-hop (direct-only), conforming to the expand contract

**Friction:** expand(subclasses) returned the full transitive closure — the lone edge violating expand's "walk ONE edge to the IMMEDIATE neighbours" invariant (every other edge — members/callees/imports/imported_by/superclasses — is single-hop). It mistakenly broke progressive disclosure: on a widely-subclassed base (Django AltersData) the closure was 193 KB, overflowing the MCP token cap and inverting the cheap-by-default contract.
**Decision:** Make subclasses DIRECT-only (`include_indirect=False`), restoring the single-hop invariant and making it symmetric with superclasses. The transitive closure is served EXCLUSIVELY by `trace(follow=["subclasses"], …)`, which already owns the cap + `truncated` contract — this also fixes trace's per-hop BFS, which a closure-per-hop resolver had collapsed onto depth 1. expand(subclasses) carries a static `transitive_hint` pointer. Rejected: a `transitive=`/`depth=` flag on expand (would special-case one edge or reinvent trace, with two cap impls that drift). The counts-first direct count in `inspect.edge_counts` was NOT shipped — even a DIRECT subclass count is a reverse query (whole-project scan, same family as callers/references), deferred to #333/#397; the earlier "cheap, rides parent_to_children" premise was wrong (FQN input always builds the resolved_index).
**Anchor:** `resolve_subclasses` + `SUBCLASSES_TRANSITIVE_HINT` (`pyeye.mcp.operations.edges` / `.expand`); #422.
**Verify:** gold — over `tests/fixtures/subclasses_edge`: `expand("pkg.base.Animal","subclasses")` returns exactly {`pkg.middle.Mammal`, `script_animal.Lizard`}, excluding grandchild `pkg.middle.Dog`; `trace("pkg.base.Animal",["subclasses"],max_depth=1)` excludes Dog while `max_depth=2` includes it. (`test_edges.py` / `test_expand.py` / `test_trace.py`)
