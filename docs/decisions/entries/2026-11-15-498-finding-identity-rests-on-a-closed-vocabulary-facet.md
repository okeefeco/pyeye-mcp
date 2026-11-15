---
date: "2026-11-15"
title: "Finding identity rests on a closed-vocabulary facet, not claim prose (#498)"
issues: [498, 492, 629]
anchors: ["pyeye.architecture_review.state.observation_key", "pyeye.architecture_review.state.findings_equivalent", "pyeye.architecture_review.state.build_non_issue", "pyeye.architecture_review.state.finding_problems", "pyeye.architecture_review.gate.apply_reproduction_gate", "pyeye.architecture_review.taxonomy.AXIS_FACETS", "skills/architecture-review/auditor.md"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — Finding identity rests on a closed-vocabulary facet, not claim prose (#498)

**Friction:** Three sites keyed finding identity on the free-text `claim`: the reproduction gate, `merge_findings` and the non-issue key. The #492 dogfood ran three blind auditor runs. They agreed on handles, grade and axis, and only the claim wording differed, so the gate downgraded a structurally stable finding. On real output it promoted almost nothing, and a dismissed non-issue re-surfaced whenever the auditor reworded it. This is the third instance of the #492 rule: a guarantee rested on a volatile input.

**Decision:** a finding's identity is `observation_key = (axis, facet, sorted handles)`. `facet` is a new finding field, a closed per-axis vocabulary in `taxonomy.AXIS_FACETS` (provisional, to be calibrated). `claim` is prose for humans only. One key function feeds two predicates, so they can't drift apart:

- **`findings_equivalent(a, b)`** = same key **and** same grade (spec §10). It stays shared by the gate and `merge_findings`.
- **The non-issue key** hashes `facet:<axis>/<facet>` with the handles. A dismissal survives rewording and grade changes, and re-surfaces when the handles or the facet change.

The axis is part of the key, as the facet's namespace. The old exclusion worked only because claim strings happened to differ. Cross-axis duplicates stay separate by design.

**Honest when the key is unknown.** A finding is unkeyed when its facet is missing, `other` or unlisted, or its axis is open.

- The gate never promotes an unkeyed candidate (no re-dispatch) and never counts an unkeyed re-run finding as a reproduction.
- Merge and the non-issue key fall back to the exact normalised claim, with the axis compared too. That can under-merge, never over-merge.
- `finding_problems` lets the orchestrator reject a seed-axis finding with no valid facet.
- `STATE_VERSION` is not bumped: the change is additive, and old cached findings simply fall back.

**Rejected:**

- handles + grade only, which over-merges distinct observations at one location;
- an LLM semantic judge, which puts non-determinism inside the deterministic gate.

**Anchor:** `pyeye.architecture_review.state` (`observation_key`, `findings_equivalent`, `build_non_issue`, `finding_problems`); `pyeye.architecture_review.gate.apply_reproduction_gate`; `pyeye.architecture_review.taxonomy.AXIS_FACETS` / `FACET_OTHER`; `skills/architecture-review/auditor.md` (facet table, schema); `SKILL.md` steps 2, 3 and 7; spec §10, §14, §15; #498, #492.
**Applies-to:**

- every site that decides whether two findings are "the same" or whether a finding was dismissed: `findings_equivalent` (the gate's default `equivalent`, and `merge_findings`), `build_non_issue` / `non_issue_key`, and `apply_reproduction_gate`'s promotion rule;
- every producer of findings: the `auditor.md` prompt, which must emit `facet`;
- the orchestrator's validation step (SKILL.md step 2).

No other module in `src/pyeye/architecture_review/` compares findings: `ranking` orders and `guard` corroborates. A custom `equivalent=` passed to the gate still cannot promote an unkeyed candidate.
**Verify:** gold. `uv run pytest tests/test_architecture_review_identity.py tests/test_architecture_review_gate.py tests/test_architecture_review_state.py` covers:

- the over-merge regression (same axis, handles and grade with a different facet; and different axes);
- handle-order independence;
- the three-blind-rerun dogfood promoted at the gate and deduped at merge;
- a non-issue that survives rewording and re-surfaces on a handle or facet change;
- an unkeyed finding that is never promoted and never over-merged (missing, `other`, unlisted, wrong-axis and open-axis facets);
- orchestrator validation;
- conformance between `auditor.md`'s facet table and `AXIS_FACETS`.
