# imported_by edge design — promote `imported_by` to a Jedi/AST-backed `expand` edge

**Date:** 2026-06-10
**Issue:** #345
**Status:** design (pre-implementation)
**Branch:** `feat/345-imported-by`

## 1. Context & goal

The redesigned pyeye API ships `expand(handle, edge)` for the outbound/structural
edges Jedi produces reliably today — currently `members` and `callees` (#340, merged
in #342). Inbound/reference edges (`callers`, `references`, …) are deferred to the
Pyright reference backend (#333) because their only implementation route is
project-wide `get_references`, which is **non-deterministically wrong** (#332).

`imported_by` currently sits in `edges._DEFERRED_REFERENCE_BACKEND_EDGES` alongside
those edges, so `expand(handle, "imported_by")` returns the unsupported branch with
`reason: deferred_reference_backend`. **That categorisation is wrong.** `imported_by`
is computable **statically**: `JediAnalyzer.analyze_dependencies` already produces it
via a deterministic AST import-graph reversal with **zero `get_references`** on the
path (now correct for relative imports after #343). That is exactly the "local
Jedi/AST ops, no reverse search" criterion that marks an edge supported-now — the same
reasoning the plan already uses to carve out `subclasses` (directionally inbound, but
reliably produced by AST-walk + `goto`).

**Goal:** decouple `imported_by` from #333 and promote it to a **supported**
Jedi/AST-backed edge — `expand(handle, "imported_by")` returns the project modules
that import a target **module** — reusing the existing reverse-scan logic (and #343's
`_resolve_relative_import`), with **no `ExpandResult` shape change**.

## 2. Scope

**In:**

- Move `imported_by` from `_DEFERRED_REFERENCE_BACKEND_EDGES` to `_IMPLEMENTED_EDGES`
  in `edges.py`; register a `resolve_imported_by` resolver.
- `resolve_imported_by` — **module handles only** in this slice: returns the canonical
  handles of project modules that import the target module. Non-module handles return
  the unsupported `not_yet_implemented` branch (see §4).
- Extract the reverse-scan into a stable `JediAnalyzer.find_importers(...)` (used by
  both the new edge and the legacy `analyze_dependencies`), and extract
  `_ModuleSentinel` into a shared leaf module so `edges` can build module stubs without
  importing `inspect`.
- Conformance + unit + integration coverage mirroring the `members`/`callees` edges.

**Out (deferred — additive later, no shape change):**

- **Symbol-level `imported_by`** (`from mod import Symbol` → who imports the symbol).
  This slice is module-only; non-module handles report `not_yet_implemented`.
- **Literal-string dynamic-import detection** (`importlib.import_module("a.b.c")` with a
  string-literal arg). A documented follow-on.
- **Restoring `inspect.edge_counts.imported_by`** (cheap `len(resolver(...))`, but it
  carries its own `_PHASE4_UNMEASURED_EDGES`/linter contract change — a separate slice).
- `callers`/`references` and the symbol-level reverse edges — these genuinely require
  the Pyright backend (#333) and stay `deferred_reference_backend`.

## 3. Architecture

### 3.1 Components / file map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pyeye/mcp/operations/edges.py` | Modify | Move `imported_by` to the implemented set; add `resolve_imported_by` (module-only) to `EDGE_RESOLVERS`. Returns `EdgeResult` for modules, `None` for non-modules (the per-kind not-supported signal). |
| `src/pyeye/mcp/operations/expand.py` | Modify | Treat a `None` resolver result as the `not_yet_implemented` unsupported branch; await resolver results that are awaitable (so an async resolver composes with the existing sync ones). |
| `src/pyeye/analyzers/jedi_analyzer.py` | Modify | Extract the reverse-scan from `analyze_dependencies` into a stable `find_importers(module_path, target_file, scope) -> list[tuple[str, Path]]`; rewire the (deprecated) `analyze_dependencies` to consume it. Behaviour-preserving. |
| `src/pyeye/_module_sentinel.py` | Create | Shared leaf home for `_ModuleSentinel` (moved out of `inspect.py`). Deps: `ast`, `Path` only. |
| `src/pyeye/mcp/operations/inspect.py` | Modify | Import `_ModuleSentinel` from the shared module under its existing private alias (zero call-site churn). Behaviour-preserving. |
| `tests/unit/mcp/operations/test_edges.py` | Modify | `resolve_imported_by` adjacency, measured-empty, non-module → `None`, and the no-`get_references` spy. |
| `tests/unit/.../test_jedi_analyzer*.py` | Modify | `find_importers` unit tests + `analyze_dependencies["imported_by"]` extraction-parity. |
| `tests/integration/api_redesign/test_traversal_integration.py` | Modify | `imported_by` over the wire (module supported; non-module unsupported). |
| `tests/conformance/test_linter_adversarial_expand.py` | Modify | Dogfood real `imported_by` output (both branches) through `lint_response(..., "expand")`. |
| `tests/fixtures/...` | Identify/extend | A module imported by ≥2 project modules incl. an importing **test/script** file. |

### 3.2 Data flow

`expand("pkg.mod", "imported_by", analyzer)`:

1. `edge_status("imported_by")` → `"implemented"` (after the registry move).
2. `inspect._find_jedi_name_for_handle("pkg.mod")` → `_ModuleSentinel` (kind module,
   carries `.module_path`).
3. `await resolve_imported_by(sentinel, analyzer)`:
   - kind ≠ module → return `None`.
   - kind == module → `pairs = await analyzer.find_importers("pkg.mod",
     sentinel.module_path, scope="all")` → for each `(importer_module, importer_file)`:
     `h = Handle(importer_module)` + `_ModuleSentinel(importer_file, str(h), analyzer)`
     (the sentinel takes the canonical handle as a **string**, matching its existing
     `inspect` call site) → dedup by handle (keep first) → `EdgeResult(adjacents=sorted(...))`.
4. `expand`: `None` → unsupported `not_yet_implemented`; otherwise
   `stubs = [build_stub(name, str(h), analyzer) for (h, name) in result.adjacents]` →
   `{source, edge, stubs}`.

### 3.3 The two extractions (reuse, not duplication)

- **`find_importers`** factors the reverse-scan block out of the **deprecated**
  `analyze_dependencies` into a stable method so the new edge does not depend on
  to-be-removed code. It carries over verbatim: the `read_file_async` + `shares_package`
  pre-filter, the `ast.Import`/`ast.ImportFrom` matching, and `_resolve_relative_import`
  (#343). It takes `target_file` (the resolver already holds it via the source
  sentinel), avoiding a re-location of the target module. `analyze_dependencies` is
  rewired to `imported_by = sorted({m for m, _ in find_importers(...)})`.
- **`_ModuleSentinel`** moves to `src/pyeye/_module_sentinel.py` (a self-contained
  ~30-line class with only `ast`/`Path` deps). `edges` imports it to build a module
  Name **from the importer file it already holds** — no re-resolution. This is load-
  bearing: tests/standalone scripts are **not** importable via `find_module_file`, so a
  re-resolution path could not produce their stubs; building from the file does. Mirrors
  the `_ast_targets.py` extraction from #340 that keeps `edges` decoupled from `inspect`
  (the `inspect → edges` dependency forbids `edges → inspect`).

**Behaviour-preserving guardrails:** the legacy `analyze_dependencies` tests and all
existing `inspect` tests must pass **unmodified** after the extractions.

## 4. Contracts

`imported_by` is a normal member of the existing `ExpandResult` discriminated union
(spec `2026-06-08-expand-core-design.md` §4.2) — **no new fields, no shape change**.

**Module handle → supported:**

```text
{ "source": str, "edge": "imported_by", "stubs": [Stub, ...] }
```

- Each `Stub` is `kind: "module"`, `scope: "project"`. `stubs: []` means **measured**:
  no project file imports the target. No `unresolved_call_sites` (callees-only).

**Non-module handle → unsupported:**

```text
{ "source": str, "edge": "imported_by", "unsupported": true,
  "reason": "not_yet_implemented",
  "detail": "imported_by is supported for modules; '<handle>' is a <kind>. Symbol-level imported_by is not yet implemented." }
```

**Why non-module is `not_yet_implemented`, not `stubs: []`.** A symbol genuinely *can*
be imported by name, so returning a measured-empty `[]` for a class/function would
falsely assert "imported by nothing" — the #332 absence-vs-zero trap. `not_yet_implemented`
is the honest signal. This differs from `members`/`callees`, where `[]` for the wrong
kind is *true by definition* (a variable has no members; a non-function makes no calls).
`imported_by` is therefore the first edge where wrong-kind ≠ measured-empty.

### 4.1 Resolver convention: `EdgeResult | None`

A resolver may return `EdgeResult | None`. `None` means "this handle's **kind** is not
supported for this edge" → `expand` emits the `not_yet_implemented` unsupported branch
with the kind-specific `detail`. `members`/`callees` are **unchanged** — they keep
returning `EdgeResult([])` for the wrong kind (honest measured-empty) and never return
`None`. Only `imported_by` uses the `None` path. When the future symbol-level slice
lands, `resolve_imported_by` stops returning `None` for symbol kinds — a clean flip with
no shape change.

Note: the wrong-kind `detail` is **kind-specific** (it names the handle's kind), so
`expand` synthesises it on the `None` branch rather than routing through the generic
status-keyed `_unsupported_detail` helper (which produces the fixed per-`reason` text for
status-derived unsupported results). `reason` is still `"not_yet_implemented"`.

### 4.2 Async accommodation

`resolve_imported_by` is **async** (the scan does file I/O via `get_project_files` /
`read_file_async`). `members`/`callees` stay **sync**, and `inspect`'s
`len(resolve_members(...).handles)` delegation stays sync (the #340 refactor guardrail is
untouched). `expand` bridges both by `await`-ing the resolver result only when it is
awaitable. This is the minimal-blast-radius choice: no async cascade into the sync
resolvers or the inspect count path.

## 5. Resolver — `find_importers` / `resolve_imported_by`

`find_importers(module_path, target_file, scope="all") -> list[tuple[str, Path]]`:

1. Enumerate candidate files via `get_project_files("*.py", scope)`. **`scope="all"`**
   resolves to the project tree (which includes `tests/` and in-tree scripts), plus
   configured standalone-script dirs (`standalone_paths`, #236), namespaces, and extra
   packages — the most complete honest answer to "what depends on X".
2. For each file ≠ `target_file`: the existing pre-filter (textual `module_path`
   appearance **or** `shares_package`), then the authoritative AST check —
   `ast.Import` (`alias.name == module_path` or `startswith(module_path + ".")`) or
   `ast.ImportFrom` (resolve via `_resolve_relative_import`, then `== module_path` or
   `startswith`). On a match, record `(_get_import_path_for_file(file), file)`.
3. Dedup by importer module; deterministic order.

`resolve_imported_by(jedi_name, analyzer)`:

- kind ≠ `"module"` → `None`.
- kind == `"module"` → `find_importers(jedi_name.full_name, jedi_name.module_path,
  scope="all")` → build `(Handle, _ModuleSentinel)` per importer → `EdgeResult(adjacents)`.

`scope` lives at the analyzer layer (`find_importers` keeps the param, as
`analyze_dependencies` already does); `resolve_imported_by` fixes it to `"all"`. The
`expand` tool signature stays `(handle, edge, project_path)` — **no `scope` param** (it
would be inert for `members`/`callees`; additive later if a caller ever needs to narrow).

## 6. Guarantees & non-guarantees

**Guaranteed (firm):**

- **Soundness — no false data.** Every importer is a real project file with a real
  AST-verified `import`/`from-import` of the target. Never an invented edge; `stubs: []`
  means *measured* none, never "couldn't measure".
- **Determinism & locality.** A deterministic AST walk over project files +
  `_resolve_relative_import`. **No `get_references` / project-wide reverse symbol search
  anywhere on the path** — grep-gated and asserted by a spy test, exactly like `callees`.
- **Coverage breadth.** `scope="all"` finds importers in package modules, tests, in-tree
  scripts, configured standalone dirs, namespaces, and extra packages.

**Explicitly NOT guaranteed (documented ceiling):**

- **Runtime-dynamic imports.** `imported_by` covers static `import`/`from-import`
  (including conditional/nested ones — an AST walk sees them regardless of nesting).
  Imports whose target is computed at runtime — `importlib.import_module(var)`,
  `__import__(var)` — are undetectable and out of scope. This is the **universal static
  ceiling** of import-graph analysis (the same *class* of boundary as `callees`' dynamic
  dispatch), **not** the #332 non-determinism. Unlike `callees`' `unresolved_call_sites`,
  it is **not surfaced as a count**: a dynamic import in another file cannot be attributed
  to *this* target, so a count would be project-wide noise — the boundary is documented in
  the edge contract instead.

This is categorically different from why `callers`/`references` are deferred: those rely
on `get_references`, which is *non-deterministically wrong* — untrustworthy numbers, not
a known static ceiling.

## 7. Testing & verification

- **Unit (`test_edges.py`):** `resolve_imported_by` on a fixture module imported by ≥2
  others — correct canonical importer handles, including an importing **test/script**
  file (proving tests/scripts are covered); a module imported by nobody → `EdgeResult([])`
  (measured-none); a non-module handle → `None`. **Spy test:** the `imported_by` path
  makes no `jedi.Script.get_references` call (mirrors the callees spy).
- **Unit (analyzer):** `find_importers` directly; assert `analyze_dependencies["imported_by"]`
  is **unchanged** (extraction parity).
- **Integration (`test_traversal_integration.py`):** `expand` over the wire —
  `imported_by` on a module (supported, stubs) and on a non-module (unsupported
  `not_yet_implemented`).
- **Conformance:** dogfood real `imported_by` output (both branches) through
  `lint_response(result, "expand")`. **Expected: no linter code change** — the E.* rules
  already accept any `edge` string, the supported result carries no `unresolved_call_sites`
  (E.3 satisfied), and `not_yet_implemented` is a valid reason. `imported_by` stays in
  `_PHASE4_UNMEASURED_EDGES` (inspect `edge_counts` unchanged — §2 Out).

**Verification gates:**

- Full suite green at the coverage threshold (run `-p no:randomly` for determinism).
- Pre-commit clean (no bypass flags).
- **Grep-verified: no `get_references`/`find_references` on the `imported_by` path.**
- Legacy `analyze_dependencies` tests **and** existing `inspect` tests pass **unmodified**
  (both extractions are behaviour-preserving).

## 8. Relationship & sequencing

- **Depends on #342** (the #340 `edges`/`EdgeResult`/`expand`/conformance-linter
  foundation) — merged to `main`. This slice lands on `feat/345-imported-by` off `main`.
- **Reuses #343** (`_resolve_relative_import`), already on `main`.
- Pairs naturally with the planned `imports` (outbound) edge (currently
  `not_yet_implemented`); `find_importers` is the reusable seam for the reverse direction.
- Everything deferred in §2 lands additively later with **no `ExpandResult` shape change**:
  symbol-level `imported_by` flips the non-module `not_yet_implemented` path to real
  results; the literal-string `importlib` and `inspect.edge_counts.imported_by` work are
  independent follow-ons.
