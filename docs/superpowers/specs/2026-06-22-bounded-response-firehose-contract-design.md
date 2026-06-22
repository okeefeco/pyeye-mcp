# Bounded-Response / Firehose Contract — cross-interface design

**Status:** Draft for review
**Date:** 2026-06-22
**Drives:** #358 (first application — the mid-expansion honesty fix); #474 (Layer-1 outline natural unit — default member-mode roots to depth-1). Informs a follow-up unification across `outline` / `expand` / `trace` / `inspect` (#435).
**Related:** #422 (expand subclasses firehose → direct-only), #332 (absence-vs-zero / edge_counts), #333 (deferred Pyright reverse-edge backend).

## 1. Problem

pyeye's primitives can return *firehoses* — result sets so large they are actively
harmful to an AI consumer: they blow the context window, bury signal, and cost
tokens. This was hit concretely in #422 (`expand("…", "subclasses")` on Django
returned ~193 KB) and again in #358 (`outline` silently dropped sibling members
mid-expansion when a node budget was exhausted, presenting a *partial* list as
*complete* — a Contract-1 honesty violation).

`expand` was bounded structurally (direct-only; transitive via `trace`), but
**structural bounding does not bound breadth**: a class with 2,000 *direct*
subclasses is still a firehose. So we need a second, orthogonal layer: a uniform
*bounded-response* contract over every entries-returning result.

## 2. Non-negotiable principles

These fall out of pyeye's identity and the failure modes we explicitly rejected
while designing this.

1. **Freshness — recovery from a bound is always a *fresh re-query*, never a
   replayed snapshot.** Every answer reflects current code (live analyzer / file
   watchers). This rule **rules out**:
   - **Spilling results to a file** — a file is a point-in-time snapshot of a
     *mutable* dataset; reusing it later reads stale facts as current (a brand-new
     correctness failure mode). The mitigations (TTL, content-hash, invalidate-on-
     change) reintroduce exactly the stateful-disk layer we are avoiding. Doubly
     disqualified.
   - **Cursor / offset pagination over mutable data** — fetching "page 2" in a
     later call has the same staleness/consistency bug in milder form (the window
     shifts as the dataset changes between calls).
2. **No new statefulness.** pyeye stays a pure function surface: no on-disk
   result store, no cross-call cursors, no server-side lifecycle to manage.
3. **Layering (unchanged).** pyeye returns *pointers + structured semantic facts*,
   never source content. `Read` remains the content layer. Counts and stubs are
   facts, so they stay in-band; this contract adds no content to responses.
4. **Honesty (Contract 1/2, spec §4.2).** A result is either *fully measured*
   (entries present ⇒ the complete set) or *truncated* (entries absent + an honest
   marker). There is no silent partial. A "partial-but-present" page is precisely
   the #358 bug.

## 3. Two layers

### Layer 1 — each interface's natural unit (get the semantics right first)

| Interface | Natural unit | "Direct-equivalent" | Notes |
|-----------|--------------|---------------------|-------|
| `inspect` | counts (`edge_counts`) + facts, **no entries** | — | This **is** the count-first probe (a HEAD request). |
| `expand`  | one edge, one hop | direct adjacency (settled, #422) | transitive ⇒ `trace`. |
| `outline` | a bounded `members` tree | **direct members (depth-1)**, drill on demand | deeper levels = "transitive via re-call," analogous to expand. The current `max_depth=None` *unbounded* default for module/class roots is the firehose vector; survey mode already defaults to depth-1. Tracked as **#474** (breaking-change to the member-mode default). |
| `trace`   | multi-hop paths + stop condition | a hop | owns **all** relational/multi-hop queries. |

### Layer 2 — the bounded-response (firehose) envelope, applied over every entries-returning result

**Default: bounded.** Each entries-returning result has a soft size limit.

**On overflow: count only, no entries, + honest truncation marker.** Never a
partial page (Contract 1), never an unrequested dump.

- **Flat result (`expand`):** `{total: M, truncated: true, truncation_reason: …}`
  — no entries.
- **Tree result (`outline`):** overflow is **per-container**. An over-budget
  container becomes a **count-signposted truncated leaf**
  (`truncated: true`, `truncation_reason: "max_nodes"`, `member_count: M`, children
  **absent**); the parts of the tree that *did* fit are shown normally. The call
  does **not** collapse to a bare number.

**Count semantics.** The signpost count is fresh (computed this call).

- Forward edges — `members`, `submodules` — are available **now** (count == expand
  invariant holds).
- Reverse edges — `imported_by`, direct `subclasses` — ride the deferred Pyright
  backend (#333); their count-signpost is partial until then. State this honestly
  in the response rather than fabricating a count.

**Three fresh retrieval paths** (all single, self-contained, current calls):

1. **Count only** — the number *was* the answer (`inspect`, or the overflow
   signpost). No entries fetched.
2. **`complete=true` (or `limit=None`) — a *consented* full fetch.** Returns the
   entire set in one fresh call. This is legitimate because, unlike #422, it is
   *explicit and informed* (the agent saw the count and chose to spend the
   context). If even this is too big, that is the agent's signal to filter.
3. **Filter predicate — fresh matching subset.** Server-side projection over the
   freshly-computed result; only matches are returned. Response reports **both**
   `total` and `matched` so the consumer knows the filter's selectivity.

### Filter predicate scope (the firm line)

Filters are **flat projections over one result set** — near-zero extra cost,
because they filter data pyeye already computed:

- **regex / glob on the handle** — e.g. `subclasses matching /Admin$/`,
  `members matching test_*`.
- **equality on facts already in the stub** — `kind == "class"`,
  `scope == "project"`, module/path prefix.

**Out of scope (deliberately):** *relational / edge-match* predicates
("subclasses that themselves import X", "members that have their own subclasses").
These cost N extra resolutions per candidate and turn the API into a query engine
(scope creep, YAGNI, a perf cliff). **Relational / multi-hop queries are
`trace`'s job.** This line keeps filters cheap, honest, and bounded.

## 4. First application — #358 (`outline` mid-expansion truncation)

The bug: `outline()` exhausts `max_nodes` mid-enumeration of a container's
children, `break`s, and assigns the **partial** `children` list to the parent with
**no** truncation marker — a consumer reads partial as complete (Contract 1
violation; invisible to the linter; untested).

**Fix (binary contract + count signpost), implemented as reserve-before-expand:**

- Before expanding a container, if the remaining budget cannot admit **all** of
  its children, mark the parent `truncated: true`,
  `truncation_reason: "max_nodes"`, omit `children`, and attach the fresh
  `member_count: M`. Do **not** produce a partial list.
- This honors the existing two-contract model exactly (the conformance linter
  already enforces `truncated ⇒ children absent`), and recovery is a **fresh**
  re-outline of that subtree (raise budget / target it / filter) — never a stale
  partial.

**Acceptance (#358):**

- A budget cutoff landing mid-enumeration never yields an un-marked partial
  `children` list.
- Regression test for the mid-expansion break, including the **all-leaf-siblings**
  variant (the worst case: zero truncation markers anywhere under the old code).
- The truncated node carries a fresh `member_count`.
- Spec §4.2/§5.4 note added; conformance linter updated/confirmed.

## 5. Cross-interface consistency to reconcile (follow-up)

- `trace` uses `truncation_reasons` (a **list**); `outline` uses
  `truncation_reason` (a **single** string). Pick one shape for the unified
  contract.
- `complete` / `limit` parameter naming and the filter-predicate parameter shape
  should be identical across `outline` / `expand`.
- Decide where the soft size limit is configured (per-call arg + a default).

## 6. Out of scope

- Result files / any on-disk result store (rejected — §2.1).
- Cursor / offset pagination (rejected — §2.1).
- Relational / multi-hop filter predicates (delegated to `trace` — §3).
- Implementing the reverse-edge counts (gated on #333).
