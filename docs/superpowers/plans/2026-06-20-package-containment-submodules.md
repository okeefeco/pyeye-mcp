# Package Containment (`submodules` edge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `submodules` containment edge (package → child modules/subpackages) and the cold-start survey surface built on it, so pyeye can answer "what is in this package/project" in the handle/edge model.

**Architecture:** One private containment enumerator in `edges.py` is the single source of truth for "a package's children, including PEP 420 namespace packages." The `submodules` edge resolver, `inspect.edge_counts`, and `outline`'s package-survey mode are all thin consumers of that enumerator; registering the edge gives `expand`/`trace` the traversal for free. A separate, structural root-package disambiguation makes a bare top-level package name resolve to one handle.

**Tech Stack:** Python 3.10+, Jedi, `uv` (always `uv run`), pytest. Governing spec: `docs/superpowers/specs/2026-06-20-package-containment-submodules-design.md` (referred to below as "the spec"; section numbers `§N` are its sections).

---

## File structure

| File | Responsibility |
|---|---|
| `src/pyeye/analyzers/jedi_analyzer.py` | Expose the `added_sys_path` list as a stored attribute (the one path source for `roots`). |
| `src/pyeye/mcp/operations/edges.py` | The containment SoT: `_package_dirs`, `_enumerate_submodule_paths`, `resolve_submodules`; register `submodules`. |
| `src/pyeye/_module_sentinel.py` | Confirm/assert the dir-anchored docstring contract (`""`, never raises). |
| `src/pyeye/mcp/operations/inspect.py` | `_count_submodules` (delegates to the enumerator); wire into `_build_edge_counts` for packages. |
| `src/pyeye/mcp/operations/outline.py` | `_child_adjacents` + survey-mode bool + depth-1 default for package roots. |
| `src/pyeye/mcp/operations/resolve.py` | `_select_root_package` + `_is_top_level_package`; call before the ambiguous fallback. |
| `skills/python-explore/SKILL.md` | Supported-edge marker + edge-table row + cold-start workflow line. |
| `tests/fixtures/containment/…` | Real on-disk package trees (regular + 2-portion namespace). |
| `tests/test_*` | Per-task tests (see tasks). |

**Fixture trees (created in Task 2, reused throughout) — constraint: real directories, NOT tmp symlinks (the macOS Jedi-symlink hazard):**

```text
tests/fixtures/containment/regular/mypkg/
    __init__.py            # may contain a re-export, e.g. `from .alpha import A`
    alpha.py
    beta.py
    sub/
        __init__.py
        gamma.py
    __pycache__/cached.pyc # junk → must be skipped
    data/notes.txt         # dir with no .py and no sub-package → must be skipped

tests/fixtures/containment/ns_a/company/   # NO __init__.py (PEP 420 portion A)
    auth.py
    shared.py
tests/fixtures/containment/ns_b/company/   # NO __init__.py (PEP 420 portion B)
    api.py
    shared.py                              # name collision with portion A
```text

---

## Phase 0 — Analyzer foundation

### Task 1 — Expose `added_sys_path` as a stored attribute

**Goal:** Give the containment enumerator a single, ordered, list-derived path source, because `roots` determinism (and therefore namespace collision-winner determinism, the #419 hazard) depends on it. Today `added_sys_path` is a local in `JediAnalyzer.__init__`.

**Files:** `src/pyeye/analyzers/jedi_analyzer.py`; `tests/test_jedi_analyzer_sys_path.py` (new).

**Interfaces (produced):**

```text
JediAnalyzer.added_sys_path: list[Path]   # stored attribute, sys.path-precedence order, stable run-to-run
```

**Tests (pin these assertions):**

- For a `src`-layout fixture project, `analyzer.added_sys_path` is a `list[Path]` and contains the `src` root.
- The attribute is a plain `list` (not a `set`) and returns the same order on two constructions of the same project.
- `added_sys_path` is consistent with what is passed to `jedi.Project` (no second computation path).

**Constraints:**

- Additive only — do not change the existing `jedi.Project(added_sys_path=…)` behavior; store the same list you already build.
- Type is `list[Path]` (convert the existing `list[str]` of posix strings to `Path`, or store both — implementer's choice, but the public attribute the spec references is `list[Path]`).

**Acceptance criteria:** New test passes; full suite still green; no change to existing analyzer behavior.

**Risks:** The local is built in two branches (src-layout discovery + namespace repo roots). Ensure the stored attribute reflects the *final* merged list, not an intermediate.

---

## Phase 1 — The containment edge (single source of truth)

### Task 2 — `_package_dirs` for regular packages + fixtures

**Goal:** Resolve a *regular* package handle to its single directory, the base case the enumerator builds on. Also lands the shared fixtures.

**Files:** `src/pyeye/mcp/operations/edges.py`; `tests/fixtures/containment/…` (new, per the trees above); `tests/test_submodules_edge.py` (new).

**Interfaces (produced):**

```text
edges._package_dirs(jedi_name: Any, analyzer: JediAnalyzer) -> list[Path]
```text

**Tests:**

- A regular package handle (its `module_path` ends in `__init__.py`) → `[<that dir>]` (single element, the `__init__.py`'s parent).
- A non-package module handle (`module_path` is `foo.py`) → `[]`.
- A class/function handle → `[]`.

**Constraints:**

- The regular-vs-namespace decision is made **once** here, by inspecting the resolved handle's `module_path` (`§3.2`): ends in `__init__.py` → regular (single dir); else → namespace branch (Task 4). Do **not** re-decide per directory.
- `jedi_name` may be a real Jedi `Name` or a `ModuleSentinel`; read `module_path`/`full_name` via `getattr`, tolerate `None`.

**Acceptance criteria:** `test_submodules_edge.py` regular/non-package cases pass.

**Risks:** A `ModuleSentinel` for a package carries `module_path = <__init__.py>` already, so the same branch must handle both Jedi names and sentinels.

---

### Task 3 — `_enumerate_submodule_paths` + shallow importable-dir filter (regular packages)

**Goal:** Enumerate a regular package's direct children as `(handle, file, is_subpackage)` from a pure directory scan — the heart of the SoT — with the junk-dir filter.

**Files:** `src/pyeye/mcp/operations/edges.py`; `tests/test_submodules_edge.py`.

**Interfaces (produced):**

```text
class _SubmoduleEntry(NamedTuple):
    handle: str          # e.g. "mypkg.alpha"
    file: Path           # X.py | X/__init__.py | X/ (namespace dir)
    is_subpackage: bool

edges._enumerate_submodule_paths(jedi_name: Any, analyzer: JediAnalyzer) -> list[_SubmoduleEntry]
edges._dir_shallow_qualifies(path: Path) -> bool   # the §3.5 filter
```

**Tests (against the `regular/mypkg` fixture):**

- Children handles == `{"mypkg.alpha", "mypkg.beta", "mypkg.sub"}` (exactly — no `__init__`, no `__pycache__`, no `data`).
- `mypkg.alpha` → `is_subpackage == False`, `file.name == "alpha.py"`.
- `mypkg.sub` → `is_subpackage == True`, `file.name == "__init__.py"` and `file.parent.name == "sub"`.
- Result list is **sorted by child name** (deterministic): `["mypkg.alpha", "mypkg.beta", "mypkg.sub"]`.
- `_dir_shallow_qualifies`: a dir with a direct `.py` → True; a dir with only `notes.txt` → False; `__pycache__` → False (skipped).

**Constraints (`§3.3`, `§3.5`):**

- Enumeration rule exactly as `§3.3`: `X.py` (not `__init__`) → module; `X/__init__.py` → regular subpackage; `X/` with no `__init__.py` that shallow-qualifies → namespace subpackage (`file = X/`).
- The shallow filter is **one level, explicitly capped** (direct `.py`, or direct subdir with `__init__.py`, or direct subdir that shallow-qualifies **once**) — never a recursive "any `.py` anywhere". Cap the recursion at depth 1.
- Always skip `__pycache__` and dotfiles.
- **No file reads** in this function — `iterdir` + path/name tests only (it backs the cheap count in Task 6).

**Acceptance criteria:** All enumeration assertions pass; the filter test passes.

**Risks:** Over-eager recursion in `_dir_shallow_qualifies` would reintroduce a subtree walk — the test with a nested junk dir guards this. Keep the one-level cap.

---

### Task 4 — PEP 420 namespace support: multi-dir union + first-portion-wins

**Goal:** Make `_package_dirs`/`_enumerate_submodule_paths` handle namespace packages spanning multiple directories, with deterministic collision resolution — the spec's highest-risk correctness point (`§3.4`).

**Files:** `src/pyeye/mcp/operations/edges.py`; `tests/test_submodules_namespace.py` (new).

**Interfaces (extended, same signatures as Tasks 2–3):** `_package_dirs` now returns the **union** of matching directories for a namespace handle; `_enumerate_submodule_paths` dedupes children **by name across portions**, first-portion-wins.

**Tests (against `ns_a` + `ns_b` fixtures, analyzer roots ordered so `ns_a` precedes `ns_b`):**

- `_package_dirs("company")` → both `ns_a/company` and `ns_b/company` (union), neither containing `__init__.py`.
- Enumerated child handles == `{"company.auth", "company.api", "company.shared"}` (union, deduped).
- **Collision (`company.shared`):** its `file` is the **portion-A** file (`ns_a/company/shared.py`) — assert the winning path explicitly, because this is what pins the determinism invariant.
- Reversing the roots order in a second analyzer flips the winner to `ns_b` — proving the winner rides on `roots` order, not the name-sort.

**Constraints (`§3.4`):**

- `roots` is built from `analyzer.source_roots`, `analyzer.project_path`, and `analyzer.added_sys_path` (Task 1) — **list-derived, never set-derived**.
- **The exact `roots` order is a hypothesis to verify, not an assertion** (`§3.4`): determine the order that matches Python's `sys.path` precedence for the fixture, and let the collision test pin it. Add a one-line code comment stating "roots order = sys.path precedence; collision-winner determinism depends on it (#419 class)".
- A directory is a namespace portion iff it is a directory matching the dotted handle, has **no** `__init__.py`, and shallow-qualifies.
- Only namespace handles union; a regular handle stays single-dir (Task 2 decision, unchanged).

**Acceptance criteria:** Namespace union, dedup, and both collision-direction tests pass.

**Risks:** The collision determinism is the #419-class hazard. The two-direction test is the guard — do not weaken it to only assert membership. Caveat: wiring a 2-root namespace into a real `JediAnalyzer` may need configuring `added_sys_path`/namespace paths; if Jedi will not surface `company` as a handle, drive `_package_dirs` with a `ModuleSentinel`/minimal name object carrying `full_name="company"` and `module_path=None` — the function must not depend on Jedi resolving the namespace.

---

### Task 5 — `resolve_submodules` resolver + dir-anchored stub contract + edge registration

**Goal:** Wrap the enumerator as the `submodules` edge resolver, lock the dir-anchored stub contract, and register the edge — which gives `expand` and `trace` the traversal for free.

**Files:** `src/pyeye/mcp/operations/edges.py`; `src/pyeye/_module_sentinel.py`; `tests/test_submodules_edge.py`; `tests/test_module_sentinel.py` (new or extend).

**Interfaces (produced):**

```text
edges.resolve_submodules(jedi_name: Any, analyzer: JediAnalyzer) -> EdgeResult
# registered: "submodules" added to _IMPLEMENTED_EDGES and EDGE_RESOLVERS
```text

**Tests:**

- `resolve_submodules` on `mypkg` → `EdgeResult` whose `.handles` == the Task-3 child handles; each adjacent carries a `ModuleSentinel` (so `build_stub` needs no Jedi goto).
- Non-package handle → `EdgeResult([])` (the "wrong kind → empty, never None" convention).
- **Dir-anchored stub contract (`§3.6`):**
  - `ModuleSentinel(dir).docstring() == ""` (empty `str`, **not** `None`) and does **not** raise, where `dir` is a namespace-subpackage directory.
  - A namespace-subpackage stub survives the full `expand`/`outline` path with **no byte read** of its `file` (assert via a guard that fails if `Path.read_text`/`open` is called on a directory `file`).
- `edge_status("submodules") == "implemented"`; `"submodules" in EDGE_RESOLVERS`.
- `expand(<pkg>, "submodules")` returns the children as stubs; `trace(<pkg>, follow=["submodules"], max_depth=1)` returns them as a one-hop tree (smoke-level — deep/bounded behavior is Task 10).

**Constraints:**

- `resolve_submodules` builds adjacents as `(Handle, ModuleSentinel)` pairs from `_SubmoduleEntry` (handle, file). It adds **no** containment logic of its own — all of that stays in the enumerator.
- `ModuleSentinel` must already swallow a directory read-error to `""`; if it does not, make it do so and **assert it** (so a future refactor cannot silently start raising).
- Update the module docstring/status table in `edges.py` to include `submodules` in the implemented set (the file is self-documenting about its edge set).

**Acceptance criteria:** Resolver, registration, and both dir-stub contract tests pass; `expand`/`trace` smoke tests pass.

**Risks:** `build_stub` / `get_end_line` must tolerate a `ModuleSentinel` whose `module_path` is a directory (`line=1`, span trivial). If `get_end_line` reads the file, the dir-stub no-read test will catch it — handle the directory case.

---

## Phase 2 — Consumers

### Task 6 — `edge_counts.submodules` (cheap, delegated)

**Goal:** Advertise `submodules: N` in `inspect` for package handles via the counts-first signal, delegating to the enumerator so containment logic stays in one place.

**Files:** `src/pyeye/mcp/operations/inspect.py`; `tests/test_inspect_edge_counts.py` (extend or new `tests/test_inspect_submodules_count.py`).

**Interfaces (produced):**

```text
inspect._count_submodules(jedi_name: Any, analyzer: JediAnalyzer) -> int   # async, matches _count_module_members
# = len(edges._enumerate_submodule_paths(jedi_name, analyzer))
```

**Tests:**

- For `mypkg`: `inspect("mypkg").edge_counts["submodules"] == len(expand("mypkg","submodules").stubs)` (the invariant tying count to enumeration).
- `submodules` is **absent** from `edge_counts` for a non-package module handle, and for class/function/variable handles (absence-vs-zero — not-applicable, not zero).
- An **empty** package (a dir with only `__init__.py`) → `submodules == 0` (a measured zero, present).
- `_count_submodules` performs **no** `ModuleSentinel` construction and no file reads (it calls only `_enumerate_submodule_paths`).

**Constraints (`§4`):**

- Present **only** for package handles (`is_package`). Wire into `_build_edge_counts` under the same per-edge budget machinery as `members`/`superclasses`.
- Do **not** add any `subclasses` count alongside it — different cost class (reverse/whole-project). The spec calls this out (`§6.3`); honor it.

**Acceptance criteria:** Count invariant, absence cases, empty-package zero, and delegation tests pass.

**Risks:** `_build_edge_counts` keys edges by kind; ensure `submodules` is only added on the `module`+`is_package` path, not all modules.

---

### Task 7 — `outline` package-survey mode + depth-1 default

**Goal:** Make `outline(pkg)` return the drillable submodule tree (depth-1 by default, modules as leaves), while leaving `outline(module)`/`outline(class)` byte-for-byte unchanged.

**Files:** `src/pyeye/mcp/operations/outline.py`; `tests/test_outline_packages.py` (new); existing outline tests updated for the new package-handle contract.

**Interfaces (produced):**

```text
outline._child_adjacents(jedi_name: Any, analyzer: JediAnalyzer, survey_mode: bool) -> list[tuple[Handle, Any]]
# survey_mode and is_package(jedi_name) -> resolve_submodules(...).adjacents ; else -> resolve_members(...).adjacents
```text

**Tests:**

- `outline("mypkg")` with no `max_depth` (depth-1 default):
  - root children handles == `{"mypkg.alpha", "mypkg.beta", "mypkg.sub"}`.
  - `mypkg.sub` (subpackage, has children) → `truncated == True`, `truncation_reason == "max_depth"`, **no** `children` key.
  - `mypkg.alpha`, `mypkg.beta` (modules) → `children == []` (leaves, members not walked), no `truncated` key.
- `outline("mypkg", max_depth=2)` → `mypkg.sub` expands to `{"mypkg.sub.gamma"}`.
- The package's own `__init__.py` re-exports do **not** appear in `outline("mypkg")` (submodules-only).
- **Regression:** `outline(<a module>)` and `outline(<a class>)` produce identical trees to before this change (snapshot/equality against the pre-change behavior on an existing fixture).

**Constraints (`§6`):**

- Replace **all three** `resolve_members(...)` call sites (the depth-frontier peek and the expand step) with `_child_adjacents(...)`, so the peek checks `submodules` for packages.
- Survey mode is set from the **root** handle's `is_package`; within survey mode, expandable = `is_package(node)` (plain modules become leaves).
- Kind-dependent default: a package root with `max_depth=None` is treated as `max_depth=1`; module/class roots keep `None`. Document this in the `outline` docstring as intentional.
- Reuse the existing caps, truncation contracts, and source-order sort unchanged.

**Acceptance criteria:** All package-outline assertions pass; module/class regression tests unchanged and green.

**Risks:** The semantic change to package handles will break existing outline-on-package tests — that is expected; update them to the new contract (this *is* #423). Do not weaken the module/class regression check.

---

### Task 8 — Root-package disambiguation in `resolve`

**Goal:** Make a bare top-level package name (e.g. `resolve("django")`) resolve to one handle instead of an ambiguous set, via a structural (not name-based) rule.

**Files:** `src/pyeye/mcp/operations/resolve.py`; `tests/test_resolve_root_package.py` (new).

**Interfaces (produced):**

```text
resolve._is_top_level_package(candidate: _Candidate, analyzer: JediAnalyzer) -> bool
resolve._select_root_package(candidates: list[_Candidate], analyzer: JediAnalyzer) -> _Candidate | None
```

**Tests:**

- A project with a top-level package `mypkg` plus an unrelated same-named symbol deeper in the tree: `resolve("mypkg")` → a single success result with `handle == "mypkg"` (the root `__init__.py`), **not** ambiguous.
- A deeper `a.b.mypkg` candidate is **not** promoted (its handle has dots → fails clause 1).
- A `mypkg.py` module (not an `__init__`, not a dir) is **not** promoted (fails clause 2).
- When two genuinely distinct top-level handles match → result stays **ambiguous** (no false promotion).
- Resolving a directory **path** (`resolve("…/mypkg")`) and resolving dotted handles are unchanged (regression).

**Constraints (`§7`):**

- `_select_root_package` runs in `_resolve_bare_name` **before** building `_AmbiguousResult`. Keep `_resolve_bare_name`'s single-match and not-found paths unchanged.
- `_is_top_level_package` is the exact two-clause predicate in `§7.1`: (1) handle has no dots and equals the queried name; (2) `location.file` is a root-level package anchor — `__init__.py` whose parent is the name and grandparent is `project_path`/a `source_root`, **or** a directory named the name directly under `project_path`/a `source_root`.
- Dedupe the kept candidates by **handle string**: exactly one distinct handle → promote; zero or >1 → return `None` (stay ambiguous).
- **Namespace-root boundary (`§7.2`):** do not add special machinery to surface Jedi-invisible namespace roots by bare name; if `find_symbol` returns nothing, `resolve("<name>")` stays not-found and `resolve(path)` is the entry. (No test should assert a Jedi-invisible namespace root resolves by bare name.)

**Acceptance criteria:** All promotion/non-promotion/ambiguity-preserved/regression tests pass.

**Risks:** Over-promotion is the failure mode. The "deeper same-named" and "`.py` not `__init__`" negative tests are the guards — keep them.

---

## Phase 3 — Docs, conformance, integration

### Task 9 — Skill update + conformance

**Goal:** Keep the shipped `python-explore` skill truthful about the supported edge set (conformance-guarded) and document the survey workflow.

**Files:** `skills/python-explore/SKILL.md`; verify `tests/test_python_explore_skill_conformance.py` passes (no change expected to the test itself).

**Tests:** `uv run pytest tests/test_python_explore_skill_conformance.py` passes with `submodules` present.

**Constraints (`§8`):**

- Add `submodules` to the `<!-- pyeye-supported-edges: ... -->` marker (the conformance test asserts this set **equals** `_IMPLEMENTED_EDGES`).
- Add the edge-table row: `submodules | package → child modules/subpackages | one hop; full tree via trace; one-call survey via outline`.
- Add one cold-start workflow line: `resolve(root) → outline(pkg) | expand(pkg,"submodules") → drill into a module → inspect / expand members / trace`.

**Acceptance criteria:** Conformance test green; markdownlint green (use a language on any fenced block).

**Risks:** Forgetting the marker fails conformance — that is the safety net working.

---

### Task 10 — Integration / acceptance + full validation

**Goal:** Prove the end-to-end cold-start workflow and the bounded-tree caps on a realistically deep package, then run full validation.

**Files:** `tests/test_submodules_integration.py` (new).

**Tests (against a multi-level fixture package — extend `mypkg` with enough depth/breadth, or a dedicated deeper fixture):**

- **Bounded trace:** `trace(<deep pkg>, follow=["submodules"], max_nodes=<small>)` returns a tree that respects `max_nodes` and carries honest `truncated`/`truncation_reason` — never an unbounded dump.
- **Cold-start workflow:** `resolve(<root>)` → handle; `outline(<root>)` → depth-1 children; `expand(<a child pkg>, "submodules")` → its children; `inspect(<a child module>)` → its node. The full chain works using only handles (no `ls`/grep).
- **Count/enumeration invariant** holds end-to-end: `inspect(pkg).edge_counts["submodules"] == len(expand(pkg,"submodules").stubs)`.

**Constraints:** Real on-disk fixtures only (no tmp symlinks). Use the performance-threshold framework if any timing assertion is added — no naive `assert elapsed < X`.

**Acceptance criteria:**

- `uv run pytest --cov=src/pyeye --cov-fail-under=85` passes; new code ≥90% covered.
- `uv run mypy src/pyeye` clean for changed files.
- Pre-commit hooks pass.

**Risks:** Deep fixtures can be slow under Jedi; keep the fixture modest but multi-level. If the count/enumeration invariant fails, the bug is a divergence between `_count_submodules` and `resolve_submodules` — they must both bottom out in `_enumerate_submodule_paths`.

---

## Notes for the executor

- **TDD per task:** write the failing test → run it and confirm it fails for the right reason → implement the minimal code → run until green → run the relevant neighbors (and the full suite at phase boundaries) → commit test + implementation together.
- **Commit discipline:** conventional commits referencing #423; never `--no-verify`; if pre-commit modifies files, review and re-commit. End commit messages with the `Co-Authored-By: Claude Opus 4.8 (1M context)` trailer.
- **Decision log:** at the commit that lands Task 7 (the deliberate `outline`-on-package semantic change) — or at final merge — invoke the `pyeye:decision-log` skill: it is contract-significant and friction-driven.
- **Dependency order:** Task 1 → 2 → 3 → 4 → 5 unblock Phase 2 (6/7/8 are independent of each other once 5 lands) → 9/10 last.

```text
