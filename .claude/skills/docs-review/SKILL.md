---
name: docs-review
description: Use when reviewing pyeye's own documentation for usability and honesty — "review the docs", "docs review", "check the pages bound to the facts this PR changed", "work down the uncovered-fact ledger", "/docs-review". Reviews registered pages over a caller-supplied scope with a fresh-context reviewer, and returns findings that each name their anchor and give a way forward. Nothing is ever applied automatically. Internal to this repo (not shipped). Does NOT check facts (that is `docs_facts check`), and does NOT audit code conventions (architecture-review) or copies (duplication-review).
---

# Docs Review (internal)

Review the hand-written documentation for what a fact check can't see: prose
that misleads, overclaims, or doesn't serve its audience. This is the
presentation layer of #818: facts come from the code and `docs_facts check`
keeps them right, while this review keeps the prose usable. It sits beside
`architecture-review` and `duplication-review` and reuses their state machinery
(D7).

## The Review Principle — Read First

- **The tool never decides.** A finding is a recommendation or a set of options,
  never an edit. Nothing is applied, codified or dismissed without the human.
- **Every finding names its anchor**: the fact ID, the code symbol (its
  canonical pyeye handle, for prose the code contradicts), the D12 clause, the
  audience rule or the style rule it rests on.
- **Every finding gives a way forward:**
  - **a clear fix** (plain fact drift, a broken link) carries one proposed
    replacement text, and no options;
  - **genuine ambiguity** carries `needs_decision`, the question it needs
    answered, and two or three options, each with its cost. It recommends one
    and names the recommendation's anchor whenever an anchor exists. When none
    exists it still gives an assessment, labelled `unanchored: judgment only`,
    never presented as settled.

This differs from `architecture-review`, which withholds a recommendation when
nothing anchors one. Here an unanchored assessment is still given, and labelled.
`scripts/docs_review.py validate` enforces the shape; a finding that fails it is
never shown.

## Scope Is Required

There is no default scope. Pick one of:

- **Change-triggered:** `scope --base origin/main`. It selects every page that
  binds or covers a fact added or changed since the base, plus the ledger's new
  uncovered facts. Run it for a PR that changed facts.
- **On demand:** `scope <pages or globs>` and/or `scope --audience human|claude|both`.

The release-time full pass with task scoring is not part of this internal skill
yet (#830).

## Running It

All mechanics are in `scripts/docs_review.py` (logic in
`pyeye.docs_facts.review`). Every command prints JSON.

| Command | Does |
|---|---|
| `scope [PAGES…] [--audience A] [--base REF]` | Reviewer packets: per page, its audience, kind, facts and sections, each section marked `needs_review` or not. |
| `validate FINDINGS.json [--today D]` | Rejects any finding without its anchor or a way forward (exit 1); otherwise gives each one's status. |
| `mark-fine PAGE SECTION --date D` | Records a section as reviewed and fine. |
| `dismiss FINDINGS.json --index N --reason R --date D [--review-after D]` | Records one finding as dismissed. |
| `dismiss-uncovered FACT --reason TEXT --date D` | Records a fact as deliberately not covered. |
| `move KEY NEW` | Carries an orphaned or lapsed dismissal over to its anchor's new form: the new fact ID, the new canonical handle, or the reworded subject. |
| `forget KEY` | Deletes a dismissal, e.g. one whose fact was removed. |

State lives in `docs/facts/review-state.json`. Commit it, so the whole team
shares the verdicts. Dates are always supplied by the caller; nothing reads a clock.

## The Review Loop

1. **Scope.** Run `scope` and read the packets. Skip sections whose
   `needs_review` is false: they were marked fine and neither their text nor
   their facts have changed since.
2. **Dispatch the reviewer**, one fresh subagent per page, with
   [`reviewer.md`](reviewer.md) and that page's packet. It reads the page with
   targeted reads and returns a JSON array of findings, nothing else.
3. **Validate.** You run it, never the reviewer. Write the findings to a
   scratch file and run `validate`. A finding with problems goes back to the
   reviewer with the problems quoted; never fix it up yourself.
   - "page … changed since scope": the page changed under the review. Re-run
     `scope` for that page and send the reviewer its fresh packet.
   - A repeated finding (same page, section, category, anchor and, for a rule
     anchor, subject) is rejected: there is one finding per identity, the same
     identity dismissals use.
   - Proposed wording is checked against the rules too: an unbacked claim, or
     a hand-written value of the anchor fact, is rejected.
4. **Present** each shown finding to the human verbatim, with its status:
   - `new`: not seen before;
   - `resurfaced`: dismissed before, but its anchor fact's value changed;
   - `review-due`: a dismissal whose `review_after` date has come.

   Lead with `fact_drift`, `code_contradiction` and `honest_claims` findings,
   then `audience`, then `style`.
5. **The human decides**, per finding:
   - **accept**: the human edits the page, or tells you to apply the proposed
     text. Only on that explicit instruction, and only that text;
   - **dismiss**: `dismiss` with a reason (`fine`, `deliberate`, `other`);
   - **choose an option**, for a needs-decision finding.
6. **Mark sections fine** with `mark-fine`, only for sections the human agrees
   need nothing.
7. **Uncovered facts** (from the scope's `uncovered` list): for each, either
   propose where prose should explain it (an `uncovered_fact` finding with a
   replacement, anchored on the fact), or, if the human says it deliberately
   needs no prose, `dismiss-uncovered` with their reason. Then run
   `uv run python scripts/docs_facts.py generate`, which moves the fact to the
   ledger's read-only `dismissed` section.

## Dismissals

- A dismissed finding stays dismissed when it is reworded: identity is the page,
  section, category and anchor, never the prose. For a rule anchor (claims,
  audience, style) its quoted `subject` is part of the identity too, so
  dismissing one broken link doesn't hide a different one added later.
- It returns as `resurfaced` when what it rests on changes: the anchor fact's
  value, or the anchored symbol's signature or docstring as pyeye reports them
  (a body edit doesn't count).
- A "deliberately not covered" fact returns to the ledger when its value changes.
- A heading rename resets that section: its "fine" verdict and its dismissals are
  pruned on the next state write (the command output lists them), so its
  findings come back for review rather than staying hidden.
- A dismissal whose quoted subject no longer occurs in its section has lapsed:
  `check` stays green, the next command here prunes it (the output lists it),
  and its finding may come back. Editing prose never means touching the state.
- `docs_facts check` fails on a dismissal whose fact no longer exists or whose
  symbol no longer resolves. The PR that made the change fixes it: `move KEY NEW`
  for a rename, `forget KEY` otherwise. The failure message gives both commands
  with the key.

## Honest Limits

- The review is judgment, not verification. Its findings say what they rest on
  so the human can check them.
- It sees only registered pages (the doc registry) and never generated
  reference pages.
- Fact values are checked mechanically elsewhere. A reviewer that "finds" a
  wrong value in a fact block has found a `docs_facts` bug: report it as an
  issue, not a finding.
