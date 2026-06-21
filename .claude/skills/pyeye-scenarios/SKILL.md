---
name: pyeye-scenarios
description: Use when provisioning a real-world dogfooding scenario to verify pyeye against — cross-repo / namespace / single-tree codebases at pinned commits. Triggers on "set up a dogfooding scenario", "provision the jaraco/django scenario", "stand up a namespace scenario for pyeye", "what scenarios do we have". This is the DATA layer (catalog + pins + baselines); the procedure that runs against it lives in the pyeye-verify skill. Does NOT trigger for ordinary code navigation (use python-explore) or for running the verification pass itself (use pyeye-verify).
---

# pyeye Scenarios

The **catalog of real-world codebases** we provision to dogfood and verify pyeye, each
pinned to a commit so its recorded baseline stays meaningful. This skill is the *data*:
which repos, at which commits, how they're laid out, the `.pyeye.json` that wires them,
the probe suite, and the expected baseline. The *procedure* that runs the probes and
judges the results lives in **[[pyeye-verify]]**.

**Announce at start:** "Using the pyeye-scenarios skill to provision `<scenario>`."

## Why scenarios exist

Different codebase shapes stress different pyeye capabilities. One target (a single tree)
can't exercise cross-repo resolution, namespace stitching, or the namespace cold-start
path. The catalog is the **axis of variation**:

| Scenario | Shape | Stresses | Provision |
|----------|-------|----------|-----------|
| `django` | single tree | depth, scale, canonical-handle collapse, `imported_by`/`superclasses`, static-surface ceiling, honest-limit refusal | clone (heavy — use `--reference`) |
| `namespace-jaraco` | 3 repos, PEP 420 namespace | namespace stitching via `.pyeye.json`, cross-repo `resolve`/`trace`, #444 cold-start | clone 3 small repos |
| `zope` *(planned)* | 2 repos, PEP 420 namespace | deep inheritance + dense cross-import graphs | — |
| `google-cloud` *(planned)* | monorepo, many dists | scale + 3-segment namespaces | — |

## Conventions (apply to every scenario)

- **Target dir is an in-repo, gitignored dir — never a machine-global path.** The default
  is `<current-worktree-root>/.scenario-repos/`, resolved with
  `git rev-parse --show-toplevel` so it follows you **into a worktree** automatically
  (each worktree gets its own isolated clones, removed when the worktree is). Overridable
  with `PYEYE_SCENARIO_DIR`. The `.pyeye.json` paths are relative, so the scenario's
  siblings just need this common parent. (`.scenario-repos/` is in the repo's
  `.gitignore`; do NOT hardcode a personal path like `~/GitHub/test` — it isn't portable
  and shared external clones collide across worktrees.)
- **Pin commits.** A recorded baseline is only meaningful against fixed source. Each
  scenario lists exact SHAs.
- **Full clone, not `--depth 1`.** A shallow clone cannot check out an arbitrary pinned
  SHA. The jaraco repos are ~350 KB each (free), so a per-worktree clone is trivial.
  django is ~366 MB — to avoid re-downloading it per worktree, clone with
  `--reference <shared-django>` (borrows objects from an existing local clone; the
  per-worktree copy is tiny on disk yet can still check out the pinned SHA), or point
  `PYEYE_SCENARIO_DIR` at a shared cache for that scenario.
- **Idempotent.** Skip a repo that already exists; never re-clone over local work.
- **Never vendor.** Third-party code is cloned on demand and **never committed** — a
  gitignored in-repo dir is never in git history, so "in the worktree" ≠ "vendored." The
  convention is about git history, not disk presence.

## Generic provision procedure

For each repo in a scenario's manifest:

```bash
# In-repo, gitignored, worktree-local by default (override with PYEYE_SCENARIO_DIR).
TARGET="${PYEYE_SCENARIO_DIR:-$(git rev-parse --show-toplevel)/.scenario-repos}"
mkdir -p "$TARGET"
cd "$TARGET"
[ -d "<repo>" ] || git clone "<url>" "<repo>"   # idempotent, full clone
                                                # (heavy repos: add --reference <shared-clone>)
git -C "<repo>" fetch --quiet origin <commit>
git -C "<repo>" checkout --quiet <commit>
```

Then write the scenario's `.pyeye.json` into its `root` repo (if it declares one), and
hand off to **[[pyeye-verify]]** to run the probe suite.

---

## Scenario: `django`

Single source tree — the depth/scale baseline. No `.pyeye.json`, no namespace.

### Manifest

| Field | Value |
|-------|-------|
| repo | `https://github.com/django/django` |
| commit | `cd385e6b8c` |
| size | ~366 MB — clone with **`--reference <shared-django>`** (or set `PYEYE_SCENARIO_DIR` to a shared cache) to avoid a full per-worktree download |
| `project_path` | `<TARGET>/django` |
| root / `.pyeye.json` | none |

### Probe suite + recorded baseline *(captured 2026-06-22, build `dev416+g406783dd6` = main incl. #458; re-verified unchanged vs the 2026-06-21 global-server capture except row 5's `report_issues` key)*

| # | Probe | Expected (baseline) | Demonstrates |
|---|-------|---------------------|--------------|
| 1 | `resolve("django.db.models.Model")` | `handle: django.db.models.base.Model`, `kind:class`, `scope:project`, `base.py:501` | **canonical-handle collapse** — the re-export resolves to its definition site |
| 2 | `inspect("django.db.models.Model")` | `superclasses:["…utils.AltersData"]`, `signature:"Model()"`, `edge_counts:{members:68, superclasses:1}`, `re_exports:["…operations.fields.Model"]`; **no `callers`/`references` key** | **absence-vs-zero** (no caller key) + **static-surface ceiling** (`members:68` omits metaclass-injected `_meta`/`objects`/`DoesNotExist`) |
| 3 | `expand("django.db.models.Model", "superclasses")` | one stub: `django.db.models.utils.AltersData` | matches `edge_counts.superclasses` |
| 4 | `expand("django.core.signing", "imported_by")` | 10 module stubs incl. `django.http.request`, `django.contrib.sessions.backends.base`, and `tests.*` | reverse-static import graph (deterministic) |
| 5 | `expand("django.db.models.Model", "callers")` | `unsupported, reason:"deferred_reference_backend"` (#333), plus a `report_issues` URL (**#458**, PR #460) | **honest-limit refusal** — not faked, not empty; refusal now carries the in-band report path |

> Probe 2's `members:68` is a count of *statically written* members. Reporting it as
> "Model's complete attribute set" would be wrong — `_meta`, `objects`, `DoesNotExist`
> are metaclass-injected and invisible to static analysis. The verify rubric treats
> mislabelling a static count as runtime-exhaustive as a FAIL.

---

## Scenario: `namespace-jaraco`

Three small modern repos sharing the PEP 420 `jaraco` namespace (each `jaraco/<subpkg>/`
with **no** `jaraco/__init__.py`), with real cross-repo imports.

### Manifest

| repo | commit | note |
|------|--------|------|
| `jaraco.text` | `1683d5a` | **root** — gets `.pyeye.json`; imports the other two |
| `jaraco.functools` | `0e89d96` | tagged v4.5.0 |
| `jaraco.context` | `bfcb95c` | |

- url pattern: `https://github.com/jaraco/<repo>`
- `project_path`: `<TARGET>/jaraco.text`
- layout: all three siblings under `<TARGET>/`

**`.pyeye.json`** (write into `jaraco.text`):

```json
{ "namespaces": { "jaraco": ["../jaraco.functools", "../jaraco.context"] } }
```

The real cross-repo imports the probes lean on live at
`jaraco.text/jaraco/text/__init__.py:23-24`:

```python
from jaraco.context import ExceptionTrap            # -> ../jaraco.context
from jaraco.functools import compose, method_cache  # -> ../jaraco.functools
```

### Probe suite + recorded baseline *(captured 2026-06-22, build `dev416+g406783dd6` = main incl. #423/#444/#454, `project_path = .../jaraco.text`)*

| # | Probe | Expected (baseline) | Demonstrates / tracking |
|---|-------|---------------------|-------------------------|
| 1 | `resolve("jaraco.context.ExceptionTrap")` | `kind:class`, `scope:project`, file in `../jaraco.context` | ✅ **cross-repo resolution** — sibling repo resolves as project |
| 2 | `expand("jaraco.text", "imports")` (and `trace(... ["imports"])`) | the three `jaraco.*` targets (`context.ExceptionTrap`, `functools.compose`, `functools.method_cache`) report **`scope:project`**; stdlib targets stay `external` | ✅ **cross-repo edge scope** — **#454** (edges agree with `resolve`) |
| 3 | `resolve("jaraco")` | `kind:module`, `scope:project`, anchored at `jaraco.text/jaraco` | ✅ **#444** namespace cold-start anchoring |
| 4 | `inspect("jaraco")` | `is_package:true`, `edge_counts:{members:0, submodules:3}` | ✅ **#444 / #423** |
| 5 | `outline("jaraco")` | `module`/`project` with 3 submodule children (`context`, `functools`, `text`; `text` `truncated:max_depth`) | ✅ **#444 / #423** depth-1 survey |
| 6 | `resolve("jaraco.text")` (child contrast) | `kind:module`, `scope:project` | ✅ child handle resolves |
| 7 | `expand("jaraco", "submodules")` | 3 stubs: `jaraco.context`, `jaraco.functools`, `jaraco.text` (all `project`) | ✅ **#423 / #444** namespace union across sibling repos |

Rows 2–5 + 7 are the **#423 / #444 / #454** acceptance check, and now pass. Against the
*earlier* stale build (the 2026-06-21 global server, pre-#423/#444/#454) row 2's `jaraco.*`
edges came back `external`, `resolve("jaraco")` was ambiguous-external (`kind:variable`,
`file:""`), `inspect`/`outline` were empty, and `submodules` was unknown/empty — so this
scenario doubles as the regression guard for all three fixes.

> ⚠️ **Baselines are build-tagged.** The table above was captured against an up-to-date
> build (`dev416+g406783dd6`, main incl. #423/#444/#454) on 2026-06-22. An earlier capture
> against the stale globally-installed server (2026-06-21) showed the pre-fix behaviour —
> `jaraco.*` import edges `external`, `resolve("jaraco")` ambiguous, `submodules`
> unknown/empty. Same probes, different build: that divergence is the
> regression-vs-environment **signal**, not a bug. Always re-record against the build under
> test and note which build (see the `pyeye-verify` classification).

---

## Adding a scenario

1. Pick a real repo (or repos) that stresses a shape the catalog doesn't cover yet.
2. Add a manifest block: repos + **pinned SHAs**, `project_path`, `root`/`.pyeye.json`.
3. Provision it, then capture its probe suite + baseline via **[[pyeye-verify]]** and
   paste the recorded table here, each row tagged with the build it was captured on and
   tied to an issue where the result is a known gap.
4. Keep it declarative — commands and pinned data only, no hand-listed "current files".
