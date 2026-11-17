---
date: "2026-11-18"
title: "/docs-review: code_contradiction findings anchored on a canonical symbol with checked evidence, and subject-keyed rule dismissals that lapse (#829, C15, C16)"
issues: [829, 818]
anchors: ["pyeye.docs_facts.review.Symbols", "pyeye.docs_facts.review.project_symbols", "pyeye.docs_facts.review.finding_problems", "pyeye.docs_facts.review.SUBJECT_KINDS", "pyeye.docs_facts.review.orphaned", "pyeye.docs_facts.review.move", "tests/test_docs_facts_review.py"]
status: "active"
amends: ["2026-11-18-829-docs-review-never-decides-every-finding-names-its-anchor.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — /docs-review: code_contradiction findings anchored on a canonical symbol with checked evidence, and subject-keyed rule dismissals that lapse (#829, C15, C16)

**Friction:** #855's `/docs-review` had two gaps.

- It had no way to say "the prose contradicts the code". A behaviour, a raised error or a hard-coded default that no extractor turns into a fact could only be filed as style. worker-4 found this.
- A dismissal on a rule anchor (style, claims, audience) had no value to pin, so it never lapsed. It was keyed only on page, section, category and anchor, so dismissing one broken link in a section also hid a different broken link added there later.

**Decision** (the maintainer's rulings, recorded as C15 and amended by C16):

- **`code_contradiction` findings.**
  - They rest on a `symbol` anchor: the code symbol by its canonical pyeye handle, never `path:line`, so they're stable under unrelated edits.
  - `validate` checks with pyeye's own resolver that the handle resolves to a project symbol and is canonical. A re-export alias is refused, naming the canonical handle.
  - Prose must not state code facts (C15 as revised, #860): a statement of what the code does comes from a bound fact or an executed example. So `code_contradiction` is a narrow fallback for behaviour claims that can be neither. The finding is always a clear fix and says its `route`, in preference order:
    - `fact`, naming the `extractor` that would produce the fact;
    - `example`, an executed example;
    - `wording`, only with a `route_reason` saying why neither of the other two works.

    `reviewer.md` makes conversion the default.
  - It must carry `evidence` of what pyeye reports for the handle: the `inspect` signature (exactly), a docstring excerpt, or an edge's handles from `expand`. `validate` checks each item against pyeye. The finding is the reviewer's reading of code, so the reading must be checkable.
- **Symbol dismissals are pinned to the signature and docstring as `inspect` reports them.** Edits to the body, or elsewhere in the file, keep the dismissal; a change to either lapses it, and the finding returns as `resurfaced`. A handle that no longer resolves is an orphan.
- **Rule-anchored findings quote their `subject`**: the exact page text they are about. `validate` rejects a subject that doesn't occur verbatim (whitespace aside) in the section. The subject is part of the dismissal's identity, so a different subject is a `new` finding. When a dismissed subject no longer occurs in its section, the dismissal LAPSES (C16, which reverses C15's fail): `check` stays green, the next `/docs-review` command prunes it, and its finding may resurface. A prose editor never has to touch `review-state.json`. Only fact orphans and unresolved symbols fail `check`. A gone section is pruned the same way.
- **Prose must not restate an executed example (C16).** It may point at the example and say why it matters. A sentence restating what the example shows (its keys, counts or shapes) is a restated fact: the `restated-example` style rule, whose fix deletes it and points at the example.
- **One `move` for every anchor kind.** It takes the new fact ID, the new canonical handle or the reworded subject, and moves only an orphan or a lapsed subject. A fact or symbol keeps its old pin, so it holds only if nothing it rests on changed. The orphan message gives the right `move` argument for each kind.
- **`Symbols` is a protocol** (`canonical`, `surface`, `edge`). `project_symbols(root)` answers it with pyeye's `resolve_handle`, `inspect` and `expand` on a lazily built analyzer. `docs_facts check` passes it, and the root, to `orphaned`, so the analyzer is only built when a symbol dismissal exists.

**Anchor:** `pyeye.docs_facts.review.Symbols`; `pyeye.docs_facts.review.project_symbols`; `pyeye.docs_facts.review.finding_problems`; `pyeye.docs_facts.review.orphaned`; `pyeye.docs_facts.review.move`; design C15; #829.
**Applies-to:**

- the category and evidence: `pyeye.docs_facts.review.finding_problems`, `pyeye.docs_facts.review.CATEGORY_ANCHOR`, `.claude/skills/docs-review/reviewer.md`;
- symbols: `pyeye.docs_facts.review.Symbols`, `pyeye.docs_facts.review.project_symbols`;
- subjects and pins: `pyeye.docs_facts.review.SUBJECT_KINDS`, `dismiss_finding`, `triage`, `orphaned`, `move`;
- check: `pyeye.docs_facts.cli.plan`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_review.py` passes:

- `TestCodeContradiction`: canonical handles; the route required (fact with its extractor, example, or wording with its reason); evidence required and checked against pyeye, as signature, docstring and edge; always a clear fix; `project_symbols` over the real repo.
- `TestSymbolDismissals`: a body edit holds and a docstring change resurfaces; an unresolved handle is an orphan, and `move` fixes it.
- `TestSubjects`: the subject is required and must occur in the section; a different subject is new; a vanished subject lapses with `check` green and is pruned on the next write; `move` to the reworded text keeps it.
