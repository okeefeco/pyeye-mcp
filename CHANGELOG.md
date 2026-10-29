# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### BREAKING CHANGES

#### MCP tool surface redesigned around progressive-disclosure primitives

The Jedi-shaped navigation tools have been replaced by six primitives that
operate on **canonical handles** (re-exported paths collapse to the definition
site), return small structural responses by default (no source content), and
honour an absence-vs-zero invariant. See `docs/api-redesign.md` for the full
rationale.

**New interface:** `resolve` / `resolve_at` / `inspect` / `outline` / `expand`
/ `trace`.

##### Removed tools

The clearly-replaced legacy navigation tools were **removed** from the MCP
surface (#376). Migrate existing agent/integration code as follows:

| Removed tool | Replacement | Notes |
|--------------|-------------|-------|
| `find_symbol(name)` | `resolve(name)` | Canonical handle; ambiguity surfaced explicitly |
| `goto_definition(file, line, col)` | `resolve_at(file, line, col)` | Returns a canonical handle directly |
| `get_type_info(file, line, col)` | `inspect(handle)` | Richer Node; no source content |
| `get_module_info(module)` | `inspect(module_handle)` | Same Node contract; member count via `edge_counts.members` |
| `find_imports(module)` | `expand(handle, edge="imported_by")` | Stub-based, canonical handles |
| `find_subclasses(class)` | `expand(handle, edge="subclasses")` (direct) / `trace(follow=["subclasses"], max_depth=k)` (closure) | Direct subclasses are one hop (#422); full transitive closure via `trace`. Not in `edge_counts` (cheap count gated on #333/#397). |
| `list_packages` / `list_modules` | `outline` | One structural lister |
| `list_project_structure` | `outline` | One structural lister |

Note: several same-named `JediAnalyzer` methods are internal implementation and
remain because they back the new operations — `analyzer.find_symbol` (behind
`resolve`), `analyzer.find_subclasses` (behind the `subclasses` edge),
`analyzer.find_importers` (behind `imported_by`), and `analyzer.find_reexports`
(behind `inspect(...).re_exports`). For the tools in this table only the MCP
**tool wrappers** were removed. Others (`analyzer.list_modules`,
`analyzer.list_packages`, `analyzer.find_imports`) survive without a production
caller and are not load-bearing for anything. The three tools
removed under #505 below are the exception: their backing methods
(`find_references`, `get_call_hierarchy`, `analyze_dependencies`, and the
transitively-orphaned `get_module_info`) were deleted outright, so they cannot be
re-exposed by a future wrapper.

##### Also removed: the last three legacy tools (#505)

`find_references`, `get_call_hierarchy`, and `analyze_dependencies` were
previously slated to survive this release as deprecated. They are **removed**
instead. An audit for the 2.0 tag found they do not merely under-report — they
answer *confidently and wrongly*, which is the failure mode this release exists
to eliminate:

- **`get_call_hierarchy`** — `callees` could never be populated at all. It read
  module-level names with Jedi's defaults (`definitions=True, references=False`)
  and then skipped every result via `if name.is_definition(): continue`, so the
  list was structurally always empty. Its callers half resolved bare names by
  taking the *first* `_search_all_scopes` match with no ambiguity signal, so it
  could report a different symbol's callers as your symbol's.
- **`analyze_dependencies`** — derived `project_modules` from `rel_path.parts[0]`,
  which on a `src/` layout is `"src"`, so every first-party module was classified
  as third-party. That emptied the input to the cycle scan, making
  `circular_dependencies: []` wrong by construction on exactly the layout it was
  most often pointed at. Its stdlib set was also a hardcoded ~40-name literal
  rather than `sys.stdlib_module_names`.
- **`find_references`** — advertised "Find ALL usages" while returning a flat list
  with no absence-vs-zero signal, so an empty result was indistinguishable from a
  search that never reached. Its standalone-file branch matched candidates by
  string comparison where its own comment claimed a `goto` check.

| Removed tool | Replacement | Notes |
|--------------|-------------|-------|
| `find_references` | **None** — deferred to #333 | Reverse references are not answerable today. Delegate to a language server: `resolve` gives the definition-site position an LSP `findReferences` needs. `expand` reports the edge as unsupported rather than guessing. |
| `get_call_hierarchy` | `expand(handle, edge="callees")` (forward only) | Forward calls are covered, with `unresolved_call_sites` marking un-inferable sites. Callers remain deferred to #333. |
| `analyze_dependencies` | `expand(handle, "imports")`, `expand(handle, "imported_by")`, `trace(follow=["imports"])` | Fan-in/fan-out and the import closure are covered. For cycles, scan the `trace` result's `edges` for one whose `to` is the start module — documented in the `python-explore` skill. |

The superseded `lookup` entry point (`pyeye.mcp.lookup` /
`pyeye.mcp.lookup_builders`) was removed in the same change. It had not been
registered as an MCP tool since the primitives landed, and was the only remaining
non-MCP consumer of the removed analyzer methods.

`pyeye.agents` (the test-coverage agent) was removed too. It shipped in the wheel
while planning its work entirely in terms of tools deleted across both v2.0
phases — emitting instructions naming `mcp__pyeye__find_references`,
`mcp__pyeye__get_call_hierarchy`, `mcp__pyeye__analyze_dependencies`,
`mcp__pyeye__find_symbol`, `mcp__pyeye__get_module_info` and more — so any
consumer following one of its plans would hit tool-not-found. It was orphaned
(no importer outside its own test) and, like the retired
`cross-platform-validator` agent (#483), could not be restored by renaming onto
the primitives: its planning relied on fuzzy symbol search, reverse references,
and call hierarchy, which the redesign dropped or deferred to #333.

**Required action:** if you call any of these three tools, migrate per the table
above. If you were using `find_references` or `get_call_hierarchy` for caller
data, route that question to a language server instead — pyeye will not answer it
until #333 lands, and will say so rather than guess.

`configure_packages` and the framework plugin tools (Django, Pydantic, Flask)
are orthogonal to the navigation redesign and are unchanged.

#### Unresolvable handles return an explicit not-found result (#545)

`inspect`, `outline` and `expand` no longer invent an answer when a handle does
not resolve. Previously `inspect` returned a placeholder node (`kind:
"variable"`, `scope: "external"`, empty `file`) that looked like a real
variable, `outline` returned the same placeholder as a one-node tree with
`children: []`, and `expand` returned `stubs: []` — which its own contract
defines as "measured, none found" — plus `unresolved_call_sites: 0` for
`callees`. All three now return:

```json
{"found": false, "handle": "<input>", "reason": "unresolved",
 "detail": "Handle '<input>' did not resolve to a symbol. Call resolve('<leaf>') to find its canonical handle."}
```

`expand` also echoes `edge`. A not-found result carries no `kind`, `location`,
`node`, `children` or `stubs`. `reason` uses the same value `resolve` already
returns.

Every successful response from these three tools now includes `found: true`
(on the root of an `outline` tree only), so callers check one field instead of
guessing from which keys are present. `expand` now resolves the handle before
checking the edge, so a nonexistent handle paired with an unsupported edge such
as `callers` reports not-found rather than "unsupported". `trace` is unchanged:
it already lists unresolved start handles in `unresolved_roots`.

**Required action:** check `found` before reading `inspect` / `outline` /
`expand` results. Code that treated `kind == "variable"` with an empty
`location.file`, or an empty `stubs` list, as "symbol not found" must switch to
`found is False`. An empty `stubs` list with `found: true` now always means the
symbol exists and has no neighbours on that edge.

#### Python 3.11 or newer required (#528)

Python 3.10 support is dropped: `requires-python` is now `>=3.11`. Python 3.10
reached end of life on 2026-10-01 (PEP 619), and some security fixes in pyeye's
dependencies (filelock ≥4.2.1) only ship for 3.11+.

**Who needs to act:**

- **Claude Code plugin users:** nothing to do. The plugin builds its own
  environment with `uv`, which picks or downloads a suitable interpreter.
- **`pip` / `pipx` installs:** install into a Python 3.11+ interpreter, for
  example `pipx install --python python3.12 pyeye-mcp`.

This only affects the interpreter pyeye *runs on*. pyeye still analyzes code
written for older Python versions.

### Added

- Python 3.13 support (#529): CI tests it (Linux, Windows and macOS on PRs; all three on main) and the classifiers list it. The CI pre-commit job now audits dependencies on 3.13, the newest supported version. `.pre-commit-config.yaml` now builds hook environments with `python3` instead of a pinned `python3.12`, which the 3.13 runner didn't have (the remaining remote hooks move to `uv run` in #547). `path_utils.dedupe_paths` now rejects paths containing a NUL byte explicitly; on Windows with 3.13, `Path.resolve()` no longer raises for them, so such paths had slipped into root lists.
- Progressive-disclosure operations over canonical handles: `resolve`,
  `resolve_at`, `inspect`, `outline`, `expand`, and `trace`. Supported `expand`
  / `trace` edges: `members`, `callees`, `imports`, `imported_by`,
  `subclasses`, `superclasses`, `enclosing_scope`, and `submodules`.
- `pyeye://about` MCP resource and in-band issue-reporting pointers (server
  `instructions`, `report_issues` keys on unsupported `expand`/`trace`
  payloads).
- `trace` honesty fields so an empty/clean-looking subgraph is never misread as a
  real zero (#488): `unresolved_roots` (always present; `[]` when every start
  handle resolved, the failed handles otherwise) and `unresolved_call_sites` (a
  `{handle: count}` map, present only when `callees` is traced) surfacing per-node
  calls that didn't resolve — restoring across hops the count `expand(callees)`
  already reports. Conformance-guarded (linter rules T.6/T.7).
- `unresolved_imports` honesty field on the `imports` edge (#494): a
  statically-present `from X import Y` that forward-`goto` cannot resolve is now
  surfaced (by its intended dotted target) instead of being silently dropped —
  `expand(handle, "imports")` carries a list (`[]` when all resolved) and
  `trace(follow=["imports"])` a `{handle: [target, …]}` map (present only when
  `imports` is traced). Closes a silent false-negative in dependency-graph
  queries. Conformance-guarded (linter rules E.5/T.8).

### Removed

- `worktree-manager` agent and the `claude/development` "learning hub" workflow. Worktrees now use native tooling (the `EnterWorktree` tool / superpowers `using-git-worktrees` skill) under `.claude/worktrees`; removal safety remains via `scripts/worktree_safety.py` and the rules in `01-core-rules.md`. Also removed the now-obsolete `docs/CLAUDE_WORKTREE_WORKFLOW.md` and `.claude/startup-context.md`.
- `cross-platform-validator` agent (`.claude/agents/cross-platform-validator.md` + `cross-platform-issues.yaml`) and its `scripts/test_cross_platform_agent.py` harness (#483). It was built on the Jedi-shaped tools removed in this release and re-implemented, semantically, a textual pattern check that `scripts/check_cross_platform_paths.py` already does statically. Cross-platform path validation now uses that script plus the rules in `.claude/instructions/10-cross-platform.md`.
- Unused `diskcache` runtime dependency (#289). It was declared in `pyproject.toml` but never imported anywhere in the codebase — caching is entirely in-memory (`cache.py` uses `watchdog` + `DependencyTracker`; `file_artifact_cache.py` is an `OrderedDict` LRU) and there is no `pickle` usage in `src/`. Removing the dependency resolves CVE-2025-69872 (diskcache pickle deserialization, **no upstream fix exists**) outright rather than waiting on upstream, and drops the corresponding `--ignore-vuln` from the `pip-audit` pre-commit hook. The `DOCUMENTATION.md` architecture diagram, which showed the result cache as "DiskCache", now reads "In-Memory".
- The v1 API reference pages `docs/api/core-navigation.md`, `docs/api/module-analysis.md` and `docs/api/quick-reference.md` (#509). Of the 15 tools they documented, only `configure_packages` still exists. The core primitives are documented in the README's Core Tools section and the `python-explore` skill instead, so there is one source rather than a hand-kept copy that drifts. `docs/api/README.md` now indexes the framework plugin docs and has a corrected `configure_packages` reference. The old page listed a nonexistent `auto_discovered` result and omitted `standalone_dirs`.
- `safety` dev dependency (#522). Every release pins `filelock<4`, which blocks the filelock security fix, and nothing ran it: CI had already dropped its safety step and pre-commit scans dependencies with `pip-audit`. Removing it also drops `nltk`, which was the source of 22 open Dependabot alerts.

### Changed

- Shipped docs no longer teach removed tools (#509). `DOCUMENTATION.md`'s Tools Reference now points to the README and the `python-explore` skill instead of documenting 13 removed tools. The migration guide, troubleshooting guide, testing conventions/performance guides, and the metrics docs' sample output use the primitives. `docs/api-redesign.md` no longer says `find_references` / `get_call_hierarchy` / `analyze_dependencies` are still present. A new conformance test (`TestNoShippedProseTeachesRemovedTools`) fails on any mention of a fully removed tool in shipped `.md`/`.json` outside a reasoned allowlist, and on any API heading for a name that survives only as an internal method.
- The server runs on the MCP Python SDK 2.x (#538): `FastMCP` → `MCPServer` (`mcp.server.mcpserver`), requirement `mcp[cli]>=2.3.0,<3`. `instructions` stays a keyword argument (mcp 2's second positional is `title`) and the server now passes `version=`, so `serverInfo.version` reports the pyeye version. Verified at the wire level over stdio JSON-RPC against the mcp 1.30 server: instructions, all 22 tool names/descriptions/input schemas (including dynamically registered plugin tools), tool results and `structuredContent`, error results (`isError` with the same messages) and the `pyeye://about` resource are identical; the only difference is that mcp 2 no longer advertises an empty `experimental` capability. Dependency changes come from mcp itself: `httpx` → `httpx2`, and `opentelemetry-api` is required again.
- Every Python pre-commit hook now runs from the uv environment with `uv run --frozen` (#547), finishing #413. detect-secrets, bandit, pydocstyle, commitizen and the `pre-commit-hooks` file checks were remote hook repos with their own pinned versions, which Dependabot never updated and which had drifted from `uv.lock`: the commit hook ran bandit 1.8.6 while CI ran 1.9.4, and commitizen 3.13.0 while the lock had 4.19.3. `pre-commit-hooks` 4.5.0 joins the dev group. Hook behavior is unchanged (verified hook-by-hook against deliberately bad files), and neither upgraded tool flags anything new. Only markdownlint (Node) stays remote; contract tests enforce this.
- Python 3.11 is now the minimum (#528). ruff, black and mypy target 3.11; the CI and release workflows test 3.11 and 3.12 (Codecov uploads moved from the 3.10 job to 3.11); the `filelock` version split and the `tomli` fallback are gone; `asyncio.TimeoutError` is written as the built-in `TimeoutError`, which it aliases from 3.11.
- Bumped the pinned dev linters: ruff 0.15.21 → 0.16.10, mypy 2.2.0 → 2.4.0 (#525). Neither surfaces new findings. Redoes Dependabot #521, which updated the pins without regenerating `uv.lock`.
- Migrated the Claude instructions off the removed worktree agent and the persistent `claude/development` branch (`04-agent-triggers.md`, `02-session-startup.md`, `06-workflow-commits.md`, `08-project-specific.md`, `11-pr-requirements.md`, `00-documentation-system.md`). Per-worktree environment setup now uses `uv sync` (`dev` is a default dependency group as of #414).

### Fixed

- `inspect`, `expand`, `outline` and `trace` now describe external (stdlib / site-packages) symbols reached through a re-export, such as `asyncio.Queue`, `json.JSONDecoder`, or `pathlib.Path` on Python 3.13 (where it moved to `pathlib._local`) (#529). Previously `resolve_canonical` could not follow external modules, so the alias retry (#431) found nothing and these returned a placeholder node (`kind: "variable"`, empty location) instead of the class. `resolve` now takes kind and location from the external resolver when the canonical definition is outside the project. An external re-export under a *different* name (`from x import A as B`) still stays unresolved rather than risk describing the wrong object.
- The release workflow's `validate` job now runs `pytest`, `mypy` and `bandit` through `uv run` (#540). Since #414 the job installs dependencies with `uv sync` into `.venv`, so the bare commands were no longer on `PATH` and the next tag push would have failed. A contract test (`tests/test_ci_uv_run_tools.py`) fails if any workflow step calls a venv tool without `uv run`.
- `pip install pyeye-mcp` no longer installs a server that can't start (#537). The `mcp` requirement had no upper bound, so installs without the lockfile resolved mcp 2.x, which removed `mcp.server.fastmcp` (the server failed with `ModuleNotFoundError`). The requirement now has an upper bound on the major the server is built for (`mcp[cli]>=2.3.0,<3` after the `MCPServer` migration, #538). Plugin installs were unaffected because they use `uv.lock`. Also removed the unused standalone `fastmcp` dependency (pyeye uses the FastMCP bundled in `mcp`), which drops 35 transitive packages including authlib, opentelemetry-api and dnspython. A contract test (`tests/test_mcp_dependency_contract.py`) ties the declared `mcp` range to the API the server imports.
- Resolved open Dependabot security alerts (#522) by upgrading locked versions within current majors: pyjwt 2.15.1, anyio ≥4.14.2, urllib3 2.8.0, fastmcp/fastmcp-slim 3.4.11, mcp 1.30.0, opentelemetry-api 1.45.1, setuptools 84.2.1, pip 26.2.2, msgpack 1.2.4. `filelock` now requires ≥4.2.1, which needs Python 3.11 (see the Python 3.11 requirement under BREAKING CHANGES, #528). The CI pre-commit job now runs on Python 3.12 so `pip-audit` audits the newest supported environment. Bumped `black` to 26.10.1 (GHSA-cg8m-r9f2-5wm2).
- CI no longer posts a false "Documentation-only change detected" comment on PRs that also change code (#500). The feedback now lives in `ci.yml` and reuses the same `changes` (docs-vs-code) classifier as the test gate, so the comment can never contradict what CI actually ran; the divergent `docs.yml` workflow was removed. Also stripped fabricated time/percentage "CI savings" figures from the workflow comments, keeping the accurate platform-multiplier table.

## [1.0.0] - 2025-10-04

### BREAKING CHANGES

#### Complete rebrand from "python-code-intelligence-mcp" to "PyEye"

This is a breaking change that requires migration steps:

#### Required Actions

1. Rename configuration files:
   - `.pycodemcp.json` → `.pyeye.json`
   - `.pycodemcp.yaml` → `.pyeye.yaml`
   - `.pycodemcp.override.json` → `.pyeye.override.json`

2. Rename configuration directories:
   - `~/.pycodemcp/` → `~/.pyeye/`
   - `~/.config/pycodemcp/` → `~/.config/pyeye/`

3. Update environment variables:
   - `PYCODEMCP_*` → `PYEYE_*`
   - Example: `PYCODEMCP_CACHE_TTL` → `PYEYE_CACHE_TTL`

4. Update pyproject.toml sections:
   - `[tool.pycodemcp]` → `[tool.pyeye]`

5. Update MCP configuration:
   - Module import: `from pyeye.mcp.server import mcp`
   - Package name: `pyeye-mcp`

#### What Changed

- Package renamed: `python-code-intelligence-mcp` → `pyeye-mcp`
- Module renamed: `pycodemcp` → `pyeye`
- Server moved: `pyeye.server` → `pyeye.mcp.server`
- All documentation updated to reflect new branding
- All configuration file formats updated

### Fixed

- Renamed `.pycodemcp.json.example` to `.pyeye.json.example` (missed in initial rebrand)
- Fixed Sphinx documentation paths for `pyeye.mcp.server` module structure
- Fixed test mocking conflicts with new module structure
- Restored `_version.pyi` type stub file for proper type checking
- Updated release workflow package names from `python_code_intelligence_mcp` to `pyeye_mcp`

## [0.3.0] - 2025-08-27

### Added

- Git-based versioning with setuptools_scm - automatic version management from git tags
- Persistent branch support in worktree-manager agent for claude/development workflow

### Changed

- Switched from manual version management to setuptools_scm
- Simplified release process - no more version files to update
- Version now automatically derived from git tags and commits

### Fixed

- CI installation of setuptools_scm before generating version file
- Proper version imports for CI and type checking environments
- Type annotations for version tuple

### Removed

- Obsolete release automation agent (replaced by simplified git tag process)
- Manual version sync scripts (no longer needed with setuptools_scm)
- Version management scripts: check_version_sync.py, prepare_release.py
- Outdated release documentation: RELEASING.md, RELEASE_CHECKLIST.md
- Release automation tests (no longer applicable)

## [0.1.0] - 2025-08-24

### Added

- Initial release of PyEye Server
- Core navigation tools (find_symbol, goto_definition, find_references)
- Multi-project support with LRU caching
- Namespace package resolution across repositories
- File watching with automatic cache updates
- Configuration system (files, env vars, auto-discovery)
- Plugin architecture for framework-specific intelligence
- Django plugin with model/view/URL analysis
- Pydantic plugin with model schema extraction
- Flask plugin with route/blueprint/template analysis
- Module and package analysis tools
- Circular dependency detection
- Connection pooling for optimized multi-project workflows
- Comprehensive test suite
- Pre-commit hooks for code quality
- Documentation and examples

### Fixed

- Author and copyright information corrected

## [0.2.0] - 2025-08-25

### Feat

- enable connection pooling by default for better performance
- add MCP monitoring hooks system for automatic usage tracking
- add persistent branch handling for claude/development workflow
- add PR merging capabilities and composite agent workflows
- add pr-workflow agent for complete PR lifecycle management
- add worktree-manager agent for safe git worktree operations
- add smart-commit agent for intelligent git commit workflow
- add first true Claude Code agent for cross-platform validation
- **agents**: enhance test coverage agent with quality guidelines
- **metrics**: unified metrics system with improved tests
- **metrics**: implement unified metrics collection system
- implement test coverage enhancement agent for systematic improvement
- Complete documentation deployment system setup
- implement release automation agent for end-to-end release management
- **ci**: add version validation to CI pipeline

### Fix

- record cache metrics in ScopedCache to fix 0% hit rate issue
- skip Codecov uploads for Dependabot PRs to prevent CI failures
- add small delay in Windows test for file system sync
- move psutil from dev to main dependencies
- replace DIY atomic operations with filelock for cross-platform compatibility
- implement atomic file operations for Windows compatibility
- resolve defaultdict serialization issue in unified metrics
- properly preserve async functions in fallback decorator
- Make unified metrics import optional to fix CI failures
- Add Windows support for file locking in unified metrics
- **tests**: use sys.executable for Windows CLI test compatibility
- **tests**: handle stderr being None on Windows in CLI test
- **release-automation**: resolve Windows Unicode encoding issues
- **release-automation**: preserve indentation in commitizen version updates
- Properly configure uv virtual environment for docs build
- Remove problematic plugin autosummary entries from docs
- Add --system flag for uv pip install in documentation workflow
- Merge main and update deprecated actions/upload-artifact
- Move docs deployment workflow to correct location
- Update deprecated actions/upload-artifact to v4
- **dogfooding**: implement MCP usage tracking integration
- replace Unicode emojis with ASCII markers for Windows compatibility
- use manual TOML parsing for Python 3.10 compatibility
- improve release process and add worktree safety (issues #162-#165)

## v0.1.0 (2025-08-24)

### Feat

- Update dev workflow to use PAT for branch protection bypass
- Implement development versioning strategy
- Implement automated release workflow
- **dogfooding**: add complete automation for metrics tracking (fixes #138)
- **dogfooding**: implement metrics tracking for MCP usage (fixes #135)
- **guidelines**: add automated checks and documentation to prevent CI failures
- **scope**: implement smart defaults and performance optimizations for namespace packages
- **plugins**: Add namespace package support to all plugin classes
- implement MCP-first dogfooding workflow for development
- Add scope parameter support to 6 core analyzer methods
- Implement core infrastructure for namespace-aware file operations
- Add find_subclasses tool for general inheritance tracking
- Add comprehensive performance monitoring and metrics collection
- **security**: Enable Dependabot for automated dependency updates
- Add configurable performance settings via environment variables
- add re-export tracking to find_symbol tool
- Add module/package listing and dependency analysis tools
- Add workflow_dispatch trigger to CI workflow
- Add coverage percentage badge to README
- Add comprehensive error handling with custom exception hierarchy (#21)
- Add comprehensive input validation and sanitization
- Add CI pipeline status badges to README
- Add comprehensive pre-commit hooks and achieve 100% compliance (#8)
- Add comprehensive pre-commit hooks and achieve 100% compliance
- Add comprehensive pre-commit hooks and achieve 100% compliance

### Fix

- correct changelog generation in release workflow
- disable coverage requirement for version consistency tests in release workflow
- critical syntax error in release workflow
- Update workflow to use DEV_TOKEN instead of ADMIN_PAT
- Simplify dev version workflow for admin bypass
- Fix dev version workflow coverage issue and cleanup test
- Add Python 3.10 compatibility for TOML parsing in tests
- Version synchronization across package files
- resolve find_imports performance and namespace handling issues
- restore default scope to 'all' for backward compatibility
- optimize find_imports performance with ripgrep pre-filtering
- Fix settings import issue causing connection pooling tests to fail
- Address pre-commit hook failures
- Handle PosixPath in get_call_hierarchy errors
- Use as_posix() instead of str() for cross-platform compatibility
- Handle PosixPath serialization in error messages
- ruff linting issues in tests
- synchronize formatter versions and resolve CI failures
- resolve CI failures - black formatting and Windows path tests
- **test**: use as_posix() for cross-platform path comparison in test_list_packages_single_package
- disable cross-platform path pre-commit hook by default
- resolve cross-platform path violations across entire codebase
- **tests**: resolve Windows compatibility issues in test_automation.py
- **scope**: resolve cross-platform path handling and CI performance issues
- **django**: Add scope parameter support and fix duplicate detection
- Update Django plugin tests to use async/await
- specify UTF-8 encoding for Windows compatibility in tests
- simplify dogfooding tests to avoid async execution issues in CI
- update dogfooding tests to handle CI environment differences
- Re-enable test_goto_definition_not_found with proper mocking
- Use POSIX path format for cross-platform template names
- Make tests Windows-compatible
- Resolve paths in tests to handle symlinks and short names on Windows/macOS
- Make decorators async-aware to fix MCP coroutine issue
- Update codecov-action parameter from 'file' to 'files' for v5 compatibility
- Remove test docs file
- **ci**: Add dummy success jobs for docs-only PRs
- replace missed hardcoded assertion with threshold function
- make performance tests more tolerant on CI environments
- add Windows CI exception for flaky performance test
- Make timing-based tests more reliable across platforms
- Move temp_project fixture to module level for all test classes
- Fix flaky cache memory efficiency test
- add pull-requests read permission for paths-filter action
- make performance benchmark test tolerant of CI timing variance
- increase wait time for macOS in flaky debounce test
- update test to use GranularCache instead of ProjectCache
- Make path validation tests cross-platform
- Correct CI workflow syntax for conditional jobs
- correct CI badge URL in README
- Update coverage target to 75% and fix flaky macOS test
- update tests for re-export feature changes
- add company affiliation to author and copyright information
- correct author name and email information
- Prevent infinite recursion in circular dependency detection
- Fix Windows path separators and remove unnecessary type ignores
- Add token to Codecov badge for private repository
- Use Codecov's native badge format
- Add CODECOV_TOKEN to CI workflow
- Also mock watcher in test_cross_repository_import_resolution
- Resolve macOS-specific test failure in multi-project workflow (#24)
- Replace environment variable configuration with override files (#19)
- Cross-platform path resolution issues
- Allow legitimate relative paths in PathValidator while maintaining security
- Remove deprecated safety check and fix mypy CI issues
- Update CI workflow to use pyproject.toml for uv cache

### Refactor

- use as_posix() for all file paths in API responses
- Replace print statements with logging in settings.py
- Move Jedi methods from server to JediAnalyzer

### Perf

- Implement connection pooling for multiple projects
- implement smart cache invalidation for 2-3x performance improvement
- Implement smart cache invalidation for 2-3x performance improvement
- Implement async file operations for non-blocking I/O
- Add performance benchmarking suite with baseline measurements
