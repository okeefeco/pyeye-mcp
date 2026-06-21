# Package containment design — the `submodules` edge + cold-start survey

**Date:** 2026-06-20
**Issue:** #423
**Status:** design (pre-implementation)
**Branch:** `feat/423-package-containment`

## 1. Context & goal

The redesign deprecated the legacy survey tools (`list_packages`, `list_modules`,
`list_project_structure`). The symbol-anchored primitives that replaced them
(`resolve`/`inspect`/`outline`/`expand`/`trace`) all require a handle the caller
**already knows**, and pyeye models a package as nothing more than its `__init__.py`
module. There is no edge that traverses **package → child modules/subpackages**, so:

```text
inspect("django.db.models")          -> { is_package: true, edge_counts: { members: 1 } }   # only __all__
expand("django.db.models", "members") -> [ django.db.models.__all__ ]                        # just __all__
```

`django/db/models/` actually contains 17 submodules + 3 subpackages. "What modules
exist under this package?" and "what is this project's layout?" are **not answerable**
in pyeye today — an agent must drop to `ls`/grep to orient, then return to pyeye to
drill. pyeye is a strong second-stage drill but cannot do first-stage orientation.

**Goal:** restore the top-down survey **in the handle/edge model** (not by resurrecting
the legacy listers), so orientation is a launchpad into `expand`/`trace`/`outline`
rather than a separate, dead-end read.

### Resolution direction (from the #423 discussion)

The three legacy tools conflated three concerns. Only one is genuinely missing:

| Legacy tool | Real concern | Verdict |
|---|---|---|
| `list_project_structure` | filesystem tree | **Drop** — shell's job; `resolve(path)` already maps a dir → handle |
| `list_packages` | package containment graph | **Re-home as an edge** — the one true gap |
| `list_modules` | modules + exports + metrics | **Split** — modules = containment edge; exports already in `inspect.re_exports` + `expand members`; metrics = out of scope |

This spec adds the **`submodules` containment edge** and the survey surface built on
it. It refines no prior spec; where it touches `outline`, it governs the package-handle
case (the 2026-06-13 outline design governs module/class handles, unchanged).

## 2. Scope

**In:**

- `src/pyeye/mcp/operations/edges.py` — new `submodules` edge: a single containment
  enumerator (the **only** place package-children / PEP 420 logic lives), the
  `resolve_submodules` resolver, registration in `_IMPLEMENTED_EDGES` + `EDGE_RESOLVERS`.
- `src/pyeye/mcp/operations/inspect.py` — `edge_counts.submodules` for package handles,
  delegating to the shared enumerator (count = `len`, no stub builds).
- `src/pyeye/analyzers/jedi_analyzer.py` — expose the existing `added_sys_path` list as a
  stored attribute so the containment enumerator builds its search roots from one path
  source (§3.4).
- `src/pyeye/mcp/operations/outline.py` — package-survey mode: `outline(pkg)` walks
  `submodules` (depth-1 default, modules-as-leaves). Module/class outline unchanged.
- `src/pyeye/mcp/operations/resolve.py` — root-package disambiguation so a bare
  top-level package name resolves to one handle instead of an ambiguous set.
- `skills/python-explore/SKILL.md` — add `submodules` to the supported-edge marker +
  edge table + cold-start workflow line.
- `tests/` — edge, count, outline, resolve, PEP 420, and conformance tests.

**Out (deliberate):**

- Filesystem-tree primitive (shell's job).
- Per-module metrics (a separate surface if ever wanted — not bundled into survey).
- A `subclasses` count in `edge_counts` (reverse/whole-project scan — different cost
  class; see §6.3).
- Resurrecting any legacy `list_*` tool.

## 3. The `submodules` edge

### 3.1 Definition

`submodules`: **package → its direct child modules and subpackages**, as canonical
handles. One hop (direct children only); the recursive tree is the consumer's job
(`trace`/`outline` apply caps). A non-package handle yields `EdgeResult([])` — the
same "wrong kind → empty, never None" convention `enclosing_scope`/`subclasses` use.

This is a **forward/local** edge: a package's children come from listing its own
directory. No project-wide scan. That cheapness is load-bearing for §6.

### 3.2 Single containment source of truth

All "how do I find a package's children, including PEP 420 namespace packages"
knowledge lives in **one** private enumerator. Every consumer is a thin caller; the
non-trivial namespace logic must never be duplicated (it would drift).

```text
_enumerate_submodule_paths(jedi_name, analyzer) -> list[ChildEntry]
    # ChildEntry = (child_handle: str, file: Path, is_subpackage: bool)
    # PURE directory scan: no file reads, no Jedi goto. The ONLY containment logic.
```

Built on a package→directories resolver:

```text
_package_dirs(jedi_name, analyzer) -> list[Path]
```

The regular-vs-namespace branch is **decided once, by Jedi's classification of the
already-resolved handle** — never re-decided per directory (a stray `__init__.py`
under one root must not flip the decision):

- **Regular package** — `jedi_name.module_path` ends in `__init__.py`
  → `[module_path.parent]` (single directory).
- **Namespace package (PEP 420)** — handle is not anchored on an `__init__.py`
  → union of every directory matching the dotted handle across the project roots
  (§3.4). Only namespace handles union.

### 3.3 Enumeration rule (per directory, then union)

For each directory from `_package_dirs`, scan its **direct** entries (one `iterdir`):

- `X.py` where `X != "__init__"` → child **module**, `file = X.py`.
- `X/__init__.py` exists → child **subpackage** (regular), `file = X/__init__.py`.
- `X/` with no `__init__.py` that **shallow-qualifies** as importable (§3.5)
  → child **namespace subpackage**, `file = X/` (the directory itself).
- Always skip `__pycache__`, dotfiles, and dirs that do not shallow-qualify.

Order across the unioned directories: dedupe child entries **by child name**, then
sort by name for a deterministic result list.

### 3.4 Namespace directory resolution + determinism

A namespace package can span multiple directories. `_package_dirs` searches the
project roots in **sys.path-precedence order**. A directory
`root_i / Path(*handle.split("."))` is a namespace portion iff it is a directory
**without** an `__init__.py` that shallow-qualifies.

**Roots source (implementation note).** `JediAnalyzer` stores `self.project_path` and
`self.source_roots` (both `list[Path]`), but the `added_sys_path` list it passes to
`jedi.Project` is currently a **local variable** in `__init__`, not a stored attribute.
The implementation must **expose that ordered list as an attribute** (a small additive
change — e.g. `self.added_sys_path: list[Path]`) so `roots` can be built from it; it
must not be recomputed ad hoc in `edges.py` (that would be a second source of path
truth). The codebase's established search-root idiom is
`list(self.source_roots) + [self.project_path]` (source roots first, project root
last — see `jedi_analyzer.py` `_resolve_*` helpers); `roots` follows that same
precedence, with the exposed `added_sys_path` appended. The **starting hypothesis**
(to verify, not asserted) is:

```text
roots = [*analyzer.source_roots, analyzer.project_path, *analyzer.added_sys_path]
```

The exact order is not free to choose — it **must** match Python's `sys.path`
precedence for the project. This has **not** been empirically confirmed here; the plan
must verify it against the existing idiom and a multi-portion namespace fixture (the
collision test that asserts *which* portion wins is the check that pins it). All three
inputs are **lists** (never set-derived), so whatever the verified order, it is stable
run-to-run.

**Collision rule — first portion wins.** When two portions define a child of the same
name, the first portion in `roots` order supplies the winning `file` (and kind). This
mirrors Python's own runtime semantics: on a real cross-portion name collision, the
first entry on `sys.path` wins. Within a single directory the filesystem forbids
duplicate names, so collision determinism reduces **entirely** to `roots` order.

> **Determinism invariant (assert + comment in code):** `roots` is constructed in
> sys.path-precedence order (`source_roots`, then `project_path`, then the exposed
> `added_sys_path` — all in their stored list order, per §3.4). The name-sort in §3.3 makes the
> *list order* deterministic but does **not** decide the collision winner — that rides
> on `roots` order, upstream of the sort. If any portion of `roots` could reorder
> run-to-run, the winning file for a duplicate-named namespace submodule would flip
> intermittently (the #419 class of bug). This invariant is the guard.

### 3.5 Shallow importable-directory check

The "is this directory an importable namespace subpackage, or just a data/junk dir?"
test is **shallow and explicitly capped** — it must not become a subtree walk per
candidate (that would destroy the cheap-scan premise). A directory `X/` (no
`__init__.py`) qualifies iff, among its **direct** entries, any of:

- a direct `*.py` file, or
- a direct child dir with an `__init__.py`, or
- a direct child dir that itself shallow-qualifies **once** (one bounded extra level
  — never recursive "any `.py` anywhere").

Rationale: runtime Python will namespace-import even an empty directory; this filter
exists only to skip obvious non-packages (`__pycache__`, `tests/fixtures/data/`,
`.git`). A shallow heuristic is the right amount of strict.

### 3.6 Stubs for children — cheap, no Jedi resolve

Each `ChildEntry` becomes an adjacent `(Handle, ModuleSentinel)` pair.
`ModuleSentinel(file, child_handle, analyzer)` synthesizes a Jedi-`Name`-shaped object
(`type="module"`, `full_name=child_handle`, `line=1`, AST docstring) from a file path
alone, and `build_stub` reads only those attributes. So **children get stubs from a
pure filesystem scan — zero Jedi goto/resolution**.

For a **regular** child the `file` is a real source file (`X.py` or `X/__init__.py`):
stub `file` is editor-openable, `line=1`, docstring from AST.

For a **namespace subpackage** child the `file` is the **directory** itself. This is
**not novel** — it is the existing representation for a directory-anchored package
handle: `resolve("…/django/db")` already returns `django.db` with `location.file` =
the directory and `line_start = 1`. Two contracts pin its behavior:

> **Dir-anchored stub contract:**
>
> 1. **No consumer may read the bytes of a stub's `file`.** Stubs are pointers
>    (no-source principle); a `file` that is a directory would raise if any code ever
>    `open()`s it. `outline`/`expand` already only read attributes — a test asserts a
>    namespace-subpackage stub survives the full `outline`/`expand` path with **no**
>    byte read.
> 2. **Docstring on a directory resolves to the empty string, never raises.**
>    `ModuleSentinel.docstring()` returns `""` (an empty `str`, **not** `None`) when
>    its `file` is a directory — its AST read swallows the directory read-error. A
>    test asserts `ModuleSentinel(dir).docstring() == ""` and does not raise, so a
>    future refactor of the swallow cannot silently start raising.

Accepted limitation: a `dir:1` location is not editor-openable. This is honest and
unavoidable for PEP 420 packages with no `__init__.py`; not worth solving.

### 3.7 Resolver + registration

```text
resolve_submodules(jedi_name, analyzer) -> EdgeResult
    package handle     -> EdgeResult of (Handle, ModuleSentinel) per ChildEntry
    non-package handle -> EdgeResult([])
```

Registered in `_IMPLEMENTED_EDGES` and `EDGE_RESOLVERS`. Registration is what gives
`expand` and `trace` the edge **for free** (§5). `edges.py` remains the single source
of truth for the edge set; `inspect`/`outline` import the enumerator but never
reimplement it (preserving the inspect→edges import direction, no cycle).

## 4. `edge_counts.submodules`

`inspect`'s `_count_submodules` is a **thin delegator** over the shared enumerator:

```text
_count_submodules(jedi_name, analyzer) = len(_enumerate_submodule_paths(jedi_name, analyzer))
```

No `ModuleSentinel` construction, no file reads — the cheapest path. Containment and
PEP 420 logic live **only** in the enumerator; the count cannot drift from the edge
**for regular packages** (see the scope note below).

- Present **only** for **regular** package handles (anchored on an `__init__.py`).
  The value may be `0` (a genuinely empty package — a measured zero, valid under
  absence-vs-zero).
- **Absent** for non-package modules and all non-module kinds (submodules is
  not-applicable, not zero — mirroring how `enclosing_scope` on a module is `[]`).
- **Scope — regular packages only (count==expand boundary, #444).** A PEP 420
  namespace package surfaces as a `kind=="namespace"`/`scope=="external"` handle
  and never reaches the `kind == "module"` counting branch, so `inspect` omits its
  `submodules` count even though `expand(pkg, "submodules")` can still enumerate
  children. The `count == len(expand)` equality is therefore guaranteed for
  regular packages only; making it hold for namespace packages requires anchoring
  them to a project handle first (deferred to #444, consistent with the
  best-effort namespace-root boundary in §7.2).
- Wired into `_build_edge_counts` under the same per-edge budget machinery as
  `members`/`superclasses`.

## 5. The free three-tier stack

Registering one edge yields the full progressive-disclosure stack — the same shape as
`subclasses`:

- `expand(pkg, "submodules")` → **direct** children, one hop.
- `trace(follow=["submodules"], max_depth=k)` → **bounded containment tree**. The
  resolver returns full *direct* lists; recursion + capping is the consumer's job, so
  `trace`'s existing `max_nodes`/`max_depth`/`truncated` caps protect against a deep
  tree like top-level `django` (verified as an acceptance test, §7.6).
- `outline(pkg)` → **depth-1 skeleton** (§6).

## 6. `outline` package-survey mode

### 6.1 Trigger and the two rules

When the **root** handle is a package (`is_package`), `outline` enters **survey mode**
— one bool threaded into the existing BFS; caps, truncation contracts, and the
source-order sort are reused verbatim. The edge is consumed at exactly three sites
today (`resolve_members` at the depth-frontier peek and the expand step); all three
become an edge-selection helper:

```text
_child_adjacents(jedi_name, analyzer, survey_mode):
    survey_mode and is_package(jedi_name) -> resolve_submodules(...)   # packages recurse
    else                                  -> resolve_members(...)      # unchanged
```

Two behaviors flow from the "submodule tree only" decision:

1. **Edge selection** — packages expand via `submodules` (and recurse into
   subpackages, which are also packages).
2. **Expandability** — in survey mode only **packages** are expandable; a **plain
   module is a leaf** (`children: []`, members not walked). This is what makes
   `django.db.utils` a leaf while `django.db.models` recurses.

```text
survey_mode -> expandable = is_package(node)      # modules become leaves
else        -> expandable = _is_container(kind)   # today: class | module
```

`outline(module)` / `outline(class)` use `survey_mode=False` — **completely
unchanged** code path.

### 6.2 Depth-1 default (kind-dependent)

`outline` gains a **kind-dependent default**: a package root with `max_depth=None` is
set to `max_depth=1` (direct children — subpackages marked `truncated: max_depth`,
modules as leaves); module/class roots keep the existing `None` default. This realizes
the issue's "top-level packages first, drill on demand" constraint. The caller passes
a higher `max_depth` to go deeper. Documented as intentional in the docstring + spec.

Example:

```text
outline("django.db")            # depth-1 default
  django.db
  ├ django.db.models      (subpackage) truncated: max_depth   # has submodules
  ├ django.db.backends    (subpackage) truncated: max_depth
  ├ django.db.utils       (module)     children: []           # leaf
  └ django.db.transaction (module)     children: []           # leaf
```

### 6.3 Recorded consequences

- The package's own `__init__.py` members (re-exports) do **not** appear in
  `outline(pkg)` — submodules-only by design. They remain reachable via
  `inspect(pkg).re_exports` and `expand(pkg, "members")`. Accepted.
- `outline` on a package handle is a **deliberate semantic change** (was: walk members
  → only `__all__`; now: walk submodules → the module tree). Existing outline-on-package
  tests are updated to the new contract; this *is* the #423 fix. It is
  contract-significant + friction-driven → logged via the decision-log skill at commit.
- The `submodules` count in `edge_counts` is safe **only because containment is
  forward/local** (a directory listing). This is the same cheapness test that
  *excluded* `subclasses` (reverse, whole-project scan, gated on #333/#397). The next
  reader must not "helpfully" add a `subclasses` count beside it — different cost class.

## 7. Root-package disambiguation (resolve)

`resolve("django")` is ambiguous today because `find_symbol("django")` returns several
matches. A **principled, structural** disambiguation pass runs in `_resolve_bare_name`
**before** the `_AmbiguousResult` fallback. It keys on file structure, **not** the
name string, so a submodule sharing the root's name is never wrongly promoted.

### 7.1 The one precise rule

```text
_select_root_package(candidates, analyzer):
    keep candidates for which _is_top_level_package(candidate, analyzer) is True
    dedupe the kept set by handle string:
        exactly one distinct handle -> return it as the success resolution
        zero, or >1 distinct handles -> return None  (keep the ambiguous result)
```

`_is_top_level_package(candidate, analyzer)` — a candidate is a top-level package iff
**both**:

1. its handle has **no dots** and equals the queried name (a *deeper* `foo.bar.django`
   has dots → never qualifies); and
2. its `location.file` `F` is a **root-level package anchor**, i.e. either
   - **regular root:** `F` is named `__init__.py`, `F.parent.name == name`, and
     `F.parent.parent` is `analyzer.project_path` or in `analyzer.source_roots`; or
   - **directory-anchored root:** `F` is a directory `D` with `D.name == name` and
     `D.parent` is `analyzer.project_path` or in `analyzer.source_roots`.

A `django.py` module (not an `__init__`, not a dir) and a deeper `…​.django` (has
dots) both fail this predicate. Dedupe-by-handle makes a namespace root that surfaces
as multiple same-handle portions collapse to one handle → promoted.

### 7.2 Namespace-root scope boundary (the pinned contradiction)

`_select_root_package` can only promote a candidate that `find_symbol` actually
returns. A **regular** root package surfaces as its `__init__.py` module → promoted by
clause (2a). A **PEP 420 namespace root with no `__init__.py` anywhere** may not
surface as a `find_symbol` match at all; clause (2b) promotes it **only if** Jedi
surfaces it as a directory-anchored candidate.

Therefore, precisely:

> **Bare-name resolution of a namespace root is best-effort.** If Jedi surfaces the
> namespace package as a candidate, clause (2b) promotes it. If Jedi surfaces nothing
> for the bare name, `resolve("<namespace-name>")` returns **not-found** — and the
> reliable cold-start entry for that package is `resolve("<directory path>")`, which
> already maps a directory → handle (the bootstrap is not missing; see §1). This is a
> deliberate boundary, not a regression: the containment gap #423 fixes is enumerating
> children **once you hold the package handle**, and `resolve(path)` always yields that
> handle.

Net: regular roots resolve unambiguously by bare name; namespace roots resolve by bare
name when Jedi indexes them and otherwise via `resolve(path)`. No code path both
unions and single-dirs the same handle, and no path promotes a non-root same-named
symbol.

## 8. Skill + conformance

- Add `submodules` to the `<!-- pyeye-supported-edges: ... -->` marker in
  `skills/python-explore/SKILL.md`. `tests/test_python_explore_skill_conformance.py`
  asserts that marker set **equals** the live `_IMPLEMENTED_EDGES`, so this line is
  mandatory — the registration and the skill cannot drift.
- Add an edge-table row:
  `submodules | package → child modules/subpackages | one hop; full tree via trace; one-call survey via outline`.
- Add one cold-start workflow line:
  `resolve(root) → outline(pkg) | expand(pkg, "submodules") → drill into a module → inspect / expand members / trace`.

## 9. Test plan

Real on-disk package trees as fixtures (including a no-`__init__.py` namespace dir) —
**not** tmp symlinks (the Jedi-on-macOS-symlink hazard, `feedback_jedi_macos_tmp_symlink`).

1. **Edge resolver:** regular package → direct modules + subpackages as handles;
   non-package handle → `EdgeResult([])`; deterministic sorted order.
2. **PEP 420 namespace package** spanning 2 dirs → union of children;
   **first-portion-wins** on a name collision (assert *which* file wins, tied to
   `roots` order); `roots` built in sys.path-precedence order (assert/comment).
3. **Dir-anchored stub:** survives the full `outline`/`expand` path with **no** byte
   read; `ModuleSentinel(dir).docstring() == ""` and does not raise.
4. **Shallow importable-dir filter:** `__pycache__`/data dirs skipped; one-level
   qualification only (no recursive subtree walk).
5. **`edge_counts`:** for a **regular** package,
   `inspect(pkg).edge_counts.submodules == len(expand(pkg, "submodules").stubs)`;
   absent for non-package modules and non-modules; `0` for an empty package.
   (Namespace packages are out of scope for this equality — see §4 scope note /
   #444 — and the namespace cases here are covered at the enumerator level via a
   `_NameStub`, not through the real `inspect`/`expand` pipeline.)
6. **`trace(follow=["submodules"])`** on a deep package: bounded by `max_nodes`/
   `max_depth` with honest `truncated`/`truncation_reason`.
7. **`outline(pkg)`:** depth-1 default — subpackages `truncated: max_depth`, modules
   are leaves (`children: []`); `outline(module)`/`outline(class)` unchanged (regression).
8. **`resolve`:** bare top-level package → single root handle; deeper same-named symbol
   not promoted; ambiguity preserved when no unique root package; namespace root via
   `resolve(path)` unchanged.
9. **Conformance:** `test_python_explore_skill_conformance.py` passes with `submodules`
   in the marker.

**Validation:** full `uv run pytest --cov=src/pyeye --cov-fail-under=85`; new code
targets >90%.

## 10. Risks & accepted limits

- `dir:1` stubs are not editor-openable (honest, unavoidable for namespace packages).
- Mixed regular+namespace for one dotted name resolves as **regular** (Jedi-classified,
  single dir) — documented, not unioned.
- Bare-name resolution of a Jedi-invisible namespace root returns not-found by design;
  `resolve(path)` is the reliable entry (§7.2).
- Static-surface ceiling unchanged: `submodules` sees packages on disk, not
  runtime-synthesized module objects.

## 11. File-by-file summary

| File | Change |
|---|---|
| `src/pyeye/mcp/operations/edges.py` | `_package_dirs`, `_enumerate_submodule_paths`, `resolve_submodules`; register `submodules` in `_IMPLEMENTED_EDGES` + `EDGE_RESOLVERS` |
| `src/pyeye/analyzers/jedi_analyzer.py` | expose the `added_sys_path` list as a stored attribute (`self.added_sys_path`) so `_package_dirs` builds `roots` from the single path source (§3.4) |
| `src/pyeye/_module_sentinel.py` | confirm/assert dir-anchored docstring contract (`""`, no raise) |
| `src/pyeye/mcp/operations/inspect.py` | `_count_submodules` (delegates to enumerator); wire into `_build_edge_counts` for packages |
| `src/pyeye/mcp/operations/outline.py` | `_child_adjacents`; survey-mode bool; depth-1 default for package roots |
| `src/pyeye/mcp/operations/resolve.py` | `_select_root_package` + `_is_top_level_package`; call before ambiguous fallback |
| `skills/python-explore/SKILL.md` | supported-edge marker + edge-table row + cold-start line |
| `tests/…` | §9 cases |
