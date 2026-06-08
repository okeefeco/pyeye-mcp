# Expand-core design — `expand(handle, edge)` for `members` + `callees`

**Date:** 2026-06-08
**Issue:** #340
**Status:** design (pre-implementation)
**Branch:** `feat/340-expand-core`

## 1. Context & goal

The redesigned pyeye API ships `resolve` and `inspect` (orient: "what is this?"). The next layer is **progressive-disclosure traversal** — `outline`, `expand`, `trace` — fully designed in the reviewer-approved plan `docs/superpowers/plans/2026-06-02-outline-expand-trace.md`, which is scoped to the edges Jedi produces reliably today (outbound/structural) and explicitly defers inbound/reference edges to the Pyright backend (#333).

This spec carves out a **thin vertical learning slice** of that plan: `expand(handle, edge)` working end-to-end and callable on the MCP wire, for **exactly two edges** — `members` and `callees` — built on the proper shared foundation. It is the first slice, chosen to validate the foundation + wire on the easy edge (`members`) and to **de-risk the one genuinely-tricky reliable edge (`callees`) early**, before committing to the full plan. The deeper goal is dogfooding knowledge: cursor-less expand, the unsupported-edge signal, the `inspect` extraction, and — most of all — confirming `callees` stays local and reliable.

## 2. Scope

**In:**

- `stubs.py` — single-source `Stub` builder.
- `edges.py` — edge-resolver registry with a per-edge **status model**; `members` and `callees` resolvers implemented.
- `expand.py` — single-hop expansion, no pagination/filters.
- `inspect.py` — refactor to route its stub-shaped fields **and** member enumeration through `stubs.py`/`edges.py` (no change to `inspect`'s observable output).
- `server.py` — register one new `@mcp.tool`: `expand`.
- Minimal conformance-linter extension for `Stub` + `ExpandResult`.

**Out (deferred to the full plan / later phases):**

- Pagination/cursors, filters (`include_tests`/`module_pattern`/`same_package`).
- The other four supported outbound edges: `superclasses`, `subclasses`, `imports`, `enclosing_scope`.
- `outline`, `trace`.
- All inbound/reference edges (`callers`, `references`, `imported_by`, `overrides`/`overridden_by`, `decorated_by`/`decorates` — non-exhaustive; §4.3 is the authoritative deferred list) — require the Pyright reference backend (#333).

## 3. Architecture

### 3.1 Components / file map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pyeye/mcp/operations/stubs.py` | Create | The single-source `Stub` builder: Jedi name / handle → `{handle, kind, scope, signature?, line_start, line_end}`. No source content. Reuses existing helpers (signature, kind normalisation, scope classification, location span) — calls them, never reimplements. |
| `src/pyeye/mcp/operations/edges.py` | Create | Edge-resolver registry + per-edge status (`implemented` / `deferred_reference_backend` / `not_yet_implemented`). Implements `members` and `callees` resolvers (source handle → adjacent canonical handles). The single place edge support is declared. |
| `src/pyeye/mcp/operations/expand.py` | Create | `expand(handle, edge)` — single hop via the registry → `ExpandResult`. No cursor/filter in this slice. |
| `src/pyeye/mcp/operations/inspect.py` | Modify | Route stub-shaped fields + member enumeration through the shared modules. No observable output change. |
| `src/pyeye/mcp/server.py` | Modify | Register `expand` as a new `@mcp.tool`. Do not touch existing tools. |
| `tests/unit/mcp/operations/test_stubs.py` | Create | Stub builder across kinds; no-content invariant. |
| `tests/unit/mcp/operations/test_edges.py` | Create | `members`/`callees` adjacency on fixtures; each non-implemented edge returns its status; **assert callees path makes no `get_references` call**. |
| `tests/unit/mcp/operations/test_expand.py` | Create | Expand over members/callees; deferred/not-yet/unknown edge signals; empty-vs-unsupported distinction. |
| `tests/integration/api_redesign/test_traversal_integration.py` | Create | `expand` end-to-end via the MCP wire against a real fixture. |
| `tests/conformance/response_linter.py` | Modify | Validate `Stub` + `ExpandResult` (both union branches): layering (no source content) + structural floors. |

### 3.2 Data flow

`expand(handle, edge)` → resolve `handle` to a Jedi name (reuse `inspect._find_jedi_name_for_handle`) → registry looks up `edge`'s status:

- `implemented` → run resolver → adjacent canonical handles → `stubs.py` builds a `Stub` per handle → `ExpandResult{source, edge, stubs[, unresolved_call_sites]}`.
- otherwise → `ExpandResult{source, edge, unsupported: true, reason, detail}`.

### 3.3 The `inspect` refactor (reuse, not duplication)

`stubs.py` becomes the one place stub fields are assembled; `inspect.py` is rewired to call it. `edges.py`'s `members` resolver becomes the one enumeration of container members; `inspect`'s `edge_counts.members` becomes `len(members_resolver(...))` (killing the duplication #330/#339 flagged).

**One intended observable change — module member counts now exclude imports.** Today `_count_module_members` is a flat `len(get_names(all_scopes=False, definitions=True))`, which counts *imported* names as members (e.g. `mypackage._core.widgets` reports 7, of which `ClassVar` is an import). The shared resolver excludes imports (§5.1), so module counts drop by the number of top-level imports (widgets: 7 → 6). This is a deliberate correctness fix, and it keeps `members` disjoint from the future `imports` edge — NOT an accidental regression. Class member counts are unaffected (the class counter already matches by `full_name` prefix + exact depth, which never includes imports).

**Guardrail (checkable):** every existing `inspect` test must stay green **unmodified**. This holds despite the module-count change because those tests assert lower bounds, not exact counts (`test_module_has_members_count` → `>= 4`; the class test → `>= 5`; widgets 7 → 6 still satisfies `>= 4`). If any `inspect` test asserting an **exact** count (or an upper bound) needs editing, that is the signal the extraction changed behaviour *beyond* the intended import exclusion — stop and reconsider.

## 4. Contracts

### 4.1 `Stub`

```text
{
  "handle": str,          # canonical definition-site handle
  "kind": str,            # normalised kind (class|function|method|module|attribute|property|variable)
  "scope": "project" | "external",
  "signature": str,       # one-line, present for callable kinds; ABSENT otherwise
  "line_start": int,
  "line_end": int
}
```

No source content ever — pointers + the same one-line signature form `inspect` already produces.

### 4.2 `ExpandResult` — discriminated union

`expand` is a **new** tool, so a discriminated union is intentional and correct here (contrast #336, which forbade leaking a new union shape onto a *deprecated* tool).

**Supported edge:**

```text
{
  "source": str,                 # the source handle (canonical)
  "edge": str,                   # the edge requested
  "stubs": [Stub, ...],          # adjacents; [] means MEASURED, none found
  "unresolved_call_sites": int   # callees ONLY: count of call sites Jedi could not resolve
}
```

- No `cursor` field in this slice → per the spec convention, absent cursor = "complete". Forward-compatible: pagination later just begins populating `cursor`; the shape is unchanged.
- `unresolved_call_sites` appears only on the `callees` path. See §5.2 / §6.

**Not-supported edge:**

```text
{
  "source": str,
  "edge": str,
  "unsupported": true,
  "reason": "deferred_reference_backend" | "not_yet_implemented" | "unknown_edge",
  "detail": str   # human-readable explanation
}
```

- This is the #332 absence-vs-zero contract made explicit: an edge we cannot measure is NEVER reported as `stubs: []`. The `reason` distinguishes "requires the reference backend (#333)" from "reliable, planned, just not built in this slice" from "no such edge name".

### 4.3 Edge status model (`edges.py`)

| Status | Edges | `expand` behaviour |
|--------|-------|--------------------|
| `implemented` | `members`, `callees` | run resolver → stubs |
| `not_yet_implemented` | `superclasses`, `subclasses`, `imports`, `enclosing_scope` | unsupported, reason `not_yet_implemented` |
| `deferred_reference_backend` | `callers`, `references`, `read_by`, `written_by`, `passed_by`, `imported_by`, `overrides`, `overridden_by`, `decorated_by`, `decorates` | unsupported, reason `deferred_reference_backend` |
| (unknown name) | — | unsupported, reason `unknown_edge` |

## 5. Resolvers

### 5.1 `members` (the easy edge)

Direct structural members of a container:

- **class** → methods + nested classes + class-level attributes/properties **defined in the class** (direct; inherited members excluded — they are reachable via the `superclasses` edge, out of scope here).
- **module** → top-level classes, functions, and module-level variables **defined in this module**. **Imports and re-exports are excluded** — an imported name is a dependency, not a structural member, and belongs to the `imports` edge (deferred). See the re-export caveat below.
- **non-container** (function/method/variable/...) → `[]` (measured: genuinely no members).

Enumerated from the container's own file (local, reliable); each member → **canonical handle** (via `canonicalization`). The count is then `len(...)` of that list, so `members` and `edge_counts.members` share one enumeration.

**The two counters differ in mechanism — only one needs an import filter:**

- `_count_class_members` matches by `full_name` prefix + **exact depth** (`handle_depth + 1`), which already yields direct, defined members and never includes imports. The resolver reuses this matching and adds handle construction.
- `_count_module_members` is a **flat** `len(get_names(all_scopes=False, definitions=True))`, which **does include top-level imports** as definitions. The resolver must therefore **exclude imports** for modules (e.g. an AST top-level walk over class/function/assign nodes, skipping `Import`/`ImportFrom`, then canonicalising each) — this is both the import-exclusion fix (§3.3) and the single most substantive piece of new logic in `members` (producing a canonical handle per member is real work, not a rename). The planner should treat module-member enumeration as its own task.

**Re-export caveat (deferred):** excluding imports also excludes `__init__.py` re-exports (e.g. `from ._impl import Widget` in a package init), so `members` of a re-exporting package will omit its re-exported public surface in this slice. Distinguishing re-export-as-public-member from import-for-use needs `__all__`/canonical-re-export analysis (the `imports`/re-export work) and is **deferred to the full plan**. For this slice, `members` is strictly "defined in this file."

### 5.2 `callees` (the risk-prober)

Outbound call edges of a **function/method** (other kinds → `[]` for this slice; module-level top-level calls noted as a future extension). Mechanics:

1. Locate the def node in the file's **cached AST** (`file_artifact_cache.get_ast` — reuse, per #339).
2. Walk the body for `ast.Call` nodes, **stopping at nested `def`/`async def`/`lambda`/`class` boundaries** — a nested function's calls are *its* callees, not the outer's.
3. For each call, resolve the call target's position via `goto(line, col, follow_imports=True)` → definition → canonicalize → handle. Dedup by handle.
4. Count call sites whose target `goto` could not resolve → `unresolved_call_sites`.

**Load-bearing constraint:** `callees` is **forward** resolution — one `goto` per call site, the same local, deterministic mechanism `_resolve_base_class_via_jedi` already uses reliably. It must **never** touch `get_references` / project-wide reverse search (the broken #332 path). A unit test + a grep gate assert this.

**Implementation fallback:** if `callees` cannot be done reliably within local AST + per-call-site `goto` (i.e. it would fall through to reverse search), demote it to `not_yet_implemented` and ship `members`-only. Expectation: it holds.

## 6. Guarantees & non-guarantees

Stated precisely, because the distinction is the whole point of the honesty contract.

**Guaranteed (firm):**

- **Soundness — no false data.** Every returned stub is a real, canonical definition. Every `callees` entry came from an actual `ast.Call` whose target `goto` resolved. We never invent an edge, and never return `[]` to mean "couldn't measure".
- **`members` completeness.** A class/module's source-defined members are a closed, statically-determinable set; `members` enumerates them exhaustively.
- **Determinism & locality of `callees`.** Same input → same output; computed from the function's own file + per-call-site `goto`; no project-wide reverse search anywhere on the path.

**Explicitly NOT guaranteed:**

- **`callees` completeness under dynamic dispatch.** Calls Jedi cannot statically resolve — `getattr(obj, name)()`, calls through a variable of un-inferable type, dict-of-callbacks — are omitted. This is the **universal boundary of static call-graph extraction** (no static tool, Jedi or Pyright, can resolve a runtime-determined target), NOT a defect in this implementation and NOT the #332 non-determinism. It is surfaced honestly via `unresolved_call_sites: N`, so `callees` reads as "≥ these edges (and N call sites I saw but could not statically resolve)", never an over-claimed "exactly these".

This is categorically different from why `callers`/`references` are deferred: those rely on `get_references`, which is *non-deterministically wrong* (returns 3 where the truth is 83 depending on anchor position) — untrustworthy numbers, not a known static ceiling.

## 7. Testing & verification

- **Unit:** `test_stubs` (shape per kind, no content, signature presence, external scope); `test_edges` (members/callees adjacency on fixtures; each non-implemented edge → its status; **explicit assert: callees path makes no `get_references` call**); `test_expand` (members/callees → stubs; deferred edge → `deferred_reference_backend`; not-yet edge → `not_yet_implemented`; unknown edge → `unknown_edge`; a function's `members` → `stubs: []` *distinct from* unsupported; `unresolved_call_sites` present and correct on a fixture with a dynamic call).
- **Integration:** `expand` over the MCP wire against a real fixture — a members call, a callees call, a deferred-edge call.
- **Refactor guardrail:** all existing `inspect` tests pass **unmodified**.
- **Conformance:** extend `response_linter` for `Stub` + `ExpandResult` (both branches) — layering (no source content) + structural floors (required keys; `unsupported`/`reason` on the unsupported branch; `unresolved_call_sites` only on `callees`).

**Verification gates (between/within the work):**

- Full suite green at the coverage threshold.
- Pre-commit clean (no bypass flags).
- **Grep-verified: no `get_references`/`find_references` introduced on the `members` or `callees` path** — the load-bearing trust constraint.
- New response shapes pass the conformance layering check (no source content).

## 8. Relationship to the broader plan & what's deferred

This slice is a strict subset of `docs/superpowers/plans/2026-06-02-outline-expand-trace.md` (its Phase 1 foundation + a reduced Phase 3 `expand` + Phase 5 registration/conformance for just these shapes). Everything else in that plan — the remaining outbound edges, `outline`, `trace`, pagination, filters, and the inbound/Pyright edges (#333) — is deferred and lands additively later: the registry's `not_yet_implemented` edges flip to `implemented`, and the `deferred_reference_backend` edges flip once the Pyright backend exists, with no shape change to `ExpandResult`.
