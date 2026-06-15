# Decision Log

Contract/invariant-significant, friction-driven decisions. Each entry is a small verifiable fact: Friction · Decision · Anchor (stable ref) · Verify (checkable or honestly-labelled). Newest on top. Maintained via the `decision-log` skill.

## 2026-06-13 — decision-log ships in the pyeye plugin, not ~/.claude/skills

**Friction:** A loose `~/.claude/skills/` file is unmanaged — not versioned, lost on a machine move, not shareable — and it split the work across two homes (user dir + repo).
**Decision:** Bundle the skill in the pyeye plugin's `skills/` (alongside `python-explore`) so it ships, versions, and reinstalls with pyeye while staying globally available. Keep the pyeye-dependency *soft* — `Verify` tiers allow grep / import-linter / tests / human, not just pyeye. Rejected: loose user-level skill.
**Anchor:** `skills/decision-log/SKILL.md` ; `.claude-plugin/plugin.json` ; this session
**Verify:** gold — `test -f skills/decision-log/SKILL.md && ! test -e ~/.claude/skills/decision-log` (skill present in plugin, no shadow copy).

## 2026-06-13 — decision-log fires at the commit checkpoint, not ambient AI vigilance

**Friction:** An ambient "agent watches for significant changes and pipes up" trigger decays — the agent is heads-down on the task and catches the moment inconsistently (the same reason "always do X" instructions lapse).
**Decision:** Anchor the trigger to the commit — a deterministic pause with the diff already on the table — via the `smart-commit` agent, plus on-demand ("log this decision"). Rejected: always-on agent vigilance.
**Anchor:** `skills/decision-log/SKILL.md` ("When This Fires") ; `.claude/agents/smart-commit.md`
**Verify:** PARTIAL — `grep -q "commit checkpoint" skills/decision-log/SKILL.md` and a decision-note step exists in `.claude/agents/smart-commit.md` confirm the documented trigger. Whether it *actually* fires reliably is behavioural — human-observed over time [unverifiable mechanically].

## 2026-06-13 — decisions captured as an append-only log, not one ADR file per decision

**Friction:** Per-file ADRs (`NNNN-slug.md`) are ceremony that rots; the goal is the lowest friction that still yields retrievable, verifiable facts (avoid the ADR graveyard).
**Decision:** A single append-only `docs/decisions/DECISIONS.md`, newest on top, one short entry per distinct decision (Friction · Decision · Anchor · Verify). Rejected: one ADR file per decision; commit-trailer-only (buried in git history).
**Anchor:** `docs/decisions/DECISIONS.md` ; `skills/decision-log/SKILL.md` ("File Convention")
**Verify:** gold — `head -1 docs/decisions/DECISIONS.md` equals `# Decision Log`; entries are `##` headings carrying the four bold fields Friction/Decision/Anchor/Verify.
