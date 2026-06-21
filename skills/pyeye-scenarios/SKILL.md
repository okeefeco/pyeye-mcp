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
| `django` | single tree | depth, scale, canonical-handle collapse, `imported_by`/`superclasses`, static-surface ceiling, honest-limit refusal | reuse existing clone |
| `namespace-jaraco` | 3 repos, PEP 420 namespace | namespace stitching via `.pyeye.json`, cross-repo `resolve`/`trace`, #444 cold-start | clone 3 small repos |
| `zope` *(planned)* | 2 repos, PEP 420 namespace | deep inheritance + dense cross-import graphs | — |
| `google-cloud` *(planned)* | monorepo, many dists | scale + 3-segment namespaces | — |

## Conventions (apply to every scenario)

- **Target dir is a parameter** — default `~/GitHub/test/` (matches the existing django
  convention). Substitute freely; the `.pyeye.json` paths are relative so siblings just
  need a common parent.
- **Pin commits.** A recorded baseline is only meaningful against fixed source. Each
  scenario lists exact SHAs.
- **Full clone, not `--depth 1`.** A shallow clone cannot check out an arbitrary pinned
  SHA. The jaraco repos are ~350 KB each (free); django is ~366 MB (reuse it).
- **Idempotent.** Skip a repo that already exists; never re-clone over local work.
- **Never vendor.** Third-party code is cloned on demand, never committed into this repo —
  same as django is today.

## Generic provision procedure

For each repo in a scenario's manifest:

```bash
TARGET="${TARGET:-$HOME/GitHub/test}"        # parameter
cd "$TARGET"
[ -d "<repo>" ] || git clone "<url>" "<repo>"   # idempotent, full clone
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
| size | ~366 MB — **reuse the existing `~/GitHub/test/django`**, don't re-clone |
| `project_path` | `<TARGET>/django` |
| root / `.pyeye.json` | none |

### Probe suite + recorded baseline *(captured 2026-06-21, global server)*

| # | Probe | Expected (baseline) | Demonstrates |
|---|-------|---------------------|--------------|
| 1 | `resolve("django.db.models.Model")` | `handle: django.db.models.base.Model`, `kind:class`, `scope:project`, `base.py:501` | **canonical-handle collapse** — the re-export resolves to its definition site |
| 2 | `inspect("django.db.models.Model")` | `superclasses:["…utils.AltersData"]`, `signature:"Model()"`, `edge_counts:{members:68, superclasses:1}`, `re_exports:["…operations.fields.Model"]`; **no `callers`/`references` key** | **absence-vs-zero** (no caller key) + **static-surface ceiling** (`members:68` omits metaclass-injected `_meta`/`objects`/`DoesNotExist`) |
| 3 | `expand("django.db.models.Model", "superclasses")` | one stub: `django.db.models.utils.AltersData` | matches `edge_counts.superclasses` |
| 4 | `expand("django.core.signing", "imported_by")` | 10 module stubs incl. `django.http.request`, `django.contrib.sessions.backends.base`, and `tests.*` | reverse-static import graph (deterministic) |
| 5 | `expand("django.db.models.Model", "callers")` | `unsupported, reason:"deferred_reference_backend"` (#333) | **honest-limit refusal** — not faked, not empty |

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

### Probe suite + recorded baseline *(captured 2026-06-21, global server, `project_path = .../jaraco.text`)*

| # | Probe | Expected (baseline) | Demonstrates / tracking |
|---|-------|---------------------|-------------------------|
| 1 | `resolve("jaraco.context.ExceptionTrap")` | `kind:class`, `scope:project`, file in `../jaraco.context` | ✅ **cross-repo resolution** — sibling repo resolves as project |
| 2 | `trace("jaraco.text", follow=["imports"])` | edges cross into `jaraco.context.*` and `jaraco.functools.*` with full signatures | ✅ **cross-repo trace** |
| 3 | `resolve("jaraco")` | `ambiguous:true`, 2× `scope:external` (`namespace`+`module`), `file:""` | ❌ expect a project-scoped handle — **#444** |
| 4 | `inspect("jaraco")` | `kind:"variable"`, `scope:"external"`, `edge_counts:{}` | ❌ **#444** |
| 5 | `outline("jaraco")` | `kind:"variable"`, `children:[]` | ❌ **#444** |
| 6 | `resolve("jaraco.text")` (child contrast) | `kind:module`, `scope:project` | ✅ confirms "must already know a child handle" |
| 7 | `expand("jaraco", "submodules")` | `unsupported / unknown_edge` **on the global server** | the `submodules` edge ships only in the **#423 / PR #443** delivery worktree (unmerged) — re-baseline from that worktree, where rows 3–5 + this should improve |

Rows 3–5 + 7 are the live **#444 / #423** acceptance check: run this scenario against a
build that fixes them and the ❌ rows should flip to project-scoped handles with a
populated `submodules` survey.

> ⚠️ **Baselines are environment-tagged.** The tables above were captured against the
> globally-installed pyeye server on 2026-06-21. A build under active delivery (e.g. the
> PR #443 worktree) legitimately differs — that divergence is the *signal*, not a
> regression. Always re-record against the build under test and note which build.

---

## Adding a scenario

1. Pick a real repo (or repos) that stresses a shape the catalog doesn't cover yet.
2. Add a manifest block: repos + **pinned SHAs**, `project_path`, `root`/`.pyeye.json`.
3. Provision it, then capture its probe suite + baseline via **[[pyeye-verify]]** and
   paste the recorded table here, each row tagged with the build it was captured on and
   tied to an issue where the result is a known gap.
4. Keep it declarative — commands and pinned data only, no hand-listed "current files".
