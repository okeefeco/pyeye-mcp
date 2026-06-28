# `/architecture-review` (increment A) — Dogfood + value-metric report (Task 4.2)

**Date:** 2026-06-29 · **Issue:** [#492](https://github.com/okeefeco/pyeye-mcp/issues/492) ·
**Spec:** `docs/superpowers/specs/2026-06-28-architecture-review-audit-design.md` (§13 value metric, §17 spike measures)

This is the §13 **value metric**, not raw yield. It is a *report*, not a pass/fail gate. Target: the
committed planted-stakes fixture `tests/fixtures/architecture_review/app/` (load-bearing per §17;
pyeye-itself-as-tidy-control is the flattering case and was not run).

> **Revision note.** An earlier draft of this report (a) mis-diagnosed the ranking failure as
> *calibration* and proposed floor/log1p/recalibration remedies that **do not clear bet-3** on the
> actual numbers; (b) implied the full pipeline was exercised when only the front half was; and
> (c) under-disclosed that `deterministic_single` findings existed in the run. All three are corrected
> below, and the ranking has since been re-implemented (product → bucketed-lexicographic).

## Method

1. **Blind auditor pass.** A fresh subagent ran the shipped auditor prompt (`skills/architecture-review/auditor.md`)
   over `app/` only, blind to `GROUND_TRUTH.md`, using pyeye primitives corroborated by targeted `Read`.
2. **Ranking** with `pyeye.architecture_review.ranking.rank` and a `blast_fn` from the fixture's real
   `imported_by` magnitudes (HUB `app.core.config`=9, LEAF `app.security.permission_check`=0).
3. **Confident-path live dogfood:** 3 blind re-dispatches over a narrow scope to exercise the reproduction
   gate; the cross-derivation guard run as a shipped stage over real fixture source.
4. **Evaluation** against `GROUND_TRUTH.md`.

## Tier 1 — validated live (the core thesis, earned)

### Detection — 5/5 planted divergences surfaced

| Plant | Axis | Grade | Notes |
|------:|------|-------|-------|
| 1 Prevalence-trap error handling | `error_handling` | `ambiguous` | swallow×3 vs propagate×1, **neutral**, no majority rec |
| 2 High-stakes validation on a LEAF | `validation_placement` | `ambiguous` | boundary unvalidated; `null` rec |
| 3 Low-stakes naming on a HUB | `naming_api_shape` | `ambiguous` | 3 accessor prefixes; `null` rec |
| 4 Module-global dep acquisition | `dependency_acquisition` | `ambiguous` | singleton/lazy/injection; `null` rec |
| 5 Ambiguous result-shape fork | `naming_api_shape` | `ambiguous` | dict/dataclass/tuple; **`null`** (empty-recommendation fixture) |

**Disclosure (corrected):** the run ALSO produced three `deterministic_single` findings (consistent
`layering`, `module_boundaries`, `handle_*`/`load_*` naming) and two `mechanical_fact` findings. The
earlier draft's detection table showed only the five ambiguous plants. The confident path therefore *did*
have candidates — see Tier 2 for what happened when they were run through it live.

### Honesty invariants — upheld

prevalence ≠ correctness (Plant 1 neutral); every genuine fork `null` (Plants 2–5); the **only** non-null
recommendation was the bare-`except:` finding, correctly anchored to a PEP 8 idiom (an allowed anchor);
Plant 5 produced clusters + `null` (the empty-recommendation case).

### Ranking dominance (bet-3) — now PASSES by construction

The earlier `prior × blast` **product** FAILED bet-3: a product makes stakes and blast co-equal
multiplicative factors, so a high-blast low-stakes hub overtakes a low-blast high-stakes leaf; with the
leaf at blast 0 the product is 0 for *any* prior, making prior calibration structurally inert. The
proposed floor/log1p/recalibration remedies do **not** fix it (verified): floor@1 → validation `0.9×1=0.90`
vs naming `0.3×9=2.70`; log1p(floor@1) → `0.624` vs `0.691`; hub wins both. The fix was a **functional-form
change**, not calibration.

Ranking is now **bucketed-lexicographic** (spec §11, rev 12): an explicit `AXIS_STAKES_BUCKET` map
(high/med/low — the source of truth for tier, **not** thresholded from the provisional priors) is the
primary key; blast orders only *within* a bucket; the prior float is demoted to a within-bucket tiebreaker
that can never cross a bucket. Re-run over the original 10 findings:

```text
ambiguous tier (above all confident findings), by (bucket, blast, prior):
  0  error_handling          high   blast 1     <- Plant 1
  1  validation_placement    high   blast 0     <- Plant 2 (leaf) — now ABOVE Plant 3
  2  dependency_acquisition  med    blast 9     <- Plant 4
  3  naming_api_shape (HUB)  low    blast 9     <- Plant 3
  4  naming_api_shape (fork) low    blast 0     <- Plant 5
PROXY-INVERSION CHECK (bet-3): Plant 2 at position 1, Plant 3 at position 3 => PASS
```

Both high-stakes findings lead the queue regardless of blast (Plant 2 is #1–2 at blast 0); blast only
orders within a bucket. The guarantee is now *by construction* and pinned by
`test_dominance_independent_of_prior_values` (a prior recalibration cannot re-tier) and
`test_every_seed_axis_is_explicitly_bucketed` (an unmapped seed axis fails loudly, not silently to `low`).
Tradeoff (stated honestly): the bucket map is now load-bearing — §15 calibration is a **hard dependency**
of trusting queue position, not optional polish. Logged in `docs/decisions/DECISIONS.md`.

## Tier 2 — confident path: dogfooded live, one defect found, one path un-plantable

The earlier draft said the promotion chain was "not run live (cost)." That undersold it. Run live:

- **Reproduction gate (promote) — DEFECT FOUND ([#498](https://github.com/okeefeco/pyeye-mcp/issues/498)).**
  Three blind re-dispatches over `app/handlers`+`app/services` returned the universals (`handle_*` 6/6,
  `load_*` 4/4) as `deterministic_single` with **identical handle-sets and grades in all three runs** — the
  auditor is structurally stable. But the shipped gate **downgrades them to `ambiguous`** anyway, because
  `findings_equivalent` keys on the claim *string* (whitespace+case only) and LLM phrasing varies run-to-run
  (`findings_equivalent(run1, run2) == False` despite identical handles+grade). Spec §10 says equivalence
  ignores phrasing; the implementation doesn't. **Consequence:** on real LLM output the confident path
  promotes ~nothing — not from low consensus, but from an over-strict predicate. Unit tests miss this (they
  use identical mocked claims); only live dogfooding surfaced it. Filed as #498 (preferred fix: a stable
  structured `claim_key`, echoing the bucket-map lesson — don't rest a stability guarantee on an unstable
  free-text string).
- **Cross-derivation guard (#494) — dogfooded live, PASS.** Run as a shipped stage over real committed
  source (`app/services/report_service.py`, AST imports `{app.core, app.handlers}`): a `deterministic_single`
  finding claiming a *dropped* import (`{app.core}` only, #494-shape) with a deliberately *lying* `evidence`
  field was correctly downgraded to `ambiguous` + `possible_extractor_bug` via the independent
  `imports_via_ast`, while the correct finding passed untouched. This validates the guard one step beyond its
  unit test (real fixture source, not `tmp_path`). **Limit:** a *fully* end-to-end auditor→guard catch needs a
  real live extractor bug to exist; with pyeye correct on the fixture, the catch is exercised by injecting the
  wrong fact, not by a naturally-wrong edge.
- **Gate genuine-downgrade (instability) — UN-PLANTABLE.** A finding the gate should downgrade *because the
  model disagrees with itself across re-runs* cannot be planted in static fixture code (instability is LLM
  non-determinism, not a source property). Stays unit-test-only (`test_architecture_review_gate.py`) by
  nature. Stated, not faked. (Note the irony: the gate *does* downgrade the stable universals live — but for
  the wrong reason, #498, not genuine instability.)

## Tier 3 — unit-test only (not dogfooded)

Codification end-to-end (human-confirmed norm → `decision-log` entry + fitness-function stub; dismissal →
`build_non_issue`) is exercised only by unit tests. The non-issue keying and `build_non_issue` are tested;
the human-gated decision-log flow is inherently interactive and was not dogfooded.

## §10 confounds (so the numbers aren't misread)

- **Codebase consensus:** the fixture is messy by construction → low confident-path yield is expected, not a
  kill. (But note #498 means yield is *also* suppressed by the equivalence bug, independent of consensus.)
- **Nomination:** single first-pass auditor; confident-path yield is bounded by nomination quality.
- **Selection:** closed for seed axes by the §6.5 taxonomy (all seven swept).
- **Tidy control (pyeye itself):** not run; per §17 it is only the flattering case.

## Go / no-go (three tiers of confidence, not two)

- **GO — detection + honesty + anchor discipline + ranking dominance** (Tier 1): validated live. 5/5
  detection, correct neutrality/empty-recommendations/anchor discipline, and — after the functional-form fix
  — stakes-dominant ranking that is correct by construction and test-pinned.
- **CONDITIONAL — confident path** (Tier 2): the cross-derivation guard works live; the reproduction gate's
  *promote* path is **blocked by #498** (phrasing-sensitive equivalence) and must be fixed before the
  confident path is usable on real output; the genuine-instability downgrade is un-plantable and stays
  unit-tested. Trusting queue *position* also depends on §15 bucket calibration (now load-bearing).
- **NOT YET DOGFOODED — codification end-to-end** (Tier 3): unit-tested only.

The core result is real and earned: the tool finds unknown divergences and stays honest about them, and
ranks them by stakes. The confident-path machinery is sound in unit tests but, run live, surfaced a binding
defect (#498) that the unit tests could not — which is exactly why it needed dogfooding.
