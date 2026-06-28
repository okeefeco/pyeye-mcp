# `/architecture-review` (audit scope, increment A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the convention-divergence auditor (increment A) as a pyeye-plugin skill backed by a deterministic Python substrate, validated by spec `docs/superpowers/specs/2026-06-28-architecture-review-audit-design.md` (rev 10). The spec and this plan are a **synchronized pair** — any scope-changing edit lands in both in the same pass.

**Architecture:** A pyeye-plugin **skill** (`skills/architecture-review/`) does orchestration + judgment via a dispatched **fresh auditor subagent**; the parts that must NOT be LLM-eyeballed — the seed taxonomy + axis-stakes priors, the ranking, and the cross-run state — live in a deterministic Python package (`src/pyeye/architecture_review/`) and are unit-tested. The skill is conformance-bound to the taxonomy the way `python-explore` is bound to the edge registry.

**Tech Stack:** Python 3.10+, `uv`, pytest; pyeye primitives (resolve/outline/inspect/expand) as the Tier-1 fact source; the in-harness LSP for caller-count magnitude (#489); the `decision-log` skill as the codification target.

---

## File structure

- `src/pyeye/architecture_review/__init__.py` — package marker.
- `src/pyeye/architecture_review/taxonomy.py` — the 7 seed axes + provisional axis-stakes prior vector (the single source the conformance test binds to).
- `src/pyeye/architecture_review/ranking.py` — deterministic `rank(findings, blast_fn, priors)` → ordered findings; ordering-only.
- `src/pyeye/architecture_review/state.py` — cross-run cache schema + load/merge/save; coverage-freshness; confirmed-non-issue structural keys.
- `skills/architecture-review/SKILL.md` — methodology, output contract, honesty invariants, orchestration (dispatch → merge → rank → human loop → codify), conformance anchor.
- `skills/architecture-review/auditor.md` — the auditor subagent prompt (taxonomy sweep, grading, honesty rules, finding schema).
- `tests/test_architecture_review_skill_conformance.py` — skill ↔ taxonomy/output-contract drift guard.
- `tests/test_architecture_review_ranking.py` — ranking + ordering-only + proxy-inversion-fix.
- `tests/test_architecture_review_state.py` — cache schema, non-issue invalidation, coverage freshness.

## Shared decisions (pinned — every task honors these verbatim)

- **Finding shape** (dict): `{"axis": str, "claim": str, "grade": str, "handles": list[str], "evidence": str, "recommendation": str | None}`.
- **Grades** (exactly one): `"mechanical_fact" | "deterministic_single" | "ambiguous" | "no_signal"`.
- **Output-contract states** (§8): mechanical-fact (stated), deterministic-single (confirm, evidence shown), ambiguous (clusters + recommendation **only if** an external anchor exists, else `None`), no-signal.
- **7 seed axes** (duplication is NOT one — #495): `layering`, `module_boundaries`, `dependency_acquisition`, `error_handling`, `validation_placement`, `naming_api_shape`, `cross_cutting`.
- **Honesty invariants** (§9): prevalence ≠ correctness (never assert which cluster is correct on `ambiguous`); a `recommendation` is non-null **only** with an external anchor (documented decision / language-stdlib idiom); ranking ≠ correctness (the axis prior is ordering-only, never a recommendation).
- **Confidence model (resolves the gate/grade question):** the §10 gate **rewrites grade** — it downgrades an unstable `deterministic_single` → `ambiguous` (the spec's own wording). So **post-gate `grade` alone encodes confidence**: `ambiguous` = unconfirmed, `deterministic_single`/`mechanical_fact` = confident. There is **no separate `confident` boolean**; ranking (T1.1) and the cross-derivation guard (T3.1) both key on grade.

---

## Phase 0 — Taxonomy + priors (the conformance anchor)

### Task 0.1 — Seed taxonomy + axis-stakes prior as data

- **Goal:** One authoritative, importable definition of the 7 axes and their *provisional* stakes priors, so the skill, ranking, and conformance test all bind to the same source (prevents the #374 drift).
- **Files:** `src/pyeye/architecture_review/__init__.py`, `src/pyeye/architecture_review/taxonomy.py`.
- **Interfaces (produced):**
  - `SEED_AXES: tuple[str, ...]` — exactly the 7 axis keys above, in display order.
  - `AXIS_STAKES_PRIOR: dict[str, float]` — one entry per axis; **provisional** values (calibrate, §15). Constraint: every key in `SEED_AXES` is present; values in `(0, 1]`.
  - `AXIS_DESCRIPTIONS: dict[str, str]` — one-line human description per axis (for the skill + human loop).
- **Tests:** covered by Task 4.1 conformance (keys match `SEED_AXES`, priors complete).
- **Constraints:** Mark `AXIS_STAKES_PRIOR` in a module docstring as a **provisional default to be calibrated against real review data** (§11/§15). Do NOT include `duplication`.
- **Acceptance:** module imports; `set(AXIS_STAKES_PRIOR) == set(SEED_AXES)`; no `duplication` key anywhere.
- **Risks:** Over-tuning the priors now — they are explicitly first-guess; resist precision.

---

## Phase 1 — Deterministic substrate (ranking + state)

### Task 1.1 — Ranking: `axis-stakes prior × blast-radius`, ordering-only

- **Goal:** Make ranking a deterministic, testable function (bet-3 proved agent-eyeballed/blast-alone ranking inverts stakes), enforcing the §11 constraints in code.
- **Files:** `src/pyeye/architecture_review/ranking.py`; test in Task 1.2.
- **Interfaces (consumed):** `AXIS_STAKES_PRIOR` (Task 0.1); a caller-supplied `blast_fn: Callable[[str], float]` mapping a handle → magnitude (so ranking does not itself call pyeye — keeps it pure/testable).
- **Interfaces (produced):**
  - `finding_blast(finding: dict, blast_fn) -> float` — **max** over `finding["handles"]` of `blast_fn(handle)` (the §11 default aggregation; document max can over-rank a finding that merely references a hub).
  - `rank(findings: list[dict], blast_fn, priors: dict[str, float] = AXIS_STAKES_PRIOR) -> list[dict]` — returns a **permutation** of the input. Tier on **post-gate grade**: the *unconfirmed* tier (`grade == "ambiguous"`) sorts **above** the *confident* tier (`grade in {"deterministic_single", "mechanical_fact"}`); `no_signal` sorts last. Within each tier, order by `priors[axis] * finding_blast` descending.
- **Tests (Task 1.2 pins these):** see below.
- **Constraints (CRITICAL):**
  - **Ordering-only:** `rank` MUST return every input finding exactly once (a permutation) — it never drops, filters, or truncates. (A low-stakes axis can never remove a finding from view; §11 constraint 2.)
  - **Tier split is by post-gate grade, not a boolean.** The §10 gate (Task 2.2) has already downgraded unstable `deterministic_single` → `ambiguous`, so grade alone encodes confidence. No separate `confident` flag exists (Shared Decisions).
  - Unknown axis → treat prior as a documented floor (e.g. min prior), never raise (honest degradation).
- **Acceptance:** `sorted(rank(xs)) == sorted(xs)` by identity for any input; documented behavior on ties is stable.
- **Risks:** Tiering on the auditor's *pre-gate* grade — `rank` runs on post-gate grades (after Task 2.2), or unstable findings rank as confident.

### Task 1.2 — Ranking tests (incl. the proxy-inversion fix)

- **Goal:** Lock the behavior bet-3 exposed: axis-prior must rank a high-stakes-leaf finding above a low-stakes-hub finding, and ranking must never suppress.
- **Files:** `tests/test_architecture_review_ranking.py`.
- **Tests (pinned assertions):**
  - *Proxy-inversion fixed:* given a low-stakes finding (`axis="naming_api_shape"`) with high blast and a high-stakes finding (`axis="validation_placement"`) with low blast, `rank` orders the validation finding **before** the naming one. (This is the bet-3 scenario; blast-alone would invert it.)
  - *Ordering-only:* for any findings list, `rank(xs)` is a permutation (same multiset, no drops) — assert length and membership preserved.
  - *Tier precedence:* an `ambiguous` finding sorts before a `deterministic_single` finding even when the latter has higher `prior × blast`.
  - *Override:* passing a custom `priors` that raises `naming_api_shape` flips the first assertion (proves per-project overridability is real).
- **Acceptance:** all pass; `uv run pytest tests/test_architecture_review_ranking.py`.

### Task 1.3 — Cross-run state (cache schema, freshness, non-issue keys)

- **Goal:** The orchestrator-owned durable state that makes "accumulates across runs" real (§6) and stores confirmed non-issues with structural keys that survive cosmetic edits (§14).
- **Files:** `src/pyeye/architecture_review/state.py`; test in Task 1.4.
- **Interfaces (produced):**
  - `load_state(path: Path) -> dict` / `save_state(path: Path, state: dict) -> None` — JSON; missing file → a valid empty state.
  - `state` shape: `{"version": int, "coverage": dict[str, CoverageEntry], "findings": list[dict], "confirmed_non_issues": list[NonIssue]}` where `CoverageEntry = {"last_audited_at": str, "content_hash": str}` and `NonIssue = {"handles": list[str], "structural_fact": str, "key": str}`.
  - `non_issue_key(handles: list[str], structural_fact: str) -> str` — stable key over **sorted handles + the structural fact** (NOT a content hash — §14).
  - `is_stale(entry: CoverageEntry, current_hash: str) -> bool` — true when the unit's structural content changed since `last_audited_at`.
  - `merge_findings(prior: list[dict], new: list[dict]) -> list[dict]` — union deduped by §10 finding-equivalence (handle-set + grade + claim-semantics).
- **Tests:** Task 1.4.
- **Constraints:** `non_issue_key` must be invariant under whitespace/comment/rename-of-unrelated-symbols (keyed on structural fact + handles, §14); timestamps are passed in by the caller (never `Date.now()`-style internal clocks — keeps tests deterministic).
- **Acceptance:** round-trip `save`/`load` is identity; empty-file path yields a valid state.
- **Risks:** Keying non-issues on content hash (the rejected design — re-nags on cosmetic edits).

### Task 1.4 — State tests

- **Files:** `tests/test_architecture_review_state.py`.
- **Tests (pinned):**
  - Non-issue suppression: a dismissed divergence with the same `non_issue_key` is recognized as suppressed; a cosmetic edit (whitespace/comment) to the involved code (same structural fact) keeps the same key (still suppressed); a genuine structural re-divergence (different `structural_fact`) yields a new key (re-surfaces).
  - Coverage freshness: `is_stale` is false right after audit, true after the unit's content hash changes.
  - `merge_findings` dedupes equivalent findings and unions non-equivalent ones.
- **Acceptance:** all pass.

---

## Phase 2 — The skill + auditor (judgment + orchestration)

### Task 2.1 — Auditor subagent prompt

- **Goal:** The fresh-context auditor that sweeps the seed axes over a scope and emits graded findings — the prompt validated across the spike's four runs.
- **Files:** `skills/architecture-review/auditor.md`.
- **Interfaces (produced):** a prompt that, given a scope path, emits **only** a JSON array of findings in the pinned Finding shape, grades per the four grades, and obeys the honesty invariants. It instructs: navigate/scope with pyeye primitives, targeted-Read only spans pyeye points to (the bet-1b fact path), never free-read wholesale at scale.
- **Constraints:** Must encode verbatim: the 7 axes + descriptions (from `AXIS_DESCRIPTIONS`), the grade definitions, "prevalence ≠ correctness — never assert which cluster is correct even if it is the majority", and "recommendation non-null ONLY with an external anchor, else null (null is the expected answer for most forks)". Must NOT mention `duplication` as an axis.
- **Acceptance:** dispatching it over the committed planted-stakes fixture (Task 4.0) reproduces the bets-2+3 behavior: detects the planted divergences, stays neutral on the prevalence-trap, null recommendations on anchorless forks. (Manual/dogfood acceptance — not a unit test.)
- **Risks:** Prompt drift from the taxonomy module → guarded by Task 4.1 conformance.

### Task 2.2 — Reproduction gate (§10) — stage 1 of the confidence promotion chain

- **Goal:** Compute confidence by **reproduction** — the mechanism §10 is named for, on which the entire confident/unconfirmed split rests. A `deterministic_single` from a single auditor pass is only *claimed* confident; the gate confirms it is *stable*. (This is the task that was missing — three tasks consume its output.)
- **Files:** orchestration step in `skills/architecture-review/SKILL.md`; a helper in `src/pyeye/architecture_review/` for the loop + equivalence application; test in this task.
- **Interfaces (consumed):** the **finding-equivalence predicate from `merge_findings` (Task 1.3)** — handle-set + grade + claim-semantics — reused **verbatim**, NOT rebuilt (it is the same equivalence the gate needs); the auditor dispatch (Task 2.1).
- **Interfaces (produced):** for each first-pass `deterministic_single` candidate, **re-dispatch the auditor N=2–3× over its scope**; the candidate **keeps** `deterministic_single` **only if** an equivalent finding appears in **all N** runs, **else its grade is rewritten to `ambiguous`** (§10 "downgraded to ambiguous"). Runs on the **confident-candidate subset only** (cost control), never the whole audit.
- **Tests:** with auditor outputs **mocked** (so the test is deterministic): N identical-equivalent candidate → stays `deterministic_single`; a candidate that differs in ≥1 of the N runs → rewritten to `ambiguous`; non-candidates (already `ambiguous`/`mechanical_fact`/`no_signal`) are untouched and not re-dispatched.
- **Constraints:** N is **provisional** (2–3; §17 discipline — a config value, not a magic constant). The gate **rewrites grade**, it does NOT set a side boolean (Shared Decisions). Equivalence MUST be the Task 1.3 predicate.
- **Acceptance:** mocked-output tests pass; only confident candidates are re-dispatched.
- **Risks:** Re-running the whole audit (cost) instead of the candidate subset; rebuilding equivalence instead of reusing `merge_findings`'s.

### Task 2.3 — SKILL.md: orchestration, output contract, human loop

- **Goal:** The shipped skill that drives the whole flow and is the single source of truth for *how* to audit (conformance-bound like `python-explore`).
- **Files:** `skills/architecture-review/SKILL.md`.
- **Interfaces (produced):** documented orchestration steps — (1) load Tier-3 baseline + cross-run state; (2) dispatch the auditor (Task 2.1) over the **supplied scope**; (3) merge into state (`merge_findings`); (4) **promotion chain** — run the reproduction gate (Task 2.2) **then** the cross-derivation guard (Task 3.1): a finding keeps `deterministic_single` only if reproduction-stable **and** cross-derivation-corroborated, else rewritten to `ambiguous`; (5) **rank** (Task 1.1, on post-gate grades) showing the prior + offering reorder; (6) human loop per the four output-contract states; (7) codify (Task 3.2).
- **Constraints:** Embed the `<!-- architecture-review-axes: ... -->` conformance anchor listing the 7 axes (Task 4.1 binds to it). Carry the honest-expectation + hard scope caveat from spec §2 (A does convention divergence, NOT duplication — that's #495). Scope is **caller-supplied** (bounded-scope auto-iteration over large repos is deferred, §15). State that grade for mechanically-determinable conventions comes from extraction, not an LLM label (§8). The human loop handles **exactly the four output-contract states** (contest signals are deferred, §15 — do not add a fifth branch).
- **Acceptance:** conformance test (4.1) passes; a human reading it can run the flow end-to-end.
- **Risks:** Restating tool mechanics that belong in `python-explore` — reference, don't duplicate.

---

## Phase 3 — The #494 guard + codification

### Task 3.1 — Cross-derivation guard (REQUIRED — spec §9) — stage 2 of the promotion chain

- **Goal:** Turn #494's lesson into a mechanism: a reproducibly-wrong Tier-1 fact must not pass as `deterministic_single`. Runs **after** the Task 2.2 reproduction gate (a finding can be reproduction-stable yet stably-wrong — that is exactly #494).
- **Files:** orchestration step in `skills/architecture-review/SKILL.md`; optional helper in `src/pyeye/architecture_review/` if a structured comparison helps.
- **Interfaces (produced):** for every **post-gate `deterministic_single`** finding (the survivors of Task 2.2), **independently re-derive** its underlying Tier-1 fact (see the independence constraint) and compare; on divergence, **rewrite grade to `ambiguous` and flag `possible_extractor_bug`** (surface, do not confirm).
- **Tests:** acceptance fixture — a finding whose pyeye-derived fact is known to diverge from source (e.g. the #494 `imports`-edge drop) is flagged + downgraded, not confirmed. The test must confirm the corroboration is computed from an **independent** source (source/AST or LSP), not from the auditor's stored `evidence` or the same pyeye edge.
- **Constraints:**
  - **Independence is the whole point** (without it the guard is theater). The corroborating derivation MUST be independent of the pyeye edge that produced the fact: re-derive from **source text / AST** (a fresh read of the relevant span) or the **LSP**, then compare. **Never** corroborate a pyeye fact with another pyeye primitive that could inherit the same defect, and **never** reuse the auditor's own `evidence` field — that is checking a thing against itself. #494 was caught *precisely because* a source-AST read of the import statements disagreed with the suspect `imports` edge; a same-source cross-check would have passed the wrong fact.
  - Runs **only on the confident subset** (cheap). This is a **plan acceptance item**, not optional (spec §9).
- **Acceptance:** the #494-style divergence fixture is flagged; a non-divergent confident finding passes untouched.
- **Risks:** Skipping it as "a footnote" — it is the only guard against the gate's reproducibility-not-truth blind spot.

### Task 3.2 — Codification path (positive norms + confirmed non-issues)

- **Goal:** A human-confirmed norm becomes a `decision-log` entry (+ optional fitness-function stub); a dismissal becomes a structurally-keyed non-issue (Task 1.3).
- **Files:** orchestration step in `SKILL.md`; reuse the `decision-log` skill.
- **Interfaces (consumed):** `non_issue_key` (Task 1.3); the `decision-log` skill's entry format.
- **Constraints:** Promotion Tier-2→Tier-3 and any non-issue write are **human-gated** (§9). Positive norm → prefer an executable fitness-function/conformance-test stub; non-executable residual → an explicitly-flagged checklist note (§14 anti-drift, qualified).
- **Acceptance:** confirming a norm produces a well-formed `decision-log` entry; dismissing produces a non-issue with a correct structural key.
- **Risks:** Auto-codifying without the human gate.

---

## Phase 4 — Fixture + conformance + dogfood validation

### Task 4.0 — Promote the planted-stakes fixture into the repo

- **Goal:** The fixture backs Task 2.1's and Task 4.2's acceptance and the whole §13 go/no-go, so it must be a committed, version-controlled asset — not an ephemeral scratch path.
- **Files:** `tests/fixtures/architecture_review/app/…` (the deliberately-messy package) + `tests/fixtures/architecture_review/GROUND_TRUTH.md` (the stakes/blast oracle, **outside** the audited `app/` subtree).
- **Interfaces (produced):** the fixture mirrors the spike design — planted divergences with known stakes + blast: prevalence-trap error-handling (majority swallow vs minority propagate); high-stakes validation-placement on a **leaf**; low-stakes naming on a **hub**; module-global dependency-acquisition; an ambiguous result-shape fork (no anchor). `GROUND_TRUTH.md` records each plant's axis / stakes / blast / expected behavior (incl. the proxy-inversion pair and the empty-recommendation fork).
- **Constraints:** the fixture is **intentionally lint/security-dirty** (bare `except`, unused vars) — **exclude `tests/fixtures/architecture_review/` from ruff / bandit / coverage** in the relevant config (or scoped `# noqa`/`# nosec`) so pre-commit does not fight it. **Build it from this task's Interfaces block + the bets-2+3 spike log on [#492](https://github.com/okeefeco/pyeye-mcp/issues/492)** — the plants (axes, stakes, blast, the proxy-inversion pair, the empty-recommendation fork) are fully specified there. Do **not** depend on any session scratchpad path (the spike's seed was session-local and is gone).
- **Acceptance:** fixture committed; pre-commit green; `GROUND_TRUTH.md` present and out of `app/`.
- **Risks:** Pre-commit rejecting the deliberately-bad code → handle via the exclusions above.

### Task 4.1 — Skill ↔ taxonomy conformance test

- **Goal:** Anti-drift guard (the #374 defense), modeled on `tests/test_python_explore_skill_conformance.py`.
- **Files:** `tests/test_architecture_review_skill_conformance.py`.
- **Tests (pinned):**
  - The `<!-- architecture-review-axes: ... -->` anchor in `SKILL.md` equals `set(SEED_AXES)`.
  - `auditor.md` mentions every axis in `SEED_AXES` and mentions **no** axis named `duplication`.
  - The four output-contract grades appear in `SKILL.md`.
  - `set(AXIS_STAKES_PRIOR) == set(SEED_AXES)`.
- **Acceptance:** `uv run pytest tests/test_architecture_review_skill_conformance.py` passes; full suite `uv run pytest --cov=src/pyeye --cov-fail-under=85` stays green.

### Task 4.2 — Dogfood + value metric (go/no-go evidence, §13)

- **Goal:** Run the end-to-end skill over the committed planted-stakes fixture (Task 4.0) (and pyeye itself as tidy control) and record the **value metric**, not raw yield.
- **Files:** none shipped — a recorded result (comment on #492 / a notes file).
- **Acceptance (report, not pass/fail):** detection of planted high-stakes findings; their **ranking position** (validation/error-handling above naming after the axis-prior fix); prevalence-trap neutrality; null recommendations on anchorless forks; confident-path cross-derivation flags a planted divergence. Report the §10 confounds (consensus, nomination, selection) alongside.
- **Constraints:** Raw confident-path yield is **descriptive only** — near-zero on messy code is expected, not a kill (§13).
- **Risks:** Treating raw yield as the success metric (the §13 trap).

---

## Notes for the implementer

- **Provisional values stay provisional:** `AXIS_STAKES_PRIOR` defaults and any thresholds are first guesses to calibrate against real runs (§11/§15) — do not present them as validated.
- **pyeye build-notes (spike):** read `async`-ness via `inspect` (not `outline`); pass dotted handles (file-path handles to `outline` return junk); the `imports` edge can silently drop a real import (#494) — the Task 3.1 guard exists because of this; do not treat the edge as exhaustive for layering blast.
- **Tests required** per project rules (≥85% coverage; run the full suite before pushing).
