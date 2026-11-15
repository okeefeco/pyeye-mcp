---
date: "2026-06-13"
title: "decisions captured as an append-only log, not one ADR file per decision"
issues: []
anchors: ["docs/decisions/DECISIONS.md"]
status: "superseded"
amends: []
supersedes: []
amended_by: []
superseded_by: ["2026-11-15-679-one-file-per-decision-with-no-committed-index.md"]
---

## 2026-06-13 — decisions captured as an append-only log, not one ADR file per decision

**Friction:** Per-file ADRs (`NNNN-slug.md`) are ceremony that rots; the goal is the lowest friction that still yields retrievable, verifiable facts (avoid the ADR graveyard).
**Decision:** A single append-only `docs/decisions/DECISIONS.md`, newest on top, one short entry per distinct decision (Friction · Decision · Anchor · Verify). Rejected: one ADR file per decision; commit-trailer-only (buried in git history).
**Anchor:** `docs/decisions/DECISIONS.md` ; `skills/decision-log/SKILL.md` ("File Convention")
**Verify:** gold — `head -1 docs/decisions/DECISIONS.md` equals `# Decision Log`; entries are `##` headings carrying the four bold fields Friction/Decision/Anchor/Verify.
