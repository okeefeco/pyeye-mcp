---
date: "2026-11-15"
title: "The cross-derivation guard has a third verdict, cannot_confirm, for unresolvable facts (#499)"
issues: [499, 494, 629]
anchors: ["pyeye.architecture_review.guard.apply_cross_derivation_guard", "pyeye.architecture_review.guard.corroborate_imports", "pyeye.architecture_review.guard.CANNOT_CONFIRM", "skills/architecture-review/SKILL.md"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — The cross-derivation guard has a third verdict, cannot_confirm, for unresolvable facts (#499)

**Friction:** The guard's corroborator was a `bool`: corroborated (keep `deterministic_single`) or divergent (downgrade and flag `possible_extractor_bug`). When the `imports` edge reports an import in `unresolved_imports` (#494), or the source doesn't parse, the honest answer is "couldn't decide". A `bool` forced that into one of the two confident answers. Read as agreement, it silently passed a fact nobody verified. Read as divergence, it raised a false extractor-bug flag. Both are the #494 failure class.

**Decision:** the verdict has three states, `"corroborated"`, `"divergent"` and `"cannot_confirm"`. `True`/`False` stay accepted as aliases, and any other value raises `ValueError` so it can't be misread.

- `cannot_confirm` rewrites the grade to `ambiguous` and adds `corroboration: "cannot_confirm"`, with **no** `possible_extractor_bug`. The finding is unpromoted, for human review.
- `divergent` keeps its behaviour and now also carries `corroboration: "divergent"`.
- `corroborate_imports(claimed, unresolved, file)` implements the mapping for import facts:
  - A source that doesn't read or parse is `cannot_confirm`.
  - An invented import, or a dropped import that no `unresolved_imports` target accounts for, is `divergent`. A real divergence wins.
  - Otherwise any unresolved import is `cannot_confirm`, and agreement with nothing unresolved is `corroborated`.
- Rejected: treating unresolved as agreement (the silent pass), or as divergence (it blames the extractor for an honest disclosure).

**Anchor:** `pyeye.architecture_review.guard` (`apply_cross_derivation_guard`, `corroborate_imports`, `CORROBORATED` / `DIVERGENT` / `CANNOT_CONFIRM`); `skills/architecture-review/SKILL.md` step 4.2; #499, #494.
**Applies-to:** every `corroborate_fn` passed to `apply_cross_derivation_guard`. Today that is the orchestration in `skills/architecture-review/SKILL.md` (step 4.2), which wires `corroborate_imports` for import / layering facts. `corroborate_imports` is the only concrete corroborator. A future corroborator for another fact type (e.g. an LSP-derived one) must return `cannot_confirm` when its derivation fails, never a `bool` guess.
**Verify:** partial. `uv run pytest tests/test_architecture_review_guard.py` covers all three verdicts, the bool aliases, rejection of unknown verdicts, and every branch of `corroborate_imports` (the unparseable source, unreadable file, and a real divergence beside an unresolved import), plus the #499 acceptance test. The residue: no test sweeps the orchestrator's choice of corroborator, because the orchestration lives in skill prose, not code.
