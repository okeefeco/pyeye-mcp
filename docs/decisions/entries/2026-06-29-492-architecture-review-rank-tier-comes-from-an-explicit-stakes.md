---
date: "2026-06-29"
title: "architecture-review rank tier comes from an EXPLICIT stakes-bucket map, not a product and not thresholded priors (#492)"
issues: [492]
anchors: ["pyeye.architecture_review.taxonomy.AXIS_STAKES_BUCKET", "pyeye.architecture_review.ranking.rank", "pyeye.architecture_review.ranking.stakes_bucket"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-29 — architecture-review rank tier comes from an EXPLICIT stakes-bucket map, not a product and not thresholded priors (#492)

**Friction:** Spec §11's bet-3 is a *dominance* requirement ("the axis carries the stakes; blast only the reach") — a high-stakes finding must outrank a low-stakes one REGARDLESS of blast. Two forms fail it. (1) The `axis-stakes prior × blast-radius` PRODUCT: a large enough blast on a low-stakes item always overtakes a high-stakes one, and `blast = 0 ⇒ product = 0` for ANY prior, making prior recalibration structurally inert — the #492 dogfood reproduced this, a high-stakes `validation_placement` leaf (blast 0) buried under a low-stakes `naming_api_shape` hub. (2) Deriving buckets by *thresholding the provisional priors* (`prior ≥ 0.8 → high`) REINTRODUCES the failure by the back door: it makes dominance depend on the third decimal of a §15-uncalibrated float, so a routine prior nudge (`0.9 → 0.79`) silently re-tiers a high-stakes axis to `med` and breaks dominance with nothing failing loudly.
**Decision:** The SOURCE OF TRUTH for ranking tier is an **explicit `AXIS_STAKES_BUCKET` map** (one `{high,med,low}` entry per seed axis) in `taxonomy.py`. Rank WITHIN each grade-tier bucketed-lexicographically: stakes bucket (from the map) PRIMARY, blast-radius DESCENDING SECONDARY (orders only within a bucket), stakes prior TERTIARY (within-bucket tiebreaker only). `AXIS_STAKES_PRIOR` is DEMOTED to that within-bucket tiebreaker — it can never re-tier an axis. There are NO threshold constants. Re-tiering an axis is an explicit, reviewable edit to the bucket map. Dominance holds by construction and is independent of prior VALUES. The grade-tier split (ambiguous above confident, no_signal last) stays the TOP-LEVEL ordering. Tradeoff: lexicographic fully trusts the bucket map — blast can no longer rescue a mis-bucketed finding — so the explicit map is load-bearing and its §15 calibration is a hard dependency (prior calibration is now only polish). Rejected: the product (and blast-floor / `log1p(blast)` variants — all let blast cross stakes boundaries); AND threshold-derived buckets (let an uncalibrated float silently re-tier).
**Anchor:** `pyeye.architecture_review.taxonomy.AXIS_STAKES_BUCKET` + `pyeye.architecture_review.ranking.rank` + `pyeye.architecture_review.ranking.stakes_bucket`; spec §11 (rev 12); #492.
**Verify:** gold — `tests/test_architecture_review_ranking.py::TestDominanceByConstruction::test_dominance_independent_of_prior_values` asserts a high-stakes `validation_placement` finding outranks a low-stakes `naming_api_shape` finding even when validation's prior float is set BELOW naming's, because the explicit bucket map tiers them (a prior value cannot re-tier). Plus `test_high_stakes_leaf_beats_low_stakes_hub_blast_zero` (blast-0 leaf beats blast-9 hub) and `test_med_bucket_high_blast_below_high_bucket_low_blast`. Run `uv run pytest tests/test_architecture_review_ranking.py`.
