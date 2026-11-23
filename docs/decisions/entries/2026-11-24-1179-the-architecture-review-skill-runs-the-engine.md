---
date: "2026-11-24"
title: "The architecture-review skill runs the engine; every resolution is a decision entry (#1179)"
issues: [1179, 1132, 1178, 1181]
anchors: [".claude/skills/architecture-review/SKILL.md", ".claude/skills/architecture-review/reviewer.md", "tests/test_docs_facts_skills.py", "tests/test_architecture_review_skill_loop.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-24 — The architecture-review skill runs the engine; every resolution is a decision entry (#1179)

**Friction:** after #1178 the engine compares an area with its recorded architecture, but the shipped `architecture-review` skill still ran the old audit. That audit had the auditor fan-out, seven axes and four grades, the reproduction gate and the cross-derivation guard, stakes-bucket ranking, and dismissals in a state file. #1132's audit found it costly and hard to run. #1132 R7 also says a resolution must be a decision entry, not a dismissal.

**Decision:** assigned by coordinator-3 (2026-11-24, scope option A). The `.claude/` edits need the user's direct approval in the editing session before they are pushed.

- **The skill keeps its name** and is rewritten around the engine: `plan AREA` → one fresh reviewer (`reviewer.md`, replacing `auditor.md`) over the packet → `validate`, with rejections sent back and never fixed up → `report`, presented verbatim in its tiers.
- **The reviewer** reads only the packet:
  - it confirms or refutes each candidate decision and each convention section, as adherence or deviation;
  - it reports a pattern no record covers as a decision needed or an ambiguity, with prevalence as evidence;
  - it never makes a `rule` finding, since rules are mechanical.
- **Codify**, always on the user's decision:
  - a decision entry through `decision-log`, whose `Applies-to` names the governed sites by canonical handle, so the next plan finds it as a candidate;
  - where `CHECK no-import: A -> B` can express the decision, a drafted `CHECK` line for the area's architecture page, added only on confirmation.

  A decision no existing rule kind can express stays an entry. No new rule kind is invented.
- **No dismissals.** "Both patterns are acceptable" is a decision entry too. A deferral is recorded nowhere and is reported again.
- **Removed facts:** the skill no longer binds the old taxonomy's `review.*` facts. They enter the uncovered ledger as `new` until #1181 removes their extractor along with `taxonomy`, `ranking`, `gate` and `guard`. The identity test's `auditor.md` check is deleted with the file. The rest of that test file goes with the taxonomy (#1181).

**Anchor:** `.claude/skills/architecture-review/SKILL.md`, `.claude/skills/architecture-review/reviewer.md`; `tests/test_docs_facts_skills.py` (`TestArchitectureReview`), `tests/test_architecture_review_skill_loop.py`; #1179, #1132.

**Applies-to:**

- the shipped skill: `.claude/skills/architecture-review/SKILL.md` and `.claude/skills/architecture-review/reviewer.md`, and its conformance tests `tests/test_docs_facts_skills.py` and `tests/test_architecture_review_skill_loop.py`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_skills.py tests/test_architecture_review_skill_loop.py` passes. It checks:

- the skill and the reviewer explain all four outcomes;
- the skill runs the engine's commands, says the engine's no-architecture note, codifies through `decision-log` and a `CHECK` line, and has no dismissals;
- every example finding in `reviewer.md` passes the engine's validator;
- end to end on the engine's fixture repository, a codified item comes back as an adherence candidate on the next run, a drafted `CHECK` line runs mechanically, and a deferred item is reported again.
