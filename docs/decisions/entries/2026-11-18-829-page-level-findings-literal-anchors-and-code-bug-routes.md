---
date: "2026-11-18"
title: "/docs-review C17: page-level findings, literal anchors, code_bug and link/delete routes, and closed rule IDs for the real runs (#829-4)"
issues: [829, 818, 830]
anchors: ["pyeye.docs_facts.review.PAGE", "pyeye.docs_facts.review.src_literals", "pyeye.docs_facts.review.lift_blocked", "pyeye.docs_facts.review.ROUTES", "pyeye.docs_facts.review.RULE_IDS", "pyeye.docs_facts.review.main", "tests/test_docs_facts_review.py"]
status: "active"
amends: ["2026-11-18-829-finding-identity-equals-dismissal-identity-and-proposals-meet-the-rules.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — /docs-review C17: page-level findings, literal anchors, code_bug and link/delete routes, and closed rule IDs for the real runs (#829-4)

**Friction:** the real `/docs-review` runs found things the finding model couldn't express:

- a defect spanning a whole page (a page describing a test suite that doesn't exist);
- a misquoted error message or log line, which is neither a fact nor a symbol;
- docs that are right about code that is wrong;
- a stale test-helper name that should just link the helper file, and a dead section that should go;
- contradictory directives;
- volatile status and bare numbers, which reviewers stretched other D12 IDs to cover.

`validate` also printed Jedi log lines before its JSON, and reported no counts.

**Decision** (the maintainer's C17, and builder calls from the run feedback):

- **Page-level findings.** Section `"*"` is a page-wide finding: its section text is the whole page, and its dismissal lives as long as the page does. `fact_drift` and `uncovered_fact` are always clear fixes in one section, so `validate` rejects `"*"` on them.
- **The `literal` anchor.** A runtime string (an error message, a log line) by its exact text, for a `code_contradiction`. `validate` checks it against the string literals parsed from `src/` with `ast`, f-string constant parts included, so a comment or a partial match doesn't satisfy it. The dismissal is keyed on the string; a string gone from `src/` is an orphan (C14), and `move` takes the new string. Labels and tags go under a rule anchor, with the label as the subject.
- **Routes.** In preference order: `fact`, `example`, `link` (with the repo file to link), `delete`, `code_bug` (with `blocked_by: "#N"`) and `wording`.
  - A `code_bug` finding is for docs that are right about code that is wrong. The human files or approves the issue and dismisses the finding as deliberate. `lift-blocked` (via `gh`) lifts the dismissal once the issue closes, so the finding returns; offline it changes nothing.
  - `reviewer.md` lists the registered extractor names for the `fact` route, and a test keeps that list equal to `EXTRACTORS`. CLI and library code has no example harness, so it takes `wording`, saying so.
- **Closed rule IDs.**
  - `claims_rule`: `D12-volatile` and `D12-number`.
  - `audience_rule`: `contradictory-directive`, which is always `needs_decision`: keep one directive and link to it from the other.
  - `style_rule`: `duplicated-prose` replaces `duplication`. The fix is a one-line pointer and a link to the page that owns the subject. It is reviewer judgement only: C17 chose that over a mechanical check.
- **One finding per fact.** A sentence restating several facts is one finding per fact. Any registered fact or view may be an anchor, and packets now list the views their blocks bind.
- **`validate` stdout is JSON only.** Work runs with stdout redirected to stderr, so log lines can't corrupt it. It reports `ok`, `accepted` and `rejected`, and exits 1 on any rejection.
- **Out of scope here, assigned elsewhere:** the facts for pre-commit hook IDs and CI flags (worker-4, #830), and widening the executed-examples fence (worker-3). `reviewer.md` points reviewers at both rulings.

**Anchor:** `pyeye.docs_facts.review.PAGE`, `src_literals`, `lift_blocked`, `ROUTES`, `RULE_IDS`, `main`; design C17; #829, #830.
**Applies-to:**

- page-level: `pyeye.docs_facts.review.PAGE`, `section_text`, `_location_problems`, `prune`;
- literals: `pyeye.docs_facts.review.src_literals`, `Symbols.has_literal`, `_orphan_reason`, `move`;
- routes: `pyeye.docs_facts.review.ROUTES`, `_route_problems`, `lift_blocked`, `gh_issue_closed`, `dismiss_finding`;
- rule IDs: `pyeye.docs_facts.review.RULE_IDS`, `.claude/skills/docs-review/reviewer.md`;
- output: `pyeye.docs_facts.review.main`, `_run`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_review.py` passes:

- `TestC17`: page-level findings, prune and the fact-category refusal; literals parsed by `ast`, orphaned and moved; link, delete and code_bug routes; lifting closed, open and offline; contradictory directives; the new IDs; views in packets; and JSON-only stdout with counts.
- The extractor-list test.
