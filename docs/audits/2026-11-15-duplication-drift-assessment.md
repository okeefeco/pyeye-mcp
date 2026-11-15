# Duplication and drift assessment: pyeye `src/` (2026-11-15)

<!-- Audience: Both. This is a point-in-time audit, not a living document. -->

**Trigger:** issue #602. Edge-emitted stdlib module handles don't round-trip, and a bare `functools` resolves silently to `jaraco.functools`.

**Question:** is #602 a local bug, or a symptom of build iterations that each fixed one thing while adding copies that then drifted apart without anyone seeing it?

**Baseline:** `main` @ `7e18ab4`. Since then the only upstream change is a dependency bump, `d615b3a`.

**Tracking:** epic #629. Phase 0: #614, #615, #616. Phase 1: #617–#622. Phase 2: #623–#627. Phase 3: #628.

## 1. Bottom line

The hypothesis holds. The git history shows it directly.

- **Copies are made at fix time, and fixes reach only one copy.**
  - The Jedi synthetic-import inference was copied from `inspect` into `resolve` in the same PR (#328). The copy had *no* acceptance guard, under a docstring that said it "Mirrors" the original.
  - #546 later added a guard to a third copy in `canonicalization`. #566 carried that guard into `resolve`, but never touched `inspect`.
  - Today, three copies apply two different guards, and `resolve("os.path")` and `inspect("os.path")` give opposite answers.
- **Decisions are applied at the site where the friction showed up, not everywhere they govern.**
  - #457 (use the AST name-index, not `project.search`) still has `project.search` in `inspect` and `project_manager`.
  - #454 (reconcile stub scope) was never applied to `resolve_at`.
  - #545 (one not-found shape) covers 3 of 5 tools.
  - #360 (one module-scope walk) covers 2 of 5 walkers.
  - In no case would the decision's own *Verify* check catch the gap. One test even pins the banned `project.search` path as expected behaviour.
- **Fallbacks pile up; nothing is replaced.**
  - `_find_jedi_name_for_handle` grew from 4 strategies to 5, plus a post-processor and a retry wrapper.
  - `resolve._resolve_dotted_name` grew from 3 placement steps to 7.
- **Nothing in the repo checks a rule at more than one site.**
  - No round-trip test, no tool-agreement test, and no duplicate-code check.
  - The architecture-review skill explicitly excludes duplication (#495, open).
  - Tests are spread across about 100 calls to private helpers, which pin each copy separately.

**Consequences found:**

- About a dozen confident-wrong or silently-partial answers. Three or four are more serious than #602 (§4.1).
- About 1,400 lines (~45%) of `jedi_analyzer.py` can't be reached from any MCP tool.
- Eight comments claim one copy matches another, and are false.

**Recommendation:**

1. Fix visibility first: add cross-tool fitness tests, and make them fail on today's gaps (allow-listed with issue numbers).
2. Then consolidate behind one handle resolver, one edge-kind policy and one cache-invalidation path. Each consolidation PR removes a copy *and* turns its allow-list entries green.
3. Do the cleanup in steps, each tied to a guard test, not as one big rewrite. §6 has the order.

## 2. How this was measured

Four independent read-only investigations, plus the earlier resolution-layer audit:

- the architecture-review auditor;
- a per-tool resolution-path map;
- git-history archaeology;
- a tool-surface duplication audit;
- an analyzer/plugins/support-module audit;
- a guardrail and decision-drift audit.

I re-checked every load-bearing claim myself before it went in here.

**Markers:**

- **[V]** — verified by me in this session (code read, git, or a probe I ran).
- **[V-agent]** — verified by an investigator's probe or reading; I did not re-run it.
- **[I]** — inferred, not executed.

**Probe I ran** (`/tmp/rt602.py`):

- For every module in `src/pyeye` (59 modules), `expand` on `imports`, `members`, `superclasses` and `callees`, then feed every distinct emitted handle (488) back into `resolve` and `inspect`.
- Result: **31 of 488 (6.4%) can't be resolved by either tool. All 31 are `scope: external`.** Examples: `ast`, `asyncio`, `typing.TYPE_CHECKING`, `typing.Callable`, `__future__.annotations`.
- Under `get_analyzer`, resolve and inspect agreed on found/not-found for all 488.
- An investigator found they *disagree* under a bare `JediAnalyzer(".")` [V-agent].

## 3. How drift gets in

| # | Mechanism | Evidence |
|---|---|---|
| M1 | **Layering forces copies.** `inspect` imports `resolve`, and `edges` imports `resolve`. `resolve` is the leaf, so anything it needs from above gets copied, or is pushed down to `canonicalization` only once someone notices. Private cross-module imports (`resolve._normalise_kind`, `inspect._build_signature`, …) work around it. | The inference copy in `1a1eedd` (#328) was made because `inspect` already imported `resolve` [V]. DECISIONS #444 records that resolve "can't import edges". |
| M2 | **Fix scope = the reproduction tool.** A PR's tests exercise one entry point, so only that copy changes. | #546 changed canonicalization only. #566 changed canonicalization and resolve, not inspect [V `3bb0023 --stat`]. #454 changed `build_stub` only. #457 explicitly scoped out inspect. |
| M3 | **Fallbacks stack.** "It missed X" becomes "add a strategy", so the order of strategies differs per tool. | `_find_jedi_name_for_handle`: #328 (4 strategies), #432 anchor, #453 namespace case, #433 retry wrapper. `_resolve_dotted_name`: 3 steps → 7 [V-agent]. |
| M4 | **Parity claims are written once and never re-checked.** | 8 stale or false cross-references (§4.5). |
| M5 | **Consolidations stop at the PR's own diff.** #406, #444, #342 and #545 each unified *their* call sites and left behind copies and dangling pointers. | `edges.py:1218` → `inspect._is_method` (it moved to `resolve.py:203`) [V]. `typeref._attribute_target_position` duplicates `_ast_targets.attr_target_position` [V-agent]. |
| M6 | **The coverage gate rewards duplication.** Each copy gets its own private-helper tests, so a duplicated path looks well tested. | 20 private names from `pyeye.mcp.operations` imported by 12 test files, about 100 calls; `_find_jedi_name_for_handle` alone has 43 references [V-agent]. |

## 4. Inventory

### 4.1 Confident-wrong or silently-partial answers, by severity

| Sev | Finding | Sites | Status |
|---|---|---|---|
| 1 | **The name index never refreshes in a default setup.** A watcher is installed only when the project has explicit config listing extra packages. The handler reacts only to `FileModifiedEvent`, so created, deleted and moved files are ignored. The watcher never clears `scoped_cache` (300 s TTL on `get_project_files`). Result: new or edited classes are invisible to `resolve(bare)` until the analyzer is evicted. | `project_manager.py:89-94` (only path to `get_project` → `_setup_watcher`), `cache.py:75`, `cache.py:119` (`changes[0]` only) | [V] code; probe [V-agent] |
| 1 | **`configure_packages` leaves the name index and plugins stale.** It drops the analyzer, but `project_graph`'s index is keyed by project root and survives. The `file_artifact_cache` Script key leaves out the extra import paths. Plugins are never updated. | `server.py:378-386`, `project_manager.py:414`, `file_artifact_cache.py:88` | [V-agent] reading; effect [I] |
| 1 | **`imported_by` misnames files.** `find_importers` names files with `_get_import_path_for_file`, which disagrees with the name index's `_index_module_name` (no root-package prefix, no extra packages). In a project whose root is a package it returns a *measured empty* list; importers in extra packages are skipped silently. It also walks the whole tree, while `imports` is module-scope only, so the two edges aren't mirror images. | `jedi_analyzer.py:1592,1665` | [V-agent] probe |
| 2 | **TypeRef cache key has no position.** It is keyed on (file, mtime, raw text), so `Foo` at module scope and `Foo` inside `class Outer` share an entry. Results depend on call order. No project in the key, no size limit, and it isn't invalidated when the target file changes. | `typeref.py:158,202,214` | [V] key; order-dependence [V-agent] probe |
| 2 | **#602 cluster.** (a) 31/488 emitted external handles don't resolve. (b) The bare-name index is keyed by last segment, so `functools` becomes `jaraco.functools` with no `ambiguous`. (c) `os.path`: resolve says not found, inspect says found (as `ntpath`). (d) `io → io` self-edges from typeshed `_io.pyi`. | `project_graph.py:127`, `resolve.py:644`, the three inference copies, `edges.resolve_imports` | [V] |
| 2 | **`trace` swallows "wrong kind".** A resolver's `None` (edge not applicable) becomes `[]`, so `trace(Class, ["imports"])` reports `unresolved_imports: {}`, claiming it measured imports. `expand` reports the same request as `unsupported`. | `trace.py:123-124` vs `expand.py:213-232` | [V] code |
| 2 | **trace interior nodes skip handle resolution.** It walks any Jedi Name it has, including handles `expand` refuses. Sentinel interior nodes lose `enclosing_scope` edges (no `parent()`). | `trace.py:291-308`, `edges.py:1249` | [V] code; edge loss [V-agent] |
| 3 | **`resolve_at` emits handles nobody else can use.** If canonicalization fails it returns the raw `full_name` as `found:true`, e.g. `logging`, `pathlib`, which `resolve` and `inspect` reject. It also skips the #454 scope reconciliation. | `resolve.py:475-499` | [V] (`pathlib`); scope [I] |
| 3 | **`trace` partial fill vs `outline`'s reserve-before-expand.** The #358 fix landed in outline only. trace returns 2 of 7 members with only a global `truncated`. | `trace.py:302-304` vs `outline.py:451-453` | [V-agent] probe |
| 3 | **inspect's `superclasses` field vs the edge.** Two separate implementations. The field keeps declaration order plus raw text for unresolved bases; the edge sorts by handle and drops unresolved bases. | `inspect.py:427-525` vs `edges.py:894-1021` | [V-agent] probe |
| 3 | **Echoed handle differs.** inspect and outline echo the input alias; expand and trace echo the canonical name. `io.BlockingIOError`: resolve gives `builtins.…` (class), inspect gives `io.…`, the edge gives a variable. | `inspect.py:1108`, `outline.py:351`, `expand.py:177`, `trace.py:259` | [V-agent] probe |
| 3 | **A `kind: "namespace"` value outside the documented vocabulary leaks out, with `scope: external`** for project PEP 420 packages emitted by `imports`. `inspect` says `module` / `project`. | `resolve.py:196` passes unmapped kinds through | [V-agent] probe |
| 3 | **Plugins live in a separate world.** Their own AST walks (bypassing `file_artifact_cache`), `{name, file, line}` with no handle, scope or `found`, relative paths, first-match without ambiguity. Pydantic detection misses indirect subclasses. `flask.py` uses `ast.Str` ×11, removed in Python 3.14, behind a broad `except` that would hide the failure as empty results. | `plugins/*.py`, `pydantic.py:328` | [V-agent] probe; 3.14 [I] |
| 4 | **Arguments go unvalidated, and errors come through three channels.** `validate_mcp_inputs` raises; `get_analyzer` raises `ProjectNotFoundError`; everything else returns `found:false`. `max_nodes=0`, `max_depth=-1` and unknown `stop_when` keys are accepted. `resolve_at`'s "project-relative" `file` is actually resolved against the current working directory. Plugin tools skip validation, metrics and `project_path`. | `server.py:249,330` | [V-agent] |

### 4.2 Duplicated logic

| Capability | Copies | Identical? |
|---|---|---|
| Handle → definition | `resolve` bare, `resolve` dotted, `_find_jedi_name_for_handle`, edge `goto` | **Differ.** Strategy order, guards, search backend. |
| Synthetic-import inference | `resolve.py:830`, `canonicalization.py:488`, `inspect.py:648` | **Differ.** `name == leaf` ×2 vs `full_name == handle`. None handles a dot-free module. |
| Walk back to the nearest module, then match `full_name` | inspect Case 2, `resolve._kind_for_canonical`, `canonicalization.find_definition_name` | **Differ.** Only inspect keeps shortening after a miss and has the #429 anchor. |
| Leaf search backend | AST name-index (`_search_all_scopes`) vs `jedi.Project.search` (`inspect.py:638`, `project_manager.py:250`) | **Differ.** The latter truncates at 30 files. |
| `goto` disambiguation | typeref (unique `full_name` only), superclasses (prefer class, else first), callees/imports (first with `full_name`), typeref forward refs (`resolve_canonical`) | **Differ.** Quoted and unquoted annotations disagree. |
| Project roots | `scope._project_roots`, `resolve._project_roots`, `canonicalization._namespace_roots`, inline in `find_module_file`, inline in `_scan_package_for_handle` | **Differ.** Each includes a different subset of `additional_paths` / `added_sys_path`. |
| File → module name | `_get_import_path_for_file`, `_index_module_name`, `ImportAnalyzer.get_module_name`, `_file_to_module_path`; reverse lookups `find_module_file`, `_find_init_file` | **Differ.** This is behind the `imported_by` bug. |
| Package predicate | `inspect._is_package_path`, `outline._is_package`, `edges._package_dirs` | **Differ** on `module_path is None`. |
| Superclass resolution | inspect field, `superclasses` edge | **Differ** (order, unresolved bases). |
| Re-exports | `find_reexports` (regex, runs on every `find_symbol`, result thrown away) vs `canonicalization.collect_re_exports` (live) | Wasted work; could disagree [I]. |
| TypeRef building | `jedi_analyzer` lines 1703-1973 (test-only) vs `typeref.py` (live) | Dead copy. |
| Edge kind gates | 7 inline copies in `edges.py`, plus 2 in `expand.py`; two "wrong kind" policies (`None` vs measured `[]`) | Policies differ by edge with no stated rationale. |
| Not-found shape | resolve `_NotFoundResult`, `not_found()`, trace `unresolved_roots` | **Differ.** The linter checks only 3 tools [V `response_linter.py:1600`]. |
| Module-scope walk (#360) | `_iter_module_scope_imports` vs `base_resolution` ×3, `import_analyzer` | **Differ.** Guarded imports are invisible to subclass resolution. |
| Search scope ("main"/"all") | `JediAnalyzer._resolve_scope_to_paths`, `AnalyzerPlugin._resolve_scope_to_paths`, `SmartScopeResolver` | **Differ** (plugins lack "standalone"/"packages"). |
| "Is this in the project?" | `scope.classify_scope` (project + source + extra packages) vs search scope "all" (adds namespace/standalone) | **Differ.** A namespace-repo symbol is likely labelled `external` [I]. |
| Caches | 8 (artifact, name-index, `ScopedCache`, `GranularCache` (never stores), `_typeref_cache`, connection pool, `NamespaceResolver.package_cache`, analyzer LRU); 2 `CacheMetrics` classes | No coordinated invalidation. `GranularCache.invalidate_file` clears *every* project's index. |
| Timing / metrics | `metrics.measure` + `track_mcp_operation` on every tool; `get_performance_report` puts all new primitives under "other" | Two systems. |
| Path normalisation | `path_utils` (only `dedupe_paths` used in production) vs about 55 inline `.resolve()` calls, 4 "resolve + as_posix" helpers, 2 `_is_subpath` | Rule in `10-cross-platform.md` mostly unused. |
| Small identical pairs | `typeref._attribute_target_position` = `_ast_targets.attr_target_position`; `_SCOPE_BOUNDARY_NODES` = `_NESTED_SCOPE_TYPES` | Identical today, so the risk is future drift. |

### 4.3 Dead code still being maintained

- **`jedi_analyzer.py`: about 1,400 of 3,121 lines can't be reached from any MCP tool** [V for the named methods: only `SMART_DEFAULTS` keys and their own logging reference them].
  - `goto_definition`, `get_type_info` and the parso inheritance block (about 360 lines).
  - `find_imports`, `list_packages`, `list_modules`, `analyze_imports`, the type-ref enrichment block.
  - `get_completions`, `get_signature_help`.
  - `populate_dependencies` and `_get_project_for_path`, which have zero references even in tests [V].
- **Support modules with no live production use:**
  - `ImportAnalyzer` (only `resolve_relative_import` is live);
  - `dependency_tracker.py` (never populated);
  - `GranularCache` storage;
  - `connection_pool.py` (builds `jedi.Project`s that are thrown away);
  - `dogfooding_integration.py` (scripts and tests only).

  [V-agent]
- **Settings:**
  - `PYEYE_MAX_FILE_SIZE`, `PYEYE_MAX_WORKERS`, `PYEYE_ANALYSIS_TIMEOUT` and `PYEYE_ENABLE_MEMORY_PROFILING` are parsed but never read.
  - `PYEYE_CACHE_TTL` only affects the empty `GranularCache`; `ScopedCache` hard-codes 300 s (`jedi_analyzer.py:86`) [V].
  - **`PYEYE_CACHE_TTL` is documented** (README "Performance Settings", TROUBLESHOOTING, migration guide), so users are told to tune a setting that changes nothing. `tests/test_documented_env_vars.py` passes because `src/` does *read* it.

  The other four are parsed but unread [V-agent].
- **The dead code and its test keep each other passing.** `test_scope_defaults_conformance` checks that each `SMART_DEFAULTS` key names a real analyzer method, and the dead keys keep pointing at dead methods.

### 4.4 Decisions vs code

| Decision | Applied where | Not applied where | Would its Verify catch it? |
|---|---|---|---|
| #457 AST name-index | `_search_all_scopes` | `inspect.py:638`, `project_manager.py:250` | **No.** A test patches `project.search` and asserts the Case 3 result [V `test_inspect.py:1451-1470`]. |
| #506/#544 definition, not inference | All 3 inference copies, with different guards | `resolve_at`'s raw-handle fallback | No (resolve-only; #544 is still open). |
| #545 one not-found shape | inspect, outline, expand | resolve, resolve_at, trace | No (the linter scope is hard-coded) [V]. |
| #454 stub scope reconciliation | `build_stub` | `resolve_at`, `resolve`, `inspect` | No (stub path only). |
| Relative imports, one helper (#426) | import_analyzer, base_resolution, analyzer | `edges._import_from_target` emits raw `..x` | Partly. |
| #360 one module-scope walk | members, imports edges | `base_resolution` ×3, `import_analyzer` | No. |
| #494 / #488 honesty fields | expand, trace | (outline has no equivalent) | Yes. |
| #599 outline counts == `edge_counts` | every node (sweep) | none | **Yes. This is the model to copy.** |

### 4.5 Comments that claim parity and are false

All [V-agent] from git; the first three [V] by me.

- `resolve.py:837`: "Mirrors the synthetic-import fallback in inspect". False from day one (no guard), and still false (different guard).
- `resolve.py:282-283`: "Contrast `edges._analyzer_roots` … both share `dedupe_paths`". The function was deleted in #453, and its replacement dedupes inline.
- `edges.py:1218`: "See also `inspect._is_method`". It is now `resolve._is_method`.
- `resolve.py:986-987`: "relies on `_get_import_path_for_file`". The body calls `find_module_file`, in the same diff that added the comment.
- `jedi_analyzer.py:586` cites `lookup` as a caller (removed in #505).
- `canonicalization.py:536`: "starts with the same root as". The code requires exact equality.
- `typeref.py:370`: "Mirrors `inspect._attr_target_position`". That's an alias; there are two copies.
- `jedi_analyzer.py:239, 2015`: "LIVE … behind resolve" / "surfaced as `re_exports`". Both are test-only or replaced.
- `inspect.py:431` points at "line ~3278" of jedi_analyzer.

## 5. Why it was invisible

1. **No cross-tool invariants are tested, except count==expand for some edges and #599's sweep.**
   - Missing:
     - every emitted handle round-trips;
     - resolve and inspect agree on found and on the handle;
     - `resolve_at` → `resolve` round-trips;
     - scope is the same across tools;
     - trace expands a node only when expand would;
     - every `edge_counts` value equals `len(expand)`.
   - Only one test feeds an emitted handle back in (`test_trace_subclasses_depth_2_round_trips_the_sentinel`).
2. **Verify lines sample a single case; they never sweep.** The decision-log has no "applies to these sites" field, and nothing re-runs Verify lines.
3. **Private-helper tests pin each copy separately.**
   - inspect's inference copy has dedicated tests.
   - resolve's copy has none.
   - canonicalization's copy is patched to `None`.
   - So a guard change in one copy is invisible to tests of the others.
4. **No duplicate-code tooling at all.** No pylint `duplicate-code`, jscpd or import-linter; only a manual PR-template checkbox. architecture-review excludes duplication (#495).
5. **pyeye-verify probes are hand-picked single handles.** None feeds emitted handles back in.
6. **Layering is unenforced and drawn so that `resolve` sits at the bottom of the operations modules.** The shared resolver lives in `inspect`, so it can't be reused "downward".

## 6. Recommended plan

The order is deliberate: **visibility → consolidation → deletion**. Each step lands one guard and turns allow-list entries green.

### Phase 0: make drift visible (tests only, no behaviour change)

1. **`test_emitted_handles_round_trip`.** For every fixture module (and `src/pyeye`), every edge in `EDGE_RESOLVERS`, and every stub: `inspect(h).found`, `resolve(h).found`, and the same canonical handle from both. Allow-list today's 31 external misses against #602. `/tmp/rt602.py` is a working prototype.
2. **`test_tools_agree_on_handle`.** A corpus (aliases, nested attributes, stdlib, namespace, ghosts) × {bare analyzer, `get_analyzer`} × {resolve, resolve_at at the definition position, inspect, expand source, trace root}. They must agree on found, handle, kind and scope.
3. **`test_count_equals_expand_all_edges`.** Generalise the #599 sweep to every edge in `edge_counts`.
4. **`test_trace_expand_agree`.** A trace interior node is expanded only if `expand(h, edge)` is found and supported; wrong-kind shows up in `unsupported_edges`.
5. **Single-site fitness tests (AST scans of `src/`):**
   - `jedi.Script(code=…)` synthetic imports appear in one function only;
   - `project.search(` appears nowhere (enforces #457);
   - `tree.body` import walks appear only in `_iter_module_scope_imports` (#360);
   - one roots helper.
6. **Extend the response linter's Check N** to `resolve` and `resolve_at`, or record the exception as a decision.
7. **Process changes:**
   - add an `Applies-to:` line and a sweeping Verify to decision-log entries;
   - add a pyeye-verify round-trip probe;
   - a crude duplicate-code check (pylint `duplicate-code` on `mcp/operations` + `canonicalization`) as a first step toward #495.

### Phase 1: correctness fixes that don't need the redesign

- Install the file watcher for every analyzer, handle create, delete and move events, and pass every changed path on, not just `changes[0]`. On change, invalidate the name index, `scoped_cache` and the artifact cache together, scoped to that project.
- Make `configure_packages` rebuild the name index and plugins.
- Add the annotation's position (or enclosing scope) and the project to the TypeRef cache key, and give the cache a size limit.
- `trace`: propagate wrong-kind as unsupported, and apply outline's reserve-before-expand.
- `imported_by`: name files with the same mapper as the name index.

### Phase 2: consolidate (the design work)

1. **One handle resolver** in a lower layer (not in `inspect`): `resolve_handle(str) -> Resolved | Ambiguous | NotFound`. It owns:
   - the strategy order: exact module first (project, then namespace, then stdlib/site-packages through a Jedi module import), then definition placement, then guarded inference;
   - one acceptance guard;
   - one module/leaf split;
   - one roots policy;
   - the reported canonical handle;
   - scope, including #454;
   - not-found/ambiguous wording.

   `resolve`, `resolve_at`, `inspect`, `outline`, `expand`, trace roots *and interior nodes*, and `typeref` forward refs all call it. Edges check what they emit against it. **This closes #602.**
2. **One `goto`-disambiguation policy** shared by edges, superclasses and typeref. Delete inspect's separate superclass resolver; the field reads from the edge.
3. **One file ↔ module mapper pair** and **one package predicate**.
4. **One edge-kind policy table** (applicable kinds, and wrong-kind → unsupported), read by the resolvers, `expand` and `trace`.
5. **Plugins**: return handles via the resolver, the shared not-found shape and absolute paths; replace `ast.Str`.

### Phase 3: delete

- Remove the dead `jedi_analyzer` methods, `ImportAnalyzer` (keep `resolve_relative_import`), `dependency_tracker`, the `GranularCache` storage and `connection_pool`.
- Remove the dead `SMART_DEFAULTS` keys and the unread settings.
- Remove `find_symbol`'s wasted re-export scan (`include_import_paths=False`).
- Fix the 9 stale comments in §4.5 when their code is consolidated.

Phase 3 also removes about 2,000 lines that currently need coverage, so the 85% gate stops paying for dead code.

## 7. Caveats

- The probe counts (31/488) come from this repo's own source under `get_analyzer`. The jaraco namespace scenario will add the bare-name collision and #454-class cases, which this repo doesn't have.
- [V-agent] items come from investigators' probes in `/tmp` that I did not re-run. They should each be reproduced as a failing test before their fix (Phase 0 does this).
- Severity ranking is a judgement: confident-wrong answers in core tools first, silent partials second, consistency issues third.
- This is a point-in-time audit of `7e18ab4`; line numbers will drift.
