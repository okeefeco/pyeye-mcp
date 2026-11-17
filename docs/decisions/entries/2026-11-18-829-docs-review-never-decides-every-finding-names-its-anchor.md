---
date: "2026-11-18"
title: "/docs-review never decides: every finding names its anchor and gives a way forward, and an unanchored assessment is labelled, not withheld (#829)"
issues: [829, 818]
anchors: ["pyeye.docs_facts.review.finding_problems", "pyeye.docs_facts.review.UNANCHORED", "pyeye.docs_facts.review.triage", "pyeye.docs_facts.review.dismissed_uncovered", "pyeye.docs_facts.review.orphaned", "pyeye.docs_facts.ledger.updated", ".claude/skills/docs-review/SKILL.md", "tests/test_docs_facts_review.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-18-829-code-contradictions-and-subject-keyed-dismissals.md"]
superseded_by: []
---

## 2026-11-18 — /docs-review never decides: every finding names its anchor and gives a way forward, and an unanchored assessment is labelled, not withheld (#829)

**Friction:** #818 splits the docs into a fact layer, kept right by the code and CI, and a presentation layer that only judgment can keep usable. A judgment review risks two failure modes:

- the tool deciding for the human: applying, dismissing, or presenting an opinion as settled;
- findings the reviewer must work out how to fix.

`/architecture-review` avoids the first by withholding a recommendation when nothing anchors one. For docs, the maintainer chose differently (D8, C13, C14): a recommendation is an informed assessment, not a choice, so it is given and labelled with what it rests on.

**Decision:**

- **The finding shape is enforced in code, not in prose.** `review.finding_problems` rejects a finding that lacks a page, a section, a category (closed set) or an anchor `{kind, id}`, which must be of the kind its category rests on. A reviewer can't invent an anchor: a `fact` anchor must name a real fact, and a rule anchor must be one of `review.RULE_IDS` (the D12 clauses, the audience rules, the sweep's style categories). With the repo root, the page must be registered and the section must be one of its slugs. The recommendation anchor is checked the same way. A finding that fails is never shown.
  - **A clear fix** carries one `replacement` and none of the decision fields: options, question, assessment or recommendation.
  - **A needs-decision finding** carries its `question` and two or three `options`, each with its `cost`. It also carries either a `recommended` option with its `recommendation_anchor`, or an `assessment` starting `unanchored: judgment only`. A replacement on it is rejected, because that would present the choice as settled.
- **Nothing is applied.** The skill's loop presents findings verbatim. Only the human accepts, dismisses or chooses, and an edit is made only on their explicit instruction.
- **State reuses `architecture_review.state` (D7), in `docs/facts/review-state.json`.**
  - A "section is fine" verdict is a coverage entry over the section's text and its facts' values, and `is_stale` decides re-review.
  - A dismissal is a `non_issue_key` over `page#section` plus the category and anchor, pinned to the anchor fact's value. Rewording keeps it dismissed, and a value change brings it back as `resurfaced`.
  - Finding identity never uses prose (#498).
- **Deliberately-not-covered facts (C13)** are dismissed once, in the review state. `docs_facts generate` leaves them out of the ledger's uncovered entries and copies them into its read-only `dismissed` section. A dismissal lapses when its fact's value changes.
- **Orphans fail (C14), with a message anyone can act on.** `docs_facts check` fails on a dismissal whose fact no longer exists. Whoever removed or renamed the fact may not know dismissals exist, so the message names the fact, `docs/facts/review-state.json` and what the dismissal was for, and gives both fixes as commands: `scripts/docs_review.py move KEY NEW_FACT` for a rename, `forget KEY` for a removal. `move` refuses a dismissal whose fact still exists, so it can't re-point a live dismissal at an unrelated fact. It keeps the old value pin, so a rename that also changed the value lapses. Coverage entries and finding dismissals whose page or section is gone (a renamed heading) are pruned on every state write, not failed on.
- **A bad `--base` is an error, never the whole repo.** If the base revision has no snapshot, `scope` says so instead of treating every fact as added.
- **Internal.** The skill lives in `.claude/skills/docs-review/`, and the script is `scripts/docs_review.py`. There is no MCP tool and no public surface, so there is no changelog fragment. Shipping it, with task scoring and the release hook, is #830.

**Anchor:** `pyeye.docs_facts.review.finding_problems`; `pyeye.docs_facts.review.triage`; `pyeye.docs_facts.ledger.updated`; design D6–D8, C13, C14; #829, #818.
**Applies-to:**

- the review principle and shape: `pyeye.docs_facts.review.finding_problems`, `pyeye.docs_facts.review.UNANCHORED`, `.claude/skills/docs-review/SKILL.md`, `.claude/skills/docs-review/reviewer.md`;
- state and dismissals: `pyeye.docs_facts.review.dismiss_finding`, `dismiss_uncovered`, `dismissed_uncovered`, `triage`, `mark_reviewed`, `needs_review`, `orphaned`, `forget`, `move`;
- the ledger and check: `pyeye.docs_facts.ledger.updated`, `pyeye.docs_facts.cli.plan`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_review.py` passes:

- every D8, C13 and C14 rejection path of `finding_problems`;
- identity that ignores prose;
- fence-aware sections;
- freshness against text and fact changes;
- dismissals that survive rewording and resurface on a value change;
- `review-after` only with a supplied date;
- ledger dismissal and lapse;
- `check` failing on an orphan, with the exact message pinned, and `move` and `forget` fixing it;
- scope by page, audience and changed fact;
- every command-line path.

The skill's "the human decides" loop is prose that only review can confirm.
