# Outline / Expand / Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the progressive-disclosure traversal primitives — `outline`, `expand`, and `trace` — on top of the existing `resolve`/`inspect` surface, restricted to the edge types pyeye can produce reliably today (outbound/structural), with inbound/reference edges explicitly deferred to a later reference-backend phase.

**Architecture:** A shared `Stub` builder and an internal edge-resolver registry underpin all three primitives. `outline` is a scope-bounded recursive walk of the `members` edge. `expand` is a single-hop, paginated walk along one edge. `trace` is a bounded BFS composing `expand` over multiple edges. The keystone decision: this plan ships **only the edges backed by reliable Jedi local operations** (`members`, `superclasses`, `subclasses`, `callees`, `imports`, `enclosing_scope`); the inbound/reverse-search edges (`callers`, `references` and its `read_by`/`written_by`/`passed_by` components, `imported_by`, `overrides`/`overridden_by`, `decorated_by`/`decorates`) depend on project-wide reference search, which is the known-broken `get_references` path (issue #332). Those edges are surfaced as explicitly-unsupported (an honest "requires reference backend" signal), never as wrong/empty data, and light up in a non-breaking follow-up once the Pyright backend (#333) lands.

**Tech Stack:** Python, FastMCP, Jedi (local ops only: `goto`, `get_names`, `infer`, AST walks), pytest. Reuses `pyeye.handle.Handle`, `pyeye.scope.classify_scope`, `pyeye.canonicalization`, `pyeye._jedi_location`, and the existing `mcp/operations/inspect.py` helpers.

**Spec:** `docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md` (operations section, `Stub`/`OutlineTree`/`ExpandResult`/`Subgraph` types, and the edge-type vocabulary table).

**Carrier branch:** lands incrementally on the resolve/inspect dev branch (no separate issue/worktree), consistent with how `resolve`/`inspect` were delivered.

---

## Hard constraints (apply to every task)

- **No source content.** Stubs carry pointers (`handle`, `kind`, `scope`, `signature`, `line_start`, `line_end`) only — never bodies, snippets, or surrounding text. The conformance linter's layering check (Check A) already enforces this; new responses must pass it.
- **Absence-vs-zero, applied to edges.** An edge pyeye does not yet support must be reported as *explicitly unsupported* (a distinct, documented signal), NOT as an empty result set. An empty `stubs` list must mean "measured, none found"; "we can't measure this edge" must be a different, unmistakable response. This mirrors the `edge_counts` decision in #332.
- **Reliable edges only in this plan.** Do not wire any edge whose only implementation route is project-wide reference search (`get_references`). If an edge cannot be produced from local Jedi ops + bounded AST walks, it belongs in the deferred set, not this plan.
- **Reuse, don't duplicate.** Member enumeration, superclass resolution, scope classification, location-span building, and kind normalisation already exist in `inspect.py`/`resolve.py`/`scope.py`/`_jedi_location.py`. Extract and share rather than reimplement (note the existing duplication tracked in #330 — do not add more).
- **Canonical handles throughout.** Every stub's `handle` is a canonical definition-site handle (via `canonicalization`), so traversal dedup and cross-primitive composition work. `trace` dedups by handle.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/pyeye/mcp/operations/stubs.py` | Create | The shared `Stub` builder: given a Jedi name / handle, produce the spec `Stub` shape (handle, kind, scope, signature, line span). Single source of truth reused by outline/expand/trace and convertible from inspect's data. |
| `src/pyeye/mcp/operations/edges.py` | Create | Internal edge-resolver registry. Maps each supported edge type to a function returning the adjacent handles for a source handle. Declares which edges are supported-now vs. deferred-to-reference-backend. The one place edge support is defined. |
| `src/pyeye/mcp/operations/outline.py` | Create | `outline(handle, max_depth)` — recursive `members` walk, scope-bounded, external cap. |
| `src/pyeye/mcp/operations/expand.py` | Create | `expand(handle, edge, limit, cursor, filter)` — single-hop paginated walk over one edge via the registry. |
| `src/pyeye/mcp/operations/trace.py` | Create | `trace(start, follow, max_depth, max_nodes, stop_when)` — bounded BFS composing the edge registry; dedup by handle; `truncated` accounting. |
| `src/pyeye/mcp/server.py` | Modify | Register `outline`, `expand`, `trace` as new `@mcp.tool` endpoints. Do not modify existing tools. |
| `src/pyeye/mcp/operations/inspect.py` | Modify (small) | Extract the stub-shaped fields it already computes so `stubs.py` is the shared builder; no behavioural change to `inspect`'s output. |
| `tests/unit/mcp/operations/test_stubs.py` | Create | Stub builder unit tests across kinds. |
| `tests/unit/mcp/operations/test_edges.py` | Create | Edge-registry tests: each supported edge returns correct adjacents on a fixture; each deferred edge returns the explicit unsupported signal. |
| `tests/unit/mcp/operations/test_outline.py` | Create | Outline shape, depth bounding, scope cap, nested classes. |
| `tests/unit/mcp/operations/test_expand.py` | Create | Per-edge expansion, pagination (cursor round-trip), filter behaviour, deferred-edge signal. |
| `tests/unit/mcp/operations/test_trace.py` | Create | Multi-hop traversal, dedup/cycle handling, `truncated` accounting, `stop_when`. |
| `tests/integration/api_redesign/test_traversal_integration.py` | Create | End-to-end via the MCP wire format against a real fixture project. |
| `tests/conformance/response_linter.py` | Modify | Extend the linter to validate `Stub`/`OutlineTree`/`ExpandResult`/`Subgraph` shapes (layering + structural floors). |
| `docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md` | Modify | Add an implementation-status note recording which edges are supported now vs. deferred to the reference backend (mirrors the existing `edge_counts` note). |

---

## Phase 1: Shared foundation — Stub builder + edge registry

This phase builds the two shared units everything else depends on. Nothing user-facing ships yet, but it locks in the contracts (`Stub` shape, edge support matrix) that the three primitives rely on, so it must be correct first.

### Task 1.1: Failing tests for the `Stub` builder

- [ ] Create `tests/unit/mcp/operations/test_stubs.py`
- [ ] Write tests asserting the builder produces the exact spec `Stub` shape for each kind (class, function, method, module, attribute, property, variable): canonical `handle`, normalised `kind`, `scope` (`project`/`external`), one-line `signature` for callable kinds (absent for non-callable), and `line_start`/`line_end` from the symbol's span — because every traversal primitive returns stubs and they must be uniform across primitives
- [ ] Write a test asserting no stub field ever contains source content (multi-line bodies/snippets), so the layering invariant holds at the unit level
- [ ] Run the tests so they fail because the module does not exist
- [ ] Commit

**Constraint:** The signature must be the same single-line form `inspect` already produces — extract and share that logic, do not write a second signature extractor (see #330 for the cost of parallel implementations).

**Acceptance:** Tests fail for "module missing" reasons, and pin the stub contract for all kinds including the no-signature and external-scope cases.

### Task 1.2: Implement the `Stub` builder

- [ ] Create `src/pyeye/mcp/operations/stubs.py` with a builder that takes a Jedi name (or a resolved handle) and returns the spec `Stub`
- [ ] Reuse existing kind normalisation, scope classification, location-span, and signature helpers rather than reimplementing them
- [ ] Modify `inspect.py` minimally so the shared builder is the single source of the stub-shaped fields, with no change to `inspect`'s observable output
- [ ] Run the failing tests so they pass
- [ ] Run the full suite to confirm `inspect` did not regress
- [ ] Commit

**Constraint:** This is a refactor-plus-extract on a file already in production (`inspect.py`). The `inspect` response shape must not change — only the internal source of those fields. Verify by the existing `inspect` tests staying green untouched.

**Risk:** Over-eager extraction could change `inspect`'s output subtly (e.g. signature formatting). Keep the extraction behaviour-preserving; if any `inspect` test needs editing, that is a signal the extraction changed behaviour and should be reconsidered.

**Acceptance:** Stub tests pass; all existing `inspect` tests pass unmodified; full suite green.

### Task 1.3: Failing tests for the edge registry

- [ ] Create `tests/unit/mcp/operations/test_edges.py`
- [ ] For each **supported-now** edge (`members`, `superclasses`, `subclasses`, `callees`, `imports`, `enclosing_scope`): write a test asserting the resolver returns the correct adjacent handles for a fixture symbol, because these are the edges `expand`/`trace` will traverse
- [ ] For each **deferred** edge (`callers`, `references`, `read_by`, `written_by`, `passed_by`, `imported_by`, `overrides`, `overridden_by`, `decorated_by`, `decorates`): write a test asserting the registry reports it as *explicitly unsupported* — a distinct signal, never an empty adjacency list — because conflating "unsupported" with "none found" is the exact failure #332 exists to prevent
- [ ] Run the tests so they fail
- [ ] Commit

**Constraint:** `callees` requires reading the *target function's own body* and resolving each call via `goto` — this is local (one file) and reliable, distinct from the project-wide reverse search that `callers` needs; it is the one outbound call-edge in the supported set. Be precise about which direction each edge walks — outbound (this symbol points out: members, superclasses, callees, imports, enclosing_scope) is supported; inbound (others point at this symbol) is deferred. `subclasses` is the deliberate exception: it is directionally inbound but reliably produced by an AST-walk + `goto` (no reverse search), so it is supported. The spec's edge-vocabulary table gives each edge's direction.

**Note on `overrides`:** although a method's own ancestors' same-named methods are reachable via MRO (locally), `overrides` is placed in the **deferred** set for this plan to keep the supported scope to the six edges above and avoid a "reliable-ish" edge that risks falling through to reverse search. It can be promoted in a later phase if a purely-local implementation is confirmed.

**Risk:** `callees` is "reliable-ish" — it involves more than a single local call (read the body, resolve each call site). During implementation, confirm it stays within local-file operations and does **not** fall through to `get_references`. If it cannot be done reliably without reverse search, move it to the deferred set and note it; do not ship a shaky edge.

**Acceptance:** Failing tests define the support matrix: every supported edge has an expected-adjacency test; every deferred edge has an unsupported-signal test.

### Task 1.4: Implement the edge registry

- [ ] Create `src/pyeye/mcp/operations/edges.py` with a registry mapping each supported edge to a resolver function (source handle → list of adjacent canonical handles), and a declared set of deferred edges that resolve to the explicit unsupported signal
- [ ] Implement only the supported-now resolvers, reusing existing analyzer helpers (member enumeration, subclass search, superclass resolution, import extraction)
- [ ] Run the failing tests so they pass
- [ ] Run the full suite
- [ ] Commit

**Constraint:** Each resolver returns canonical handles (so downstream dedup/composition works), not raw Jedi names or positions. The deferred-edge signal must be machine-distinguishable from an empty result by callers (`expand`/`trace` will translate it into their own response shapes).

**Acceptance:** All edge tests pass. Grep confirms no supported-edge resolver calls `get_references` / `find_references`. Full suite green.

---

## Phase 2: `outline` ✅ COMPLETE

> **Status:** Implemented and merged (issue #355, branch `feat/355-outline`).
> Refined spec: `docs/superpowers/specs/2026-06-13-outline-design.md`.
> Implementation plan: `docs/superpowers/plans/2026-06-13-outline.md`.
>
> The original tasks below are preserved for historical context. All acceptance
> criteria were met; the conformance linter (Check O) enforces the two absence
> contracts in both directions.

The cheapest, most independent primitive — a recursive `members` walk on reliable Jedi ops. Delivers the "structural skeleton of a module/class" view the empirical analysis flagged as missing in LSP-bridges. No dependency on the reference backend.

### Task 2.1: Failing tests for `outline`

- [x] Create `tests/unit/mcp/operations/test_outline.py`
- [x] Write tests asserting: a module handle yields an `OutlineTree` whose children are its top-level classes/functions; a class handle yields its methods/nested classes; nested classes are walked but function bodies are not (no descent into local variables inside a function); each node is a `Stub`
- [x] Write a test asserting `max_depth` bounds the recursion as specified
- [x] Write a test asserting the external-scope cap: an external handle is walked at most one level deep regardless of requested `max_depth`
- [x] Run the tests so they fail
- [x] Commit

**Constraint:** Default `max_depth` is unbounded *within scope*. "Bodies are not walked" means the recursion follows `members` (class → method, module → class), not statements inside a function. Reuse the Phase 1 `members` resolver and `Stub` builder.

**Acceptance:** Failing tests pin the tree shape, depth bounding, and external cap.

### Task 2.2: Implement `outline`

- [x] Create `src/pyeye/mcp/operations/outline.py` implementing the recursive `members` walk via the edge registry, building each node with the shared `Stub` builder
- [x] Apply the external-scope cap (treat requested depth as at most one level for external handles)
- [x] Run the failing tests so they pass
- [x] Run the full suite
- [x] Commit

**Risk:** Deeply nested or large modules could produce very large trees. The scope bound and `max_depth` are the guards; confirm a large fixture module returns in reasonable time and the tree is bounded. If unbounded-within-scope proves too large in practice, note it — but do not add a silent cap that hides nodes (that would violate the honesty principle; prefer surfacing depth limits explicitly).

**Acceptance:** Outline tests pass; full suite green; manual check on a real fixture module produces a sensible skeleton with no source content.

---

## Phase 3: `expand`

Single-hop, paginated walk over one edge. The keystone that makes `inspect`'s orientation *actionable* — but in this plan only for the supported (outbound/structural) edges. Inbound edges return the explicit unsupported signal.

### Task 3.1: Failing tests for `expand` over supported edges

- [ ] Create `tests/unit/mcp/operations/test_expand.py`
- [ ] For each supported edge, write a test asserting `expand` returns `Stub`s for the correct adjacents of a fixture symbol
- [ ] Write pagination tests: a `limit` smaller than the result set returns a `cursor`; passing that cursor back returns the next page; the final page omits the cursor; the concatenation of pages equals the full set with no duplicates or gaps — because pagination correctness is the contract agents rely on to know when they have everything
- [ ] Write filter tests for `include_tests`, `module_pattern`, and `same_package` per the spec's `ExpandFilter`
- [ ] Run the tests so they fail
- [ ] Commit

**Constraint:** `expand` deliberately returns **no total count** — pagination state is read from cursor presence only (absent = complete). Ordering for stubs is `(file, line_start)` ascending for determinism, so cursors advance through a stable flat list. The cursor is opaque to callers but must encode enough to resume deterministically.

**Risk:** Cursor design is the subtle part. It must survive the result set being recomputed between calls (pyeye is stateless per call) — i.e. encode a position in a deterministic ordering rather than an in-memory offset. Constraint: the ordering must be total and stable across calls or pagination will skip/repeat. Verify with a test that paginates a set larger than one page and reconstructs it exactly.

**Acceptance:** Failing tests define per-edge expansion, exact pagination round-trips, and filter semantics.

### Task 3.2: Failing tests for `expand` over deferred edges

- [ ] Add tests asserting that calling `expand` with a deferred edge (e.g. `callers`, `references`) returns the explicit *unsupported* response — distinguishable from an empty page — and never a wrong/empty stub list, because returning `[]` for `callers` would falsely imply "no callers" (the #332 failure mode)
- [ ] Run the tests so they fail
- [ ] Commit

**Constraint:** The unsupported response must be self-describing enough that an agent understands the edge is not-yet-measured (and, ideally, that a reference backend is required), not that the symbol has zero such neighbours.

**Acceptance:** Failing tests pin the deferred-edge behaviour as an explicit signal.

### Task 3.3: Implement `expand`

- [ ] Create `src/pyeye/mcp/operations/expand.py` implementing single-hop expansion via the edge registry, with ordering, pagination/cursor, and filter support for supported edges, and the unsupported signal for deferred edges
- [ ] Run the failing tests from 3.1 and 3.2 so they pass
- [ ] Run the full suite
- [ ] Commit

**Acceptance:** All `expand` tests pass; pagination reconstructs full sets exactly; deferred edges return the explicit signal; full suite green; grep confirms no supported-edge path touches `get_references`.

---

## Phase 4: `trace`

Bounded multi-hop BFS composing `expand` over a `follow` set of edges. Restricted here to supported edges (so trace closures are trustworthy). Completes the orient → drill → traverse flow, enabling end-to-end assessment of the primitive set without the reference backend.

### Task 4.1: Failing tests for `trace`

- [ ] Create `tests/unit/mcp/operations/test_trace.py`
- [ ] Write a multi-hop test: tracing `members` (or `subclasses`/`callees`) from a start handle returns a `Subgraph` whose `nodes` are reachable stubs and whose `edges` record `(from, to, kind)` — because trace's value is exposing structure across hops, with fan-in visible
- [ ] Write a dedup/cycle test: a cyclic fixture (e.g. mutually-referencing modules or self-referential class) terminates; each handle appears once in `nodes`; edges to already-visited handles are still recorded so cycles are visible
- [ ] Write `truncated` tests: hitting `max_depth` or `max_nodes` before natural termination sets `truncated: true`; a fully-explored closure sets `truncated: false`
- [ ] Write a `stop_when` test: traversal halts at the predicate boundary (e.g. entering a matching module, or excluding tests)
- [ ] Write a multi-edge `follow` test: following more than one edge type produces edges of each kind with correct `kind` labels (edges not deduped across types)
- [ ] Run the tests so they fail
- [ ] Commit

**Constraint:** Dedup by handle; visit each handle at most once; record-but-don't-re-expand edges to visited handles (this guarantees termination on cycles even with unbounded depth). `truncated` means specifically "caps hit before natural termination," not merely "caps were set." Defaults: `max_depth` 3, `max_nodes` 50.

**Risk:** If `follow` includes a deferred edge, `trace` must surface that clearly (e.g. refuse or annotate), not silently return a partial graph that looks complete — same honesty concern as `expand`. Decide and test this behaviour explicitly.

**Acceptance:** Failing tests define traversal, cycle-safe termination, `truncated` accounting, `stop_when`, and multi-edge labelling.

### Task 4.2: Implement `trace`

- [ ] Create `src/pyeye/mcp/operations/trace.py` implementing bounded BFS over the edge registry with dedup, cycle handling, `truncated` accounting, `stop_when`, and multi-edge `follow`
- [ ] Decide and implement the behaviour when `follow` contains a deferred edge (refuse-with-signal or annotate), consistent with `expand`'s unsupported handling
- [ ] Run the failing tests so they pass
- [ ] Run the full suite
- [ ] Commit

**Acceptance:** All `trace` tests pass; cyclic fixtures terminate; `truncated` is accurate; deferred-edge-in-follow is handled honestly; full suite green.

---

## Phase 5: MCP registration, conformance, and docs

Surfaces the three primitives on the wire and locks the contracts into the conformance suite.

### Task 5.1: Register `outline`, `expand`, `trace` as MCP tools

- [ ] Modify `src/pyeye/mcp/server.py` to register the three new `@mcp.tool` endpoints, wrapping the operation implementations and resolving the analyzer per the existing pattern used by `resolve`/`inspect`. Do not modify existing tools
- [ ] Create `tests/integration/api_redesign/test_traversal_integration.py` exercising each new tool end-to-end via the MCP wire format against a real fixture project, including a pagination round-trip through the wire and a deferred-edge call
- [ ] Run the integration tests so they pass
- [ ] Run the full suite with coverage to confirm zero regressions and threshold held
- [ ] Commit

**Constraint:** Wrappers convert the operation's typed result to the plain-dict wire shape the existing tools use (same widening pattern as `resolve`/`inspect`). Tool docstrings must state plainly which edges are supported now and that inbound/reference edges require the reference backend.

**Acceptance:** Three new tools discoverable and callable via the wire; integration tests pass; full suite green at coverage threshold.

### Task 5.2: Extend the conformance linter and update the spec

- [ ] Modify `tests/conformance/response_linter.py` to validate the `Stub`, `OutlineTree`, `ExpandResult`, and `Subgraph` shapes: enforce the layering check (no source content) on all of them, and structural floors (required keys per type, cursor optionality, `truncated` boolean presence)
- [ ] Add adversarial linter tests for the new shapes (well-formed passes; source-content smuggling rejected; malformed structure rejected)
- [ ] Update `docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md` with an implementation-status note recording the supported-now vs. deferred edge split for `expand`/`trace` and pointing to #332/#333 — mirroring the existing `edge_counts` status note
- [ ] Run the conformance suite so it passes
- [ ] Commit

**Acceptance:** Linter validates all new response shapes in both directions (accepts valid, rejects violations); spec records the edge split honestly; conformance suite green.

---

## Deferred to the reference-backend phase (NOT in this plan)

Explicitly out of scope here, to be delivered after the Pyright reference backend (#333) lands, as a non-breaking addition (the registry's deferred edges flip from unsupported to supported; `expand`/`trace` gain them automatically):

- Inbound / reverse-search edges: `callers`, `references` (and `read_by`/`written_by`/`passed_by`), `imported_by`, `overrides`/`overridden_by`, `decorated_by`/`decorates`. (`overrides` may instead be promoted earlier if a purely-local MRO implementation is confirmed — see Task 1.3 note.)
- Restoring `edge_counts.callers`/`references` on `inspect` (#332).

**Note:** This split is the deliberate strategic sequencing — validate the full progressive-disclosure flow (orient → expand → trace) on trustworthy outbound edges *before* investing in the non-trivial Pyright backend, then light up the inbound half once the backend exists.

---

## Verification gates between phases

After each phase, before the next:

- [ ] Full test suite green at the coverage threshold (the project's standard gate).
- [ ] Pre-commit hooks pass (no bypass flags).
- [ ] No new call to `get_references`/`find_references` introduced on any supported-edge path (grep-verified) — the load-bearing constraint that keeps this plan's outputs trustworthy.
- [ ] New response shapes pass the conformance linter's layering check (no source content).

## Rollout note

Phases 1–2 (foundation + `outline`) are pure additive wins on reliable ops and safe to land independently. Phase 3 (`expand`) is the keystone for actionability. Phase 4 (`trace`) completes the flow and enables end-to-end assessment of whether the primitive set works — which is the decision point for whether/when to invest in the Pyright backend. Phase 5 makes it real on the wire. The deferred inbound edges are a separate, later, non-breaking initiative.
