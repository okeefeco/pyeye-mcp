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
| `multirepo-namespace` | 3 repos + main project, PEP 420 namespace, **in-repo** | namespaces outside the project root (src/ layout, flat, via `packages`), root-is-package project, cross-repo subclass/calls/re-export/alias/`TYPE_CHECKING`/lazy import, name collision | **local copy, no clone** (#667) |
| `zope` *(planned)* | 2 repos, PEP 420 namespace | deep inheritance + dense cross-import graphs | — |
| `google-cloud` *(planned)* | monorepo, many dists | scale + 3-segment namespaces | — |

## Conventions (apply to every scenario)

- **Target dir is an in-repo, gitignored dir — never a machine-global path.** The default
  is `<current-worktree-root>/.scenario-repos/`, resolved with
  `git rev-parse --show-toplevel` so it follows you **into a worktree** automatically
  (each worktree gets its own isolated clones, removed when the worktree is). Overridable
  with `SCENARIO_DIR`. The `.pyeye.json` paths are relative, so the scenario's
  siblings just need this common parent. (`.scenario-repos/` is in the repo's
  `.gitignore`; do NOT hardcode a personal path like `~/GitHub/test` — it isn't portable
  and shared external clones collide across worktrees.)
  pyeye's own project scan skips a nested clone (its `.git` is a directory, #810), so
  clones here don't pollute pyeye-on-pyeye analysis.
- **Pin commits.** A recorded baseline is only meaningful against fixed source. Each
  scenario lists exact SHAs.
- **Full clone, not `--depth 1`.** A shallow clone cannot check out an arbitrary pinned
  SHA. The jaraco repos are small, so a per-worktree clone is trivial.
  django is large: to avoid re-downloading it per worktree, clone with
  `--reference <shared-django>` (borrows objects from an existing local clone; the
  per-worktree copy is tiny on disk yet can still check out the pinned SHA), or point
  `SCENARIO_DIR` at a shared cache for that scenario.
- **Idempotent.** Skip a repo that already exists; never re-clone over local work.
- **Never vendor.** Third-party code is cloned on demand and **never committed** — a
  gitignored in-repo dir is never in git history, so "in the worktree" ≠ "vendored." The
  convention is about git history, not disk presence.

## Generic provision procedure

For each repo in a scenario's manifest:

```bash
# In-repo, gitignored, worktree-local by default (override with SCENARIO_DIR).
TARGET="${SCENARIO_DIR:-$(git rev-parse --show-toplevel)/.scenario-repos}"
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
| size | large — clone with **`--reference <shared-django>`** (or set `SCENARIO_DIR` to a shared cache) to avoid a full per-worktree download |
| `project_path` | `<TARGET>/django` |
| root / `.pyeye.json` | none |

### Probe suite + recorded baseline

The probe suite and its expected results, the round-trip probe, the timings and the tripwire are in the dated record [`baselines/django.md`](baselines/django.md). Run it with **[[pyeye-verify]]**; record a new baseline as a new record, never by editing an old one.

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

### Probe suite + recorded baseline

The probe suite and its expected results, and the round-trip probe (both predate #623 and #712: re-capture before relying on exact values) are in the dated record [`baselines/namespace-jaraco.md`](baselines/namespace-jaraco.md). Run it with **[[pyeye-verify]]**; record a new baseline as a new record, never by editing an old one.

---

## Scenario: `multirepo-namespace` (local, #667)

A synthetic multi-repo workspace that lives **in this repo**, so it needs no network and
runs in CI (`tests/test_cross_tool_invariants.py` corpus `multirepo_namespace`, plus
`tests/integration/test_multirepo_namespace_scenario.py`, which pins the expected handles
and scope). Use it here for an offline [[pyeye-verify]] pass. Layout and the relationships
it exercises: `tests/fixtures/scenarios/multirepo_namespace/README.md`.

### Manifest

| Field | Value |
|-------|-------|
| source | `tests/fixtures/scenarios/multirepo_namespace/` (in-repo; nothing to pin, the commit under test is the pin) |
| provision | copy, never use in place: `cp -r tests/fixtures/scenarios/multirepo_namespace "$TARGET/"` |
| `project_path` | `<TARGET>/multirepo_namespace/app` |
| `.pyeye.json` | already in `app/`: `namespaces.corp = ["../corp-core/src", "../corp-web"]`, `packages = ["../corp-tools"]` |

### Probe suite + recorded baseline

The probe suite and its expected results are in the dated record [`baselines/multirepo-namespace.md`](baselines/multirepo-namespace.md). Run it with **[[pyeye-verify]]**; record a new baseline as a new record, never by editing an old one.

---

## Adding a scenario

1. Pick a real repo (or repos) that stresses a shape the catalog doesn't cover yet.
2. Add a manifest block: repos + **pinned SHAs**, `project_path`, `root`/`.pyeye.json`.
3. Provision it, then capture its probe suite + baseline via **[[pyeye-verify]]** and
   write it as a record, `baselines/<scenario>.md`, with `date`, `command`, `commit` and
   `machine` front matter, each row tagged with the build it was captured on and tied
   to an issue where the result is a known gap. Register the file as a `record` and link
   it from the scenario.
4. Keep it declarative — commands and pinned data only, no hand-listed "current files".
