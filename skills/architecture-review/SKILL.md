---
name: architecture-review
description: Use when auditing how a Python codebase's architectural conventions diverge — "review the architecture", "audit conventions", "where does this code disagree with itself", "find inconsistent error-handling/layering/validation patterns", "is this package internally consistent". Surfaces a ranked queue of "here are N ways your code does X — you decide", many entries with no recommendation by design. Audits convention DIVERGENCE, not semantic duplication (that is #495). Scope is caller-supplied. Requires the pyeye MCP server.
---

# Architecture Review

Surface and prioritise how a Python codebase's **architectural conventions
diverge from each other**, with cited evidence and honest grades — so a human can
decide which convention to keep. This skill is the single source of truth for
*how* to run the audit; it orchestrates a fresh-context auditor over a supplied
scope and drives the human review loop.

<!-- architecture-review-axes: layering module_boundaries dependency_acquisition error_handling validation_placement naming_api_shape cross_cutting -->

## What This Is (and Is NOT) — Read First

**Honest expectation.** This tool produces a **ranked queue of "here are N ways
your code does X — you decide."** Many entries will carry **no recommendation by
design** (see the honesty invariants). It makes *unknown divergences visible and
ordered by impact* — it does **not** remove the work, and it is emphatically
**not** "the AI cleans up its own mess." You still make the architectural calls;
this just stops you from making them blind.

**Hard scope caveat — divergence, NOT duplication.** This audits **convention
divergence** ("your code does X seven different ways"). It does **NOT** detect
**semantic duplication** ("the same code copy-pasted in many places"). Duplication
is a content-similarity problem this skill structurally cannot do; it is carved
out to issue **#495**. Do not run this expecting duplication detection — you will
not get it.

**Scope is caller-supplied and REQUIRED.** You must hand this a scope — a package,
module, or directory. Bounded-scope auto-iteration over a whole large repo is
**deferred**; this skill audits exactly the scope it is given.

## The Seven Seed Axes

The auditor sweeps (at minimum) these seven convention axes. The keys are the
single source of truth in `pyeye.architecture_review.taxonomy.SEED_AXES`; the
auditor may also surface other axes it finds.

| Axis key | What it covers |
|---|---|
| `layering` | Layering / dependency direction: which layers/packages may import which. |
| `module_boundaries` | Module & placement boundaries: where a *kind* of thing lives. |
| `dependency_acquisition` | Dependency acquisition: constructor-injection vs import vs global/singleton. |
| `error_handling` | Error handling: raise vs return-sentinel vs result-type; exception types; where caught. |
| `validation_placement` | Validation placement: at the boundary vs in core vs scattered. |
| `naming_api_shape` | Naming & API shape: naming patterns, return-type conventions, sync/async split. |
| `cross_cutting` | Cross-cutting access: logging, config, path handling. |

> **Not an axis: code duplication.** Carved out to #495 (see the scope caveat
> above). It never appears as an axis here.

## The Output Contract — Four Grades

Every finding the auditor emits carries exactly one of these four grades, and the
human loop handles **exactly these four states** (there is no fifth branch —
contest signals are deferred):

- `mechanical_fact` — extracted and deterministic; stated as context, no action.
- `deterministic_single` — a single convention the codebase consistently follows
  ("N/N do X"); presented for confirmation with evidence. Survives as
  `deterministic_single` **only** if it passes the promotion chain (step 4).
- `ambiguous` — multiple clusters with no deciding anchor; all clusters surfaced
  with neutral evidence; usually carries **no** recommendation.
- `no_signal` — nothing found on this axis; stated honestly.

**Grade by extraction where mechanical.** For a mechanically-determinable
convention the grade is a *counting fact*, not an LLM label: `N == total` →
`deterministic_single`; a split → `ambiguous`. Judgment is reserved for the
within-axis question "does this divergence matter?", not for grades that fall out
of the count.

## Tool Mechanics Live in `python-explore`

Both this orchestrator and the auditor build their structural model with pyeye
primitives (`resolve` / `inspect` / `outline` / `expand` / `trace` over canonical
handles). **Do not restate the primitives here** — follow the
[`python-explore`](../python-explore/SKILL.md) skill for all tool mechanics,
including its **honest-limits rule**: pyeye has no reverse-reference / caller data
(deferred to #333), so never fake "who calls this" with `grep` or the legacy
`find_references` / `get_call_hierarchy` tools — delegate caller questions to an
LSP, or state the limit. `imported_by` (static importers) is fine and is a primary
signal for the `layering` axis.

## Orchestration — The Seven Steps

Run these in order. The deterministic substrate lives in
`src/pyeye/architecture_review/` and is the authority for every mechanical step;
the orchestrator's job is to wire the steps together and drive the human loop.

### 1. Resolve scope + load baseline and cross-run state

- **Resolve the caller-supplied scope** to a canonical handle (a package, module,
  or directory). Scope is **required** — if the caller gave none, ask for one; do
  not default to the whole repo (auto-iteration is deferred).
- **Load the Tier-3 baseline:** `docs/decisions/DECISIONS.md` plus any existing
  conformance tests / fitness functions. These are the *only* first-strength
  external anchors a recommendation may cite.
- **Load prior cross-run state** with `state.load_state(path)`: prior coverage,
  prior findings, and confirmed non-issues. This is what lets the audit suppress
  things the human already dismissed and carry a per-project axis prior.

### 2. Dispatch the auditor over the scope

Dispatch the fresh-context auditor (`auditor.md`) over the resolved scope, seeding
it with the Tier-3 baseline and the prior cross-run state (so it suppresses
confirmed non-issues and does not re-surface settled forks). The auditor builds a
structural model with pyeye, does targeted reads only, and returns **a JSON array
of graded findings** — nothing else. (Run it as a fresh subagent so its judgment
is uncontaminated by this conversation.)

### 3. Merge into cross-run state

Merge the new findings into prior state with
`state.merge_findings(prior, new)`, which dedups by `state.findings_equivalent`
(same axis + handles + normalised claim). This accumulates coverage across runs
rather than starting cold each time.

### 4. Promotion chain — two stages, in order

A finding keeps `deterministic_single` **only if it passes BOTH** stages. Each
stage can only *downgrade* a grade (to `ambiguous`); neither invents or promotes.

1. **Reproduction gate** —
   `gate.apply_reproduction_gate(findings, redispatch_fn, runs=DEFAULT_GATE_RUNS, equivalent=findings_equivalent)`.
   Each `deterministic_single` candidate is re-dispatched `runs` times
   (`DEFAULT_GATE_RUNS` = 3, configurable) over its scope; it keeps the grade only
   if an equivalent finding appears in **every** re-run, else → `ambiguous`. This
   checks **reproducibility, not truth.**
2. **Cross-derivation guard (#494)** —
   `guard.apply_cross_derivation_guard(findings, corroborate_fn)`. For each
   *surviving* `deterministic_single`, the injected `corroborate_fn`
   **independently re-derives its Tier-1 fact** from source / AST (or an LSP) —
   **NOT** from another pyeye edge and **NOT** from the auditor's own evidence
   (for import / layering facts, wire in `guard.imports_via_ast`, a from-scratch
   stdlib `ast` reader). If the independent derivation diverges from the
   auditor's fact, the guard rewrites the grade to `ambiguous` and sets
   `possible_extractor_bug = True` (surface, do not confirm). This is what catches a
   *reproducibly-wrong* Tier-1 fact (e.g. pyeye's `imports` edge silently dropping
   a real import, #494) — the gate cannot, because a reproducible error reproduces.

Net: `deterministic_single` survives only when **reproduction-stable AND
cross-derivation-corroborated.**

### 5. Rank (ordering only)

Rank the **post-gate** findings with
`ranking.rank(findings, blast_fn, priors=AXIS_STAKES_PRIOR)`: tiered by post-gate
grade, and within a tier by `axis-stakes prior × blast-radius`. The prior is
carried in cross-run state and is **per-project overridable**.

**Show the human the ranking basis verbatim, and offer to reorder:**

> Ranked by axis-stakes prior (validation/error-handling > … > naming) ×
> blast-radius — reorder?

Ranking is **ordering only**: it never drops, suppresses, or recommends. It is a
queue order, not a verdict.

### 6. Human loop — exactly the four output-contract states

Surface the auditor's structured findings **and cited evidence VERBATIM**
(evidence-transparency, spec §5/§9) — do **not** re-narrate, so the human judges
the facts, not your framing. Then, per grade:

- `mechanical_fact` → state it as context. No action.
- `deterministic_single` → "X is universal (N/N), evidence shown — recommend
  codifying. Confirm?" → on confirm, codify (step 7).
- `ambiguous` → surface **ALL** clusters with neutral cited evidence; offer a
  recommendation **only if an external anchor exists** (often there is **none** →
  "no recommendation — you decide"). The human picks/writes the norm, **or** marks
  it a confirmed non-issue.
- `no_signal` → note it honestly.

There is **no fifth branch.** Contest signals are deferred — do not add one.

### 7. Codify (human-gated) and save state

Both paths below are **human-gated** — nothing is codified without explicit
confirmation. Then call `state.save_state(path, state)` so the next run starts
from this point.

#### Dismissal path

Call `state.build_non_issue(finding)` → append the returned `NonIssue` dict to
`state["confirmed_non_issues"]`. Key design: `build_non_issue` sets
`structural_fact = finding["claim"]` and `key = non_issue_key(handles,
structural_fact)`, so:

- Cosmetic source edits that leave the finding's `handles` + `claim` intact keep
  the **same key** — the finding stays suppressed on the next run.
- A genuine structural re-divergence changes the claim/handles the auditor reports →
  **new key** → the finding re-surfaces for human review.

The auditor is seeded with `state["confirmed_non_issues"]` at step 2 so it skips
findings whose `non_issue_key` matches an entry in this list.

#### Positive-norm path (confirmed `deterministic_single`)

Invoke the [`decision-log`](../decision-log/SKILL.md) skill's
**human-gated propose → draft → confirm → append** flow. That skill's rigid gate
applies in full — propose in ONE line; never draft before the user confirms; never
fabricate the date. The entry's `Anchor` must use stable refs (canonical symbol
handles / #issue) — never bare `file:line`; `Verify` must be honestly tiered
(gold / partial / unverifiable).

When drafting the entry, pull evidence and handles from the finding verbatim.
The entry appends to `docs/decisions/DECISIONS.md` (newest on top; create with
the standard header if absent).

**Prefer an executable fitness-function or conformance-test stub** so the norm
becomes a running check (anti-drift, spec §14): the stub lives in `tests/` and
the decision-log entry's `Verify` cites it as a gold assertion. Only if the norm
is non-executable (e.g. a naming convention that resists automated checking) fall
back to an **explicitly-flagged checklist note** in the entry, with `Verify:
unverifiable — <reason>` or `Verify: partial — <checkable part>; <residue> needs
human review`.

## Honesty Invariants — Non-Negotiable

These bind the whole flow (spec §9). They are why most forks correctly produce
**no** recommendation.

- **prevalence ≠ correctness.** Never assert which cluster is correct, *even the
  strict majority*. In an AI-written brownfield the majority pattern may *be* the
  mess. Prevalence is a descriptive fact, never a justification.
- **A recommendation is non-null ONLY with an external anchor** — a documented
  decision / Tier-3 baseline, or a language / stdlib idiom. Import-graph and
  structural facts of *this* codebase are **corroborating only, never sole
  grounds** (deciding on them just re-entrenches the mess). For genuine
  architecture forks the ladder usually yields no anchor → **an absent
  recommendation is the correct output, not a defect.**
- **ranking ≠ correctness.** The axis prior orders the queue; it is never a
  recommendation, is always shown and overridable (never a silent constant), and
  never suppresses a finding.
- **the gate checks reproducibility, not truth.** A reproducibly-wrong Tier-1 fact
  passes the reproduction gate — which is exactly why the cross-derivation guard
  (#494) re-derives the fact independently.
- **grade by extraction where mechanical.** For mechanically-determinable
  conventions the grade falls out of counting, not an LLM label.

## Failure Modes

- **No scope supplied** → ask for one; do not audit the whole repo.
- **pyeye unavailable** → the auditor degrades per `python-explore`'s failure mode
  (note it, fall back to `Read`, warn that structural analysis is reduced).
- **Auditor returns non-JSON** → its output contract is JSON-only; treat any
  surrounding prose as a contract violation and re-dispatch.
- **No LSP for the cross-derivation guard** → derive the Tier-1 fact from a
  targeted source / AST read instead; never skip the guard for a
  `deterministic_single` finding.
