---
date: "2026-11-20"
title: "subclasses and superclasses resolve a declared base one way; an ambiguous base is unresolved in both (#1057)"
issues: [1057, 452, 419, 624, 445]
anchors: ["pyeye.resolver.base_class_target", "pyeye._goto.pick_target", "pyeye.mcp.operations.edges.superclass_bases", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._resolve_base_to_key", "tests/test_edge_determinism.py"]
status: "active"
amends: ["2026-11-20-452-every-edge-declares-a-determinism-tier.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — subclasses and superclasses resolve a declared base one way; an ambiguous base is unresolved in both (#1057)

**Friction:**

- Measured on django, the class graph behind `subclasses` had a different key set in every fresh process (1336 or 1337 keys). The cause was `threading.local`, a standard-library try/except shim.
  - `expand("_threading_local.local", "subclasses")` returned 0, 1 or 2 of its two django subclasses, depending on the process.
  - `superclasses` of the same two classes was stable.
- A five-file project shim (`try: from ._fast import Local` / `except ImportError: from ._slow import Local`) flipped a *project* adjacency too, even across a rebuild in one process. #452's conformance test pinned this as a strict xfail plus a skip set, `_KNOWN_1057`.
- The cause: `JediAnalyzer._resolve_base_to_key`, the graph's fallback when the AST can't commit, took the first `script.goto` result with a `full_name`. For a shim, Jedi returns both branches, in an order that isn't stable. `superclass_bases` used the one goto policy (#624), so the two edges disagreed.

**Decision:** the maintainer's ruling, option A (relayed by coordinator-3, 2026-11-20).

- **One resolution of a declared base.** `pyeye.resolver.base_class_target(script, base)` does the following, in a lower layer that both callers can import:
  - unsubscripts the base (#921);
  - names no class for an expression that isn't a name or attribute (#922);
  - runs `goto_target(prefer="class")` at the rightmost identifier;
  - requires a class (#922);
  - refuses a restricted directory (#999).
  `superclass_bases` and the graph's goto fallback both call it. That makes the edges symmetric by construction: a child is under `subclasses(B)` exactly when `B` is in its `superclasses`.
- **An ambiguous base is unresolved.** There are two forms:
  - **A shim:** a name whose goto gives two different classes, as a try/except shim does. `ShimChild` is in neither `Local`'s subclasses, and `superclasses` lists `Local` in `unresolved_superclasses`.
  - **A rebinding:** a name bound at two places in one file, such as an if/else. On django, `if is_psycopg3: class Cursor` / `else: Cursor = psycopg2.extensions.cursor` makes `MyCursor`'s base unresolved, rather than the class branch.

  Two definitions in different files under one `full_name` are one class (a `.pyi` stub and its `.py` source), not a rebinding (coordinator-3's refinement). `threading.local` has a single class target, so `ThreadState` is under `_threading_local.local` in every process.
- **The goto policy picks independently of order** (#624, `_goto.pick_target`). Of several results with one `full_name`, the representative is the `prefer` type, then the earliest by file and position. Before, it was the first returned, and Jedi's order differs between processes: django's `Cursor` base resolved in one seed and not in the next. This is strictly more deterministic for every caller.
- **No new field** (P2, coordinator-3). The `declared_bases` and `literal_subclassing` ceiling texts state the rule. The maintainer's ruling via designer (Q6) requires the `subclasses` ceiling to disclose that classes with an ambiguous base are not listed. The base-side `ambiguous_subclass_count` is deferred. The details field is #1065. A field naming a shim's candidates (`unresolved_superclass_details`, P1) is filed as a separate follow-up needing a design ruling. Option B, listing the child under both with a `conditional` marker, may come later as an addition.
- **Amends #452's entry:** the strict xfail is green and `_KNOWN_1057` is gone, along with its ratchet, so the rebuild and cross-process checks skip nothing. The goto tier's meaning drops the #1057 gap.
- **Behaviour change, accepted:** a base that the old first-result pick filed under one of several targets now goes under none. A base whose single goto target isn't a class is no longer keyed either, just as `superclasses` already refused it.

**Anchor:** `pyeye.resolver.base_class_target`; `pyeye.mcp.operations.edges.superclass_bases`; `pyeye.analyzers.jedi_analyzer.JediAnalyzer._resolve_base_to_key`; `pyeye.mcp.operations.edges.CEILING_MEANINGS` / `DETERMINISM_MEANINGS`; #1057, #452, #419, #624.

**Applies-to:** `pyeye.resolver.base_class_target`, `pyeye.resolver._rebound`, `pyeye._goto.pick_target`, `pyeye.mcp.operations.edges.superclass_bases`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._resolve_base_to_key`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._build_class_graph`.

**Verify:** gold. `uv run pytest tests/test_edge_determinism.py` passes with no xfail. It checks:

- `subclasses` and `superclasses` agree for `Widget`, `Gadget`, `ShimChild`, `ThreadState`, `CursorChild` and `LocalCursor`;
- over three rebuilds, both `Local` classes and the rebound `pkg.rebind.Cursor` have no subclasses, the shim and rebinding children list their base in `unresolved_superclasses`, and `_threading_local.local`'s subclasses are `["pkg.users.ThreadState"]`;
- the rebuild and two-seed cross-process checks pass with nothing skipped.

`uv run pytest tests/unit/mcp/operations/test_goto_policy.py` checks the rest:

- `pick_target` gives the same answer for either order of a rebound name's results;
- `base_class_target` refuses a same-file rebinding in either order, and keeps a stub plus its source resolved.

django, three fresh seeds: one class-graph digest.
