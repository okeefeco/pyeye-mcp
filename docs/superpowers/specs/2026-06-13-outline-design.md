# Outline design — `outline(handle)` structural skeleton

**Date:** 2026-06-13
**Issue:** #355
**Status:** design (pre-implementation)
**Branch:** `feat/355-outline`

## 1. Context & goal

The redesigned pyeye API ships `resolve`/`resolve_at` (orient: "give me a handle"),
`inspect` (orient: "what is this?"), and the traversal primitives `expand` (single
hop) and `trace` (bounded BFS). `outline` is the **last unbuilt progressive-disclosure
primitive** — Phase 2 of the reviewer-approved plan
`docs/superpowers/plans/2026-06-02-outline-expand-trace.md`. Phases 1 (the shared
`stubs.py` + `edges.py` foundation), 3 (`expand`), and 4 (`trace`) have all landed.

`outline` returns the **structural skeleton of a module or class** — a tree of
`(name, kind, signature, line span)` with no source content. The empirical analysis
in the parent design (`docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`,
§Empirical anchor) flagged the *absence* of an outline primitive as the #1 shape
failure in LSP-bridge MCPs: with no "structure of this scope" operation, an agent
either assembles it from many `documentSymbol`/`definition` calls (agent-lsp: 7
calls) or pulls full source (~13× the bytes of the skeleton it needed). `outline`
is the single-call answer.

This spec **refines** the `outline(handle) → Tree` section of the 2026-05-02 parent
design with decisions made after that design was written — specifically the honesty
conventions (`absence-vs-zero` applied to tree edges) that `expand` and `trace`
established in practice, plus a node budget the parent design lacked. Where this
spec and the 2026-05-02 section differ, **this spec governs** for `outline`.

## 2. Scope

**In:**

- `src/pyeye/mcp/operations/outline.py` — `outline(handle, max_depth, max_nodes)`
  recursive `members` walk → `OutlineTree`. Pure consumer of the existing edge
  registry.
- `src/pyeye/mcp/server.py` — register one new `@mcp.tool`: `outline`.
- `tests/conformance/response_linter.py` — `OutlineTree` shape + the two absence
  contracts (§4.2), plus adversarial tests.
- Unit + integration tests.

**Out (explicitly not this slice):**

- Any new edge or any change to `edges.py` / `resolve_members`. `outline` is a
  registry *consumer* (like `trace`); it adds **no** edge-resolution logic.
- Pagination/cursors (that is `expand`'s concern; an outline tree is delivered
  whole, bounded by `max_depth`/`max_nodes`).
- Filters (`include_tests` / `module_pattern` / `same_package`) — `outline` walks
  `members` only; scope filtering belongs to `expand`/`trace`.
- Walking any edge other than `members` (no `callees`/`subclasses`/etc. in the
  tree — those are `expand`/`trace`).

## 3. Architecture

### 3.1 Components / file map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pyeye/mcp/operations/outline.py` | Create | `outline(handle, analyzer, max_depth=None, max_nodes=200)` — BFS-bounded recursive `members` walk, building each node with `build_stub`, returning a nested `OutlineTree`. |
| `src/pyeye/mcp/server.py` | Modify | Register `outline` as a new `@mcp.tool`, widening the typed result to the plain-dict wire shape (same pattern as `resolve`/`inspect`/`trace`). Existing tools untouched. |
| `tests/conformance/response_linter.py` | Modify | Validate the `OutlineTree` shape: layering (no source content), required `node` key, the `children` absence contract, and the `truncated`/`truncation_reason` invariants (§4.2). |
| `tests/unit/mcp/operations/test_outline.py` | Create | Tree shape per kind; depth bounding; node-budget cutoff; external cap; the genuine-leaf-vs-truncated distinction; source ordering. |
| `tests/integration/api_redesign/test_outline_integration.py` | Create | End-to-end via the MCP wire format against a real fixture project. |
| `tests/conformance/test_linter_adversarial_outline.py` | Create | Well-formed passes; source-content smuggling rejected; `children: []` on a `truncated` node rejected; `truncated: false` rejected. |

### 3.2 Reuse (no new machinery)

`outline` introduces no analysis logic. It composes existing, battle-tested units:

- **`edges.resolve_members(jedi_name, analyzer) → EdgeResult`** — the single
  member-enumeration source (the same one `inspect.edge_counts.members` and
  `expand(handle, "members")` use). Returns `(Handle, Name)` pairs as
  `EdgeResult.adjacents`, so each child's Jedi `Name` is **carried** — `outline`
  recurses by calling `resolve_members` on that carried `Name`, never
  re-resolving a handle.
- **`stubs.build_stub(jedi_name, handle, analyzer) → Stub`** — builds every
  `node`. `build_stub` already returns `scope`, which the external cap reads.
- **`inspect._find_jedi_name_for_handle(handle, analyzer)`** — resolves the root
  handle to a Jedi `Name` (identical to how `trace` resolves its roots).

Because `resolve_members` returns `[]` for non-containers, recursion terminates
naturally: a `function`/`method`/`variable`/`attribute`/`property` node is always
a leaf. Nested classes recurse; class methods are leaves (a method has no
`members`); **function bodies are never walked** — the recursion follows the
`members` edge (module → class/function, class → method/nested-class), not
statements inside a function.

## 4. Response shape

### 4.1 `OutlineTree`

```text
OutlineTree = {
  "node":      Stub,                  # ALWAYS present (spec §4.1 Stub)
  "children":  [OutlineTree, ...],    # see §4.2 — present iff the node was walked
  "truncated": true,                  # see §4.2 — present ONLY on cut-off nodes
  "truncation_reason": "max_depth" | "max_nodes" | "external",  # iff truncated
}
```

`node` is exactly the §4.1 `Stub` (`handle`, `kind`, `scope`, optional
`signature`, `line_start`, `line_end`) — no new fields, no source content.
Implementation note: `Stub` is a *shape*, not a class — `stubs.build_stub`
returns a plain `dict[str, Any]` (the established "widen to plain-dict wire
shape" pattern). There is no `Stub` class to import; `outline` builds each
`node` by calling `build_stub` and nests it.

### 4.2 The two absence contracts (load-bearing)

These apply the `absence-vs-zero` invariant (the same principle behind
`inspect.edge_counts` omissions and `expand`'s unsupported-edge signal) to the
tree. They are the reason `outline` is honest rather than merely cheap, and the
conformance linter enforces both.

**Contract 1 — `children` absent ⇔ not expanded.**

- `children` **present** (including `children: []`) means *measured: this is the
  complete set of the node's direct members*. `children: []` is a genuine leaf —
  a container with no members, or any non-container.
- `children` **absent** means *we did not walk this node* (a cap fired). A
  consumer MUST treat a missing `children` as "unknown," never as "empty."

This is what stops a cut-off container from impersonating a genuine leaf — the
exact `absence-vs-zero` failure (#332) the whole surface guards against. Emitting
`children: []` for a depth-capped class would falsely read as "this class has no
members."

**Contract 2 — `truncated` is absent-not-false.**

- `truncated: true` is present **only** on a node that a cap cut off; it always
  co-occurs with `truncation_reason` and with an **absent** `children`.
- A fully-walked node OMITS `truncated` entirely (never `truncated: false`) —
  same idiom as a `Stub` omitting `signature` and `inspect` omitting an unmeasured
  edge count. No `truncated: false` noise anywhere in the tree.

Linter invariants (both directions):

- `truncated` present ⇒ value is exactly `true`, `truncation_reason` present and
  one of the three enum values, and `children` ABSENT. (`truncated: false`
  rejected; a `truncated` node carrying `children` rejected.)
- `truncated` absent ⇒ `truncation_reason` absent.
- `children` present ⇒ it is a list (possibly empty) of `OutlineTree`.

### 4.3 Worked example

```jsonc
// outline("pkg.widgets", max_depth=2)  — module with two classes
{
  "node": { "handle": "pkg.widgets", "kind": "module", "scope": "project",
            "line_start": 1, "line_end": 1 },
  "children": [
    { "node": { "handle": "pkg.widgets.Widget", "kind": "class",
                "scope": "project", "signature": "Widget(name: str)",
                "line_start": 10, "line_end": 48 },
      "children": [                         // depth 1 → walked
        { "node": { "handle": "pkg.widgets.Widget.render", "kind": "method",
                    "signature": "render(self) -> str", "scope": "project",
                    "line_start": 12, "line_end": 14 },
          "children": [] },                 // method: genuine leaf
        { "node": { "handle": "pkg.widgets.Widget.Style", "kind": "class",
                    "scope": "project", "line_start": 20, "line_end": 30 },
          "truncated": true,                // nested class AT depth 2 frontier,
          "truncation_reason": "max_depth"  // peek found members → cut off
                                            // (no "children" key)
        }
      ] },
    { "node": { "handle": "pkg.widgets.helper", "kind": "function",
                "signature": "helper() -> None", "scope": "project",
                "line_start": 50, "line_end": 52 },
      "children": [] }                      // function: genuine leaf
  ]
}
```

`Widget.render` (method) and `helper` (function) carry `children: []` — measured
leaves. `Widget.Style` (nested class at the `max_depth=2` frontier) carries
`truncated`/`truncation_reason` and NO `children` — its members exist but were not
walked. The two are unmistakable to the consumer.

## 5. Semantics

### 5.1 Signature

```python
async def outline(
    handle: str,
    analyzer: JediAnalyzer,
    max_depth: int | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]
```

- `max_depth=None` → unbounded within scope (the parent-design default). The root
  is depth 0.
- `max_nodes=200` → total-node budget (the parent design had none; see §5.4). The
  root always counts as 1 and is always included.
- Returns the root `OutlineTree`. Never raises; an unresolvable root yields a
  minimal single-node tree (mirroring `inspect`'s minimal-node fallback), with
  `children: []`.

`async` matches the surrounding tool surface (`inspect`/`trace` are async) and
leaves room for an async edge in the tree later. Whether the body actually awaits
(`resolve_members` is sync today) is an implementation detail settled in the plan;
if it does not await, document the "async for surface uniformity" reason inline so
it does not read as an oversight.

### 5.2 Traversal: BFS inclusion, source-order presentation

Two orderings, deliberately independent:

- **Inclusion order is BFS (level-order).** Nodes are discovered and admitted to
  the budget breadth-first by depth. This makes the `max_nodes` cutoff degrade
  gracefully — "all of depth 1, most of depth 2" — rather than DFS burning the
  whole budget on the first subtree and never showing its siblings.
- **Presentation order is source order.** Within each parent, `children` are
  sorted by `(line_start, handle)`. The skeleton reads top-to-bottom like the
  file an agent will `Read` next, so `line_start` values climb monotonically as it
  scans. The `handle` tiebreaker keeps order total and deterministic in the
  (degenerate) case of equal `line_start`.

Source order is fully deterministic (line numbers are a file property), so it
gives up nothing on stability/caching/test-repeatability versus a handle sort —
it strictly adds information (authorial co-location is preserved). This diverges
from `subclasses`/`imported_by`, which sort by handle **out of necessity** (their
members span files and arrive in `PYTHONHASHSEED`-dependent set order with no
single source order to fall back on); a single container's `members` are
same-file and have a real source order, so that precedent does not transfer.

### 5.3 Depth frontier peeks; budget/external cutoffs do not

To honour Contract 1, `outline` must distinguish a genuine empty leaf from a
cut-off container. The rule differs by cause:

- **`max_depth` frontier — peek.** At `depth == max_depth`, call `resolve_members`
  once on the node (one hop, do not recurse). Empty → emit `children: []` (genuine
  leaf). Non-empty → emit `truncated: "max_depth"`, omit `children`. This mirrors
  `trace` resolving edges one hop past its frontier to detect truncation.
- **`max_nodes` — reserve-before-expand (amended by #358).** A container is
  expanded only if the budget can admit ALL its direct members; otherwise it is
  cut off **whole** (`truncated: "max_nodes"`, `children` omitted). One peek
  counts the members (adding no nodes) so the cut-off node carries an honest
  `member_count`. Genuinely empty containers are leaves (`children: []`), never a
  `max_nodes` truncation. Honest: "didn't walk," not a false `[]`, and never a
  *partial* `children` list.
- **`external` cap — do not peek deeper.** See §5.4.

> **Amendment (#358, 2026-06-22).** The original rule above said "do not peek"
> and treated `max_nodes` as a per-node dequeue check. That left a hole: when the
> budget was exhausted *mid-enumeration of a container's children*, the loop
> broke and assigned the **partial** `children` list with no truncation marker —
> a Contract-1 violation (a partial set read as complete). The fix is
> **reserve-before-expand** + a `member_count` signpost on every `max_nodes`
> truncation, so a container is never partially expanded. See the cross-interface
> design in `2026-06-22-bounded-response-firehose-contract-design.md` (§4).

### 5.4 Bounds

**Node budget (`max_nodes`, default 200).** The parent design bounded `outline`
only by scope + `max_depth`; a large package or wide module could still produce an
unbounded tree (the parent plan's Phase 2 Risk note flagged exactly this). A node
budget bounds worst-case size. It is safe *because* Contract 1/2 land with it: a
budget cutoff is surfaced honestly (`truncated: "max_nodes"`), never as silently
dropped/empty nodes. Default 200 (higher than `trace`'s 50 — an outline is a cheap
structural skeleton meant to show a whole module, whereas a trace deliberately
samples a neighbourhood). The root counts as node 1.

**External-scope cap.** For a node whose `scope` is `external`, effective depth is
`min(max_depth, 1)`: the immediate members of an external class/module are
returned, but pyeye does not walk deeper into third-party code even if a larger
`max_depth` was requested. A container that would recurse past that one level is
cut off with `truncated: "external"`, `children` omitted (no peek deeper — that is
the point of the cap). This matches the lazy-resolution principle for external
symbols already stated in the parent design: agents wanting to go deeper into an
installed package call `inspect`/`outline` on a specific member. The root itself,
even if external, is always rendered with one level of members (subject to the
node budget).

When both a depth/external cap *and* the node budget could apply to the same node,
`max_nodes` takes precedence in `truncation_reason` (the budget is the harder
global bound). This is a reporting tiebreaker only; in all cases `children` is
omitted and the node is honestly marked cut-off.

`truncation_reason` is deliberately a **single string** (one node has exactly
one cut-off cause), unlike `trace`'s `truncation_reasons` **list** (one BFS can
hit several caps across different frontier nodes). This divergence is
intentional — do not "harmonise" `outline` to a list for false symmetry with
`trace`.

### 5.5 Cycles / termination

The `members` edge is a strict containment hierarchy (module ⊃ class ⊃
method/nested-class), which is acyclic, so unlike `trace` there is no cycle to
guard. Termination is guaranteed by: natural leaves (`resolve_members` → `[]`),
`max_depth`, and `max_nodes`. Each node is built exactly once.

## 6. Honesty / layering invariants (enforced by the linter)

1. **No source content** anywhere in the tree — every `node` is a `Stub`; the
   existing Check A layering walk applies to the whole `OutlineTree` recursively.
2. **Contract 1** (`children` absent ⇔ not expanded) and **Contract 2**
   (`truncated` absent-not-false, co-occurs with `truncation_reason` and absent
   `children`) per §4.2.
3. **`members`-only.** No edge other than `members` ever contributes a child —
   `outline` does not smuggle `callees`/`subclasses`/references into the tree.
4. **Count consistency.** For a fully-walked container (one with `children`
   present and not `truncated`), `len(children) == inspect(handle).edge_counts.members`
   — because both derive from `resolve_members`. (Holds only when the node is not
   truncated and the container was not below the external cap.)

## 7. Test strategy

- **Unit (`test_outline.py`):** module root → top-level classes/functions as
  children; class root → methods/nested classes; nested-class recursion; methods
  and functions are `children: []` leaves; `max_depth` bounds recursion and the
  frontier peek yields genuine `[]` vs `truncated: "max_depth"`; `max_nodes`
  cutoff marks excess containers `truncated: "max_nodes"` with no `children`;
  external handle capped at one level (`truncated: "external"`); children sorted by
  `(line_start, handle)`; unresolvable root → minimal single-node tree.
- **Conformance (`response_linter.py` + `test_linter_adversarial_outline.py`):**
  the §4.2 invariants in both directions — valid tree passes; `children: []` on a
  `truncated` node rejected; `truncated: false` rejected; `truncation_reason`
  without `truncated` rejected; source content anywhere rejected.
- **Integration (`test_outline_integration.py`):** `outline` over the MCP wire
  against a real fixture project — a module skeleton, a depth-bounded call showing
  the truncation markers, and the §6.4 count-consistency check against
  `inspect(...).edge_counts.members` for a fully-walked container.
- **Grep gate:** `outline.py` introduces no `get_references`/`find_references`
  call (it only consumes `resolve_members`, already grep-clean).

## 8. Acceptance criteria

1. `outline` callable on the MCP wire, returning an `OutlineTree` for module and
   class handles.
2. The §4.2 absence contracts hold and are linter-enforced in both directions.
3. `max_depth`, `max_nodes`, and the external cap each bound the tree and surface
   their cutoff honestly via `truncated`/`truncation_reason`.
4. Children are in source order; inclusion under budget is breadth-first.
5. No source content; no new edge logic; no change to `edges.py`/`resolve_members`.
6. Full suite green at the coverage threshold; pre-commit clean; no
   `get_references` on the `outline` path.

## 9. Open questions

- **Issue/branch:** to be filed (the parent plan landed `expand`/`trace`
  incrementally on a dev branch; `outline` should get its own issue for
  traceability, consistent with #348 `subclasses`).
- **`async` body:** confirmed `async def` for surface uniformity; the plan decides
  whether the implementation awaits anything today or documents the no-await
  rationale inline.
</content>

</invoke>
