---
date: "2026-11-18"
title: "/docs-review: finding identity equals dismissal identity, findings carry the page hash, and proposed wording meets the rules it enforces (#829-3)"
issues: [829, 818, 830]
anchors: ["pyeye.docs_facts.review.finding_key", "pyeye.docs_facts.review.batch_problems", "pyeye.docs_facts.review.page_hash", "pyeye.docs_facts.review.proposal_problems", "pyeye.docs_facts.review.mentioned_facts", "pyeye.docs_facts.review.RULE_IDS", "tests/test_docs_facts_review.py"]
status: "amended"
amends: ["2026-11-18-829-code-contradictions-and-subject-keyed-dismissals.md"]
supersedes: []
amended_by: ["2026-11-18-829-page-level-findings-literal-anchors-and-code-bug-routes.md"]
superseded_by: []
---

## 2026-11-18 — /docs-review: finding identity equals dismissal identity, findings carry the page hash, and proposed wording meets the rules it enforces (#829-3)

**Friction:** the first real `/docs-review` runs (worker-2 on the history pages, worker on the README, worker-4 on seven API and architecture pages) found rough edges:

- Findings were keyed without their subject, so two broken links in one section looked like one finding while their dismissals stayed two. Designer's point: a dismissal could cover a finding it never saw.
- A README edit during a review silently staled around twenty slugs and lines.
- A proposed replacement still carried "~17,500/~527 bytes" and "0.03×": the tool proposed the overclaim it was meant to remove.
- Packets listed only the facts a page binds, so a hand-restated env var couldn't be anchored.
- Reviewers had no rule ID for a plain unbacked measurement, or for a correct statement of code behaviour that belongs in a fact or example. They stretched `D12-comparison` and `link-not-restate`.
- The honest-claims seeds had to be handed to reviewers by hand.

**Decision** (builder calls, cleared with designer):

- **Finding identity equals dismissal identity.** `finding_key` is page, section, category and anchor, plus the `subject` for a rule anchor: the same identity `_structural_fact` gives a dismissal, without its pin. A test checks they agree for fact, symbol and rule anchors. `validate` rejects a second finding with the same key in one batch.
- **`page_hash`.** A packet carries the page's content hash, and every finding echoes it. `validate` rejects a finding against a page that changed since scope, naming the page and saying to re-run scope for it.
- **Proposed wording meets the rules it enforces.** `proposal_problems` runs the D12 honest-claims patterns (`claims.claims`) over the replacement and every option's text. For a fact-anchored finding, it rejects wording that hand-writes the anchor fact's value outside a fact block (C15).
- **Packets carry more:** the page's `claim_seeds` (#830's core), and `mentioned`, the registry facts the page names but doesn't bind. An anchor uses the item fact ID, not a view such as `….default`.
- **Two rule IDs join the closed sets.** `claims_rule:D12-measurement` covers an unbacked measurement or measurement table. `style_rule:restated-code` covers a correct statement of what the code does that belongs in a bound fact or an executed example (C15).
- **`reviewer.md` states the rules itself:** C15, C16, D12 and the proposal rule; one finding per identity and per section; and that the orchestrator, not the reviewer, runs `validate`.
- **Unchanged:** worker-3's #871 removes the #857 alias guard and its strict xfail once #857 is fixed.

**Anchor:** `pyeye.docs_facts.review.finding_key`, `batch_problems`, `page_hash`, `proposal_problems`, `mentioned_facts`; #829, #830.
**Applies-to:**

- identity: `pyeye.docs_facts.review.finding_key`, `pyeye.docs_facts.review.batch_problems`;
- staleness: `pyeye.docs_facts.review.page_hash`, `pyeye.docs_facts.review.packet`, `_location_problems`;
- proposals: `pyeye.docs_facts.review.proposal_problems`;
- packets: `pyeye.docs_facts.review.mentioned_facts`, `pyeye.docs_facts.review.packet`;
- rule IDs: `pyeye.docs_facts.review.RULE_IDS`, `.claude/skills/docs-review/reviewer.md`, `.claude/skills/docs-review/SKILL.md`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_review.py` passes:

- `TestFeedback829_3`: identity agreement for every anchor kind, two links as two findings, a repeat rejected, a changed page rejected, packets carrying the hash and seeds, `D12-measurement`, and `validate` reporting a repeat;
- `TestProposalsMeetTheRules`: unbacked claims in a replacement or an option are rejected, a restated fact value is rejected, and a fact block is accepted;
- the mentioned-facts tests, including worker-4's `caching.md` case.
