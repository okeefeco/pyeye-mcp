# imported_by edge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `imported_by` from a deferred reference-backend edge to a supported Jedi/AST-backed `expand` edge — `expand(handle, "imported_by")` returns the project modules that import a target module — with no `ExpandResult` shape change.

**Architecture:** Reuse the deterministic AST import-graph reversal that already lives inside `JediAnalyzer.analyze_dependencies` (no `get_references`), by extracting it into a stable `find_importers` method and extracting `_ModuleSentinel` into a shared leaf so the `edges` resolver can build module stubs without importing `inspect`. A new module-only `resolve_imported_by` resolver plugs into the existing `expand` registry; non-module handles return the honest `not_yet_implemented` branch rather than a misleading measured-empty result.

**Tech Stack:** Python, FastMCP, Jedi (local AST ops only — `file_artifact_cache.get_ast`, `get_project_files`, `_resolve_relative_import`), pytest. Reuses `pyeye.handle.Handle`, the `edges` registry / `EdgeResult` / `build_stub` / `expand` foundation from #340 (#342), and `_resolve_relative_import` from #343.

**Spec:** `docs/superpowers/specs/2026-06-10-imported-by-edge-design.md` (authoritative — contracts, the `EdgeResult | None` convention, the documented dynamic-import ceiling).

**Branch / issue:** `feat/345-imported-by`, issue #345. Off `main` (which already carries #342 + #343).

---

## Hard constraints (apply to every task)

- **No reverse symbol search.** No path for `imported_by` may call `get_references`/`find_references`. The reverse scan is a deterministic AST walk + `_resolve_relative_import` only. This is grep-verified and asserted by a spy test, exactly as `callees` is. This is the load-bearing reason the edge can be promoted at all.
- **No `ExpandResult` / linter shape change.** `imported_by` is a normal member of the existing discriminated union — module → supported `{source, edge, stubs}`; non-module → unsupported `{…, reason: "not_yet_implemented", detail}`. No new fields. The conformance linter should need no code change (its E.* rules already cover any `edge` string and a stub-only supported result).
- **Module-only; non-module → `not_yet_implemented`, never `[]`.** Because a symbol genuinely *can* be imported by name, a measured-empty `[]` for a non-module would be the #332 absence-vs-zero lie. The resolver signals wrong-kind with `None`; `expand` maps that to the unsupported `not_yet_implemented` branch with a kind-specific `detail`.
- **Behavior-preserving extractions.** The `_ModuleSentinel` move and the `find_importers` extraction must not change observable behavior: the existing `inspect` tests AND the existing `analyze_dependencies` tests must pass **unmodified**. If one breaks on something other than the move, stop and reconsider — the extraction changed behavior beyond intent.
- **Reuse, don't duplicate.** `resolve_imported_by` consumes `find_importers`; it must not reimplement the scan. The legacy `analyze_dependencies` is rewired to consume the same `find_importers` — both share one implementation. New code must not depend on the deprecated `analyze_dependencies` method directly.
- **Canonical handles throughout.** Every importer adjacency is a canonical module `Handle`; each module stub is built from the importer's own file (via the shared sentinel), so tests/standalone scripts — which are not importable via `find_module_file` — still produce stubs.
- **One intended observable registry change (with one intended test edit).** Moving `imported_by` from the deferred set to the implemented set flips `edge_status("imported_by")`. The existing status-matrix test that parametrizes `imported_by` under `deferred_reference_backend` (`tests/unit/mcp/operations/test_edges.py`) **must** be updated to reflect the new bucket — this is the *intended* test change, distinct from the behavior-preserving guardrails above. `imported_by` stays in the linter's `_PHASE4_UNMEASURED_EDGES` because `inspect.edge_counts.imported_by` is **not** restored in this slice.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pyeye/_module_sentinel.py` | Create | Shared leaf home for `_ModuleSentinel` (moved from `inspect`). Pure `ast`/`Path` deps; importable by both `inspect` and `edges` without a cycle. |
| `src/pyeye/mcp/operations/inspect.py` | Modify | Import `_ModuleSentinel` from the shared leaf under its existing private alias; remove the local class definition. No other change. |
| `src/pyeye/analyzers/jedi_analyzer.py` | Modify | Extract the reverse-scan into a stable `find_importers` returning `(importer_module, importer_file)` pairs; rewire `analyze_dependencies` to consume it for its `imported_by` field. |
| `src/pyeye/mcp/operations/edges.py` | Modify | Move `imported_by` from the deferred set to the implemented set; add the async `resolve_imported_by` (module → `EdgeResult`; non-module → `None`) to the resolver registry. |
| `src/pyeye/mcp/operations/expand.py` | Modify | Await resolver results that are awaitable; treat a resolver `None` as the `not_yet_implemented` unsupported branch with a synthesized kind-specific `detail`. No change to the `members`/`callees` outcomes. |
| `tests/unit/mcp/operations/test_edges.py` | Modify | Update the status-matrix assertion; add `resolve_imported_by` adjacency / measured-empty / non-module-`None` / no-`get_references` coverage. |
| `tests/integration/jedi_integration/test_module_analysis.py` (and any other `analyze_dependencies` tests) | Reference | Must pass unmodified (extraction parity); add direct `find_importers` unit coverage here or alongside. |
| `tests/unit/mcp/operations/test_expand.py` | Modify | `imported_by` supported (module) and unsupported (`not_yet_implemented`, non-module) over the operation. |
| `tests/integration/api_redesign/test_traversal_integration.py` | Modify | `imported_by` end-to-end via the already-registered MCP `expand` tool. |
| `tests/conformance/test_linter_adversarial_expand.py` | Modify | Dogfood real `imported_by` output (both branches) through the linter; confirm no linter code change. |
| `tests/fixtures/resolve_project/...` | Identify/extend | A target module imported by ≥2 project modules, including a non-package (test/script-style) importer to prove coverage breadth. |

---

## Phase 1: Extract `_ModuleSentinel` to a shared leaf

The prerequisite that lets `edges` build module stubs without importing `inspect`.

### Task 1.1: Move `_ModuleSentinel` into `src/pyeye/_module_sentinel.py`

- [ ] Move the `_ModuleSentinel` class out of `inspect.py` into a new shared leaf module, and have `inspect.py` import it back under its existing private name so every existing call site is unchanged — because `edges` (which must not import `inspect`) needs to construct module Names, and a shared leaf is the cycle-free home (mirroring the `_ast_targets.py` extraction from #340).
- [ ] Confirm the existing `inspect` test suite passes **unmodified** (the move is behavior-preserving) and that the new module can be imported from `edges` without a circular import.
- [ ] Commit.

**Files:** `src/pyeye/_module_sentinel.py`, `src/pyeye/mcp/operations/inspect.py`.
**Constraints:** The shared module must depend only on `ast`/`Path` (no `inspect`/`edges`/`expand` imports), so it stays a true leaf. Preserve the class's public surface exactly — its constructor takes the canonical handle as a **string**. Check for any `isinstance(..., _ModuleSentinel)` uses and ensure they still resolve through the re-imported name.
**Acceptance:** Existing `inspect` tests green unmodified; `_ModuleSentinel` importable from a leaf module with no cycle.
**Risks:** A hidden dependency on an `inspect`-internal symbol would break the leaf property — if found, that symbol must move too or be passed in, not imported back from `inspect`.

---

## Phase 2: Extract `find_importers`

The reusable reverse-scan, lifted out of the deprecated `analyze_dependencies` so new code doesn't build on to-be-removed code.

### Task 2.1: Failing tests for `find_importers`

- [ ] Write tests asserting a new `find_importers` on `JediAnalyzer` returns, for a fixture target module, the importer `(module, file)` pairs for every project module that imports it (directly via `import` and via relative `from`-imports), excludes the target's own file, and dedups — because this is the deterministic adjacency the edge depends on.
- [ ] Write a test asserting the legacy `analyze_dependencies`'s `imported_by` for the same target is unchanged once it is rewired to consume `find_importers` (extraction parity) — because the legacy method must keep its exact output.
- [ ] Write a test asserting an importer that is a **test/script-style** file (a project file outside the importable package roots) is still reported — because coverage breadth (tests + scripts) is a guaranteed property and is exactly what the re-resolution-free approach buys.
- [ ] Run the tests; confirm they fail (method missing).
- [ ] Commit.

**Files:** the `analyze_dependencies` test module (`tests/integration/jedi_integration/test_module_analysis.py`) or a sibling, plus a fixture importer if one is needed.
**Constraints:** Resolution must remain a pure AST walk + `_resolve_relative_import`; the test must not assume any `get_references`. The scan operates at `scope="all"` so the importer set spans the project tree, standalone dirs, namespaces, and extra packages. Pick/extend a fixture so at least two distinct importers exist and at least one is a non-package file.
**Acceptance:** Failing tests pin the `find_importers` adjacency, the dedup, the relative-import case, the test/script-importer case, and the legacy-parity contract.
**Risks:** The existing scan has a heuristic source-text pre-filter (`shares_package` + textual match) before the authoritative AST check — the tests should target the AST outcome, not the pre-filter, so the refactor is free to keep or adjust the pre-filter as long as results are identical.

### Task 2.2: Implement `find_importers` and rewire `analyze_dependencies`

- [ ] Factor the reverse-scan block out of `analyze_dependencies` into `find_importers(module_path, target_file, scope)`, returning `(importer_module, importer_file)` pairs, and rewire `analyze_dependencies` to derive its `imported_by` field from the projected result — so the scan has a single implementation shared by the legacy method and the new edge.
- [ ] Run the new tests and the full existing `analyze_dependencies` suite; confirm the new tests pass and the legacy tests pass **unmodified**.
- [ ] Commit.

**Files:** `src/pyeye/analyzers/jedi_analyzer.py`.
**Constraints:** Pass the target's file in (the edge resolver already holds it via the source sentinel) to avoid re-locating the module and the not-found path. Carry over the pre-filter, the `ast.Import`/`ast.ImportFrom` matching, and `_resolve_relative_import` verbatim. Keep `find_importers` async (it uses `get_project_files`/`read_file_async`).
**Acceptance:** `find_importers` tests pass; legacy `analyze_dependencies` tests pass unmodified; the duplication between the two is gone.
**Risks:** If the legacy `imported_by` output shifts at all, the projection from `(module, file)` pairs back to the sorted module list isn't equivalent — reconcile before proceeding rather than editing the legacy tests.

---

## Phase 3: `resolve_imported_by` + registry move

The edge resolver and its registration.

### Task 3.1: Failing tests for the registry move and `resolve_imported_by`

- [ ] Update the status-matrix test so `imported_by` is asserted as `implemented` (and removed from the `deferred_reference_backend` parametrization) — because the edge legitimately changes bucket; this is the one intended test edit.
- [ ] Write tests asserting `resolve_imported_by` returns the correct canonical importer handles for a fixture module imported by ≥2 modules (including the test/script-style importer), returns a measured-empty result for a module nobody imports, and returns the wrong-kind `None` signal for a non-module handle — because these three outcomes are the resolver's whole contract.
- [ ] Write a test asserting the `resolve_imported_by` path makes no `get_references`/`find_references` call (spy), mirroring the `callees` trust test — the load-bearing constraint.
- [ ] Run the tests; confirm they fail.
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_edges.py`.
**Constraints:** The resolver returns `EdgeResult` for modules and `None` for non-modules (the per-kind not-supported signal the spec introduces); it must not return `EdgeResult([])` for non-modules. Importer adjacents are `(Handle, module-sentinel)` pairs so `expand` can build stubs. The resolver is async.
**Acceptance:** Failing tests pin the new status bucket, the module adjacency, the measured-empty case, the non-module `None`, and the no-reverse-search constraint.
**Risks:** `None`-vs-`EdgeResult([])` is the subtle correctness point — a test must distinguish "non-module → None (not_yet_implemented downstream)" from "module with no importers → EdgeResult([]) (measured none)".

### Task 3.2: Implement `resolve_imported_by` and move the edge

- [ ] Move `imported_by` from the deferred set to the implemented set, implement the async `resolve_imported_by` (module: resolve via `find_importers` using the source sentinel's file → build a `(Handle, module-sentinel)` per importer → dedup → `EdgeResult`; non-module: `None`), and register it in the resolver registry — reusing `find_importers` and the shared sentinel, not reimplementing either.
- [ ] Run the Phase-3 tests and the full suite; confirm green.
- [ ] Grep-verify no `get_references`/`find_references` on the `imported_by` path.
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/edges.py`.
**Constraints:** Build each importer's module Name from its own file (via the shared sentinel), never by re-resolving the importer handle — re-resolution fails for tests/standalone scripts. Determinism: identical importer set and order every run. Fix the scan scope to `"all"`.
**Acceptance:** All Phase-3 tests pass; full suite green; grep confirms no reverse search on the path.
**Risks:** The resolver is the first async member of the registry — make sure it composes with `expand`'s call site (handled in Phase 4); a sync-only assumption there would surface here.

---

## Phase 4: `expand` wiring

Compose the new resolver into the user-facing operation.

### Task 4.1: Failing tests for `expand` over `imported_by`

- [ ] Write tests asserting `expand(handle, "imported_by")` over a module returns the supported branch with module stubs built by the Phase-1 builder, and over a non-module returns the unsupported branch with `reason: "not_yet_implemented"` and a kind-specific `detail` naming the handle's kind — because this is the end-to-end contract and the empty-vs-unsupported distinction.
- [ ] Write a test asserting the supported `imported_by` result carries no `unresolved_call_sites` (callees-only) and the module-with-no-importers case is a supported `stubs: []`, distinct from the non-module unsupported branch — to pin the #332 distinction at the operation layer.
- [ ] Run the tests; confirm they fail.
- [ ] Commit.

**Files:** `tests/unit/mcp/operations/test_expand.py`.
**Constraints:** The non-module `detail` is kind-specific, so it is synthesized for the resolver-`None` path rather than produced by the generic status-keyed unsupported-detail helper. The supported and unsupported branches stay mutually exclusive.
**Acceptance:** Failing tests define both branches for `imported_by`, the kind-specific detail, and the empty-vs-unsupported distinction.
**Risks:** The `None` (wrong-kind) path must stay distinct from the existing source-unresolvable path (which returns a graceful supported-empty for an unresolvable handle) — don't conflate the two.

### Task 4.2: Implement the `expand` changes

- [ ] Update `expand` to await resolver results that are awaitable (so the async `resolve_imported_by` composes with the sync `members`/`callees` resolvers) and to map a resolver `None` to the `not_yet_implemented` unsupported branch with a synthesized kind-specific `detail` — without changing the `members`/`callees` outcomes.
- [ ] Run the Phase-4 tests and the full suite; confirm green (including the unchanged `members`/`callees` expand tests).
- [ ] Commit.

**Files:** `src/pyeye/mcp/operations/expand.py`.
**Constraints:** `members`/`callees` remain synchronous and continue returning `EdgeResult([])` (never `None`) for wrong kinds, so their behavior — and `inspect`'s sync `len(resolve_members(...).handles)` delegation — is untouched. The awaitable bridge must not turn the whole resolver dispatch into something that breaks the sync resolvers.
**Acceptance:** All `expand` tests pass; `members`/`callees` expand behavior unchanged; full suite green.
**Risks:** Over-broadening the async handling could accidentally await a plain `EdgeResult` — guard precisely on awaitability.

---

## Phase 5: Integration + conformance

Surface `imported_by` on the wire and lock its shape into conformance.

### Task 5.1: Wire integration tests

- [ ] Add integration tests exercising `imported_by` end-to-end through the already-registered MCP `expand` tool against a real fixture: a module call (supported, module stubs) and a non-module call (unsupported `not_yet_implemented`) — because the edge must survive the wire as a plain serialisable dict.
- [ ] Run the integration tests and the full suite with coverage; confirm green at the threshold.
- [ ] Commit.

**Files:** `tests/integration/api_redesign/test_traversal_integration.py`.
**Constraints:** No new tool registration is needed — `expand` is already a registered tool; `imported_by` is simply a new edge value. Assert plain-dict/serialisation safety as the existing wire tests do.
**Acceptance:** `imported_by` discoverable and callable via the wire for both branches; full suite green at coverage threshold.

### Task 5.2: Conformance dogfood

- [ ] Add conformance tests that run the real `imported_by` output (supported module result and non-module `not_yet_implemented`) through the response linter and confirm it passes with **no linter code change** — because the existing structural floors already cover a stub-only supported result and the `not_yet_implemented` reason.
- [ ] Confirm `imported_by` remains in the linter's unmeasured-edges set (inspect `edge_counts` is not touched in this slice) and run the conformance suite.
- [ ] Commit.

**Files:** `tests/conformance/test_linter_adversarial_expand.py`.
**Constraints:** Validate only that `imported_by` ExpandResults conform; do not restore or assert any `inspect.edge_counts.imported_by` (deferred). If the linter unexpectedly needs a change, stop and reconsider — the spec's premise is that it does not.
**Acceptance:** Linter accepts both `imported_by` branches; conformance suite green; no inspect `edge_counts` change.

---

## Verification gates (between phases)

- [ ] Full test suite green at the coverage threshold (run with the random-order plugin disabled for a deterministic read).
- [ ] Pre-commit hooks pass (no bypass flags).
- [ ] No `get_references`/`find_references` introduced on the `imported_by` path (grep-verified) — the load-bearing trust constraint.
- [ ] Existing `inspect` tests and existing `analyze_dependencies` tests pass **unmodified** (the two extraction guardrails).
- [ ] The only intended test edit is the status-matrix bucket change for `imported_by`; `ExpandResult` and linter shapes are unchanged.

## What this slice deliberately defers

Symbol-level `imported_by` (the non-module `not_yet_implemented` path flips to real results later, no shape change), literal-string `importlib.import_module` detection, restoring `inspect.edge_counts.imported_by`, and the symbol-level reverse edges (`callers`/`references`) that genuinely require the Pyright backend (#333).
