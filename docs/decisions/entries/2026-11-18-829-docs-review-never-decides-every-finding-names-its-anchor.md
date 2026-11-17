---
date: "2026-11-18"
title: "/docs-review never decides: every finding names its anchor and gives a way forward, and an unanchored assessment is labelled, not withheld (#829)"
issues: [829, 818]
anchors: ["pyeye.docs_facts.review.finding_problems", "pyeye.docs_facts.review.UNANCHORED", "pyeye.docs_facts.review.triage", "pyeye.docs_facts.review.dismissed_uncovered", "pyeye.docs_facts.review.orphaned", "pyeye.docs_facts.ledger.updated", ".claude/skills/docs-review/SKILL.md", "tests/test_docs_facts_review.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — /docs-review never decides: every finding names its anchor and gives a way forward, and an unanchored assessment is labelled, not withheld (#829)

**Friction:** #818 splits the docs into a fact layer, kept right by the code and CI, and a presentation layer that only judgment can keep usable. A judgment review risks two failure modes:

- the tool deciding for the human: applying, dismissing, or presenting an opinion as settled;
- findings the reviewer must work out how to fix.

`/architecture-review` avoids the first by withholding a recommendation when nothing anchors one. For docs, the maintainer chose differently (D8, C13, C14): a recommendation is an informed assessment, not a choice, so it is given and labelled with what it rests on.

**Decision:**

- **The finding shape is enforced in code, not in prose.** `review.finding_problems` rejects a finding that lacks a page, a section, a category (closed set) or an anchor `{kind, id}` (closed kinds), or whose `fact` anchor names no fact. A finding that fails is never shown.
  - **A clear fix** carries one `replacement` and no options.
  - **A needs-decision finding** carries its `question` and two or three `options`, each with its `cost`. It also carries either a `recommended` option with its `recommendation_anchor`, or an `assessment` starting `unanchored: judgment only`. A replacement on it is rejected, because that would present the choice as settled.
- **Nothing is applied.** The skill's loop presents findings verbatim. Only the human accepts, dismisses or chooses, and an edit is made only on their explicit instruction.
- **State reuses `architecture_review.state` (D7), in `docs/facts/review-state.json`.**
  - A "section is fine" verdict is a coverage entry over the section's text and its facts' values, and `is_stale` decides re-review.
  - A dismissal is a `non_issue_key` over `page#section` plus the category and anchor, pinned to the anchor fact's value. Rewording keeps it dismissed, and a value change brings it back as `resurfaced`.
  - Finding identity never uses prose (#498).
- **Deliberately-not-covered facts (C13)** are dismissed once, in the review state. `docs_facts generate` leaves them out of the ledger's uncovered entries and copies them into its read-only `dismissed` section. A dismissal lapses when its fact's value changes.
- **Orphans fail (C14).** `docs_facts check` fails on a dismissal whose fact no longer exists. The PR that removes or renames the fact removes or moves it.
- **Internal.** The skill lives in `.claude/skills/docs-review/`, and the script is `scripts/docs_review.py`. There is no MCP tool and no public surface, so there is no changelog fragment. Shipping it, with task scoring and the release hook, is #830.

**Anchor:** `pyeye.docs_facts.review.finding_problems`; `pyeye.docs_facts.review.triage`; `pyeye.docs_facts.ledger.updated`; design D6–D8, C13, C14; #829, #818.
**Applies-to:**

- the review principle and shape: `pyeye.docs_facts.review.finding_problems`, `pyeye.docs_facts.review.UNANCHORED`, `.claude/skills/docs-review/SKILL.md`, `.claude/skills/docs-review/reviewer.md`;
- state and dismissals: `pyeye.docs_facts.review.dismiss_finding`, `dismiss_uncovered`, `dismissed_uncovered`, `triage`, `mark_reviewed`, `needs_review`, `orphaned`;
- the ledger and check: `pyeye.docs_facts.ledger.updated`, `pyeye.docs_facts.cli.plan`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_review.py` passes:

- every D8, C13 and C14 rejection path of `finding_problems`;
- identity that ignores prose;
- fence-aware sections;
- freshness against text and fact changes;
- dismissals that survive rewording and resurface on a value change;
- `review-after` only with a supplied date;
- ledger dismissal and lapse;
- `check` failing on an orphan;
- scope by page, audience and changed fact;
- every command-line path.

The skill's "the human decides" loop is prose that only review can confirm.
