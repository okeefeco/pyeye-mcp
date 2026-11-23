---
date: "2026-11-23"
title: "generate derives the ledger and removed names from the merge base, not the working tree (#1112)"
issues: [1112, 1114, 826]
anchors: ["pyeye.docs_facts.cli.plan", "pyeye.docs_facts.cli.generate", "pyeye.docs_facts.cli.merge_base", "pyeye.docs_facts.ledger.updated", "pyeye.docs_facts.removed.updated"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — generate derives the ledger and removed names from the merge base, not the working tree (#1112)

**Friction:** Both records were derived from the working-tree copy, so the order of local `generate` runs showed in them. A fact briefly covered or absent on a branch fell out of `baseline` for good and came back as `new` (`env.PYEYE_ISSUE` and `env.PYEYE_PARENT_SESSION` in #948). A name that went and came back left a permanent `removed.json` entry.
**Decision:** The builder's pick between the two options the maintainer allowed: the merge-base diff. `generate` passes `plan` the merge base of `HEAD` and `--base` (default `origin/main`). The ledger's `baseline` and `new`, the removed entries and the old snapshot are read at that revision. From the working tree it keeps only what a person or a release wrote: a removed entry's own version (hand-edited `match`/`note`), a hand-written entry, and a release-stamped `first_seen`. It drops a removed entry generated for a name that went and came back, or that was born and gone on the branch. `check` stays a fixed-point comparison with no git, so it doesn't depend on where `main` is. Rejected: a shrink-only baseline. `baseline` already only shrinks, and that is the bug. `removed.json` is append-only, so its transient entries need a base to compare against either way. With no git or no merge base, `generate` uses the working tree and prints a note.
**Anchor:** `pyeye.docs_facts.cli.plan`, `pyeye.docs_facts.cli.generate`, `pyeye.docs_facts.cli.merge_base`, `pyeye.docs_facts.ledger.updated`, `pyeye.docs_facts.removed.updated`; #1112.
**Applies-to:** every record `generate` derives from its own previous copy: `Paths.uncovered` (the ledger) and `Paths.removed` (the removed names). The snapshot files and reference pages are built from today's facts alone, so they are not path-dependent. `docs/facts/review-state.json` is written only by `/docs-review` and is out of scope.
**Verify:** gold. `tests/test_docs_facts_order_independent.py` runs `generate` in a git repo with the base committed, a transient run with a fact gone, then a run with it back. Both records end equal to the base and `check` passes. Unit tests cover hand edits, hand-written entries, stamped `first_seen`, the fixed point of `check`, and the fallback with no base.
