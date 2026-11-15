---
date: "2026-11-15"
title: "One file per decision, with no committed index; supersedes the append-only log (#679)"
issues: [679, 629]
anchors: ["docs/decisions/entries/", "scripts/decisions.py", "docs/decisions/DECISIONS.md", "skills/decision-log/SKILL.md"]
status: "active"
amends: []
supersedes: ["2026-06-13-decisions-captured-as-an-append-only-log-not-one-adr-file.md"]
amended_by: []
superseded_by: []
---

## 2026-11-15 — One file per decision, with no committed index; supersedes the append-only log (#679)

**Friction:** The single append-only `DECISIONS.md` (decided 2026-06-13) grew to 52 entries, 599 lines and about 135 KB (about 34k tokens).

- **Agents, the primary readers, couldn't read it whole**, so they grepped it. Grep misses a decision whose relevance shows only in its title or its Applies-to list, which is the "rule applied only where the friction showed up" failure the #629 audit found. Whether an entry still held (amended or superseded) was discoverable only by reading down the log.
- **Every PR added an entry at the same place**, the top, so nearly every merge in epic #629 hit a DECISIONS conflict and needed an extra worker merge plus a CI cycle. Changelog fragments (#660) fixed the CHANGELOG half of that.

**Decision:** one file per decision, `docs/decisions/entries/YYYY-MM-DD-<issue>-<slug>.md`, with front matter (`date`, `title`, `issues`, `anchors` for the governed symbols, `status`, and `amends` / `supersedes` / `amended_by` / `superseded_by` links). **Nothing generated is committed.**

- The directory is the index.
- `scripts/decisions.py index` (filters `--symbol`, `--issue`, `--active`, `--status`) builds a newest-first table from the front matter at run time. Agents run it first, then open the one to three entries that matter.
- `scripts/decisions.py check`, run in CI and pre-commit, validates the front matter, the name format and that every link resolves and is symmetric.
- `DECISIONS.md` becomes a short static header.
- Amending or superseding is the only edit to an existing file, and only to its front matter. That is rare, and a conflict there is a real one.
- The entry format is unchanged (Friction · Decision · Anchor · Applies-to · Verify). The original decision's concern, ceremony that rots, still holds and is still met: only the storage changed, and an entry is as short as before.
- The 52 existing entries were split verbatim, with a lossless check (header plus bodies reassembled in the original order equals the original file). Status and links come from each entry's own "amends …" text.
- Rejected: a committed generated index, which every PR would edit and which would conflict again, and per-file numbered ADRs with templates (the ceremony the original decision avoided).

**Anchor:** `docs/decisions/entries/`; `scripts/decisions.py` (`index`, `check`); `docs/decisions/DECISIONS.md` (static header); `skills/decision-log/SKILL.md` ("File Convention"); #679, #629.
**Applies-to:** every decision entry, including all 52 migrated ones, and every writer and reader of the log: the `decision-log` skill, the `architecture-review` skill's Tier-3 baseline, the smart-commit agent's decision-log step, `scripts/decision_log_nudge.py`, `.claude/instructions`, and CI (`changelog-validation`) plus the pre-commit `decisions-check` hook.
**Verify:** gold. `python scripts/decisions.py check` exits 0, and `uv run pytest tests/test_decisions_script.py` passes:

- every entry parses, is well named and is linked symmetrically;
- `check` rejects bad front matter, a dangling link, an asymmetric link, a wrong status and a mismatched heading;
- `index` filters work;
- this entry supersedes the 2026-06-13 one;
- `DECISIONS.md` holds no entry headings;
- the decision-log skill documents `docs/decisions/entries/` and `scripts/decisions.py`.
