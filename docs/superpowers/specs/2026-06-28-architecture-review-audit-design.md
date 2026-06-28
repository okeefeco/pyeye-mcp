# `/architecture-review` (audit scope) — Design Spec

**Status:** Draft (rev 10 — gate-task gap closed in plan; contest + bounded-scope deferred;
stale §6 cell fixed) — **UNCOMMITTED** in the `feat/492-architecture-review-audit` worktree
(rev 9 committed at `6471f22`); to be committed on that branch.
**Date:** 2026-06-28
**Issue:** #492
**Scope:** Increment **A** (project/audit scope). Diff-mode (B), the self-learning loop,
blocking/CI, a queryable fact store, and norm revision/retirement are deferred (see §15).

---

## 1. Problem & motivation

A human governs *direction / architecture / design* and lets the AI write the code; the AI
produces **working but architecturally-wrong** code — duplicated logic, ignored or unknown
patterns — creating a maintenance mess. Working code is verifiable against tests;
*architecturally-correct* code is only verifiable against a stated norm, and those norms are
usually **undocumented**, living implicitly in the codebase.

Naive self-review fails for two reasons: (1) **circularity** — *the same model with the same
weight-level blind spots reproduces and rationalises them*; (2) **prose norms are advisory**
— ignored under delegation pressure.

## 2. The larger vision & where this sits

Sub-project #1 of a five-layer governance system: **Facts → Norms → Checks → Review →
Derived docs**. This spec is the foundation: an **evolutionary fact-gathering** engine that
audits an existing codebase, infers the de-facto architecture, surfaces where the code
already disagrees with itself, and feeds a **human-gated** knowledge base later layers consume.

**Honest expectation.** On the brownfield this targets, the felt experience is a **ranked
queue of "here are N ways your code does X — you decide,"** many entries with no recommendation
by design (§9). A **surfaces and prioritises** the work; it does **not** remove it. The value
is real — unknown divergences made visible and ordered by impact — and the §6.5 seed taxonomy
is what keeps that queue **coherent run-to-run** instead of shifting under the user. Whoever
builds this should hold that expectation, not "the AI cleans up its own mess."

**Hard scope caveat.** A addresses *convention divergence*, **not** the duplication pain ("the
same code written in many places") that partly motivated this work. Semantic duplication is a
content-similarity problem A structurally cannot do (spike bet-1b; §3) and is tracked
separately as **#495**. A user who runs A expecting the duplication problem solved will get
conventions — state that up front.

## 3. Goals / Non-goals

**Goals (A):** audit a whole Python project; extract mechanical facts + infer observed
conventions; detect deviations honestly; drive a human-in-the-loop that codifies confirmed
norms *and* records confirmed non-issues; accumulate across runs.

**Non-goals (deferred):** per-diff gate (B); blocking/CI enforcement; a queryable structured
fact store; auto-codification; norm revision/retirement workflow; non-Python.

**Explicit limit — A does not detect semantic duplication.** A detects *convention divergence*
(a relationship over structural facts); it **structurally cannot** detect semantic duplication
("these two bodies are near-identical"), a content-similarity computation pyeye ships nothing
for by design. Spike bet-1b confirmed this empirically: free-reading found 5 cross-module
duplications, the fact-grounded pipeline found ~1. Duplication is a *different epistemic object*
with a different honesty profile (a near-dup score is a tunable threshold — a graded judgment,
not a fact, so it must never enter the Tier-1 substrate) and is handled by a **separate
similarity engine, #495** — not by A. (This replaces the earlier, now-falsified claim that the
auditor would surface duplication by reading code over pyeye facts.)

## 4. Conceptual grounding

- **Fact states.** Three positive tiers plus one negative:
  1. **Mechanical** — extracted and deterministic, **trustworthy modulo extractor bugs** (NOT
     "never wrong" — see §9: a stable-but-wrong fact reproduces perfectly and is not caught by
     the §10 gate; spike #494 found exactly this). Re-derived each run; never stored as source
     of truth.
  2. **Observed** — inferred, prevalence-tagged, **advisory**. Candidate; persisted as
     disposable cross-run state.
  3. **Confirmed (positive)** — human-anchored / fitness-function-enforced. Authoritative; the
     only tier that may later (in B) block.
  - **Confirmed non-issue (negative)** — human-confirmed "this divergence is intentional
     here." Persisted, structurally keyed, suppresses re-surfacing until the underlying
     structure changes (§6, §14). Without this, "default to flagging" on a brownfield re-nags
     every run and defeats the scarce-attention thesis.
- **Data-engine / active-learning flywheel** (Karpathy's Autopilot data engine): automate the
  confident cases, **escalate only the uncertain ones**, accumulate labels (positive *and*
  negative), improve each run. Human attention is prioritised by tier then blast radius (§11).
- **Symbolic, not weights — and it's a feature.** The loop accumulates explicit, versioned,
  inspectable facts, not model weights. Ground truth stays auditable (the honesty thesis).
- **prevalence ≠ correctness.** In an AI-written brownfield the majority pattern may *be* the
  mess. The engine reports divergence **neutrally** and never pronounces which cluster is
  correct; the human anchors the norm.

## 5. Architecture & form factor

`/architecture-review` ships as a **skill** in the pyeye plugin (consistent with
`/code-review`). The skill is the **orchestrator** (runs in the main session, owns cross-run
state, drives the human loop) and dispatches a **fresh auditor subagent** for the audit pass.

**What the subagent does and does not buy (honest framing).** The fresh subagent buys
**context-isolation** — it removes conversation anchoring and rationalisation of code written
in the same session. It does **not** buy **model-isolation**: a fresh-context instance of the
same model shares its weight-level blind spots, which is what §1's circularity actually
describes. So the subagent is *not* the answer to circularity. The genuine anti-circularity
levers are: **(a) grounding every finding in deterministic mechanical facts**, and **(b) the
human gate.** Optional third lever (a real, if partial, model-isolation knob): run the auditor
on a **different model family** than the writer.

**Isolation covers generation, not presentation.** The auditor is isolated, but the
orchestrator that *presents* findings and runs the confirmation dialogue lives in the main
(writer) session, so framing can re-enter at presentation ("X is universal — confirm?"). The
mitigation is **evidence-transparency**: the confirmation surfaces the auditor's structured
findings + cited evidence **verbatim**, not an orchestrator re-narration, so the human judges
the facts rather than the framing.

Governing principle: **maximise the deterministic/mechanical portion; use the LLM only for
genuine judgment.** The auditor reasons *over* facts; it does not free-associate about code.

## 6. Components

| # | Component | Role |
|---|---|---|
| 1 | `architecture-review` **skill** (plugin) | Orchestrator + methodology + output contract + honesty rules. Owns cross-run state. Conformance-guarded (like `python-explore`). |
| 2 | **Fact sources** | pyeye **stable-AST** primitives (`resolve`/`outline`/`expand` `members`/`imports`/`imported_by`/`subclasses`) = deterministic Tier-1. Convention *divergences* are surfaced by the auditor reasoning over these + targeted reads; A has **no content-similarity capability** — duplication is **#495** (§3). |
| 3 | **Auditor subagent** | Fresh context. Consumes facts + prior cross-run state (seeded by orchestrator) + Tier-3 baseline; emits **graded findings** per the contract. Adversarial framing; cites evidence; never invents. |
| 4 | **Cross-run state (json cache)** | **Durable**, orchestrator-owned: coverage map, prior observed findings, confirmed non-issues, reproduction history. The basis for "accumulates across runs." |
| 5 | **Observed-conventions report (md)** | **Regenerated** human-readable view of current Tier-2 (git supplies its diff). Not the source of cross-run state — the cache is. |
| 6 | **Codification path** | Confirmed positive norm → `decision-log` entry (rationale, anchored) + *optional* generated fitness-function/conformance-test stub. Confirmed non-issue → a structurally-keyed cache entry. Reuses `decision-log`. |

Cross-run state is the **orchestrator's** responsibility: the stateless subagent cannot know
what run N−1 did, so the orchestrator seeds it with prior coverage/findings and merges results
back. Otherwise "accumulates across runs" is aspirational.

## 6.5 Convention dimensions — the seed taxonomy (the core operation)

Finding-*generation* is the load-bearing step everything else (grade / gate / rank / store /
test) stands on, and the space of ways to partition a codebase is unbounded. So the auditor
does **not** free-choose what to look for: it **sweeps a documented seed list of convention
dimensions**, open-ended — *"at minimum sweep these axes; surface others you find."* The seed
list is an artifact in the skill, **conformance-anchored** (§13) like `python-explore`'s
supported-edge list.

Seed dimensions (each maps to a fact source; A-scope):

- **Layering / dependency direction** — which layers/packages may import which (`imports` /
  `imported_by`).
- **Module & placement boundaries** — where a *kind* of thing lives (`outline` / structure).
- **Dependency acquisition** — constructor-injection vs import vs global/singleton (reading
  code over members).
- **Error handling** — raise vs return-sentinel vs result-type; exception types; where caught.
- **Validation placement** — at the boundary vs in core vs scattered.
- **Naming & API shape** — naming patterns, return-type conventions, sync/async split.
- **Cross-cutting access** — logging, config, path handling (e.g. this repo's `path_utils`
  conventions).
- *(Duplication / "is there already a helper" is **NOT** a seed axis in A — spike bet-1b showed
  it is a content-similarity problem the fact path cannot do; carved out to **#495**, see §3.)*

**Why a *seed* — not a free choice, not a closed set:**

- It **pins which axes get looked at**, so two runs generate *comparable* finding sets — which
  is what makes the §10 gate and the §13 metric mean what they claim, and removes the
  convention-**selection** confound (§13).
- It stays **LLM-judgment within an axis** (does a divergence on this axis matter?), so it
  doesn't become a rigid rules engine.
- **Guarantee scope:** comparability / conformance / no-selection-confound apply to the
  **seed** axes only. The open "surface others" extension is best-effort and explicitly
  **outside** the stability guarantee.

**Composition with the gate.** The taxonomy removes *dimension-selection* drift (looking along
different axes run-to-run); §10's reproduction gate handles the residual *within-axis*
nomination variance. Fixed axes upstream, stability gate downstream.

**Axis-stakes prior (config, not a claim).** Each seed axis also carries a default *stakes
weight* used **only** for ranking (§11) — labeled, per-project-overridable config, **not** an
intrinsic property of the axis nor a claim that it matters more (ranking ≠ correctness, §11).
The default vector is provisional — calibrate against real review data (§15).

## 7. Data flow & the human loop

1. Invoke → orchestrator resolves project root, loads the **Tier-3 baseline**
   (`DECISIONS.md` + existing conformance tests/fitness functions) and **prior cross-run
   state** (coverage, prior findings, confirmed non-issues) from the cache.
2. Orchestrator dispatches the **auditor subagent** with: scope, baseline, prior state, and
   pyeye/LSP/Read access.
3. Auditor: extract Tier-1 facts → **sweep the §6.5 seed dimensions** and cluster into
   observed conventions with prevalence → detect
   deviations (outliers + internal contradictions) → **grade** each finding (§8) with attached
   evidence, suppressing
   anything matching an unexpired confirmed non-issue. Never pronounces correctness on
   ambiguous cases.
4. Auditor returns structured graded findings; orchestrator merges into cross-run state and
   regenerates the md report.
5. **Human-in-the-loop**, queue ranked per §11 (unconfirmed first, then blast radius):
   - *Mechanical fact* → context, no action.
   - *Deterministic-single* → "X is universal (N/N), evidence shown — recommend codifying.
     Confirm?" → on confirm, codify.
   - *Ambiguous* → clusters with neutral evidence + a recommendation **only if** §9 yields one
     (often none) → human picks/writes the norm, **or** marks it a confirmed non-issue.
   - *No signal* → noted.
6. **Codify**: positive norms (entry + optional check); non-issues (structurally-keyed cache
   entry). Cross-run state retained for next run.

## 8. Output contract (the four finding states)

Mirrors pyeye's own epistemics applied to conventions:

- **Mechanical fact** → stated; no confirmation.
- **Deterministic single answer** → presented *as* the answer **for confirmation**, evidence
  shown. "Deterministic" is defined by the reproduction protocol (§10), not self-report.
- **Ambiguous** → all clusters surfaced with neutral cited evidence; a recommendation **only
  if** §9's anchor rules yield one — which for genuine architecture-level forks is usually
  **not** the case, so the correct output is *clusters + evidence + no recommendation — you
  decide*. **An absent recommendation is correct behaviour, not a defect** (never backfill it
  by loosening §9). A finding whose answer a Tier-3 norm actually settles is **not
  ambiguous** — it is a known-norm violation (Tier-3 may only *partially* anchor, leaving a
  residual ambiguity on the unsettled clusters).
- **No signal** → said honestly.

**Grade by extraction where the convention is mechanical.** A universal convention ("N/N do
X") is a *counting fact*, not a judgment — so for the mechanically-extractable subset the
*grade itself* (deterministic-single vs ambiguous) should fall out of extraction, not an LLM
label. (Spike bet-1 showed LLM-labelled grades on mechanically-determinable conventions —
layering, all-async — drift across runs; this is §5's "LLM only for judgment" applied one level
deeper.) The §10 gate then guards only *genuinely* judgment-layer grades, not ones that should
never have been judgment-layer.

(A confirmed non-issue is a *human action/label* on a finding, not a finding state.)

## 9. Honesty & determinism invariants

- **prevalence ≠ correctness:** no finding asserts the "right" answer on an ambiguous case.
- **Prevalence is evidence, not grounds.** Prevalence ("7 do A, 4 do B") may be *reported* to
  the human as descriptive fact; it may **never** be the *justification* of a recommendation.
- **"Grounded" is defined and bounded.** An ambiguous-case recommendation may cite **only
  external anchors**, never internal prevalence or unanchored model judgment. Anchors, by
  strength:
  1. documented decisions / Tier-3 baseline (truly external to model and to mere prevalence);
  2. language / stdlib idioms (external standards);
  3. import-graph / structural facts — **corroborating evidence only, never sole grounds**
     (they describe *this* possibly-messy codebase, so deciding on them re-entrenches the
     existing structure).
- **Consequence — recommendations are often empty, by design.** For genuine architecture forks
  the ladder usually yields no deciding anchor (a deciding Tier-3 anchor reclassifies the
  finding off the ambiguous track; #3 cannot decide; stdlib idioms rarely apply). "No grounded
  recommendation — you decide" is the correct, thesis-consistent output, **not** a gap to be
  patched by loosening these rules.
- **Magnitude ≠ correctness.** §11 uses import-graph facts for blast-radius *magnitude*, which
  is legitimate; the bar above is on import-graph as *correctness* grounds only — the same
  split as prevalence-as-evidence vs prevalence-as-justification.
- **Confident path is reproduction-gated** (§10): a finding reaches *deterministic-single*
  only if stable across the reproduction protocol; otherwise it is downgraded to ambiguous.
  Rests on **stable-AST facts** (#488 / #419).
- **The gate checks reproducibility, not truth** — the spike's deepest lesson. §10 guarantees a
  confident finding is *stable*, not *correct*: a reproducibly-wrong Tier-1 fact (an extractor
  bug — e.g. **#494**, the `imports` edge silently dropping a real import, which three
  independent runs agreed on) sails through as `deterministic_single`, because a stable-but-wrong
  fact reproduces perfectly. Nothing downstream catches it. This residual risk is **mitigated,
  not eliminated**, by (i) testing the fact extractors and (ii) evidence-transparency (§5) — the
  human can catch a wrong fact only if the confirmation surfaces the underlying evidence, not
  just the conclusion. Tier-1 trust is therefore *conditional on extractor correctness*, which
  the architecture assumes and the spike proved must be earned.
- **Confident-path cross-derivation check (the #494 guard — a mechanism, not a caveat).** For
  every finding on the **confident path**, corroborate its underlying Tier-1 fact against a
  **second derivation** — the targeted Read the auditor already does, or the LSP — and **flag
  any divergence as a possible extractor bug** (downgrade + surface, do not confirm). This is
  exactly what caught #494; it is cheap because it runs only on the confident subset; and it is
  the only thing standing between "Tier-1 is trusted bedrock" and a reproducibly-wrong fact
  passing the §10 gate as `deterministic_single`. **Required in the build** (a plan acceptance
  item, not optional).
- **Advisory-only:** inferred conventions are advisory; only human-confirmed (Tier-3) facts
  may later (in B) block.
- **Human-gated:** Tier-2 → Tier-3 promotion is always human-gated. (Contesting or retiring an
  existing Tier-3 norm is deferred — §15.)

## 10. Reproduction protocol (defines "deterministic" and the confident-path gate)

- **Finding equivalence.** Two findings are "the same" iff they share: identical **cluster
  membership** (the set of involved handles) + the same **grade** + the same **norm-claim
  semantics** (phrasing ignored). Mechanical facts (Tier-1) are compared verbatim.
- **Shared dependency — handle stability.** Finding-equivalence (here), blast radius (§11),
  and non-issue keying (§14) all rest on pyeye **handles** being stable identifiers. pyeye
  handles are canonical qualname/dotted-module names anchored at the def-site —
  **content-edit-stable and alias-collapsing** — so cosmetic edits (whitespace/comments/
  reflow) do **not** perturb them, while a rename or module-move **does** change them
  (→ intended re-evaluation). All three mechanisms inherit exactly these semantics (§16).
- **Procedure.** Tier-1 extraction is deterministic and tested verbatim (§13). For the
  judgment layer (clustering/grading), candidate findings from the first pass are **re-run N
  times (N = 2–3) only to *promote* a would-be-confident finding** — reproduction is a
  confirmation gate on the confident path, **not** a blanket re-execution (cost control).
- **What instability is, and isn't.** Instability is a **reliability** signal (can the machine
  pin the finding down?). Its honest role is the **confident-path gate**: a finding is
  *deterministic-single* only if equivalent across all N runs; any instability → ambiguous. It
  is **not** a within-queue priority score — and because the gate re-runs only
  confident-candidates, ambiguous findings have no instability score at all. §11 therefore
  treats confidence as a **binary tier flag**, not a continuous uncertainty score. (A
  continuous score via re-running ambiguous findings is a deferred upgrade — §15.)
- **Nomination is the yield ceiling.** The gate re-runs only first-pass *confident
  candidates*, so it filters false positives (claimed-confident-but-unstable) but **not**
  false negatives: a genuinely-stable finding the first pass failed to nominate is never
  promoted. Safe direction (under-promotion → more human review), but confident-path yield is
  bounded by nomination quality, not just reproduction — a second confound for the §13 metric
  (low yield = contested codebase *or* under-nomination, which have opposite remedies).
  **Selection is further upstream still:** a dimension the auditor never sweeps generates no
  finding to nominate or gate — a *third* confound, closed for the seed axes by the §6.5
  taxonomy.
- **The gate is blunt at N = 2–3.** Requiring all-N-equivalent, a ~90%-stable finding still
  fails ~25% of the time and a ~50%-stable one passes occasionally. Acceptable only because
  the error favours human review; the gate is a coarse filter, not a crisp classifier, and a
  continuous score (§15) would need a larger N — consistent with deferring it on cost.

## 11. Ranking — escalate the unconfirmed, order by (axis-stakes prior × blast-radius)

The engine of the scarce-attention thesis. Per §10, instability is a reliability **gate**, not
a continuous score, so the ranking is **two-level**:

1. **Tier flag (binary):** unconfirmed/ambiguous findings sort **above** confident findings
   (cheap one-click confirms) — "escalate the uncertain."
2. **Within *each* tier, order by `axis-stakes prior × blast-radius magnitude`** (descending).

**Why not blast-radius alone (spike bet-3).** Blast-radius is *magnitude*, not stakes: the
spike empirically ranked a trivial naming finding (low-stakes, on a hub) **above** a
validation-security finding (high-stakes, on a leaf). The axis carries the stakes; blast-radius
only the reach.

- **Axis-stakes prior** — a per-axis weight (e.g. error-handling/validation > … > naming) that
  re-sorts the queue. It is **NOT** a fact, an external anchor, or a per-finding judgment, so by
  §9 it could never justify a *recommendation*. It is admissible **only because ranking is not
  correctness**: attention-order is reversible — no norm is decided by queue position — unlike an
  asserted answer. To stay honest it is held to three constraints:
  1. **Shown and overridable, never a silent constant.** The human sees "ranked by axis-stakes
     prior (validation/error-handling > … > naming) × blast-radius — reorder?" (the §5
     evidence-transparency standard), and the prior is **per-project overridable**, carried in
     the same cross-run state (§6) as other config. (A library whose public API *names are* the
     architecture is then a one-line override, not a fork.)
  2. **Ordering-only — it never gates, suppresses, or pushes a finding below a fold.** It
     re-sorts *within* a tier; a low-stakes axis can never remove a finding from view.
     (Suppression would let a tunable prior silence findings — worse than mis-ordering, and the
     load-bearing role §6.5 explicitly refused.)
  3. **The default weight vector is provisional, not validated.** The spike proved the
     *mechanism* (axis-weight removes the leaf-inversion) on one fixture whose stakes mapping was
     author-set — partly circular. The defaults are a first guess to **calibrate against real
     human-judged stakes over the first several runs** (the §17 "rough bands, first run
     calibrates" discipline; §15).
- **Blast-radius magnitude** (deterministic, from pyeye): `imported_by` + `subclasses` +
  package centrality; aggregation over a finding's handle-set defaults to **max** (alternatives
  open, §15 — the spike showed max can inflate a leaf finding that merely *references* a hub
  symbol). Used for *magnitude* only — §9 bars import-graph as *correctness* grounds (magnitude
  ≠ correctness). **Caveat:** caller counts are the reverse-reference gap (#333) → the **LSP
  handoff (#489)** or approximate by `imported_by` + `subclasses`.

## 12. Error handling & degradation

- pyeye unavailable → degrade to AST/LSP/Read, note it (the `python-explore` failure mode).
- Non-deterministic (goto-dependent) fact → excluded from the confident path or marked
  low-confidence; non-reproducible "single answer" → ambiguous (§10).
- Large codebase → A runs on a **caller-supplied scope**; automatic package-at-a-time iteration
  over a whole large repo is deferred (§15). Across runs it accumulates (orchestrator coverage
  map) and must **surface what was and wasn't covered** — no silent truncation. **Coverage
  freshness:**
  each coverage unit carries a *last-audited-at* stamp and is marked **stale and re-surfaced
  when its code has changed since** (same structural-change signal as the §14 non-issue key) —
  so "accumulates across runs" never means "shows run-1 facts about since-rewritten code."
- Greenfield facts → "no confirmed norms yet; here are observed conventions to consider."

## 13. Testing

- **Conformance test** binding the skill's documented **seed taxonomy (§6.5)** and
  output-contract to reality (like `test_python_explore_skill_conformance` binds the
  supported-edge list) — so the load-bearing convention-discovery step has a real anchor, not
  just the output contract and honesty rules.
- **Fixture codebase** with planted conventions + deviations → assert correct surfacing and
  grading, and that ambiguous cases are never asserted-correct. Include a **prevalence-trap**
  fixture (majority = the wrong pattern), and an **empty-recommendation** fixture (a genuine
  architecture fork with no deciding anchor → no recommendation, by §9).
- **Fact-extraction determinism test:** Tier-1 extracted twice → identical.
- **Grading-stability test:** the §10 reproduction protocol on a fixture → confident findings
  equivalent across N; an intentionally-ambiguous fixture stays out of the confident path.
- **Confirmed-non-issue test:** a dismissed divergence is suppressed on re-run, and
  **re-surfaces once the keyed structure changes** (invalidation) but **not** on a cosmetic
  edit (whitespace/comment/rename that leaves the structure intact).
- **Codification test:** confirming a norm yields a well-formed `decision-log` entry (+ stub).
- **Dogfood + value metric (not raw yield).** Raw confident-path yield mostly measures the
  *codebase's existing consensus*, not the tool's value-add: it is high on tidy codebases
  (where the tool adds least) and structurally low on the messy brownfield it targets (where
  consensus is low by construction and the consequential, contested questions land in the
  ambiguous tier *by definition*). A respectable yield can therefore mean "automated the
  settled questions, handed the human every consequential one." Measure value on the
  **planted-stakes fixture** (where you control which findings are architecturally
  consequential), split by population:
  - **Detection** (all planted findings): fraction surfaced at all — the false-negative /
    nomination check.
  - **Consensual findings:** confident-path capture (the honest, scoped use of "yield") — a
    universally-followed important norm confirmed cheaply, with its violations surfaced.
  - **Contested high-stakes findings:** **NOT** capture — auto-confirming a contested
    architecture decision violates prevalence ≠ correctness, so **high capture here is a *bad*
    sign.** The value is **detection + ranking position** (did blast-radius ordering surface
    them near the top of the human queue?).
  - Go/no-go is value on the **consequential** findings (capture where consensual,
    detection+ranking where contested), **not** raw yield. Report the §10 confounds
    (codebase consensus, first-pass nomination, and convention-**selection** — the last
    mitigated for seed axes by §6.5) alongside so a low raw number isn't misread.

## 14. Storage & codification (Approach 3, check-first, scoped to A)

- **Tier 1:** never stored — re-derived.
- **Tier 2:** durable json cache (cross-run state) + regenerated md view (§6).
- **Tier 3 (positive):** a confirmed norm becomes an **executable fitness function /
  conformance test** *wherever it can*, with rationale as a `decision-log` entry anchored to
  that test.
- **Confirmed non-issue (negative):** cache entry keyed on **involved handles + the structural
  divergence fact** (the Tier-1 relationship the human adjudicated), **not** a content hash —
  a content hash re-nags on cosmetic edits (whitespace/comment/rename) that don't touch the
  divergence, while handles are content-stable (§10). Invalidated → re-surfaced only when the
  structural fact genuinely re-diverges. Exact key granularity is open (§15).
- **Anti-drift, qualified.** "The norm *is* the check" prevents drift **only for the
  executable subset**. Non-executable norms ("prefer composition here") fall back to a prose
  checklist note — a smaller second source of truth, drift-**mitigated** by being minimal and
  reviewed, **not eliminated**. The #374 guarantee covers fitness-function-expressible norms
  only; the residual is scoped, flagged, and accepted.
- **A-scoping:** no queryable store (matters once B reads it programmatically) — a generated
  Tier-2 report + codification into `decision-log`/checks + the non-issue cache.

## 15. Deferred / open

- **B (diff-mode):** same engine scoped to changed-files-vs-siblings; thin layer once A
  exists; gains teeth from A's Tier-3 base.
- **Contest signals + norm revision/retirement (both deferred).** A neither contests existing
  Tier-3 norms nor revises/retires them. The spike never exercised contest (no Tier-3 baseline
  existed) and it matters only once the Tier-3 base is *mature*; the human-gated
  contest/revise/retire workflow (to stop the read-and-write-`DECISIONS.md` loop entrenching
  stale norms) is a fast-follow.
- **Bounded-scope auto-iteration (deferred).** A runs on a caller-supplied scope; automatically
  picking and iterating the bounded unit (package-at-a-time) over a whole large repo is a later
  orchestration enhancement (§12). The state coverage map already supports accumulation across
  manually-supplied scopes.
- **Negative-tier class-promotion (symmetric to norm-revision).** Confirmed non-issues are
  monotonic-with-no-aggregation: a new instance of an already-accepted divergence has new
  handles, correctly re-surfaces, and the human re-adjudicates it instance by instance with
  nothing noticing the same non-issue has been confirmed N times. Repeated identical
  confirmations are a promotable signal → a **class-level exception** ("this divergence is
  acceptable as a category"), exactly symmetric to Tier-2 → Tier-3 norm promotion. Deferred,
  but named so the negative-tier lifecycle isn't silently asymmetric with the (also-deferred)
  positive-tier contest/revision path above.
- **Self-learning loop / shadow-mode accumulation;** **queryable fact store;** **blocking/CI;**
  **different-model auditor** (the model-isolation knob from §5); **multi-language.**
- **Semantic-duplication detection — #495** (carved out per spike bet-1b; the #1 stated pain; a
  *separate* similarity engine, not an axis in A — see §3).
- **Tier-1 extractor correctness** is a load-bearing assumption the §10 gate does **not** verify
  (#494): extractor test coverage + evidence-transparency (§9) are the only guards against a
  reproducibly-wrong fact.
- **Open design points:**
  - Tier-2 cache schema.
  - Bounded-scope unit for very large repos (package-at-a-time assumed).
  - §10 cross-run finding-equivalence tolerance (handle-set + grade + claim-semantics assumed)
    — *matches findings across runs*.
  - **Non-issue key granularity** (structural-fact vs handle vs content-span) — *invalidates a
    stored dismissal*; distinct from the equivalence tolerance above.
  - **Blast-radius aggregation** over a finding's handle-set (max / sum / hub-centrality —
    §11 default is max).
  - **Axis-stakes default weight vector** — the spike (bet-3) proved blast-radius alone
    under-discriminates and the axis-prior mechanism (§11) fixes it, but the default *values*
    are provisional: calibrate against real human-judged stakes over the first several runs, and
    **watch for codebases where the prior inverts** (e.g. API-name-driven libraries where naming
    is high-stakes — handled by the §11 per-project override).
  - Whether to add a continuous within-ambiguous uncertainty score (§11 deferred upgrade).
  - Growth/curation of the §6.5 seed taxonomy (which axes ship in A; how new axes are added).
  - **Axis overlap** — seed axes (layering / boundaries / validation-placement) overlap, so one
    divergence can surface under several axes as separate queue entries; §10 equivalence dedupes
    some, not cross-axis. Expect this on the first real run; decide dedup/precedence
    empirically, not on paper.

## 16. Relation to existing assets

- **`decision-log` / `DECISIONS.md`** — codification target for confirmed-norm rationale.
- **Conformance-test pattern** — model for the skill's anti-drift guard and the executable
  Tier-3 form.
- **`python-explore`** — sibling skill; failure-mode/honesty conventions reused.
- **pyeye primitives** — deterministic Tier-1 source; stable-AST subset preferred over
  goto-dependent resolution for the confident path (#488 / #419). **Handle semantics** are the
  shared substrate for §10 / §11 / §14: canonical qualname/dotted-module handles anchored at
  the def-site, content-edit-stable and alias-collapsing; rename/module-move changes a handle
  (intended re-evaluation).
- **#489 LSP handoff** — supplies caller-count blast radius (§11) that pyeye defers (#333).
- **pyeye build-notes (from the spike):** read `async`-ness via `inspect` (not `outline`, which
  omits it); pass **dotted handles** (a file-path handle to `outline` returns a junk node); do
  **not** treat the `imports` edge as exhaustive for layering until **#494** is fixed (it can
  silently drop a real import).

## 17. Build approach — spike before machinery

The three load-bearing bets — **selection stability**, **confident-path value**, and
**blast-radius-as-stakes proxy** — are *asserted, not observed*. Before building the storage /
codification / non-issue machinery that assumes them, build the **thinnest slice**: the auditor
pass driven by the §6.5 taxonomy, run **N = 3**, with **no cross-run state, no codification, no
non-issue cache.**

**Targets.** A genuinely messy target is the load-bearing measurement — a real AI-written
brownfield, or the §13 planted-stakes fixture; **pyeye itself is only a tidy control** (yield
on it is the flattering case, §13). Spiking yield solely on pyeye would reproduce the
flattering-measurement problem the value metric exists to avoid.

**Measure → decision (rough bands now; the first run calibrates them — precise thresholds on
unobserved metrics would be false precision):**

1. **Selection stability** — finding-set overlap across the 3 runs (§10 equivalence, seed
   axes). *Proceed* if a clear majority of run-1 seed-axis findings recur in all 3;
   *rethink the taxonomy/gate* if recurrence is near coin-flip (within-axis drift swamps the
   seed sweep).
2. **Value delivery — not raw yield** (§13). On the planted-stakes fixture: detection-rate of
   planted findings + ranking-position of the high-stakes ones. *Proceed* if high-stakes
   findings are detected and ranked near the top; *kill/rethink* if missed or buried. Raw
   confident-path yield is descriptive only — near-zero on a messy codebase is **expected, not
   a kill** (value there is detection+ranking, not capture).
3. **Proxy validity** — do the blast-radius-top findings match human-judged stakes? *Proceed*
   if yes; *bring the §11/§15 continuous score (or a better stakes signal) forward* if the top
   is dominated by trivial high-centrality findings.

A bad result is cheap to get here and changes what you build; a good result de-risks the full
machinery. The spike must return a **decision**, not just numbers.
