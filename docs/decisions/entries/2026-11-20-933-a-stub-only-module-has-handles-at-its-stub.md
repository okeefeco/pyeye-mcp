---
date: "2026-11-20"
title: "A stub-only module has handles at its stub; a stub's imports are declarations, its bodies don't exist, and stub declarations carry `stub: true` (#933)"
issues: [933, 885, 619, 602, 625, 614, 1004]
anchors: ["pyeye.project_layout.module_name_for_file", "pyeye.project_layout.file_for_module", "pyeye.project_layout.is_module_file", "pyeye.project_layout.declaration_kind", "pyeye.project_layout.mark_stub", "pyeye.mcp.operations.edges.stub_declaration_file", "tests/test_stub_only_modules.py"]
status: "active"
amends: ["2026-11-18-885-a-pyi-stub-path-resolves-through-its-py-source.md", "2026-11-15-619-imports-and-imported-by-intentionally-differ-in-scope.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A stub-only module has handles at its stub; a stub's imports are declarations, its bodies don't exist, and stub declarations carry `stub: true` (#933)

**Friction:**

- A project module that existed only as a `.pyi` (`pkg/stubonly.pyi`, no `stubonly.py`) was half-visible. Jedi follows stubs, so the edges emitted its handles (`expand(app, "imports")` gave `pkg.stubonly.S`), but `resolve`, `inspect`, `outline` and `submodules` read `.py` files only and rejected them: a round-trip break (#602), pinned in #614's sweep (#979).
- #885 kept that consistent on purpose: the file↔module mapper stayed `.py`-only, and a stub-only file stayed `unresolved` in every file form. It left whole-surface handles to this issue, as a contract change.
- `callees` on a stub declaration (typeshed's `math.sqrt`) answered a measured `stubs: []` with `unresolved_call_sites: 0`: "calls nothing", about a body that doesn't exist.

**Decision:** the maintainer's ruling, option A (via coordinator-3, 2026-11-18).

- **One mapper, now stub-aware.** `module_name_for_file` and `file_for_module` (#625) accept a stub-only `<name>.pyi` (`project_layout.is_module_file`). `file_for_module` tries `__init__.py`, then `<name>.py`, then `<name>.pyi`, so a `.py` beside a stub always wins (#885 unchanged). Every consumer inherits it: dotted and file-form `resolve`, `resolve_at`, `inspect`, `outline`, `members`, `superclasses`. The handle's location is the `.pyi`.
- **Scanners opt in by what they answer.** `analyzer.get_module_files` (and `project_layout.iter_module_files` for a root) lists `.py` files plus stub-only `.pyi`.
  - Declaration scans use it: `subclasses` (so it agrees with `superclasses`, which reads a stub class's bases) and the bare-name and member indexes.
  - `submodules` uses the same predicate in its directory scan.
  - `imported_by` and `re_exports` keep reading `.py` only (next bullet).
- **A stub's imports are declarations, not runtime imports** (ruling item 3). `imported_by` doesn't count them, and the shared `static_imports` ceiling text says so. `imports` on a stub module still lists the stub's own statements. **This amends #619:** its forward property ("if `imports(M)` shows project module `B`, `M ∈ imported_by(B)`") holds for source modules, and exempts a stub-only `M` by design. The sweep test pins the exemption, and fails without it.
- **A stub has no bodies** (ruling item 5). A body edge (`edges.BODY_EDGES`: `callees`) on a declaration whose file is a `.pyi` is unsupported, with reason `stub_declaration` (`edges.stub_declaration_file`, checked in `expand_resolved`, so `trace` reports it too). That covers project stubs, typeshed and stub-only installed packages. Its declaration edges still apply.
- **Vendored stubs** (ruling item 4). Nothing under a `foo-stubs/` directory gets a name or is listed (`project_layout.in_stubs_package`; its name isn't an identifier anyway).
- **Watching.** The watcher and the catch-up sweep take `.py` and `.pyi` (`cache.WATCHED_SUFFIXES`), so a stub edit invalidates like a source edit.
- **One walk per listing.** Every listing of both suffixes (the sweep, `get_module_files`, `iter_module_files`) is ONE walk: `async_utils.filtered_rglob` takes a tuple of patterns. Calling it once per suffix walked each root twice, which made the pydantic plugin tests ~25% slower (several 6× slower) on a machine whose projects had hundreds of auto-discovered sibling roots (#1035).
- **Amends #885:** "the mapper stays `.py`-only" and "a stub-only file stays `unresolved`" no longer hold for a project module. A stub the mapper can't name keeps #885's honest miss and its reworded detail: typeshed, a `-stubs` package, or a package's stub-only `__init__.pyi`.
- **The stub flag** (ruling item 2, the maintainer's final placement via designer, 2026-11-20): `stub: true` on every node whose definition site is a `.pyi`, ABSENT for source.
  - **Where:** every node that carries `scope`: `resolve` and each ambiguous candidate, `resolve_at`, `inspect`, `outline` nodes, `expand` and `trace` stubs, plugin records, and a model lookup's ambiguous candidates (`_lookup_model`).
  - **One place:** `project_layout.mark_stub(node, file)` sets or clears the key from the node's definition file (`declaration_kind`). Edge stubs carry no file, so `build_stub` reads the Jedi name's or sentinel's `module_path`.
  - **Why a flag satisfies absence-vs-zero:** that invariant governs values pyeye didn't measure. Whether a definition site is a `.pyi` is always measured, so absence is a documented, measured "no". That is the same precedent as `resolve`'s `truncated: true`, which is also present only when true.
  - **Enforced:** the conformance linter's Check D (D.1 the key is only ever `true`; D.2 it is present exactly when the node's `location.file` is a `.pyi`).
  - **Superseded:** this replaces the earlier approval (2026-11-18, via coordinator-3) of an always-present `declared_in: "source"|"stub"` on every node. That approval was conditional on response size. Measured before building, it grew the median response with nodes by 8.42% and `expand` by 12.8%, against the 5% / 10% condition, so it never shipped and was never an entry of its own. The final form's cost is recorded in the PR (`scripts/measure_response_size.py --mode strip`).
- **Not decided here:**
  - **A stub-only package** (`__init__.pyi`, no `__init__.py`), filed as #1004. That is the known remaining round-trip break of this class, and it predates #933: `pkg.X` resolves through Jedi, but `pkg` doesn't. The fix changes PEP 420 namespace classification, so it needs its own design look.

**Anchor:** `pyeye.project_layout.module_name_for_file` / `file_for_module` / `is_module_file` / `is_stub_only_module` / `iter_module_files` / `in_stubs_package` / `declaration_kind`; `pyeye.analyzers.jedi_analyzer.JediAnalyzer.get_module_files`; `pyeye.mcp.operations.edges.BODY_EDGES` / `STATUS_STUB_DECLARATION` / `stub_declaration_file`; `pyeye.mcp.operations.expand.expand_resolved`; `pyeye.cache.WATCHED_SUFFIXES`; #933, #885, #619, #1004.

**Applies-to:**

- the flag: `pyeye.project_layout.mark_stub`, `pyeye.mcp.operations.stubs.build_stub`, `pyeye.mcp.operations.inspect.inspect`, `pyeye.mcp.operations.resolve.resolve`, `pyeye.mcp.operations.resolve.resolve_at`, `pyeye.plugins.handles._enrich_record`, `pyeye.mcp.server._lookup_model`;
- the mapper and its predicates: `pyeye.project_layout.module_name_for_file`, `pyeye.project_layout.file_for_module`, `pyeye.project_layout._module_file_under`, `pyeye.project_layout.is_module_file`, `pyeye.project_layout.is_stub_only_module`, `pyeye.project_layout.iter_module_files`, `pyeye.project_layout.in_stubs_package`, `pyeye.project_layout.declaration_kind`;
- the scans: `pyeye.analyzers.jedi_analyzer.JediAnalyzer.get_module_files`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer.find_subclasses`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._project_index`, `pyeye.mcp.operations.edges._enumerate_submodule_paths`;
- the refusal: `pyeye.mcp.operations.edges.stub_declaration_file`, `pyeye.mcp.operations.expand.expand_resolved`;
- the file forms: `pyeye.mcp.operations.resolve._resolve_file_only`, `pyeye.mcp.operations.resolve._stub_only_miss`;
- watching and walking: `pyeye.cache.CodebaseWatcher._record`, `pyeye.project_manager.ProjectManager._catch_up`, `pyeye.async_utils.filtered_rglob`.

**Verify:** gold. `uv run pytest tests/test_stub_only_modules.py tests/conformance/test_linter_adversarial_stub_flag.py tests/test_resolve_pyi_stubs.py tests/test_not_found_path_hint.py tests/test_imports_imported_by.py tests/test_cross_tool_invariants.py tests/test_watcher_invalidation.py tests/test_watcher_catchup_sweep.py` passes. It checks:

- a stub-only module resolves (dotted, bare, file, `file:line`, `resolve_at`), inspects and outlines at its `.pyi`, and is a submodule of its package;
- a stub class is a subclass of its project base, and that base its superclass;
- a `.py` beside a stub still wins;
- a stub importer isn't in `imported_by`, the ceiling text says so, and the stub's own `imports` still list its targets;
- #619's forward property exempts stub importers and fails without the exemption;
- nothing in `foo-stubs/` resolves or is listed;
- `callees` on project and typeshed stub declarations is `stub_declaration`, in `expand` and in `trace`, while source callees still measure;
- the #614 sweep seeds stub-only modules and round-trips their handles with no `KNOWN_GAPS` entries;
- a `.pyi` edit reaches the watcher and the catch-up sweep, and the sweep test fails when only `.py` is swept;
- `stub: true` is on project and typeshed stub declarations in `resolve` (and per candidate), `resolve_at`, `inspect`, `outline`, `expand` (including sentinel-built `submodules` and `subclasses` stubs) and `trace`, absent on source and on a stub beside its source, and the linter's D.1 and D.2 reject a wrong value, a missing flag and a spurious one.
