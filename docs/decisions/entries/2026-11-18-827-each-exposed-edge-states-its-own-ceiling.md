---
date: "2026-11-18"
title: "Each edge a tool description exposes states its own ceiling, checked by the edge-ceiling rule (#827, C12)"
issues: [827, 818, 417, 825]
anchors: ["pyeye.docs_facts.rules.missing_edge_ceiling", "pyeye.docs_facts.rules.EDGE_CEILING", "pyeye.docs_facts.describe.ceiling_statement", "pyeye.mcp.server.expand", "pyeye.mcp.server.trace", "pyeye.mcp.server.outline", "tests/test_docs_facts_edge_ceiling.py"]
status: "active"
amends: ["2026-11-17-827-tool-descriptions-fill-fact-slots-from-load-time-extractors.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — Each edge a tool description exposes states its own ceiling, checked by the edge-ceiling rule (#827, C12)

**Friction:** #417's "Static-surface ceiling" marker guards only `members` and `subclasses`. The other edges' limits were stated unevenly or not at all:

- `expand` listed every ceiling meaning, but by ceiling ID, apart from the edges.
- `trace` walks nine edges and stated no edge's ceiling: its list of edges carried none.
- `outline` named its two ceiling IDs without their meanings.

An agent reading `trace` learned that a hop is "complete only over that edge's measured scope" without being told what that scope is. The maintainer's ruling C12 (option c): every tool description states the ceiling meaning of each edge it exposes, from that edge's `EDGE_CEILINGS` fact, with a check that no exposed edge lacks one.

**Decision:**

- **Two rules, one source.** The #417 marker rule stays as #825 and #847 derive it: the marker is required for edges whose ceiling is `static_definitions` or `literal_subclassing`. A second rule, `edge-ceiling`, covers every edge with any ceiling. A description that names an edge (as ``` ``edge`` ``` or `"edge"`) must state ``` ``<ceiling>``: <meaning> ```:
  - in the edge's own entry, when the description has one (`expand`'s bullets);
  - anywhere in the description, when it only lists or names the edge (`trace`, `outline`).

  Exact edges (`enclosing_scope`) are skipped. The rule scans the live tool descriptions only. Registered pages show ceilings through `edges.table` and `ceilings.table` blocks.
- **The slot and the check share one renderer.** `describe.ceiling_statement` builds the statement from the edge fact and its `ceiling.*` fact. The new `ceiling` form (inline, one edge) and `ceilings` form (block, an edge list) render it, and the rule looks for exactly that text. They can't disagree.
- **`ceilings` bullets read "On ``edge``: …".** A bullet that starts with the edge name is that edge's own entry to the #417 marker rule, and would have to carry the marker.
- **`expand`'s separate ceiling list is gone.** Each edge entry now states its ceiling, and the hand-written ceiling sentences in the `members`, `imported_by` and `subclasses` entries became slots. The marker phrase and the Django example stay as prose.

**Anchor:** `pyeye.docs_facts.rules.missing_edge_ceiling`; `pyeye.docs_facts.describe.ceiling_statement`; design C12; #827, #417, #825.
**Applies-to:**

- the rule: `pyeye.docs_facts.rules.missing_edge_ceiling`, `pyeye.docs_facts.rules.EDGE_CEILING`;
- the renderer and forms: `pyeye.docs_facts.describe.ceiling_statement`, `describe.FORMS` (`ceiling`, `ceilings`);
- the descriptions it governs: `pyeye.mcp.server.expand`, `pyeye.mcp.server.trace`, `pyeye.mcp.server.outline`, and any tool description that names an edge.

**Verify:** gold. `uv run pytest tests/test_docs_facts_edge_ceiling.py` passes:

- an entry without its ceiling is flagged, and one with it passes;
- a named edge needs its ceiling somewhere, and a `ceilings` slot satisfies it;
- exact edges and registered pages are skipped;
- every live description passes;
- `expand` and `trace` state every implemented edge's ceiling;
- `ceiling_statement` matches `EDGE_CEILINGS` and `CEILING_MEANINGS`.

Against `main` before this change, the rule flags 8 `expand` entries, 8 `trace` edges and 2 `outline` edges.
