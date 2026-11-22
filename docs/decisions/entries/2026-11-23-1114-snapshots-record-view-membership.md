---
date: "2026-11-23"
title: "Each snapshot file records every view's members, so a view losing a member reaches the change-triggered review (#1114)"
issues: [1114, 1108, 818]
anchors: ["pyeye.docs_facts.facts.memberships", "pyeye.docs_facts.cli.snapshot_text", "pyeye.docs_facts.changed.diff", "pyeye.docs_facts.changed.base_views", "pyeye.docs_facts.review.scope", "tests/test_docs_facts_view_membership.py"]
status: "active"
amends: ["2026-11-23-1108-reference-only-fact-families-and-own-snapshots.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — Each snapshot file records every view's members, so a view losing a member reaches the change-triggered review (#1114)

**Friction:** #1108 put a view that GAINS a member into the changed-fact list, because a new member of a bound view counts as covered at once (D5) and the change-triggered review (D6) is what sends the page back for a read. A view that LOSES a member got no such nudge. The gone member was listed as removed with no pages: `bound_pages` is built from the head facts, where it belongs to no view, and the snapshot held fact values only.

**Decision:** the maintainer, via the designer, 2026-11-23, option (a): store view membership in the committed snapshot. This keeps C4's plain snapshot diff and puts no git in the engine.

- Each snapshot file has a `views` section mapping view ID to members in display order. A view is recorded in its family's file, so the per-family split (#1108) holds.
- `changed.diff` compares the base and head memberships:
  - "Views with a new member" (the gain now also comes from the memberships, with the added-facts rule for a view the base doesn't record);
  - "Views that lost a member";
  - a gone member names the pages of the views that held it.
  - A member moving between views shows on both, even though no fact changed.
- The `/docs-review` scope adds the views that lost a member to its changed facts, and picks a page whose block names one.
- A base snapshot from before #1114 has no `views` section: no loss can be seen against it, and nothing fails.

**Anchor:** `pyeye.docs_facts.facts.memberships`; `pyeye.docs_facts.cli.snapshot_text` / `base_views` / `_committed_views`; `pyeye.docs_facts.changed.diff` / `base_snapshot` / `base_views`; `pyeye.docs_facts.review.scope`; #1114, #1108.

**Applies-to:** `pyeye.docs_facts.facts.memberships`, `pyeye.docs_facts.cli.snapshot_text`, `pyeye.docs_facts.cli.base_views`, `pyeye.docs_facts.cli.report_changed`, `pyeye.docs_facts.changed.Changes`, `pyeye.docs_facts.changed.diff`, `pyeye.docs_facts.changed.base_snapshot`, `pyeye.docs_facts.changed.base_views`, `pyeye.docs_facts.changed.summary`, `pyeye.docs_facts.review.scope`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_view_membership.py` passes. It checks:

- the memberships, and that each view sits in its family's file;
- a view losing a member, both in `facts.json` and in the family's own file, end to end through `changed`;
- a member moving between views;
- a base from before the memberships;
- the review scope on pyeye's `determinism.table`.

`docs/facts/facts.json` has a `views` section.
