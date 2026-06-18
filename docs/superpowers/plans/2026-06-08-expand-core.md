# Expand-core (members + callees) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `expand(handle, edge)` end-to-end and callable on the MCP wire for exactly two edges — `members` and `callees` — on a proper shared foundation (`stubs.py` builder + `edges.py` status registry), with `inspect` refactored to share the member enumeration.

**Architecture:** A single-source `Stub` builder (`stubs.py`) and an edge-resolver registry with an explicit per-edge status model (`edges.py`) underpin a single-hop `expand`. `members` and `callees` are the only implemented edges; every other edge is declared with an explicit not-supported status (never an empty result). `inspect` is rewired to consume the same `members` enumeration so the duplication is killed. No pagination/filters/`outline`/`trace`; no Pyright/reference edges.

**Tech Stack:** Python, FastMCP, Jedi (local ops only: `goto`, `get_names`, AST walks via `file_artifact_cache.get_ast`), pytest. Reuses `pyeye.handle.Handle`, `pyeye.canonicalization`, `pyeye.scope.classify_scope`, and existing `mcp/operations/inspect.py` helpers.

**Spec:** `docs/superpowers/specs/2026-06-08-expand-core-design.md` (authoritative — contracts, edge status model, guarantees/non-guarantees).

**Broader plan this is a strict subset of:** `docs/superpowers/plans/2026-06-02-outline-expand-trace.md`.

**Branch / issue:** `feat/340-expand-core`, issue #340. Lands incrementally on this branch.

---

## Hard constraints (apply to every task)

- **No source content.** Stubs carry pointers + a one-line signature only — never bodies/snippets/surrounding text. The conformance layering check enforces this.
- **Explicit-unsupported, never empty.** An edge that is not implemented must return the distinct unsupported signal (`unsupported: true` + `reason`), never `stubs: []`. An empty `stubs` list means "measured, none found." This is the #332 absence-vs-zero contract.
- **Reliable edges only; no reverse search.** No path for `members` or `callees` may call `get_references`/`find_references`. `callees` is forward `goto`-per-call-site only. This is grep-verified at the relevant tasks.
- **Reuse, don't duplicate.** Reuse the existing signature/kind/scope/span helpers and the member-enumeration logic; do not add parallel implementations (see #330).
- **Canonical handles throughout.** Every adjacency and every stub `handle` is a canonical definition-site handle (via `canonicalization`), so dedup/composition work later.
- **`members` excludes imports.** Module members are symbols *defined in the module*; imported/re-exported names are excluded (they belong to the deferred `imports` edge). Class members are direct (inherited excluded).
- **One intended observable `inspect` change.** Routing `edge_counts.members` through the shared resolver makes module counts drop by the number of top-level imports (a correctness fix). Existing `inspect` tests must still pass **unmodified** — they assert `>=` lower bounds, so the drop is safe. If a test asserting an exact/upper-bound count needs editing, stop and reconsider.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pyeye/mcp/operations/stubs.py` | Create | Single-source `Stub` builder: Jedi name / canonical handle → `{handle, kind, scope, signature?, line_start, line_end}`. No source content. Reuses existing helpers. |
| `src/pyeye/mcp/operations/edges.py` | Create | Edge-resolver registry + per-edge status (`implemented` / `not_yet_implemented` / `deferred_reference_backend`, plus an `unknown_edge` fallback for unrecognised edge names). Implements `members` and `callees` resolvers (source handle → adjacent canonical handles). Single place edge support is declared. |
| `src/pyeye/mcp/operations/expand.py` | Create | `expand(handle, edge)` — single hop via the registry → `ExpandResult` (supported or unsupported branch). No cursor/filter. |
| `src/pyeye/mcp/operations/inspect.py` | Modify | Route member enumeration (and the overlapping stub-shaped fields, where shapes align) through `edges.py`/`stubs.py`. No observable change except the intended module-member-count drop. |
| `src/pyeye/mcp/server.py` | Modify | Register `expand` as a new `@mcp.tool`. Do not touch existing tools. |
| `tests/unit/mcp/operations/test_stubs.py` | Create | Stub builder across kinds; no-content invariant. |
| `tests/unit/mcp/operations/test_edges.py` | Create | Status model; `members`/`callees` adjacency on fixtures; no-`get_references` assertion on the `callees` path. |
| `tests/unit/mcp/operations/test_expand.py` | Create | Expand over members/callees; deferred/not-yet/unknown signals; empty-vs-unsupported distinction; `unresolved_call_sites`. |
| `tests/integration/api_redesign/test_traversal_integration.py` | Create | `expand` end-to-end via the MCP wire against a real fixture. |
| `tests/fixtures/...` | Create/identify | A fixture function for `callees` with both statically-resolvable calls and at least one dynamic (unresolvable) call. |
| `tests/conformance/response_linter.py` | Modify | Validate `Stub` + `ExpandResult` (both branches): layering + structural floors. |

---

## Phase 1: Stub builder

The shared leaf every primitive returns. Build and prove it in isolation first because its shape is a contract all later phases depend on.

### Task 1.1: Failing tests for the `Stub` builder

- [ ] Write tests asserting the builder produces the exact `Stub` shape for each kind (class, function, method, module, attribute, property, variable): canonical `handle`, normalised `kind`, `scope` of `project`/`external`, a one-line `signature` for callable kinds and its absence for non-callables, and `line_start`/`line_end` from the symbol's span — because every traversal primitive returns stubs and they must be uniform.
- [ ] Write a test asserting no stub field ever carries multi-line source content, so the layering invariant holds at the unit level.
- [ ] Run the tests; confirm they fail because the module does not exist.
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_stubs.py`.
**Constraints:** The signature must be the same one-line form `inspect` already produces — reuse that helper, do not write a second signature extractor (#330). Use the existing `resolve_project` fixture for the kinds it already covers.
**Acceptance:** Tests fail for "module missing" reasons and pin the stub contract for all kinds, including the no-signature and external-scope cases.
**Risks:** Some kinds (attribute/property/variable) may not have a natural signature — the test must assert *absence*, not an empty string, to match the contract.

### Task 1.2: Implement the `Stub` builder

- [ ] Implement `stubs.py` taking a Jedi name (or resolved handle) and returning the spec `Stub`, reusing the existing kind-normalisation, scope-classification, signature, and location-span helpers.
- [ ] Run the failing tests; confirm they pass.
- [ ] Run the full suite; confirm no regression.
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/stubs.py`.
**Constraints:** `Stub.location` is the flattened `line_start`/`line_end` form, which is *narrower* than `inspect`'s richer location dict (it also carries columns/file). Share the underlying span computation; do not force `inspect`'s location shape onto the stub. No `get_references` anywhere.
**Acceptance:** Stub tests pass; full suite green.
**Risks:** Over-reaching into `inspect`'s field assembly here (rather than just building stubs) would couple this task to the Phase 5 refactor — keep `stubs.py` standalone for now; `inspect` is rewired in Phase 5.

---

## Phase 2: Edge registry + `members`

The registry that declares edge support, plus the easy edge that validates the whole pipeline.

### Task 2.1: Failing tests for the registry status model and `members`

- [ ] Write tests asserting the registry classifies every edge into exactly one status: `members`/`callees` as `implemented`; `superclasses`/`subclasses`/`imports`/`enclosing_scope` as `not_yet_implemented`; the inbound/reference edges as `deferred_reference_backend`; an unrecognised name as `unknown_edge` — because this matrix is the single source of edge support and `expand` reads it directly.
- [ ] Write tests asserting the `members` resolver returns the correct adjacent canonical handles for a class (its methods/nested classes/attributes, direct only) and for a module (its defined top-level classes/functions/variables), and an empty result for a non-container — because `members` is the edge that proves the end-to-end path.
- [ ] Write a test asserting module `members` **excludes imports** (e.g. an imported name present in the module's top-level `get_names` does not appear in the resolver's output) — because this is the deliberate divergence from the old flat count and the thing that keeps `members` disjoint from the `imports` edge.
- [ ] Run the tests; confirm they fail.
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_edges.py`.
**Constraints:** Resolvers return canonical handles, not Jedi names or positions. Class members reuse the existing prefix+exact-depth matching (already import-free). Module members must filter imports out (e.g. a top-level AST walk over definition nodes, skipping `Import`/`ImportFrom`). Pick a fixture module that contains at least one import plus several definitions so the exclusion is observable.
**Acceptance:** Failing tests define the status matrix and the `members` adjacency contract including the import-exclusion.
**Risks:** Jedi reports an imported name as a top-level definition (it typed `ClassVar` as `class`), so relying on Jedi's `definitions=True` alone will *not* exclude imports — the resolver needs an explicit import filter. The test must assert exclusion of a real imported name to catch this.

### Task 2.2: Implement the edge registry and `members` resolver

- [ ] Implement `edges.py` with the status model (the four-way classification + an unsupported-signal value the consumers can translate) and the `members` resolver for class and module containers, reusing existing enumeration/matching and `canonicalization` for handles.
- [ ] Run the failing tests; confirm they pass.
- [ ] Run the full suite; confirm no regression.
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/edges.py`.
**Constraints:** The deferred/not-yet/unknown statuses must be machine-distinguishable from each other and from a successful empty adjacency, because `expand` maps each to a specific `reason`. The `members` enumeration is the one that `inspect` will later reuse (Phase 5) — design it to return handles with the count derivable as `len(...)`.
**Acceptance:** All Phase 2 tests pass; full suite green.
**Risks:** Module member enumeration is the single most substantive piece of new logic (handles per member + import exclusion). Keep it a focused unit; if class and module enumeration diverge too much, that is expected (their mechanisms differ) — do not force a single code path that reintroduces the import bug for modules.

---

## Phase 3: `callees` (the risk-prober)

The one edge whose reliability is an open question. Built in isolation so its locality can be proven before it is composed into `expand`.

### Task 3.1: Failing tests for the `callees` resolver

- [ ] Identify or create a fixture function that makes several statically-resolvable calls (to a couple of known project/stdlib functions) **and** at least one dynamic, unresolvable call — because the resolver must be tested on both the resolvable set and the unresolved-count path.
- [ ] Write tests asserting `callees` of that function returns the correct canonical handles for the resolvable calls, dedups repeated calls, and reports the count of unresolvable call sites as `unresolved_call_sites` — because the contract is "≥ these edges, plus N unresolved," not "exactly these."
- [ ] Write a test asserting calls inside a **nested** function/lambda/class are NOT attributed to the outer function — because a nested scope's calls are its own callees.
- [ ] Write a test asserting `callees` of a non-function (class/module/variable) is an empty result.
- [ ] Write a test asserting the `callees` code path makes no call to `get_references`/`find_references` — the load-bearing trust constraint.
- [ ] Run the tests; confirm they fail.
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_edges.py` (extend), fixtures.
**Constraints:** Resolution is forward `goto`-per-call-site against the function's own cached AST; the nested-scope boundary must stop descent at `def`/`async def`/`lambda`/`class`. Builtins/stdlib callees are included (scope `external`); unresolvable calls are *counted*, not invented.
**Acceptance:** Failing tests pin the adjacency, dedup, `unresolved_call_sites`, nested-scope boundary, non-function case, and the no-reverse-search constraint.
**Risks:** This is the de-risking task. If `callees` cannot be produced reliably from local AST + per-call-site `goto` without touching `get_references`, demote it to `not_yet_implemented`, ship `members`-only, and record the finding — do not ship a shaky edge. Expectation: it holds (same mechanism as base-class resolution).

### Task 3.2: Implement the `callees` resolver

- [ ] Implement `callees` in `edges.py`: locate the def node in the cached AST, collect `ast.Call` targets within the body (stopping at nested scope boundaries), resolve each via forward `goto`, canonicalize, dedup, and count the unresolved sites.
- [ ] Run the failing tests; confirm they pass.
- [ ] Run the full suite; confirm no regression.
- [ ] Grep-verify the `callees`/`members` paths introduce no `get_references`/`find_references`.
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/edges.py`.
**Constraints:** `unresolved_call_sites` is a count only — never partial/invented handles. Determinism: the same function yields the same callee set and count every run.
**Acceptance:** All `callees` tests pass; full suite green; grep confirms no reverse search on the path.
**Risks:** Attribute-access call targets (`obj.method()`) position resolution mirrors the base-class `_attr_target_position` concern — reuse that positioning logic rather than re-deriving it.

---

## Phase 4: `expand`

Composes the registry into the user-facing single-hop operation and the discriminated-union response.

### Task 4.1: Failing tests for `expand`

- [ ] Write tests asserting `expand` over `members` and over `callees` returns the supported `ExpandResult` shape (`source`, `edge`, `stubs`), with stubs built by the Phase 1 builder — because this is the end-to-end happy path.
- [ ] Write a test asserting the `callees` result carries `unresolved_call_sites` and the `members` result does not — because that field is callees-specific.
- [ ] Write tests asserting a `deferred_reference_backend` edge, a `not_yet_implemented` edge, and an `unknown_edge` name each return the unsupported branch with the correct `reason`, distinguishable from a supported empty result — because conflating unsupported with empty is the #332 failure.
- [ ] Write a test asserting a container with no members returns a supported result with `stubs: []` (measured none), *not* the unsupported branch — to pin the empty-vs-unsupported distinction.
- [ ] Run the tests; confirm they fail.
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_expand.py`.
**Constraints:** No `cursor` in this slice — its absence means "complete." The supported and unsupported branches are mutually exclusive and both fully specified by the spec §4.2.
**Acceptance:** Failing tests define both union branches, the reason taxonomy, the empty-vs-unsupported distinction, and the callees-only field.
**Risks:** None beyond getting the discriminated-union keys exactly per spec; the linter (Phase 6) will enforce the shape.

### Task 4.2: Implement `expand`

- [ ] Implement `expand.py`: resolve the handle to a Jedi name, consult the registry, run the resolver and build stubs for supported edges (carrying `unresolved_call_sites` for `callees`), or return the unsupported branch with the mapped `reason`.
- [ ] Run the failing tests; confirm they pass.
- [ ] Run the full suite; confirm no regression.
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/expand.py`.
**Constraints:** Reuse `inspect._find_jedi_name_for_handle` (or the shared resolution path) for handle→name; do not add a parallel resolver. A handle that cannot be resolved at all should return a clear not-found-style result consistent with how `inspect` handles the same case.
**Acceptance:** All `expand` tests pass; full suite green.

---

## Phase 5: `inspect` refactor (share the enumeration)

Rewire `inspect` to consume the shared `members` enumeration, killing the duplication and accepting the one intended count change.

### Task 5.1: Route `inspect`'s member count through `edges.py`

- [ ] Change `inspect`'s `edge_counts.members` to derive from the shared `members` resolver (count = `len(...)`), and route the overlapping stub-shaped field assembly through `stubs.py` where the shapes align.
- [ ] Run the existing `inspect` test suite; confirm it passes **unmodified** (module counts drop by the number of imports but still satisfy the `>=` bounds).
- [ ] Run the full suite; confirm no regression.
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/inspect.py`.
**Constraints:** The only permitted observable change is the module-member-count drop (imports excluded). `inspect`'s richer `location` shape, `docstring`, `edge_counts` (other edges), `re_exports`, and kind-dependent fields are unchanged. Do **not** edit existing `inspect` tests. Note: in practice the member *count* (`len(members_resolver(...))`) is likely the only cleanly-overlapping piece — the stub `location` is deliberately narrower than `inspect`'s (Task 1.2), so do not force the narrow Stub shape onto `inspect`'s fields. Routing only the count is within intent.
**Acceptance:** Existing `inspect` tests pass unmodified; full suite green; the duplication between `inspect`'s member counting and the `members` resolver is gone.
**Risks:** If an existing `inspect` test fails on something *other* than would be fixed by the intended count change (e.g. a signature/location difference), the extraction changed behaviour beyond intent — stop and reconsider rather than editing the test. This is the guardrail that protects the just-merged `inspect`.

---

## Phase 6: MCP registration, integration, conformance

Surfaces `expand` on the wire and locks the new shapes into the conformance suite.

### Task 6.1: Register `expand` and add wire-level integration tests

- [ ] Register `expand` as a new `@mcp.tool` in `server.py`, wrapping the operation and resolving the analyzer per the existing `resolve`/`inspect` pattern, converting the typed result to the plain-dict wire shape. Do not modify existing tools.
- [ ] Write integration tests exercising `expand` end-to-end via the MCP wire against a real fixture: a `members` call, a `callees` call, and a deferred-edge call (asserting the unsupported branch survives the wire).
- [ ] Run the integration tests; confirm they pass.
- [ ] Run the full suite with coverage; confirm the threshold holds.
- [ ] Commit.

**Files:** `src/pyeye/mcp/server.py`, `tests/integration/api_redesign/test_traversal_integration.py`.
**Constraints:** The tool docstring must state plainly which edges are supported now and that inbound/reference edges require the reference backend (#333). Mark the tool's relationship to the deprecated tools per existing conventions if applicable.
**Acceptance:** `expand` discoverable and callable via the wire; integration tests pass; full suite green at coverage threshold.

### Task 6.2: Extend the conformance linter for the new shapes

- [ ] Extend `response_linter.py` to validate `Stub` and `ExpandResult` (both branches): the layering check (no source content) and structural floors (required keys per branch; `unsupported`+`reason` on the unsupported branch; `unresolved_call_sites` only on the `callees` supported result).
- [ ] Add adversarial linter tests (well-formed passes; source-content smuggling rejected; malformed/garbled union rejected).
- [ ] Run the conformance suite; confirm it passes.
- [ ] Commit.

**Files:** `tests/conformance/response_linter.py`, adversarial linter tests.
**Constraints:** Validate only `Stub` and `ExpandResult` here; the fuller `OutlineTree`/`Subgraph` linting stays in the broader plan.
**Acceptance:** Linter accepts valid new shapes and rejects violations in both directions; conformance suite green.

---

## Verification gates (between phases)

- [ ] Full test suite green at the coverage threshold.
- [ ] Pre-commit hooks pass (no bypass flags).
- [ ] No `get_references`/`find_references` introduced on the `members` or `callees` path (grep-verified) — the load-bearing trust constraint.
- [ ] New response shapes pass the conformance layering check (no source content).
- [ ] Existing `inspect` tests pass unmodified (the refactor guardrail) — the only intended observable change is the module-member-count drop.

## What this slice deliberately defers

Pagination/cursors, filters, the other four outbound edges (`superclasses`/`subclasses`/`imports`/`enclosing_scope`), `outline`, `trace`, all inbound/Pyright edges (#333), and the re-export-as-public-member refinement for module `members`. These land additively per the broader plan; the registry's `not_yet_implemented` edges flip to `implemented` and the `deferred_reference_backend` edges flip once the Pyright backend exists, with no shape change to `ExpandResult`.
