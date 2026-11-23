---
date: "2026-11-23"
title: "Reference-only fact families stay out of the uncovered-fact ledger; a family may keep its own snapshot file (#1108)"
issues: [1108, 826, 1092, 1083, 818]
anchors: ["pyeye.docs_facts.setup.Setup", "pyeye.docs_facts.setup.Paths", "pyeye.docs_facts.ledger.updated", "pyeye.docs_facts.cli.snapshot_texts", "pyeye.docs_facts.cli.base_snapshots", "pyeye.docs_facts.changed.diff", "pyeye.docs_facts.config.load", "pyproject.toml", "tests/test_docs_facts_reference_only.py"]
status: "amended"
amends: ["2026-11-17-826-removed-names-fail-new-facts-go-to-the-ledger.md"]
supersedes: []
amended_by: ["2026-11-23-1114-snapshots-record-view-membership.md"]
superseded_by: []
---

## 2026-11-23 — Reference-only fact families stay out of the uncovered-fact ledger; a family may keep its own snapshot file (#1108)

**Friction:** The uncovered-fact ledger (#826) treated every fact as a claim some page should explain. 28 of its 32 `new` entries were `precommit.*`, the pre-commit hook list: reference data that no prose should restate. #1092's architecture facts (`arch.*`) would add thousands more, and in `facts.json` they would bury every other change in the diff.

**Decision:** the maintainer, 2026-11-23, relayed by coordinator-3 (#1108).

- **Reference-only families.** `Setup.reference_only` is a set of fact families (a fact ID's first segment). Their facts never enter the ledger, and `generate` and `check` print `reference-only fact families, outside the uncovered-fact ledger: …`. It is data: a repository's config declares `reference_only = [...]` (an override over a `preset` too), and pyeye's own `[tool.pyeye.docs_facts]` in `pyproject.toml` declares `precommit`. The facts still bind into pages and still appear in the snapshot and the changed-fact list.
- **Own snapshot files.** `Paths.snapshots` maps a family to its own snapshot file; that family's facts leave the main snapshot. The removed-name record and the changed-fact list read every snapshot file together, so moving a family between files records no removals and reports no changes. A family's file may not be one of the other records, and two families may not share a file.
- **A view that gains a member is in the changed-fact list** (maintainer, 2026-11-23). A new member of a bound view still counts as covered at once (D5). The nudge to re-read the page is the change-triggered review (D6), so `changed.diff` lists the view under "Views with a new member" with its pages, and the `/docs-review` scope includes the view's ID. This also holds with the family in its own snapshot file.
- **`check` prints the ledger's `new` count** (maintainer, from the drift assessment): `uncovered-fact ledger: N new entries`. It is information, with no gate and no ratchet.
- **Not here:**
  - the ledger's path dependence on intermediate local runs is #1112;
  - a view losing a member reaching the review is #1114;
  - whether a new member of a bound view should count as covered is with the designer;
  - the dismissal machinery is frozen, so this adds no dismissal feature.

**Anchor:** `pyeye.docs_facts.setup.Setup.reference_only`, `pyeye.docs_facts.setup.Paths.snapshots`; `pyeye.docs_facts.ledger.updated`; `pyeye.docs_facts.cli.snapshot_texts` / `base_snapshots`; `pyeye.docs_facts.config.load`; #1108, #1092.

**Applies-to:** `pyeye.docs_facts.setup.Setup`, `pyeye.docs_facts.setup.Paths`, `pyeye.docs_facts.setup.pyeye_setup`, `pyeye.docs_facts.ledger.updated`, `pyeye.docs_facts.cli.plan`, `pyeye.docs_facts.cli.snapshot_texts`, `pyeye.docs_facts.cli.base_snapshots`, `pyeye.docs_facts.cli.report_changed`, `pyeye.docs_facts.review.scope`, `pyeye.docs_facts.changed.diff`, `pyeye.docs_facts.changed.bound_pages`, `pyeye.docs_facts.config.load`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_reference_only.py` passes. It checks:

- the ledger skips a reference-only family, and an existing entry leaves when its family is declared;
- the note is printed;
- a family's own file holds its facts, and the main snapshot no longer does;
- moving a family records no removals, and a fact leaving the family's own file is still recorded;
- the changed-fact list reads both files, and lists a view that gained a member, with its pages, which the review scope then picks;
- a bad map or declaration is refused;
- `check` prints the ledger's `new` count and never fails on it.

`docs/facts/uncovered.json` has no `precommit.*` entry.
