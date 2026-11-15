---
date: "2026-06-13"
title: "decision-log ships in the pyeye plugin, not ~/.claude/skills"
issues: []
anchors: []
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-13 — decision-log ships in the pyeye plugin, not ~/.claude/skills

**Friction:** A loose `~/.claude/skills/` file is unmanaged — not versioned, lost on a machine move, not shareable — and it split the work across two homes (user dir + repo).
**Decision:** Bundle the skill in the pyeye plugin's `skills/` (alongside `python-explore`) so it ships, versions, and reinstalls with pyeye while staying globally available. Keep the pyeye-dependency *soft* — `Verify` tiers allow grep / import-linter / tests / human, not just pyeye. Rejected: loose user-level skill.
**Anchor:** `skills/decision-log/SKILL.md` ; `.claude-plugin/plugin.json` ; this session
**Verify:** gold — `test -f skills/decision-log/SKILL.md && ! test -e ~/.claude/skills/decision-log` (skill present in plugin, no shadow copy).
