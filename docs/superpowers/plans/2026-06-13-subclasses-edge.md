# subclasses edge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `subclasses` from a `not_yet_implemented` edge to a supported Jedi/AST-backed `expand` edge — `expand(class_handle, "subclasses")` returns the project classes that subclass the target as canonical class stubs — with no `ExpandResult` shape change and no `expand.py` change.

**Architecture:** `subclasses` is the plan's deliberate "directionally-inbound but reliably-static" exception: it is produced by an AST class-graph walk + forward `goto`/`resolve_canonical` (no `get_references` / reverse symbol search), so it belongs with `members`/`callees`/`imported_by`. A new synchronous-wrapping resolver `resolve_subclasses` **reuses the existing `JediAnalyzer.find_subclasses`** (`jedi_analyzer.py:3070`) verbatim — same call shape `_count_subclasses` already uses (`scope="main"`, `include_indirect=True`) so the expanded list stays consistent with `inspect.edge_counts.subclasses`. Wrong-kind handles return a measured-empty `EdgeResult([])` (mirroring `members`/`callees`), because only a class *can* be subclassed — `[]` for a non-class is true by definition, not the #332 absence-vs-zero lie. This keeps the slice strictly additive: `edges.py` registry + one resolver, no `None` path, no `expand.py` edit.

**Tech Stack:** Python, FastMCP, Jedi (forward ops only — `find_subclasses`, `file_artifact_cache.get_script`/`get_ast`, `goto`, `resolve_canonical`), pytest. Reuses `pyeye.handle.Handle`, the `edges` registry / `EdgeResult` / `build_stub` / `expand` foundation from #340 (#342), and the existing `find_subclasses` analyzer method.

**Spec / precedent:** This slice has no dedicated spec doc. Its template is the merged `imported_by` promotion — design `docs/superpowers/specs/2026-06-10-imported-by-edge-design.md`, plan `docs/superpowers/plans/2026-06-10-imported-by-edge.md` (PR #346). Where this plan diverges from that template, the divergence is called out explicitly below.

**Branch / issue:** `feat/348-subclasses-edge`, issue #348. Off `main` (which carries #342 + #345/#346).

> **Note on the issue's cited reference.** Issue #348 cites `docs/superpowers/plans/2026-06-02-outline-expand-trace.md` (Task 1.3/1.4) for the "reliably-static" justification. **That file does not exist in this tree.** The justification is nonetheless verified directly against the code (see Phase 0) and against the `imported_by` design doc, which states the same `subclasses` carve-out reasoning. Do not block on the missing doc.

---

## Key design decisions (locked before implementation)

1. **Wrong-kind → measured-empty, NOT `None`/`not_yet_implemented`.** (User-confirmed.) `resolve_subclasses` returns `EdgeResult([])` for a non-class handle. Rationale: nothing but a class can be subclassed, so `subclasses: []` for a function/variable/module is *true by definition* — exactly the `members`/`callees` case (`[] for the wrong kind is true by definition`), **not** the `imported_by` case (a symbol genuinely *can* be imported, so `[]` there would be a lie). Consequence: `resolve_subclasses` **never returns `None`**, so `expand.py` is **untouched** — its hardcoded "supported for modules only" `None`-branch detail stays correct (only `imported_by` uses `None`). This is the single biggest simplification versus the `imported_by` template.

2. **Reuse `find_subclasses` directly — no extraction.** Unlike `imported_by` (whose scan was buried inside the deprecated `analyze_dependencies`, forcing a `find_importers` extraction), `find_subclasses` is already a standalone public `JediAnalyzer` method. `resolve_subclasses` calls it as-is. **No analyzer refactor, no `find_importers`-style extraction, no `ModuleSentinel`-style new leaf.**

3. **Call shape mirrors `_count_subclasses` exactly: `scope="main"`, `include_indirect=True`, `show_hierarchy=False`.** This is load-bearing for the progressive-disclosure contract: `inspect.edge_counts.subclasses` is computed with that exact shape (`inspect.py:757-763`), so `len(expand(C,"subclasses").stubs)` must equal `inspect(C).edge_counts.subclasses`. `scope="main"` (project-internal only, excludes stdlib/third-party/namespaces) also matches the issue's "project classes that subclass the target". `include_indirect=True` means this single-hop edge intentionally returns the full project subclass closure (direct + indirect) — a deliberate divergence from `members`/`callees` direct-only semantics, justified by count/list consistency. **Constraint:** if a later slice changes either `_count_subclasses` or this resolver's call shape, it must change both together.

---

## Hard constraints (apply to every task)

- **No reverse symbol search.** No path for `subclasses` may call `get_references` / `find_references`. `find_subclasses` resolves bases via AST walk + forward `goto(follow_imports=True)` + `resolve_canonical` only (verified in Phase 0). This is grep-verified and asserted by a spy test, exactly as `callees`/`imported_by` are. This is the load-bearing reason the edge can be promoted at all.
- **No `ExpandResult` / linter shape change.** `subclasses` is a normal member of the existing discriminated union — class → supported `{source, edge, stubs}`; non-class → supported `{source, edge, stubs: []}` (measured-none). No new fields, no `unresolved_call_sites` (callees-only), no `None` path. The conformance linter must need no code change.
- **`expand.py` is not modified.** If implementing `subclasses` appears to require an `expand.py` change, stop — it means the `None` path crept back in, contradicting decision (1).
- **Behavior-preserving reuse.** `resolve_subclasses` wraps `find_subclasses`; it must not reimplement the subclass search and must not modify `find_subclasses`. The legacy `find_subclasses` tool and all its existing tests must pass **unmodified**. The existing `inspect.edge_counts.subclasses` tests must also pass unmodified.
- **Canonical class stubs, with breadth.** Each adjacency is a canonical class `Handle`; each stub is built from a Jedi `Name` obtained by **forward enumeration over the subclass's own file** — copy the pattern from `_class_members` (`edges.py:233-274`): `get_script(subclass_file).get_names(...)` filtered to the entry whose `full_name` equals the subclass's `full_name` from the `find_subclasses` dict — **not** by dotted-handle re-resolution. Re-resolution by handle drops subclasses defined in non-importable files (e.g. a `class Impl(Base)` in a `tests/` file — which `scope="main"` *does* find) and is fragile on macOS symlinked temp dirs; file-based resolution preserves both breadth and correctness.
- **One intended observable registry change (with one intended test edit).** Moving `subclasses` from `_NOT_YET_IMPLEMENTED_EDGES` to `_IMPLEMENTED_EDGES` flips `edge_status("subclasses")`. The status-matrix test (`tests/unit/mcp/operations/test_edges.py:130-141`) parametrizes `subclasses` under `not_yet_implemented`; it **must** be updated (drop it from that param list; add a `test_subclasses_is_implemented` mirroring `test_imported_by_is_implemented`). This is the *intended* test edit, distinct from the behavior-preserving guardrails.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pyeye/mcp/operations/edges.py` | Modify | Move `subclasses` from `_NOT_YET_IMPLEMENTED_EDGES` to `_IMPLEMENTED_EDGES`; add the (async) `resolve_subclasses` resolver (class → `EdgeResult` of canonical class `(Handle, Name)` pairs; non-class → `EdgeResult([])`); register it in `EDGE_RESOLVERS`. Update the module docstring's status table + the `EDGE_RESOLVERS` comment to list `subclasses`. |
| `src/pyeye/mcp/operations/expand.py` | **Unchanged** | Already awaits awaitable resolver results and already builds stubs per `(handle, Name)`. No edit (decision 1). Listed here only to assert "no change". |
| `src/pyeye/analyzers/jedi_analyzer.py` | **Unchanged** | `find_subclasses` reused as-is. No edit. |
| `tests/unit/mcp/operations/test_edges.py` | Modify | Update the status-matrix assertion (the one intended edit). Add `resolve_subclasses` coverage: class with ≥2 subclasses incl. an indirect one and a test/script-file subclass → correct canonical class handles; class with no subclasses → `EdgeResult([])` (measured-none); non-class handle → `EdgeResult([])` (measured-none, NOT `None`); the no-`get_references` spy. |
| `tests/unit/mcp/operations/test_expand.py` | Modify | `expand(class, "subclasses")` → supported with class stubs; `expand(non_class, "subclasses")` → supported `stubs: []` (NOT the unsupported branch); supported result carries no `unresolved_call_sites`; **count/list consistency** assertion against `inspect(...).edge_counts.subclasses`. |
| `tests/integration/api_redesign/test_traversal_integration.py` | Modify | `subclasses` end-to-end via the already-registered MCP `expand` tool — class (supported, stubs) and non-class (supported, `stubs: []`) — as plain serialisable dicts. |
| `tests/conformance/test_linter_adversarial_expand.py` | Modify | Dogfood real `subclasses` output (class result + non-class measured-empty) through `lint_response(result, "expand")`; confirm **no linter code change**. |
| `tests/fixtures/...` | Identify/extend | A base class with ≥2 project subclasses including (a) an indirect/grandchild subclass and (b) a subclass defined in a non-importable file (e.g. a test/script-style module) to prove breadth. Reuse an existing `find_subclasses` fixture if one already covers this. |

---

## Phase 0: Verify the load-bearing precondition

Confirm the "reliably-static" claim before building on it, since the cited plan doc is missing.

### Task 0.1: Confirm `find_subclasses` never reaches `get_references`

- [ ] Trace the `find_subclasses` call tree (`_resolve_direct_subclass_fqns`, `_resolve_aliased_bases`, `_canonical_cached`/`resolve_canonical`, `get_project_files`, the AST helpers) and confirm none calls `get_references`/`find_references` — because the entire promotion depends on the edge being forward-only. Grep is sufficient; the known `get_references` call sites in `jedi_analyzer.py` are all on `find_references`-family paths, not the subclass path.
- [ ] Confirm `inspect.edge_counts.subclasses` is computed via `find_subclasses(scope="main", include_indirect=True, show_hierarchy=False)` (`inspect.py:_count_subclasses`) so the resolver's call shape can match it.

**Files:** none modified (investigation).
**Acceptance:** Documented confirmation (in the task's notes / commit message of Phase 1) that the subclass path is forward-only and the count call shape is known.
**Risks:** If any helper *does* reach `get_references`, the promotion premise is false — stop and escalate; the edge would belong with the deferred reference edges, not this slice.

---

## Phase 1: `resolve_subclasses` + registry move

The whole edge: resolver, registration, and the status flip. (No extraction phases are needed — contrast the `imported_by` plan's Phases 1–2.)

### Task 1.1: Failing tests for the registry move and `resolve_subclasses`

- [ ] Update the status-matrix test so `subclasses` is asserted `implemented` (drop it from the `not_yet_implemented` parametrize at `test_edges.py:132`; add a `test_subclasses_is_implemented` mirroring the existing `test_imported_by_is_implemented`) — the one intended test edit.
- [ ] Write tests asserting `resolve_subclasses` returns the correct canonical **class** handles for a fixture base class with ≥2 project subclasses — including at least one **indirect** (grandchild) subclass and one subclass defined in a **non-importable file** (proving `scope="main"` breadth + file-based stub construction) — because the canonical class adjacency (direct + indirect) is the resolver's whole job.
- [ ] Write a test asserting a class with **no** project subclasses yields `EdgeResult([])` (measured-none).
- [ ] Write a test asserting a **non-class** handle (function / variable / module) yields `EdgeResult([])` — the measured-empty wrong-kind result — and explicitly **not** `None`, because that distinction (decision 1) is what keeps `expand.py` untouched.
- [ ] Write a spy test asserting the `resolve_subclasses` path makes no `jedi.Script.get_references` call, mirroring the `callees`/`imported_by` spies — the load-bearing trust constraint.
- [ ] Run the tests; confirm they fail (resolver missing / status still `not_yet_implemented`).
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_edges.py`; fixtures as needed.
**Constraints:** Each adjacency is a `(canonical class Handle, Jedi Name)` pair so `expand` can build a class stub (with signature) without re-resolving. The resolver returns `EdgeResult` for every kind — `EdgeResult(adjacents)` for a class, `EdgeResult([])` for everything else — and never `None`. Tests must pin the canonical handles (dotted FQNs), the direct+indirect closure, and the no-reverse-search constraint. Use **real fixture directories**, not symlinked temp dirs, for any Jedi-backed resolution (Jedi `goto`/`resolve_canonical` degrade on macOS `/var`→`/private/var` symlinks).
**Acceptance:** Failing tests pin the new status bucket, the class adjacency (incl. indirect + non-importable-file subclass), the measured-empty no-subclass case, the non-class measured-empty case, and the no-`get_references` spy.
**Risks:** `find_subclasses` returns a discriminated union (`{"ambiguous": False, "subclasses": [...]}` vs `{"ambiguous": True, "candidates": [...]}`). With an FQN input it never returns the ambiguous variant (as `_count_subclasses` asserts at `inspect.py:765-767`) — the resolver should carry the **same defensive `assert not result.get("ambiguous")`** for its canonical-handle input rather than handle a `candidates` branch, so a future regression surfaces loudly instead of silently yielding an empty list.

### Task 1.2: Implement `resolve_subclasses` and move the edge

- [ ] Move `subclasses` from `_NOT_YET_IMPLEMENTED_EDGES` to `_IMPLEMENTED_EDGES`, implement `resolve_subclasses` (class kind: `await find_subclasses(handle, scope="main", include_indirect=True, show_hierarchy=False)` → for each returned subclass, build a canonical class `Handle` from its FQN and a `build_stub`-compatible Jedi `Name` via forward enumeration over the subclass's own file → dedup by handle string, deterministic order → `EdgeResult`; non-class kind: `EdgeResult([])`), and register it in `EDGE_RESOLVERS` — reusing `find_subclasses`, not reimplementing it.
- [ ] Update the `edges.py` module-docstring status table and the `EDGE_RESOLVERS` comment so `subclasses` is listed under implemented (keeping the file as the single source of truth, per its own docstring).
- [ ] Run the Phase-1 tests and the full suite; confirm green.
- [ ] Grep-verify no `get_references`/`find_references` on the `subclasses` path.
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/edges.py`.
**Constraints:** Build each subclass's Jedi `Name` from its own file (the `find_subclasses` result carries `file`/`line`/`full_name`), mirroring `_class_members`' `get_names`-filtered-by-`full_name` approach — never by dotted-handle re-resolution (breadth + symlink robustness). Determinism: identical subclass set and order every run (sort or first-seen-dedup, not set iteration order). Fix `scope="main"`, `include_indirect=True` to match `_count_subclasses`. The resolver is `async` (it awaits `find_subclasses`); `expand` already awaits awaitable results.
**Acceptance:** All Phase-1 tests pass; full suite green; `find_subclasses` and `inspect.edge_counts.subclasses` tests pass unmodified; grep confirms no reverse search on the path; `expand.py` unchanged.
**Risks:** (1) Name production is the only genuinely new logic — if forward file-enumeration cannot produce a `Name` for some subclass (e.g. a transient cache miss), drop that adjacency rather than invent a partial stub, and prefer a path that keeps `len(stubs)` equal to the edge_count (see Phase 2 consistency test); investigate any divergence rather than masking it. (2) `find_subclasses` is `async` — the resolver is the second async member of the registry after `imported_by`; `expand`'s `isawaitable` bridge already handles this, but confirm via the Phase-2 tests.

---

## Phase 2: `expand` operation-layer behavior

Confirm the edge composes correctly through `expand` — **with no `expand.py` change**.

### Task 2.1: Tests for `expand` over `subclasses`

- [ ] Write tests asserting `expand(class_handle, "subclasses")` returns the supported branch with canonical class stubs (built by the existing stub builder), and `expand(non_class_handle, "subclasses")` returns the **supported** branch with `stubs: []` (measured-none) — explicitly **not** the unsupported `not_yet_implemented` branch — because the measured-empty wrong-kind contract (decision 1) is the defining behavior of this slice.
- [ ] Write a test asserting the supported `subclasses` result carries **no** `unresolved_call_sites` key (callees-only).
- [ ] Write a **count/list consistency** test: `len(expand(C, "subclasses")["stubs"]) == inspect(C)…edge_counts.subclasses` for a fixture class — the progressive-disclosure contract that justifies the shared `scope="main"`/`include_indirect=True` call shape.
- [ ] Run the tests; confirm they pass against the Phase-1 implementation (this phase should require **no `expand.py` edit** — if a test forces one, the `None` path regressed; stop).
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_expand.py`.
**Constraints:** The non-class case must land on the *supported* branch (`stubs: []`), never the unsupported branch — this is the observable proof that `subclasses` took the `members`/`callees` measured-empty route, not the `imported_by` `None` route. Do not assert a kind-specific unsupported detail (there is none for this edge).
**Acceptance:** All `subclasses` `expand` tests pass; `members`/`callees`/`imported_by` `expand` behavior unchanged; `expand.py` unmodified; the count==len consistency holds.
**Risks:** If a fixture class's `edge_counts.subclasses` and `len(stubs)` diverge, the resolver's enumeration or dedup differs from `find_subclasses`' result list — reconcile (likely a Name-production drop or a dedup-key mismatch) rather than relaxing the assertion.

---

## Phase 3: Integration + conformance

Surface `subclasses` on the wire and lock its shape into conformance.

### Task 3.1: Wire integration tests

- [ ] Add integration tests exercising `subclasses` end-to-end through the already-registered MCP `expand` tool against a real fixture: a class call (supported, class stubs) and a non-class call (supported, `stubs: []`) — because the edge must survive the wire as a plain serialisable dict.
- [ ] Run the integration tests and the full suite with coverage; confirm green at the threshold.
- [ ] Commit.

**Files:** `tests/integration/api_redesign/test_traversal_integration.py`.
**Constraints:** No new tool registration — `expand` is already registered; `subclasses` is simply a new edge value. Assert plain-dict/serialisation safety as the existing wire tests do. Use a real fixture project (no symlinked temp dirs) so Jedi base-resolution inside `find_subclasses` is reliable.
**Acceptance:** `subclasses` discoverable and callable via the wire for both branches; full suite green at coverage threshold.

### Task 3.2: Conformance dogfood

- [ ] Add conformance tests that run the real `subclasses` output (a class result with stubs and a non-class measured-empty result) through the response linter and confirm it passes with **no linter code change** — because the existing structural floors already accept any `edge` string and a stub-only supported result.
- [ ] Run the conformance suite.
- [ ] Commit.

**Files:** `tests/conformance/test_linter_adversarial_expand.py`.
**Constraints:** Validate only that `subclasses` `ExpandResult`s conform. `subclasses` is a class-only edge in `edge_counts`, so it is already measured there (not in the linter's unmeasured-edges set, unlike `imported_by`) — do **not** alter the linter's measured/unmeasured edge sets. If the linter unexpectedly needs a change, stop and reconsider — the premise is that it does not.
**Acceptance:** Linter accepts both `subclasses` branches; conformance suite green; no linter code change.

---

## Verification gates (between phases)

- [ ] Full test suite green at the coverage threshold (run with the random-order plugin disabled, `-p no:randomly`, for a deterministic read).
- [ ] Pre-commit hooks pass (no bypass flags).
- [ ] No `get_references`/`find_references` introduced on the `subclasses` path (grep-verified) — the load-bearing trust constraint.
- [ ] `find_subclasses` legacy tests **and** existing `inspect.edge_counts.subclasses` tests pass **unmodified** (behavior-preserving reuse).
- [ ] `expand.py` and `jedi_analyzer.py` are unchanged; the only production edit is `edges.py`.
- [ ] The only intended test edit beyond new tests is the status-matrix bucket change for `subclasses`; `ExpandResult` and linter shapes are unchanged.

## What this slice deliberately defers (issue #348 "Out")

`superclasses`, `imports`, and `enclosing_scope` (the other `not_yet_implemented` edges — separate slices); any reference-backend work (`callers`/`references`, deferred on #333); restoring/altering symbol-level reverse edges. The `trace` primitive is parallelizable — it consumes the `EDGE_RESOLVERS` registry and auto-gains `subclasses`-follow once both land; this slice is the single writer to `edges.py` for `subclasses`.
