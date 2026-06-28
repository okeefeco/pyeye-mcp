# `/architecture-review` (increment A) — Dogfood + value-metric report (Task 4.2)

**Date:** 2026-06-29 · **Issue:** [#492](https://github.com/okeefeco/pyeye-mcp/issues/492) ·
**Spec:** `docs/superpowers/specs/2026-06-28-architecture-review-audit-design.md` (§13 value metric, §17 spike measures)

This is the §13 **value metric**, not raw yield. It is a *report*, not a pass/fail gate (per the plan's Task 4.2).
Measurement target: the committed planted-stakes fixture `tests/fixtures/architecture_review/app/`
(load-bearing per §17; pyeye-itself-as-tidy-control is the flattering case and was **not** run as a full pass — see Confounds).

## Method

1. **Blind auditor pass.** A fresh-context subagent ran the *shipped* auditor prompt
   (`skills/architecture-review/auditor.md`) over `app/` only, **blind to `GROUND_TRUTH.md`**.
   It built a structural model with pyeye primitives (`resolve`/`outline`/`inspect`/`expand` over
   `imports`/`imported_by`) and corroborated import-critical facts with targeted `Read`. It emitted a
   JSON findings array in the pinned schema.
2. **Ranking.** The findings were ranked with the real `pyeye.architecture_review.ranking.rank`, using a
   `blast_fn` derived from the fixture's actual `imported_by` magnitudes (HUB `app.core.config` = 9
   importers; LEAF `app.security.permission_check` = 0).
3. **Evaluation** against `GROUND_TRUTH.md` (the oracle): detection, ranking position of the
   proxy-inversion pair, prevalence-trap neutrality, empty-recommendation behaviour, cross-derivation.

## Detection — 5/5 planted divergences surfaced

| Plant | Axis | Detected? | Grade emitted | Notes |
|------:|------|:---------:|---------------|-------|
| 1 Prevalence-trap error handling | `error_handling` | ✅ | `ambiguous` | swallow×3 vs propagate×1 reported **neutrally**; **no** recommendation toward the majority |
| 2 High-stakes validation on a LEAF | `validation_placement` | ✅ | `ambiguous` | boundary `authorize_transfer` unvalidated; deep/partial validation in `_apply_transfer`; `null` rec |
| 3 Low-stakes naming on a HUB | `naming_api_shape` | ✅ | `ambiguous` | `get_`/`fetch_`/`retrieve_` on `core.config`; `null` rec |
| 4 Module-global dep acquisition | `dependency_acquisition` | ✅ | `ambiguous` | singleton `DB` / lazy `get_client` / param injection; `null` rec |
| 5 Ambiguous result-shape fork | `naming_api_shape` | ✅ | `ambiguous` | dict / dataclass / tuple; **`recommendation = null`** (the empty-recommendation fixture) |

Plus legitimate extras (consistent layering, uniform sync/no-annotations, a bare-`except:` mechanical fact).
**Detection / false-negative check: PASS** — every planted finding was nominated, including the high-stakes leaf.

## Honesty invariants — upheld

- **prevalence ≠ correctness:** the error-handling prevalence trap (Plant 1) was reported descriptively
  (counts given) with **no** recommendation favouring the majority swallow pattern. ✅
- **recommendation non-null ONLY with an external anchor:** every genuine architecture fork (Plants 2–5)
  returned `recommendation = null`. The **only** non-null recommendation in the whole run was the
  bare-`except:` finding, correctly anchored to the **PEP 8 / stdlib idiom** (an allowed anchor) — not to
  in-codebase prevalence. This is a positive two-sided signal: the anchor ladder yields a rec when a real
  external anchor exists and stays empty otherwise. ✅
- **empty-recommendation by design:** Plant 5 produced clusters + evidence + `null` — the correct
  "you decide" output. ✅
- **cross-derivation (#494) guard:** the auditor corroborated the `imports` edge against a targeted Read of
  the actual import statements and found **no** divergence (the fixture plants no extractor bug), so it
  raised **no** `possible_extractor_bug` flag — the correct silent pass. The guard's *positive* catch is
  unit-tested in Task 3.1 (`test_494_dropped_import_is_downgraded_via_ast_not_evidence`). ✅

## Ranking / proxy validity (§17 measure 3) — **FAIL on this fixture (the load-bearing signal)**

The central bet-3 claim is that the axis-stakes prior makes the high-stakes **leaf** (Plant 2,
`validation_placement`) outrank the low-stakes **hub** (Plant 3, `naming_api_shape`) despite the hub's
larger blast radius. Computed with the real ranker and the fixture's real `imported_by` magnitudes:

```text
ambiguous tier (sorts above all confident findings), by prior × blast:
  0  dependency_acquisition   blast 9  prior 0.60  score 5.40
  1  naming_api_shape (HUB)   blast 9  prior 0.30  score 2.70   <- Plant 3
  2  error_handling           blast 1  prior 0.90  score 0.90
  3  validation_placement     blast 0  prior 0.90  score 0.00   <- Plant 2 (buried)
  4  naming_api_shape (fork)  blast 0  prior 0.30  score 0.00
```

**Plant 2 (validation, leaf) ranks at position 3, BELOW Plant 3 (naming, hub) at position 1 → bet-3 FAIL.**

**Root cause (mechanism is sound; the *default calibration* is not):**

- The leaf's blast magnitude is **0** (`imported_by` = 0), so `prior × blast = 0.9 × 0 = 0`. A zero blast
  annihilates the stakes weight. The 3:1 prior ratio (`0.9 : 0.3`) cannot overcome a `9 : 0` blast ratio.
- `max`-aggregation over a finding's handle-set (the §11 default) also floated `dependency_acquisition` to
  the very top because one of its handles references the hub (`core.database`/handlers) — the exact
  "a leaf finding that merely *references* a hub gets inflated" caveat §11 names.
- The Task 1.2 unit test proves the prior mechanism works at *moderate* blast ratios (it inverts a 4:2
  spread). The fixture's *extreme* `9:0` spread is outside what a 3:1 prior can correct.

This is precisely the **§15 "watch for codebases where the prior inverts"** / **§17 measure-3 "top dominated
by trivial high-centrality findings"** case. It is **descriptive, not a kill** (§13): the high-stakes finding
*is detected* and *is in the ambiguous tier above all confident findings* — it is mis-ordered *within* that
tier, not dropped.

**Remedies (all already flagged provisional in §11/§15 — calibrate before trusting queue position):**

1. **Blast floor / normalization** so a leaf is not literally 0 (e.g. `log1p`, or a base magnitude of 1 with
   diminishing hub returns) — a raw count lets one hub dominate by 9× and swamp stakes.
2. **Recalibrate the default prior vector** against real human-judged stakes (the §15 first-runs-calibrate
   discipline) — the current 0.9/0.3 spread is a first guess.
3. **Bring forward the §11 continuous within-tier uncertainty score** (the deferred upgrade) and/or revisit
   `max` vs hub-centrality aggregation.

## §10 confounds (reported so the numbers aren't misread)

- **Codebase consensus:** the fixture is messy *by construction*, so confident-path yield is low — expected,
  not a kill (§13).
- **Nomination:** this was a **single** auditor pass; the §10 reproduction gate (N re-dispatches) was **not**
  run live here (cost) — its mechanism is unit-tested (Task 2.2). Confident-path yield is bounded by
  first-pass nomination, not just reproduction.
- **Selection:** closed for the seed axes by the §6.5 taxonomy — the auditor swept all seven axes, so no
  axis-selection drift.
- **Tidy control (pyeye itself):** not run as a full pass; per §17 it is only the flattering case and the
  planted-stakes fixture is the load-bearing measurement.

## Go / no-go

- **GO on the core thesis** (detection + honesty): unknown divergences are made **visible**, **graded**, and
  **honestly neutral** — 5/5 detection, correct prevalence-trap neutrality, correct empty-recommendations,
  correct external-anchor discipline (one PEP 8-anchored rec, all genuine forks `null`), and the
  cross-derivation guard behaves correctly.
- **CONDITIONAL on the ranking layer:** the `axis-stakes-prior × raw-blast` **default** does **not** yet
  deliver bet-3's stakes-over-blast on real code with extreme centrality spread (high-stakes leaf buried
  beneath cosmetic hub naming). This is the calibration work §11/§15 explicitly defers — do **not** rely on
  queue *position* for high-stakes-on-leaf findings until the blast is floored/normalized and the priors are
  calibrated. The ordering mechanism itself is correct (unit-proven); the default weights/aggregation need
  the first-runs calibration the spec already calls for.
