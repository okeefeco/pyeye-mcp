---
date: "2026-06-13"
title: "decision-log fires at the commit checkpoint, not ambient AI vigilance"
issues: []
anchors: []
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-13 — decision-log fires at the commit checkpoint, not ambient AI vigilance

**Friction:** An ambient "agent watches for significant changes and pipes up" trigger decays — the agent is heads-down on the task and catches the moment inconsistently (the same reason "always do X" instructions lapse).
**Decision:** Anchor the trigger to the commit — a deterministic pause with the diff already on the table — via the `smart-commit` agent, plus on-demand ("log this decision"). Rejected: always-on agent vigilance.
**Anchor:** `skills/decision-log/SKILL.md` ("When This Fires") ; `.claude/agents/smart-commit.md`
**Verify:** PARTIAL — `grep -q "commit checkpoint" skills/decision-log/SKILL.md` and a decision-note step exists in `.claude/agents/smart-commit.md` confirm the documented trigger. Whether it *actually* fires reliably is behavioural — human-observed over time [unverifiable mechanically].
