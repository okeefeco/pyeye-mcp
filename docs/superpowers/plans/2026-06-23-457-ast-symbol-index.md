# #457 — AST symbol index (Phase A PR) + #397 shared project-graph store (Phase B follow-up PR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Subagent path note:** pass worktree-relative paths (or this worktree's root) in task prompts — never absolute paths into the main checkout (see [[feedback_worktree_path_anchoring]]).

**Goal:** Make bare-name / leaf enumeration **complete and deterministic** by replacing `JediAnalyzer._search_all_scopes`'s use of `jedi.Project.search()` (silently truncates at Jedi's 30-parsed-file cap, dropping real defs of high-frequency names like `Field`/`View`/`Form`) with a build-once, **non-evicting, whole-project, invalidate-and-rebuild** AST name→definitions index — and, as a guarded second pass, fold the duplicated O(project)-per-call AST-graph rebuilds (`subclasses`, `imported_by`) onto that same store (the #397 consolidation), without adding a parallel mechanism.

**Architecture:** One shared, per-project, **watcher-invalidated, non-evicting** store holds the AST-derived graph artifacts (name→definitions index now; class/import graphs in Phase B), built by streaming every project `.py` once through the existing `file_artifact_cache.get_ast` and the existing extraction primitives in `base_resolution.py` (**no `goto`, no `get_references`, no Jedi search**). **Every artifact is built whole-project** (the union of all scope paths) so all three share one build pass and one project key; **scope narrowing happens at lookup time, never at build time** (baking scope into a project-keyed cache poisons it). ASTs continue to live in the one `file_artifact_cache` LRU — this store holds only compact metadata, kept *out* of the LRU so completeness can never depend on cache size. `_search_all_scopes` consumes the whole-project name-index and filters by the scope-resolved path set, in place of `project.search`. In Phase B, `find_subclasses`/`imported_by` read their graphs from the store instead of rebuilding per call, each gated by a differential equivalence test.

**Tech Stack:** Python, `ast`, `pyeye.analyzers.base_resolution`, `pyeye.file_artifact_cache`, `pyeye.analyzers.jedi_analyzer`, `pyeye.cache`, pytest. Verify against the pinned `pyeye-scenarios` Django scenario (`django/django @ cd385e6b8c`).

**Phasing / release safety:** **Phase A (Tasks 1–5) is the #457 fix and ships as its OWN PR** — `priority: high`, v2.0-blocking (#470). **Phase B (Tasks 6–8) is the #397 consolidation and ships as a SEPARATE follow-up PR** on the same `project_graph.py` seam (which Phase A seeds): it is post-2.0 (#470 lists #397 as such), is purely a perf change guarded by equivalence tests, and **deletes hot-path code (Task 8)** — so it is deliberately decoupled from the v2.0-blocking fix to keep that fix's blast radius and review surface small. **Default to two PRs**; only combine if Phase B proves trivial before Phase A merges.

---

## Background (root cause — already diagnosed, do NOT relitigate)

`_search_all_scopes` → `project.search(name, all_scopes=True)` greps project files in walk order and `break`s after `jedi.inference.references._PARSED_FILE_LIMIT = 30` parsed files. Django has 56 files containing `Field` (31 under `db/`, walked first), so the budget is exhausted before `django/forms/fields.py` → only `django.db.models.fields.Field` survives (there are 3 project `Field` classes). Raising `_PARSED_FILE_LIMIT` is a non-fix (Jedi-internal monkeypatch; moves the cliff). Same disease #405 cured for `find_subclasses`; `_search_all_scopes` is the last major `Project.search` consumer. Full proof on issue #457 (two maintainer comments).

## Fit with existing mechanics (decisions — avoid adding duplication)

- **One AST cache only:** ASTs come from `file_artifact_cache` (the LRU). This plan adds **no** AST cache. Task 4 raises that LRU's default; the new store holds only metadata.
- **Reuse the extraction layer:** `src/pyeye/analyzers/base_resolution.py` already owns the shared AST extractors — `build_module_defines(tree) -> dict[str,str]` (top-level name→kind: `class`/`func`/`other`/`import`), `build_import_table`, `build_star_sources`. The new name→definitions extractor is **added here**, reusing those kind conventions — NOT a parallel walker in a new module.
- **One Jedi-`Name` stand-in, not three (closes #450):** `_module_sentinel.py` already holds two copy-pasted Jedi-`Name` stand-ins — `ModuleSentinel` (`:27`, #436 `imported_by`) and `ClassSentinel` (`:104`, #445 `subclasses`) — each re-defining `docstring()`/`get_signatures()→[]`/`infer()→[]`. #457's result object would be the **third copy** #450 predicts. Instead, factor a shared `NameSentinel` base and make all three thin subclasses — so #457 **closes #450** rather than worsening it. This is the determinism pattern (#449): build edge adjacents from AST facts via a stand-in, never re-derive a Jedi `Name`.
- **The store IS the #397 substrate:** #397 ("cache the inverted class/import graph per watcher-generation") is the duplication tracker — today `find_subclasses` (`_build_ast_resolution_tables`) and `imported_by` (`find_importers`) rebuild O(project) per call. This plan builds the shared invalidate-and-rebuild store once (Phase A) and migrates those consumers onto it (Phase B), so #457 **seeds** the shared store rather than adding a fourth copy.

## Consumer contract for `_search_all_scopes` (decisions — honor exactly)

`_search_all_scopes(name, scope) -> list[Any]` returns Jedi-`Name`-like objects, read by its **4 callers** in `jedi_analyzer.py` — `find_symbol` (`:693`), the parent-component lookup (`:770`), the call-hierarchy function search (`:1420`), and the `_build_navigable_ref` resolve/`goto_definition` fallback (`:2554`) — for these attributes:

`.name` · `.module_path` (a `Path`) · `.line` (1-based) · `.column` (0-based) · `.full_name` · `.type` (`class`/`function`/`statement`/`module`) · `.description` · `.docstring()`

**Hard constraint on `.line`/`.column`:** the call-hierarchy consumer (`:1438`) feeds them straight into `script.get_references(function_def.line, function_def.column)`, which needs the **exact position of the name identifier** (the column of `Field`, not of the `class`/`def` keyword). AST-derived coords MUST equal Jedi's for the same def — internal self-consistency is not enough; wrong coords silently break call hierarchy. Verified by a dedicated test (Task 1).

The index result object is a third `NameSentinel` subclass (closes #450) and must expose all of the above, all AST-derived. `find_symbol` returns `list[dict]` (it converts Names→dicts); its downstream (`resolve._resolve_bare_name`/`_resolve_dotted_name`, `lookup.py`, `canonicalization.py`, `server.py`) consume dicts and is unchanged/out of scope. Completeness is the fix (#332 honesty): return *every* project definition of a name.

## File Structure

- **`src/pyeye/analyzers/base_resolution.py`** (MODIFY) — add the positions+nesting name→definitions extractor beside `build_module_defines` (it produces `NameSentinel` stubs; the stub *type* lives in `_module_sentinel.py`).
- **`src/pyeye/_module_sentinel.py`** (MODIFY, **closes #450**) — factor a shared `NameSentinel` base (`module_path/type/full_name/name/line/column`, no-op `get_signatures()/infer()`, default `docstring(**kwargs)`); refactor `ModuleSentinel`/`ClassSentinel` onto it (no behavioural change); add the #457 result object as the third thin subclass (flexible `type`, real `docstring()`, `description`).
- **`src/pyeye/analyzers/project_graph.py`** (NEW) — the per-project, **non-evicting, invalidate-and-rebuild** store: holds the **whole-project** name-index (Phase A) and the class/import graphs (Phase B); `get_*`/`invalidate` API + a per-project build guard. (Named for the #397 "project graph" framing; the seam subclasses/imported_by migrate onto.)
- **`src/pyeye/analyzers/jedi_analyzer.py`** (MODIFY) — `_search_all_scopes` consumes the name-index (Phase A); `find_subclasses`/`imported_by` (`find_importers`) read graphs from the store (Phase B); wire watcher invalidation; docstrings.
- **`src/pyeye/cache.py`** (MODIFY) — call store invalidation from `invalidate_file`/`invalidate_all`.
- **`src/pyeye/settings.py`** (MODIFY) — raise `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` default.
- **`tests/...`** (NEW) — extractor units, store correctness, #457 Django regression, Phase-B equivalence tests.

---

## Phase A — #457 fix (its own PR)

## Task 1 — `NameSentinel` base (closes #450) + name→definitions extractor

**Goal:** Produce the complete, deterministic name→definitions mapping that replaces the truncating search — reusing the shared extraction home (`base_resolution.py`) for the walker and a shared `NameSentinel` base (`_module_sentinel.py`) for the result stub, rather than a parallel walker or a third copy-pasted Jedi-`Name` stand-in (#450).

**Files:** `src/pyeye/_module_sentinel.py` (the `NameSentinel` base + the three subclasses), `src/pyeye/analyzers/base_resolution.py` (the extractor).

**Interfaces (produce):**

- **`NameSentinel` base (closes #450):** carries `module_path / type / full_name / name / line / column`, no-op `get_signatures() -> []` / `infer() -> []`, and a default `docstring(**kwargs) -> str` — match the existing `**kwargs` signature in `_module_sentinel.py`, NOT `raw=False`. Refactor `ModuleSentinel` (`:27`) and `ClassSentinel` (`:104`) to subclass it with **no behavioural change**.
- **The #457 result object** = a third thin `NameSentinel` subclass exposing exactly: `name`, `module_path: Path | None`, `line`, `column`, `full_name: str | None`, `type` (`"class"|"function"|"statement"|"module"`), `description: str`, `docstring()`.
- `extract_definitions(tree: ast.Module, module_name: str | None, module_path: Path) -> list[<NameSentinel-subclass>]` — pure; all defs in one module incl. **nested** (methods, nested classes), `full_name` from `module_name` + lexical nesting. Reuse `build_module_defines`' kind vocabulary (map `class`→`class`, `func`→`function`, module-level assignment→`statement`).

**Tests (pin behavior):**

- A class defined in a module → one entry, `type=="class"`, `full_name=="<module>.<Class>"`, correct `line`/`column`.
- A method `m` in class `C` (module `pkg.mod`) → `full_name=="pkg.mod.C.m"`, `type=="function"`.
- `async def` → `type=="function"`; module-level `x = 1` → `type=="statement"`.
- `docstring()` returns the def's docstring via `ast.get_docstring`, `""` when absent.
- Determinism: same tree → identical ordered output.
- **#450 refactor guard:** `ModuleSentinel`/`ClassSentinel` round-trip through `build_stub` (`mcp/operations/stubs.py:91`) and the trace hop unchanged — existing tests `test_subclasses_no_silent_drop.py`, `TestResolveImportedByModule`, `TestTraceSubclassesPerHop` stay green (no behavioural change to `expand`/`trace`).
- **Jedi-exact coordinates (load-bearing for call hierarchy):** for class / `def` / `async def` / decorated defs, the extractor's `(line, column)` equals what Jedi reports for the same definition's **name token** — assert against a real Jedi `Script` over a fixture (handle the `class`/`def`/`async def` keyword offset and decorators). Guards the `get_references` consumer (`:1438`).

**Constraints:** Pure AST, **no `goto`/`infer`/Jedi search**. `.line` 1-based, `.column` 0-based at the def-name position, matching Jedi's convention for the same definition so dedup keys/downstream locations stay byte-stable on non-truncated names.

**Acceptance:** Tests pass; `grep` confirms no `goto`/`search`/`get_references` added (the #449 static-edge determinism invariant); `_module_sentinel.py` has one `NameSentinel` base with no duplicated `get_signatures`/`infer`/`docstring` bodies (#450 acceptance); existing sentinel tests green.

**Risks:** `full_name` namespace-prefix composition must match what `_search_all_scopes` produces today (Task 3 supplies `module_name` via the same `_get_import_path_for_file`/ns-root logic, `_search_all_scopes:263-288`). Add a **namespace fixture test** asserting the extractor's `full_name` byte-equals Jedi's for a namespace-package def — not just the single-def regular-package case. Verify `_get_import_path_for_file` actually emits the namespace prefix before relying on it.

## Task 2 — non-evicting, invalidate-and-rebuild project-graph store

**Goal:** Cache the **whole-project** name-index built-once, **outside the LRU**, rebuilt on invalidation — because an evictable index = a name silently missing = #457 reincarnated. This store is the #397 substrate.

**Files:** `src/pyeye/analyzers/project_graph.py` (new); `src/pyeye/cache.py` (invalidation wiring).

**Interfaces (produce):**

- `get_name_index(project_key, py_files, file_to_module) -> dict[str, list[<ResultClass>]]` — `py_files` is the **whole-project union of all scope paths** (main + additional + namespaces), NOT a scope subset; the cached index is keyed purely by `project_key`. Builds on first call / after invalidation, streaming `file_artifact_cache.get_ast` + `extract_definitions`; otherwise returns cached. **Scope is applied by the caller at lookup (Task 3), never baked into the build** — otherwise the first scope poisons the project-keyed cache.
- `invalidate(project_key=None) -> None` — drop cached graph(s) for a project (or all). Wire it to **both** file change (watcher path) **and project eviction** (when `project_manager`'s LRU drops a project) — a non-evicting store keyed by an evicted project otherwise leaks.
- A **build guard** (per-project lock / single-flight): concurrent first-callers must not double-build, and the parse-bound build runs **off the event loop** (`asyncio.to_thread`) so it doesn't block other MCP requests for seconds.
- (Phase B will add `get_class_graph` / `get_import_graph` to the same store + builder — also whole-project, sharing this build pass.)

**Tests (pin behavior):**

- **Completeness-not-behind-LRU (load-bearing):** after building the index, drive enough unrelated `file_artifact_cache.get_ast` calls to exceed `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`; assert the index still returns all defs of a name (no eviction drop).
- **Freshness:** after `invalidate(...)`, the next `get_name_index` reflects an added/removed def; without invalidation it returns the same cached object (build-once).

**Constraints:** Non-evicting; compact metadata only (no ASTs retained). Build is parse-bound (seconds), paid once per build — NOT per `resolve`. Invalidation wired into the existing watcher path (`cache.invalidate_file`/`invalidate_all`) **and** project eviction. **Mechanism = invalidate-and-rebuild keyed by project** (no generation counter): do **not** build #397's generation-numbering model, and do **not** describe this as "generation-pinned" — minimal clear-and-rebuild is sufficient for v2.0; per-file incremental patching is out of scope.

**Acceptance:** Tests pass; lookups are O(1) dict access post-build.

**Risks:** Whole-index invalidation on any change is acceptable (rebuild cheap). Keep the store keyed by `project_key` so multiple analyzed projects don't collide; and **test that eviction-invalidation actually fires** so memory doesn't grow unbounded across many analyzed projects.

## Task 3 — wire `_search_all_scopes` onto the name-index

**Goal:** Replace the `project.search` loop with index lookups, preserving every other behavior so the 4 consumers get complete results with no other change.

**Files:** `src/pyeye/analyzers/jedi_analyzer.py`.

**Interfaces (consume):** `get_name_index` + result object (T1/T2); existing `get_project_files`, `_get_import_path_for_file`, `_resolve_scope_to_paths`.

**Tests (pin behavior):**

- Fixture with a name defined in >1 module across scope → `_search_all_scopes("Field")` returns **all** defs, deduped by `(name, module_path_as_posix, line)`.
- **Scope applied at lookup, not build (cross-scope-poisoning regression):** call `scope="main"` first, then `scope="all"`, from the **same whole-project index**, and assert `all` is NOT narrowed to the `main` subset. Mirror existing `main`/`all`/namespace scope tests.
- `_jedi_root_is_parent` filter still excludes out-of-project results.
- Build a `find_symbol` dict end-to-end from a result → dict shape **byte-stable** vs pre-change for a single-definition (non-truncated) name.
- **Behavior-change guard:** a name with **no project definition** (only ever imported) now returns `[]` (the AST def-index yields definitions, not import bindings). Confirm no existing test encoded the old import-site behavior.

**Constraints:** Preserve the existing dedup key `(r.name, Path(r.module_path).as_posix() if r.module_path else None, r.line)` and namespace `full_name`-prefix handling. Build/cache the index **whole-project** (union of all scope paths), then narrow by filtering results to `_resolve_scope_to_paths(effective_scope)` **at lookup** — preserving main/additional/namespace routing without baking scope into the cache. `find_symbol` and the other 3 consumers unchanged except completeness. Keep `_search_all_scopes` async (the lookup is sync dict access; the one-time build is the only heavy work — run it off the event loop per Task 2). `project.search(` must be gone from it (grep-clean).

**Acceptance:** Existing `_search_all_scopes`/`find_symbol`/`resolve` tests pass unchanged for non-truncated names; new completeness tests pass.

**Risks:** If the parent-lookup / call-hierarchy / 4th consumer read a Jedi-only method beyond the contract list, extend the AST result object (still goto-free) rather than reintroducing search.

## Task 4 — raise the LRU working-set default

**Goal:** The index build + whole-project ops touch every file; the 500-entry LRU under-sizes that (django package 907, repo 2,922). Raise it as a latency lever — independent of correctness (Task 2 guarantees that regardless).

**Files:** `src/pyeye/settings.py`.

**Tests:** default raised from 500; `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` env override still wins; positive bounded int.

**Constraints:** Size toward large-project file counts with a memory-aware ceiling (≈2.9k resident ASTs ≈ hundreds of MB — not unbounded). The exact number is an implementation decision justified by a quick resident-memory check; pin it in the test once chosen. Must NOT be relied on for #457 correctness.

**Acceptance:** Test pins the new default + env override.

## Task 5 — #457 Django regression + store correctness

**Goal:** Prove the user-visible bug is fixed end-to-end against the pinned scenario.

**Files:** `tests/...` (use the `pyeye-scenarios` Django scenario + the repo's scenario-availability skip; real fixture dirs — macOS-symlink caveat).

**Tests (pin behavior):**

- `resolve("Field")` on django → **ambiguous**, candidates include all 3 (`django.db.models.fields.Field`, `django.forms.fields.Field`, `django.contrib.gis.gdal.field.Field`).
- `resolve("django.forms.fields.Field")` → correct handle with a **real line** (class def), not the degraded line-1/col-0 fallback.
- A high-frequency name exceeding the 30-file cap returns >1 project def.

**Acceptance:** Tests fail on `main` (pre-fix), pass on this branch; full suite + coverage ≥85%; first-`resolve` cold build measured (parse-bound seconds, NOT #405's goto-bound ~150s) via the repo's `PerformanceThresholds` framework (no naive timing assert).

**Risks:** Cold-build cost on django — measure; the pure-AST build avoids #405's goto cost but confirm.

---

## Phase B — #397 consolidation (folded in, equivalence-guarded, separable)

> Each task migrates a currently-duplicated O(project)-per-call rebuild onto the Task 2 store. These edges are **already correct** (AST-based, not `project.search`) — so the migration is a **perf** change and its gate is a **differential equivalence test** (cached == per-call), run **before** the old path is deleted. **The equivalence test is a transitional one-shot gate:** Task 8 deletes the per-call comparator, after which it can no longer run — so before deletion, **snapshot the per-call Django output as a fixture**, and rely on the existing (kept) subclasses/imported_by behavioral tests as the long-term regression guard. If a migration can't prove equivalence cheaply, stop and leave it for #397 proper — Phase A already shipped #457.

## Task 6 — migrate `find_subclasses` resolution tables/class-graph onto the store

**Goal:** Stop rebuilding `_build_ast_resolution_tables` + the parent→children class graph on every `find_subclasses`/`expand(subclasses)`/`trace` call; read them from the invalidate-and-rebuild store instead — the #397 payoff for the class graph.

**Files:** `src/pyeye/analyzers/project_graph.py` (add `get_class_graph`/resolution-tables to the store + one-pass builder), `src/pyeye/analyzers/jedi_analyzer.py` (`find_subclasses` consumes the store).

**Interfaces (produce):** `get_class_graph(project_key, ...) -> <parent_fqn → set[child_fqn]>` (and the import/define/star tables it derives from) cached in the store; built in the same streaming pass as the name-index where possible.

**Tests (pin behavior — the validation gate):**

- **Differential equivalence:** on the Django scenario, `find_subclasses(<class>)` via the cached store returns a result **set-equal** to the current per-call implementation for a representative spread of classes (incl. a high-fanout one like `Model`/`AltersData`). This is the "validate it isn't broken before expanding" gate.
- A second call hits the cache (no rebuild) — assert via a build counter/spy.
- Invalidation: editing a file rebuilds the class graph (no stale subclasses).

**Constraints:** Result must be **byte/set-identical** to today (this is perf, not behavior). Honor the #422 direct-only `subclasses` contract and the count-consistency invariants. Only remove the per-call rebuild after the equivalence test is green.

**Acceptance:** Equivalence test passes on django; existing subclasses/superclasses/trace tests unchanged; per-call `_build_ast_resolution_tables` rebuild no longer runs once the store is built (spy-confirmed).

**Risks:** Subtle resolution-table differences (relative imports, star re-exports) — the equivalence test on django is the safety net; if it diverges, fix the store builder, do not weaken the test.

## Task 7 — migrate `imported_by` import-graph onto the store

**Goal:** Stop rebuilding the inverted import graph (`find_importers`) per `imported_by`/`trace` call; read it from the store — the #397 payoff for the import graph.

**Files:** `src/pyeye/analyzers/project_graph.py` (add `get_import_graph`), `src/pyeye/analyzers/jedi_analyzer.py` (`find_importers`/`resolve_imported_by` consume the store).

**Tests (pin behavior — the validation gate):**

- **Differential equivalence:** on django, `imported_by(<module>)` via the store is set-equal to the current per-call result for a spread of modules.
- Cache-hit on second call (spy); invalidation rebuilds on file change.

**Constraints:** Byte/set-identical to today; preserve the module-only contract + dynamic-import ceiling. Remove the per-call build only after equivalence is green.

**Acceptance:** Equivalence test passes; existing imported_by tests unchanged; per-call rebuild gone once the store is built.

**Risks:** As Task 6.

## Task 8 — remove the now-dead per-call rebuild paths

**Goal:** Delete the superseded O(project)-per-call rebuilds once both equivalence gates are green, so the duplication is actually gone (not just shadowed).

**Files:** `src/pyeye/analyzers/jedi_analyzer.py` (and `base_resolution.py` if a builder is now only called via the store).

**Constraints:** Only delete code with no remaining caller (grep-confirmed); full suite green. Keep the shared `base_resolution.py` primitives (still used by the store builder).

**Acceptance:** `grep` shows no remaining per-call `_build_ast_resolution_tables`/`find_importers` rebuild on the hot path; full suite green; coverage ≥85%.

---

## Task 9 — docs + decision note

**Goal:** Record the contract + the #457/#397/#450 relationship, place #457 in the #449 determinism thread, and refresh stale docstrings.

**Files:** `jedi_analyzer.py` / `project_graph.py` docstrings; `docs/decisions/DECISIONS.md` (decision-log skill at commit — contract-significant + friction-driven).

**Constraints:** Decision note `Verify` cites the #457 Django regression + the completeness-not-behind-LRU test + the Phase-B equivalence tests. State: Phase A (its own PR) unblocks **#470** (v2.0); Phase B (separate follow-up PR) is the **#397** first increment (invalidate-and-rebuild store seeded here; full generation-numbering model still #397); lineage with #405 ([[project_subclasses_perf]]). Phase A **closes #450** (the `NameSentinel` base) and is the next entry in the **#449** determinism thread — the note states the static-edge determinism invariant it instantiates (AST-derived facts, never per-adjacent Jedi re-derivation) and references #449. Phase B ships separately by default, so the Phase-A note covers Phase A only and #397 stays open until Phase B lands.

**Acceptance:** Docstrings no longer claim `project.search`/per-call rebuild; decision entry appended.
