# Resolve + Inspect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `resolve`, `resolve_at`, and `inspect` as new MCP tools that demonstrate the redesigned API shape — canonical Python handles, structural responses, project/external scoping, no content shipping. Existing tools continue working unchanged. First concrete deliverable of the API redesign.

**Architecture:** Seven phases, each landing as a coherent change with tests. Phases 1–3 build the foundation (handle types, resolution, basic inspect). Phase 4 adds `edge_counts` for the subset of edges the existing analyzer can produce — unmeasured edges are *omitted*, not zero. Phase 5 adds highlights. Phase 6 adds `re_exports`. Phase 7 is conformance verification (layering CI check, wire-format floors, boundary tests). First PR-able deliverable is end of Phase 4.

**Tech Stack:** Python, FastMCP, Jedi, pytest.

**Spec:** [`docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`](../specs/2026-05-02-progressive-disclosure-api-design.md)

**Carrier branch:** New branch off `feat/316-tool-ergonomics` (NOT off `main` — we'd lose the in-flight cache work). Suggested name: `feat/316-resolve-inspect`.

**Related issues:** #316, #320, #321.

---

## Hard constraints

These are non-negotiable across all phases. Verify after every commit.

1. **Existing tools must continue passing.** `find_symbol`, `find_references`, `get_type_info`, etc. are not modified by this plan. Their existing test suites stay green throughout. New operations are strictly additive.
2. **Layering principle enforced.** No new return field contains source content (snippets, bodies, surrounding context). Pointers and structural facts only. (See `feedback_pyeye_layering.md` in project memory.)
3. **No `--no-verify` or skipped tests.** Pre-commit hooks must pass on every commit. If a hook fails, fix the underlying issue.
4. **Project-scoped semantics on external nodes.** Counts and edge expansions on external handles return project-internal data only. Verify in conformance tests.
5. **Absence-vs-zero invariant.** Field absence means "we didn't measure this"; field presence (even with empty/zero value) means "we measured and here's the result." Applies to `edge_counts`, `re_exports`, `highlights`, `tags`, `properties`. Filling unmeasured edges with `0` is non-conforming. (See spec section "Absence vs. zero: a load-bearing invariant.") This must be verified in tests and enforced by the conformance linter.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/pyeye/handle.py` | Create | `Handle` type, validation, serialization. Plain Python dotted notation. |
| `src/pyeye/canonicalization.py` | Create | Definition-site canonicalization. Re-export collection. Resolves any identifier form (alias, FQN, file path) to canonical handle. |
| `src/pyeye/scope.py` | Create | Project-vs-external classification using project boundaries from existing config. |
| `src/pyeye/mcp/operations/__init__.py` | Create | New package for redesigned operations; isolation from legacy tools. |
| `src/pyeye/mcp/operations/resolve.py` | Create | `resolve(identifier)` and `resolve_at(file, line, col)` implementations. |
| `src/pyeye/mcp/operations/inspect.py` | Create | `inspect(handle)` implementation. Universal fields + kind-dependent properties. |
| `src/pyeye/mcp/operations/highlights.py` | Create (Phase 5) | Highlight ranking heuristic. |
| `src/pyeye/mcp/server.py` | Modify | Register new MCP tools alongside existing ones. Additive only. |
| `src/pyeye/analyzers/jedi_analyzer.py` | Modify (minimal) | Add helper(s) for definition-site resolution if not already present. No replacement of existing functionality. |
| `tests/unit/handle/test_handle.py` | Create | Handle type tests. |
| `tests/unit/handle/test_canonicalization.py` | Create | Canonicalization tests including re-export collapse. |
| `tests/unit/handle/test_scope.py` | Create | Scope classification tests. |
| `tests/unit/mcp/operations/test_resolve.py` | Create | Resolve operation tests. |
| `tests/unit/mcp/operations/test_inspect.py` | Create | Inspect operation tests. |
| `tests/unit/mcp/operations/test_highlights.py` | Create (Phase 5) | Highlights ranking tests. |
| `tests/integration/api_redesign/test_resolve_integration.py` | Create | End-to-end via MCP wire format. |
| `tests/integration/api_redesign/test_inspect_integration.py` | Create | End-to-end via MCP wire format. |
| `tests/integration/api_redesign/test_conformance.py` | Create (Phase 7) | Spec acceptance criteria as conformance tests. |
| `tests/integration/api_redesign/fixtures/` | Create | Project fixtures for conformance (re-exports, externals, cycles). |
| `docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md` | Modify (Phase 2) | Small spec adjustment: add `scope` to `ResolveResult`. |

---

## Phase 1: Handle infrastructure (foundation)

Pure internal work — no MCP tools yet. TDD discipline. Establishes the types and resolvers everything else depends on.

### Task 1.1: `Handle` type

- [ ] Create `tests/unit/handle/test_handle.py`
- [ ] Write tests covering: (a) creation from valid dotted names, (b) rejection of invalid forms (empty string, leading/trailing dots, spaces), (c) equality is string equality, (d) serialization round-trip (handle → dict → handle), (e) handle from path components
- [ ] Run tests — should fail (module does not exist)
- [ ] Implement `src/pyeye/handle.py` with the `Handle` type and validation
- [ ] Run tests — should pass
- [ ] Run full suite to verify no regressions
- [ ] Commit

**Acceptance:** Five tests pass; full suite green.

### Task 1.2: Basic canonicalization (single-step)

This is the foundation everything downstream depends on. The basic case is straightforward; multi-hop and aliasing complications get their own task (1.3) so partial implementations can't slip through.

- [ ] Create `tests/unit/handle/test_canonicalization.py`
- [ ] Build a fixture project at `tests/fixtures/canonicalization_basic/` with explicit re-export patterns:
  - `package/_impl/config.py` defining `class Config`
  - `package/__init__.py` doing `from package._impl.config import Config`
  - Known-correct expected handle: `package._impl.config.Config`
- [ ] Write tests covering:
  - (a) Bare definition resolves to itself: `resolve_canonical("package._impl.config.Config")` returns the same handle
  - (b) Single-step re-export collapses: `resolve_canonical("package.Config")` returns `package._impl.config.Config`
  - (c) Unresolved name returns `None` or sentinel — does not raise
  - (d) Re-export collection (single-hop): given canonical handle, returns `["package.Config"]`
- [ ] Run tests — should fail
- [ ] Implement `src/pyeye/canonicalization.py` for the single-step case. Uses existing `JediAnalyzer` to follow imports to definitions; walks `__init__.py` files to collect re-exports
- [ ] Run tests — should pass
- [ ] Run full suite
- [ ] Commit

**Acceptance:** Four tests pass on the basic fixture. Single-step canonicalization is rock-solid before multi-hop work begins.

### Task 1.3: Multi-hop and edge-case canonicalization

The subtle cases. These are where partial implementations break downstream operations (`inspect.re_exports`, `expand` reference collapse) in hard-to-debug ways. Required: explicit fixtures with known-correct expected values for every case before implementation begins.

- [ ] Extend the canonicalization test fixture or create `tests/fixtures/canonicalization_multihop/`:
  - **Multi-step re-export chain**: `package/_impl/config.py` defines `Config`; `package/subpkg/__init__.py` does `from package._impl.config import Config`; `package/__init__.py` does `from package.subpkg import Config`. Resolving `package.Config` must traverse both hops to `package._impl.config.Config`
  - **Aliased re-export of an already-re-exported symbol**: building on the chain above, `package/legacy.py` does `from package import Config as LegacyConfig`. Resolving `package.legacy.LegacyConfig` must reach the original definition
  - **Sibling alias collision**: same module imports `foo` two ways — `from x import foo` and `from x import foo as f`. Both `foo` and `f` in the importing module's namespace must resolve to `x.foo`'s canonical handle
  - **Re-export to itself doesn't loop**: `from .submodule import Foo` where the submodule already exports it via `__all__`
- [ ] Add tests covering each fixture case with explicit expected canonical handles
- [ ] Run tests — should fail (single-step impl from 1.2 won't handle multi-hop)
- [ ] Extend `canonicalization.py` to follow multi-hop chains. Be deliberate about which Jedi behavior you're relying on: Jedi's `goto` may follow all hops or stop at the first re-export depending on the call. Document the choice and verify it holds across the fixtures
- [ ] Run tests — should pass
- [ ] Add a re-export collection test for multi-hop: given the canonical handle, the re-export list includes ALL public paths binding to it (e.g., `["package.Config", "package.subpkg.Config", "package.legacy.LegacyConfig"]`)
- [ ] Run full suite
- [ ] Commit

**Constraint:** Re-export collection should respect `__all__` when present (re-exports listed in `__all__` are public; ones not listed are still collected but a future implementation may distinguish).

**Risk — Jedi behavior dependency.** Jedi's resolution semantics for multi-hop re-exports are implementation-dependent. Some `goto` calls follow all the way to the definition; others stop at the first re-export. The implementation must make a deliberate choice (probably: keep walking until the definition is reached or a cycle is detected) and verify the choice holds across all fixtures. If Jedi's behavior changes in a future version, the conformance fixtures will catch it. Pin the Jedi version in `pyproject.toml` if necessary.

**Risk — conditional imports.** `if TYPE_CHECKING:`, `try:/except ImportError` patterns are flagged in the spec as deferred dragons. Conservative behavior: return whatever Jedi sees first; mark the issue in implementation comments and reference the spec's "Edge-case handle resolution" section.

**Acceptance:** Multi-hop fixtures all resolve correctly; re-export collection enumerates the full public binding set; full test suite green.

### Task 1.4: Scope classification

- [ ] Create `tests/unit/handle/test_scope.py`
- [ ] Write tests covering:
  - (a) Project file path → `scope: "project"`
  - (b) `site-packages` path → `scope: "external"`
  - (c) Stdlib path → `scope: "external"`
  - (d) Vendored directory inside project (e.g., `_vendor/`) → handled per project config
  - (e) Build artifact path (`build/`, `dist/`) → `scope: "external"` (and ideally not surfaced at all due to project-aware scoping)
- [ ] Run tests — should fail
- [ ] Implement `src/pyeye/scope.py`. Uses existing `ProjectManager`'s configured project paths to determine boundary
- [ ] Run tests — should pass
- [ ] Run full suite
- [ ] Commit

**Constraint:** Use existing project configuration (`.pyeye.json`, `pyproject.toml [tool.pyeye]`, etc.) — do not introduce a new config layer.

**Risk:** Some projects may have `src/` layouts where the project root and the package root differ. Verify against existing fixture projects in `tests/fixtures/`.

**Acceptance:** Five tests pass. Build artifact paths classify as external (or excluded entirely).

---

## Phase 2: `resolve` and `resolve_at` as MCP tools

Public-surface phase. New MCP tools registered. After this phase, agents can convert any identifier into a canonical handle.

### Task 2.1: Spec adjustment for `scope` in `ResolveResult`

- [ ] Update [`docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`](../specs/2026-05-02-progressive-disclosure-api-design.md): add `scope: "project" | "external"` to the success variant of `ResolveResult` and to candidate entries in the ambiguous variant
- [ ] Commit (spec-only change, no code)

**Why:** Agent almost always wants scope on first lookup to decide whether to drill or not. Computing scope at resolution is cheap. Avoids a near-mandatory `inspect` follow-up.

### Task 2.2: `resolve(identifier)`

- [ ] Create `tests/unit/mcp/operations/test_resolve.py`
- [ ] Write tests covering:
  - (a) Bare name (`Config`) — finds matches in project; if exactly one, returns success; if multiple, returns ambiguous with candidates
  - (b) FQN dotted path (`a.b.c.Config`) resolves to canonical
  - (c) Re-exported path collapses (`package.Config` returns canonical from definition site)
  - (d) File path with line (`src/foo.py:42`) resolves to symbol at that line
  - (e) File path without line resolves to module
  - (f) Unresolved identifier returns `{found: false, reason: ...}`
  - (g) Each success variant includes `scope`
  - (h) Ambiguous candidates each carry kind, scope, location
- [ ] Run tests — should fail
- [ ] Implement `src/pyeye/mcp/operations/resolve.py::resolve`
- [ ] Run tests — should pass
- [ ] Commit

**Constraint:** The resolver must be deterministic. For ambiguous results, candidate ordering is `(scope, file, line)` ascending — project before external, then alphabetical by location.

**Acceptance:** Eight tests pass. Re-export handling verified with a fixture project.

### Task 2.3: `resolve_at(file, line, column)`

- [ ] Add tests to `tests/unit/mcp/operations/test_resolve.py`
- [ ] Write tests covering:
  - (a) Position on a known symbol → success with handle
  - (b) Position on whitespace → `{found: false, reason: "no_symbol_at_position"}`
  - (c) Position on a literal (string, number) → no symbol; same not-found reason
  - (d) Position with column=0 (1-indexed line) is valid; presence of column tested with `is not None` not truthiness
  - (e) Coordinates pointing at a use site (not the definition) still return the canonical handle (via Jedi's goto)
- [ ] Run tests — should fail
- [ ] Implement `src/pyeye/mcp/operations/resolve.py::resolve_at`
- [ ] Run tests — should pass
- [ ] Commit

**Acceptance:** Five tests pass. Coordinates → canonical handle path verified.

### Task 2.4: Register `resolve` and `resolve_at` as MCP tools

- [ ] Modify `src/pyeye/mcp/server.py`: register `resolve` and `resolve_at` as new `@mcp.tool` endpoints. Do not modify existing tools
- [ ] Create `tests/integration/api_redesign/test_resolve_integration.py`: end-to-end via the MCP wire format (uses FastMCP's test client)
- [ ] Run integration tests — should pass
- [ ] Run **full** existing test suite (`uv run pytest --cov=src/pyeye --cov-fail-under=85`) — verify zero regressions in legacy tools
- [ ] Commit

**Hard constraint:** If any existing test fails, stop. The constraint is that legacy tools continue passing. Either fix the cause (likely a name collision or accidental import side effect) or revert.

**Acceptance:** New MCP tools appear in tool list; integration tests pass; legacy suite still green.

---

## Phase 3: `inspect` with universal + kind-dependent fields

Returns a Node with everything *except* `edge_counts`, `highlights`, `re_exports` (those come in Phases 4–6). After this phase, an agent can ask "what is `a.b.c.Foo`?" and get back identity, kind, scope, location, signature, parameters, type, etc.

### Task 3.1: Failing tests for `inspect` universal fields

- [ ] Create `tests/unit/mcp/operations/test_inspect.py`
- [ ] Write tests covering, for each Python kind (class, function, method, module, attribute, property, variable):
  - (a) Universal fields populated: `handle`, `kind`, `scope`, `location`, `docstring` (when present)
  - (b) Kind-dependent properties populated correctly:
    - class: `signature` (constructor), `superclasses: Handle[]`
    - function/method: `signature: string`, `parameters: Param[]`, `return_type?: string`, `is_async`, `is_classmethod`, `is_staticmethod`
    - module: `package?: Handle`, `is_package: boolean`
    - attribute/property/variable: `type?: string`, `default?: string` (literals only)
  - (c) `edge_counts: {}` (empty map — Phase 4 populates it)
  - (d) `highlights`, `re_exports` are absent (not yet implemented)
  - (e) External-scope handle returns shallow data with `scope: "external"`
- [ ] Run tests — should fail
- [ ] Commit (failing tests)

**Acceptance:** Tests pin down the contract for inspect's universal + kind-dependent return shape.

### Task 3.2: Implement `inspect`

- [ ] Implement `src/pyeye/mcp/operations/inspect.py::inspect`
- [ ] Use existing analyzer (`JediAnalyzer`, `get_type_info`, etc.) to populate fields
- [ ] **No source content fields**. Bodies, snippets, surrounding text are not returned. Pointers (`location`) only.
- [ ] `edge_counts` returns empty map for now
- [ ] Verify external-scope handles return shallow data without errors (Jedi follows into site-packages on demand)
- [ ] Run tests — should pass
- [ ] Run full suite — no regressions
- [ ] Commit

**Constraint:** Verify by inspection (or a temporary linter) that no field returned by `inspect` contains source text. The layering CI check from Phase 7 will enforce this permanently.

**Risk:** Some kinds may surface fields that look semantic but smuggle content (e.g., a complex `default` expression rendered as a string). Default values: limit to simple literals; for complex expressions, omit the field entirely (the agent can read at the location).

**Acceptance:** All Phase 3.1 tests pass. Manual smoke test: `inspect("pyeye.cache.GranularCache")` returns a clean structural response, ~30 lines of structured data, no source content.

### Task 3.3: Register `inspect` as MCP tool

- [ ] Modify `src/pyeye/mcp/server.py`: register `inspect` as a new `@mcp.tool` endpoint
- [ ] Create `tests/integration/api_redesign/test_inspect_integration.py`: end-to-end via the MCP wire format
- [ ] Run integration tests — pass
- [ ] Run full existing suite — no regressions
- [ ] Commit

**Acceptance:** New tool appears in MCP tool list; integration tests pass; legacy suite green.

---

## Phase 4: `edge_counts` (Phase 1 subset, omitted for unmeasured)

After this phase, `inspect` returns counts for the edges the existing analyzer can produce. Unmeasured edges are **omitted**, not zero — agents can distinguish "we measured zero" from "we don't yet measure this." First PR-able deliverable lands here.

### Task 4.1: Failing tests for `edge_counts`

- [ ] Add tests to `tests/unit/mcp/operations/test_inspect.py` covering:
  - (a) `edge_counts.members` populated for class and module handles (count of direct members)
  - (b) `edge_counts.superclasses` populated for class handles
  - (c) `edge_counts.subclasses` populated for class handles (project-scoped)
  - (d) `edge_counts.callers` populated for function/method handles
  - (e) `edge_counts.references` populated as the aggregate of read/written/passed (Phase 1 returns the *total* count even though the underlying split isn't yet computed via expand)
  - (f) **Unmeasured edges omitted from `edge_counts`** — `read_by`, `written_by`, `passed_by`, `decorated_by`, `decorates`, `imports`, `imported_by`, `enclosing_scope`, `callees`, `overrides`, `overridden_by` do NOT appear in the response. Tests assert `assert "read_by" not in response.edge_counts` etc., not `assert response.edge_counts.read_by == 0`
  - (g) **Measured-and-zero edges return `0`, not omitted** — fixture: a class with no subclasses returns `subclasses: 0` (key present, value zero), NOT omitted from `edge_counts`. Tests assert both `"subclasses" in response.edge_counts` and `response.edge_counts["subclasses"] == 0`
  - (h) On external nodes, counts are project-scoped: `edge_counts.subclasses` on `pydantic.BaseModel` reflects project subclasses only
- [ ] Run tests — should fail
- [ ] Commit (failing tests)

**Acceptance:** Tests pin down both directions of the absence-vs-zero invariant: unmeasured edges are absent; measured-and-zero edges are present with value 0.

### Task 4.2: Implement `edge_counts` with per-measurement time budgets

- [ ] In `inspect.py`, populate `edge_counts` using existing analyzer methods:
  - `members` — from outline/structure analysis (existing `get_module_info` / class member walk)
  - `superclasses` — from class definition analysis
  - `subclasses` — from `find_subclasses` (project-scoped via existing scope-aware analyzer)
  - `callers` — from `find_references` filtered to call sites (or `get_call_hierarchy`)
  - `references` — from `find_references` count, **excluding call sites** (per the spec's references-aggregate boundary; calls are exclusively `callers`, not double-counted)
- [ ] Implementation detail: the unmeasured edges must be entirely *absent* from the dict, not present with value 0. Tests in 4.1.(f) verify this.
- [ ] **Per-measurement time budget.** Each edge measurement runs under a configurable timeout (default 2 seconds). On timeout, the edge is **omitted** from `edge_counts` — consistent with the absence-vs-zero invariant ("we didn't measure this"). Never raise from inspect. The agent gets an honest response without that edge.
- [ ] **Log/metric per-edge timeouts with the edge name.** Use the existing logging/metrics infrastructure (`metrics.py`, `unified_metrics.py`). Record at minimum: `edge_type`, `handle` (or its scope), and the elapsed time at cutoff. This is cheap to add now and surfaces patterns over time — e.g., "subclasses on widely-extended base classes accounts for 80% of timeouts" — that drive future tuning of which edges deserve indices, smarter caching, or different default budgets per edge type.
- [ ] Run tests — should pass
- [ ] Add a test for the timeout case: a measurement that exceeds the budget produces a response with that edge absent from `edge_counts`. Use a mock to force timeout deterministically — don't rely on real-time slow operations
- [ ] Run full suite
- [ ] Commit

**Constraint:** Counts on external nodes are project-scoped. Use scope-aware filtering when delegating to existing analyzer methods.

**Constraint — references excludes calls.** The spec's `references` aggregate is `read_by ∪ written_by ∪ passed_by` and explicitly excludes call sites. `callers` is the exclusive home for invocation relationships. If `find_references` in the existing analyzer includes call sites, filter them out for the `references` count. Verify with a fixture that has both calls and non-call references — `callers + references` should equal the total without double-counting.

**Constraint — per-measurement isolation.** A timeout on `subclasses` for `Exception` must not block `members` measurement on the same call. Each edge runs independently under its own budget. Implementation may run them concurrently or sequentially; concurrency is preferable for inspect responsiveness but not required for Phase 1.

**Risk — `inspect("Exception")` and similar widely-used base classes.** Real codebases have heavily-extended built-ins. Without per-measurement timeouts, `subclasses` could hang the analyzer for seconds. The time budget bounds the worst case; the absence-vs-zero invariant communicates to the agent that the count is unknown rather than zero.

**Acceptance:** All Phase 4.1 tests pass plus the timeout test. Smoke test: `inspect("pyeye.cache.GranularCache")` returns counts for `members`, `subclasses`, `superclasses`, `callers`, `references`; other edge types absent from `edge_counts`. Adversarial smoke test: `inspect("Exception")` (or another widely-extended class in fixtures) returns within ~2 seconds × N-edges with `subclasses` either populated quickly or omitted on timeout — never hangs.

### 🚩 First PR-able deliverable

After Phase 4 commits, the branch can be opened as a PR. The PR demonstrates:

- Canonical handles (Phase 1)
- Three new MCP tools: `resolve`, `resolve_at`, `inspect` (Phases 2–3)
- Structural inspect responses with measured edge counts and honest omission of unmeasured ones (Phase 4)
- Existing tools and tests entirely undisturbed

Phases 5–7 can land as follow-on commits or separate PRs.

---

## Phase 5: Highlights

`inspect` returns top-N adjacent handles per measured edge type, ranked by a simple heuristic.

### Task 5.1: Highlights ranking heuristic

- [ ] Create `src/pyeye/mcp/operations/highlights.py`
- [ ] Document the heuristic in module docstring:

  ```text
  Ranking (highest to lowest):
  1. Same package as the source handle > different package
  2. Non-test file > test file (heuristic: path contains 'test' or 'tests')
  3. Alphabetical by handle (deterministic tiebreaker)
  ```

- [ ] Create `tests/unit/mcp/operations/test_highlights.py`
- [ ] Write tests verifying the ranking on a fixture with mixed package + test status
- [ ] Implement
- [ ] Run tests — pass
- [ ] Commit

**Acceptance:** Tests confirm the ranking is deterministic and matches the documented rules.

### Task 5.2: Wire highlights into `inspect`

- [ ] Add tests to `tests/unit/mcp/operations/test_inspect.py`: highlights field populated for measured edges, top-N (default N=5) per edge type
- [ ] Run — should fail
- [ ] Wire highlights computation into `inspect.py`. Use `Phase 4`'s edge-fetching code; truncate to N after ranking
- [ ] Verify highlights field is omitted (not empty array) for unmeasured edges, consistent with edge_counts
- [ ] Run tests — should pass
- [ ] Commit

**Constraint:** Highlights N default is 5; configurable via a constant (not a public API parameter for now). Tunable later if usage shows the wrong number.

**Acceptance:** Smoke test: `inspect("pyeye.cache.GranularCache")` returns up to 5 handle stubs for each measured edge type, ordered per the heuristic.

---

## Phase 6: `re_exports` collection

`inspect` returns the public re-export paths binding to the canonical handle.

### Task 6.1: Re-export pattern detection

- [ ] Add tests to `tests/unit/handle/test_canonicalization.py` (or a new `test_re_exports.py`) covering:
  - (a) Direct re-export: `from package._impl.config import Config` in `package/__init__.py` — `Config`'s re_exports include `package.Config`
  - (b) Aliased re-export: `from package._impl.config import Config as PublicConfig` — re_exports include `package.PublicConfig`
  - (c) `__all__` declaration: re-exports listed in `__all__` are collected; others are also collected (no `in_all` distinction in Phase 1, deferred per spec)
  - (d) Multiple re-export sites: a symbol re-exported from two different `__init__.py` files lists both paths
  - (e) Symbol with no re-exports returns empty `re_exports` (or omits the field — pick one, document)
- [ ] Run tests — fail
- [ ] Implement re-export walker in `canonicalization.py` (or a new `re_exports.py`)
- [ ] Run tests — pass
- [ ] Commit

**Constraint:** Walk only project `__init__.py` files. Do not walk external packages' `__init__.py`s for re-exports of project symbols (rare and expensive).

**Risk:** Star imports (`from .submodule import *`) are valid Python but harder to fully resolve statically. For Phase 1, collect what's explicitly re-exported via named imports or `__all__`; star-import re-exports are flagged as a known limitation in implementation comments.

**Acceptance:** Five tests pass on a fixture with typical re-export patterns.

### Task 6.2: Wire `re_exports` into `inspect`

- [ ] Add tests to `tests/unit/mcp/operations/test_inspect.py`: `re_exports` field populated for re-exported symbols; absent or empty for non-re-exported symbols
- [ ] Run — fail
- [ ] Wire into `inspect.py`. Cache the re-export index per project (use existing cache infrastructure)
- [ ] Run tests — pass
- [ ] Commit

**Acceptance:** `inspect("package._impl.config.Config")` on a re-exported class returns `re_exports: ["package.Config"]`; non-re-exported symbol omits the field.

---

## Phase 7: Conformance and acceptance

Verify the spec's acceptance criteria. The layering CI check is the most important deliverable here — it prevents future regressions from quietly violating the principle.

### Task 7.1: Conformance linter — layering + absence-vs-zero

The conformance linter is the most valuable long-term artifact in this plan. It runs as a pytest fixture / custom pre-commit hook over responses from `resolve`, `resolve_at`, and `inspect`.

- [ ] Create the linter (e.g., `tests/conformance/response_linter.py`)
- [ ] **Check A — Layering principle.** Multiple smuggling vectors to catch:
  - **Multi-line string vector.** Any string field with line count > threshold (suggested: 5; tunable via constant). Tune so a 4-line type annotation passes while a 30-line docstring extract fails. Allowlist for known-large semantic fields (e.g., long docstrings) — but require explicit allowlist entry, never silent
  - **Field-name patterns.** Reject any field whose name matches `body`, `source`, `code`, `snippet`, `text`, or contains `_source`, `_body`, `_snippet`, `_code`, `_text`. These names should never appear in the schema. Pattern match on the response key, independent of value
  - **Default-value smuggling.** For `parameters[].default` fields specifically: if value is a string containing newlines OR length > ~80 chars, fail with a pointer to the spec's note that complex defaults should be omitted in favor of source pointers. Verifies Phase 3.2's "limit to simple literals" risk handling actually happened
  - **Indented-block heuristic.** Any string value containing patterns like `def`, `class`, `if`, `for`, `return` — these are syntactic smells of source code rendered as strings
  - On any failure, point to `feedback_pyeye_layering.md` and the spec's layering section
- [ ] **Check B — Absence-vs-zero invariant.** Mechanical, not heuristic:
  - Values in `edge_counts` are integers (no nulls, no booleans, no strings, no floats)
  - The set of keys in `edge_counts` is a subset of known edge types — no unknown keys
  - Implementation registers what it claims to measure (Phase 4 measures `members`/`superclasses`/`subclasses`/`callers`/`references`); the linter cross-checks that these keys appear (with 0 or positive values) on every node where they apply, and that other edge types do NOT appear
  - For `re_exports`, `highlights`, `tags`, `properties`: present-but-empty is valid; presence with `null` value is invalid (use absence to signal "not measured")
- [ ] Apply both checks to all responses from new operations across the test suite
- [ ] **Adversarial test suite for the linter itself.** Write tests that intentionally smuggle content via each plausible vector and verify the linter catches each one:
  - A response with a `body` field — caught by name pattern
  - A response with a `signature` containing 30 lines — caught by multi-line vector
  - A response with `parameters[].default` containing newlines — caught by default-value smuggling
  - A response with a `docstring` field formatted to look like indented code — caught by indented-block heuristic
  - A response with `edge_counts.read_by: 0` (where read_by is unmeasured in Phase 4) — caught by Check B
  - A response with `edge_counts.unknown_edge: 5` — caught by Check B (unknown key)
  - A response with `re_exports: null` — caught by Check B (null in optional field)
   These tests prove the linter has teeth. If any vector passes silently, the linter is incomplete.
- [ ] Add the linter as a pre-commit hook
- [ ] Run on existing implementation; verify clean pass
- [ ] Commit

**Constraint:** Heuristic for Check A must be conservative — false positives are tolerable (overridable with explicit allowlist); false negatives defeat the purpose. Check B is mechanical and exact, not heuristic.

**Acceptance:** Linter passes on current implementation. Adversarial test suite passes — every smuggling vector triggers the linter exactly once.

### Task 7.2: Re-export canonicality conformance

- [ ] Create `tests/integration/api_redesign/test_conformance.py` (or use the existing file)
- [ ] Conformance test (matching spec acceptance criterion 6): given a re-exported symbol,
  - `resolve("package.Config")` and `resolve("package._impl.config.Config")` return the same handle
  - `inspect(canonical_handle).re_exports` includes `"package.Config"`
  - (Note: edge expansion test for collapse comes when `expand` is implemented in a later plan — skip here)
- [ ] Run — should pass given Phases 1–6
- [ ] Commit

**Acceptance:** Conformance test passes against a fixture project.

### Task 7.3: Project/external boundary conformance

- [ ] In `test_conformance.py`, add (matching spec acceptance criterion 7):
  - `inspect("pydantic.BaseModel")` returns `scope: "external"` (use a fixture that imports pydantic, or mock the resolver)
  - Shallow-derived data only: kind, signature, docstring, members count, location in site-packages
  - `edge_counts.subclasses` reflects project subclasses only (set up fixture with at least one project class extending the external symbol)
- [ ] Run — should pass given Phases 3–4
- [ ] Commit

**Acceptance:** Conformance test passes.

### Task 7.4: Absence-vs-zero conformance

Matches spec acceptance criterion 10. Independent of Task 7.1's mechanical linter — this test validates the *semantic* contract on representative real-world responses.

- [ ] In `test_conformance.py`, add tests:
  - (a) Inspect a class with no subclasses (e.g., a leaf class in a fixture). Verify `"subclasses" in response.edge_counts` and `response.edge_counts["subclasses"] == 0` — measured-and-zero, present
  - (b) Inspect any Phase 1 node. Verify `"read_by" not in response.edge_counts` and similarly for the other unmeasured edges — unmeasured, absent
  - (c) Inspect a symbol with no re-exports. Verify either: re_exports is absent (if no re-export computation ran) OR re_exports == [] (if the computation ran and found none) — pick the behavior matching the implementation
  - (d) Inspect a Python kind. Verify `properties` is absent (it's only on plugin kinds)
  - (e) Document: a future implementation that adds `read_by` measurement should add the key to ALL responses (zero where applicable), not just where the count is positive. Cross-reference Phase 4's hard constraint
- [ ] Run — should pass given Phases 3–4 + linter from Task 7.1
- [ ] Commit

**Acceptance:** Both directions of the invariant verified on representative fixtures.

### Task 7.5: Wire-format ratio test (where measurable)

- [ ] In `test_conformance.py`, add (matching spec acceptance criterion 4 — partial; full ratio test requires `outline` which isn't in this plan):
  - **Record the LSP-bridge baseline as a literal byte count, not a recomputed value.** From the 2026-05-02 measurement: mcp-language-server's `definition` for the `GranularCache` class returned approximately 470 lines / ~17,500 bytes (one copy; both copies were ~35,000 bytes). Use the canonical-copy figure as the baseline. Hard-code this in the test as a literal with a comment: `# Baseline: 17,500 bytes from 2026-05-02 mcp-language-server definition call on GranularCache. Update only if methodology changes (different bridge, different fixture, different version).`
  - For `inspect`: measure response byte size on the same `GranularCache` fixture. Assert the ratio is ≤ 0.3× the literal baseline (i.e., ≤ ~5,250 bytes)
  - **Don't re-measure the baseline at test time.** Recomputing the baseline against the live LSP-bridge is brittle (pyright-lsp behavior drifts; mcp-language-server may change). Hard-coding makes the test fail for a known reason if pyeye regresses, rather than mysteriously
- [ ] Note in the test comment: actual measurement will likely be much smaller (~0.05–0.10×) because pyeye ships no source. The 0.3× floor is intentionally conservative; beating it comfortably is expected. If it's anywhere near 0.3×, content is leaking somewhere
- [ ] Run — should pass given the structural-only design
- [ ] Commit

**Acceptance:** Inspect response on `GranularCache` is well under 30% of the recorded baseline. Test fails for a known reason if a future change pushes the response size up.

### Task 7.6: Documentation

- [ ] Update `README.md` (or a new `docs/api-redesign.md`) with:
  - The three new operations and what they return
  - **Explicit explanation of the absence-vs-zero invariant** — agents and future contributors must understand "absent in `edge_counts` means we didn't measure" so they don't write code that assumes zero where they should accept uncertainty
  - Migration note: existing tools coexist; no breaking changes; new operations are additive
  - Cross-reference to spec, especially the "Absence vs. zero" subsection
- [ ] Update `.claude/instructions/03-mcp-dogfooding.md` if relevant — agents should prefer `resolve` + `inspect` over `find_symbol` + `get_type_info` for new code; document the invariant so prompts can rely on it
- [ ] Commit

**Acceptance:** Documentation explains how to use the new operations, signals they're the preferred shape, and treats the absence-vs-zero invariant as a load-bearing semantic rule (not a footnote).

---

## Phase 8: `TypeRef` recursive type resolution (post-spec-amendment; refines Phase 3)

Added after Phase 7 closed, when a 2026-05-04 spec amendment replaced flat `string` for type-annotation fields with the recursive `TypeRef` shape `{raw, handle?, args?}`. Phase 3.2 implemented these as flat strings (matching the original spec); Phase 8 brings them in line with the amended spec.

Pulled out as its own phase rather than folded back into Phase 3 because the test scenarios partition cleanly into distinct failure modes — clean leaf resolve, compound generic, PEP 604 union, Callable degraded path, typing-alias-vs-builtin head canonicalisation, unresolvable forward ref. Each warrants its own fixture and assertion. Bundling them into a single "kind-dependent properties" task obscures which scenario broke.

### Task 8.1: Failing tests for TypeRef shape

- [ ] Add tests to `tests/unit/mcp/operations/test_inspect.py` (or a new `test_inspect_typeref.py`) covering each TypeRef scenario distinctly:
  - (a) Bare-name leaf: `def f(x: Path)` → `parameters[0].type == {raw: "Path", handle: "pathlib.Path"}` (no `args`)
  - (b) Generic with typing alias: `from typing import Dict, List; def f(x: Dict[str, List[CustomModel]])` → root `handle == "typing.Dict"`, recursive args resolve to `builtins.str` / `typing.List` / `<project>.CustomModel`. Asserts the rule that `handle` is what Jedi resolves at the annotation site.
  - (c) Generic with PEP 585 builtin: `def f(x: dict[str, list[CustomModel]])` → root `handle == "builtins.dict"`. Implementation MUST NOT rewrite `typing.Dict` ↔ `builtins.dict`.
  - (d) PEP 604 union: `def f(x: str | None)` → TypeRef with `handle` absent at root, `args` containing both alternatives with their handles.
  - (e) Unresolvable forward ref: `def f(x: "FutureType")` where `FutureType` doesn't exist → `{raw: "FutureType"}` with `handle` absent. Asserts the no-guess rule (must not silently bind to an unrelated symbol).
  - (f) Callable degraded path: `def f(callback: Callable[[int, str], bool])` → TypeRef with non-empty `raw == "Callable[[int, str], bool]"`; `handle` and `args` may be absent. Conformant.
  - (g) Return type symmetry: `def f(...) -> Dict[str, CustomModel]` → `inspect(handle).return_type` is an equivalent TypeRef.
  - (h) Attribute type symmetry: `class C: field: List[CustomModel]` → `inspect("<project>.C.field").type` is an equivalent TypeRef.
- [ ] Run tests — should fail (current implementation returns flat strings)
- [ ] Commit (failing tests)

**Acceptance:** Tests pin down the recursive shape contract for every scenario the spec calls out, including both halves of the head-canonicalisation rule and the Callable degraded path.

### Task 8.2: Implement TypeRef builder

- [ ] Create the type-expression parser + leaf resolver. Suggested location: `src/pyeye/mcp/operations/typeref.py` (sibling to `resolve.py` / `inspect.py`):
  - Parse type expressions with `ast.parse(source, mode="eval")` — handles most forms; on parse failure, return `{raw: source}` with no `handle` or `args` (graceful degradation).
  - Walk the parsed AST recursively:
    - `ast.Name` / `ast.Attribute` as the head → call `resolve_canonical` with annotation-site file/line context. Populate `handle` only on exactly one definition; otherwise omit.
    - `ast.Subscript` → recurse into the slice for `args`.
    - `ast.BinOp` with `ast.BitOr` (PEP 604 union) → emit TypeRef with `args` for each alternative, no `handle`.
    - `ast.Constant(str)` (PEP 484 forward-ref strings) → re-parse the string and recurse.
  - **Must-not-guess discipline**: handle is populated only when Jedi `goto` returns exactly one definition. Multiple or zero results → absent. No fallback to global bare-name search (avoid the lookup-style failure mode the spec explicitly cites).
- [ ] Replace flat-string population in `inspect.py`:
  - `_build_parameters` (line 230): each `param_dict["type"]` becomes a TypeRef.
  - `_extract_return_type` (line 312): returns a TypeRef (or `None`) instead of a string.
  - `_extract_attribute_info` (line 338): returns `(TypeRef | None, default_str | None)`.
- [ ] Run Task 8.1 tests — should pass
- [ ] Run full suite (`uv run pytest --cov=src/pyeye --cov-fail-under=85`) — verify no regressions in legacy tools or existing inspect tests
- [ ] Commit

**Risk — performance.** Each annotation triggers multiple Jedi goto calls (one per leaf). A function with 5 parameters of 2-leaf compound types is 10+ goto calls per inspect. Cache aggressively per `(file, type-string)` — leaves repeat heavily within a module. The Phase 4 per-edge time budget doesn't apply (TypeRef is part of universal/kind-dependent fields, not `edge_counts`), but consider a per-annotation soft cap to bound worst case.

**Risk — Callable / Literal / Annotated frequency.** Common in real codebases — proportion of annotations hitting the degraded path is non-trivial. Wire the metrics requirement from the spec (track which annotation shapes hit degradation, by category — Callable, Literal, Annotated, ParamSpec, etc.) in this task. Even a simple `metrics.measure("typeref_degraded", category=...)` is enough to start. This makes future-pass prioritization empirical, not guessed.

### Task 8.3: Conformance fixture for spec criterion 14

- [ ] Create `tests/integration/api_redesign/fixtures/typeref_compound/`:
  - `models.py` defining a project class `CustomModel`
  - `service_typing_aliases.py` — uses `from typing import Dict, List`; `def process(x: Dict[str, List[CustomModel]]) -> List[CustomModel]`
  - `service_pep585.py` — same shape with `dict`, `list` builtins
  - `service_callable.py` — `def register(callback: Callable[[int, str], bool]) -> None`
  - `service_forward_ref.py` — `def future(x: "DoesNotExist") -> None`
- [ ] Add a test in `tests/integration/api_redesign/test_conformance.py` covering criterion 14: verify both fixture-A and fixture-B produce the expected handles (asserting `typing.Dict` vs `builtins.dict` distinction); verify Callable returns non-empty `raw`; verify forward-ref leaf has absent `handle`; verify return_type symmetry on the typing-aliases fixture.
- [ ] Run — should pass given Task 8.2
- [ ] Commit

**Acceptance:** Criterion 14 conformance test passes against both fixtures. The typing-vs-builtin distinction is preserved in the wire format. The Callable and forward-ref degraded paths are detected as conformant (no false handles).

### Task 8.4: Update agent-facing documentation

- [ ] Update `docs/api-redesign.md` (from Phase 7.6): describe the TypeRef shape on type-bearing fields, show a worked example response with a nested TypeRef tree, cross-reference the spec subsection.
- [ ] Update `.claude/instructions/03-mcp-dogfooding.md` if any examples reference `param.type` as a string — agents need to know the field is now a tree.
- [ ] Verify the conformance linter (Phase 7.1) doesn't false-positive on TypeRef's nested `raw` strings (which can be longer than the linter's multi-line threshold for compound types). Adjust the linter's allowlist if needed; otherwise it'll flag legitimate complex annotations.
- [ ] Commit

**Acceptance:** Documentation matches the implemented shape. An agent reading docs alone would correctly walk the TypeRef tree. Conformance linter doesn't false-positive on legitimate TypeRef.raw values.

---

## Verification gates between phases

After each phase, before moving to the next:

- [ ] Full test suite green: `uv run pytest --cov=src/pyeye --cov-fail-under=85`
- [ ] Pre-commit hooks pass (no `--no-verify`)
- [ ] Existing tools still pass their tests (the additivity constraint)
- [ ] Manual smoke test: invoke the new operation(s) via MCP and verify shape matches the spec for at least one Python kind

If any gate fails, stop and resolve before advancing. Don't accumulate test debt.

---

## Cross-cutting: Spec alignment

Every commit on this branch should leave the spec and the code consistent. If implementation surfaces a need that the spec doesn't address (e.g., an edge case in canonicalization, a field not currently in the schema), update the spec in the same commit or its own preceding commit. Don't ship code that contradicts the spec; don't leave the spec behind.

---

## Rollout note

Phases 1–4 are the first PR-able deliverable. They can be opened as a PR after commits land. Phases 5–7 can either:

- Land as follow-on commits to the same PR (cleaner history, single PR review)
- Be split into a second PR (smaller reviews, faster initial merge)

I'd suggest the first option — Phases 5–7 are small enough that a single coherent PR is reviewable, and shipping the full Phase 1 deliverable in one merge is cleaner for downstream consumers.

**Phase 8 should be its own PR.** It was added after Phases 1–7 closed (post-spec-amendment), it touches the wire format of `inspect` for every Python kind that has type-bearing fields, and it has substantial implementation surface (parser, recursive resolver, four distinct conformance scenarios). Folding it into the Phases 1–7 PR would balloon review scope and obscure the type-resolution work in a sea of unrelated infrastructure. Ship Phases 1–7 first, then Phase 8 as a focused follow-on.

**Personal-discipline checkpoint after Phase 4 lands.** Before starting Phase 5, deliberately use `resolve` + `inspect` for at least a week of your own daily work in this codebase. Resist falling back to `find_symbol` + `get_type_info` when habit pulls. The truest test of whether the redesign delivers what we wanted is whether the new operations naturally feel better, not whether they pass conformance tests. If they feel worse — heavier, more friction, less informative — stop and rethink before adding highlights/re_exports on top. Phase 4's deliverable should already be visibly better in daily use; if it isn't, layering more on top won't fix it.

After this plan completes, the natural follow-ons are:

- **Plan: `outline` implementation** — needs the same `members` walking code Phase 4 builds, plus tree-shaped responses and the external-scope cap
- **Plan: `expand` implementation** — needs cursor mechanics, the missing edge type analysis (`read_by`/`written_by`/`passed_by`/`decorated_by`/`decorates`/`imports`/`imported_by`/`callees`/`overrides`/`overridden_by`/`enclosing_scope`)
- **Plan: `trace` implementation** — needs `expand` plus BFS with handle dedup, stop predicates, subgraph assembly
- **Plan: Plugin migration** — Pydantic plugin's existing tools become deprecated thin wrappers over derived views

---

## Cross-references

**Spec:**

- [`docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`](../specs/2026-05-02-progressive-disclosure-api-design.md)

**Project memory:**

- `feedback_pyeye_layering.md` — the layering principle (no content shipping)
- `project_api_redesign.md` — the redesign direction overall

**Predecessors:**

- [`docs/superpowers/specs/2026-03-27-tool-ergonomics-design.md`](../specs/2026-03-27-tool-ergonomics-design.md)
- [`docs/superpowers/specs/2026-03-27-unified-lookup-tool-design.md`](../specs/2026-03-27-unified-lookup-tool-design.md)
- [`docs/superpowers/plans/2026-05-02-lookup-performance-cache.md`](2026-05-02-lookup-performance-cache.md) — cache infrastructure (Phase 1 complete; Phases 4–6 on hold pending API redesign)

**Issues:**

- #316 — tool ergonomics
- #320 — symbol_name parameter (subsumed by canonical handles)
- #321 — module FQN handling (subsumed by canonical handles)
