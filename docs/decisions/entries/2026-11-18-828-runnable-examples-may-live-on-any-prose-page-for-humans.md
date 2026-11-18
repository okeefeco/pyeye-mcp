---
date: "2026-11-18"
title: "Runnable examples may live on any registered prose page for humans, never on history pages or under .claude/ (#828, design C17)"
issues: [828, 818]
anchors: ["pyeye.docs_facts.examples.allows_examples", "pyeye.docs_facts.examples.WHERE_EXAMPLES_LIVE", "tests/test_docs_facts_examples.py"]
status: "active"
amends: ["2026-11-18-828-documented-examples-are-executed-and-matched-on-structure.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — Runnable examples may live on any registered prose page for humans, never on history pages or under .claude/ (#828, design C17)

**Friction:** #828 allowed `json pyeye-example` blocks only in `docs/api/`, `docs/reference/` and skills. A guide, README or architecture page that shows a tool call couldn't make it executable, so its examples stayed unchecked prose: exactly the drift #818 exists to stop.

**Decision:** design C17, item 2 (designer, maintainer-approved).

- **Widened:** `allows_examples` also accepts every registered page of kind `prose` whose audience is `human` or `both`.
- **Unchanged:** `docs/api/`, `docs/reference/` and skills, including `.claude/skills/*`, are allowed as before.
- **Still refused:**
  - a `history` page, refused first: it records the past, which may no longer run;
  - Claude-only prose (`CLAUDE.md`, `.claude/instructions/`);
  - anything else under `.claude/` (its human `README.md` included).
- **Wording:** `check` reports a misplaced example with the one wording, `WHERE_EXAMPLES_LIVE`.
- **Scope:** this widens the fence only. No page is converted here.

**Anchor:** `pyeye.docs_facts.examples.allows_examples`, `WHERE_EXAMPLES_LIVE`; `pyeye.docs_facts.cli.plan`; `tests/test_docs_facts_examples.py::TestWhereExamplesLive`; `tests/test_docs_examples.py::test_an_example_on_a_widened_page_runs`; #828, #818.
**Applies-to:** `pyeye.docs_facts.examples.allows_examples` (and through it `pyeye.docs_facts.cli.plan` and `tests/test_docs_examples.py`'s collection).
**Verify:** gold. `uv run pytest tests/test_docs_facts_examples.py tests/test_docs_examples.py` passes:

- the fence table allows human and both prose and skills (`.claude/skills` included), and refuses history, Claude prose and `.claude/README.md`;
- `check` reports only the history and `.claude/` pages;
- an example on a README-like page runs, lints and matches;
- every existing example still runs.
