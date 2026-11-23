---
date: "2026-11-22"
title: "docs-facts runs on any repository through a Setup; a rule whose facts are absent is skipped and reported (#1091)"
issues: [1091, 1083, 818, 825, 826]
anchors: ["pyeye.docs_facts.setup.Setup", "pyeye.docs_facts.setup.pyeye_setup", "pyeye.docs_facts.rules.Rule", "pyeye.docs_facts.rules.missing_facts", "pyeye.docs_facts.cli.plan", "tests/test_docs_facts_portable.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-23-1091-a-data-only-docs-facts-config-per-repository.md", "2026-11-23-1092-the-structure-kinds-fact-contract.md"]
superseded_by: []
---

## 2026-11-22 — docs-facts runs on any repository through a Setup; a rule whose facts are absent is skipped and reported (#1091)

**Friction:** RFC #1083 builds architecture facts on the docs-facts engine. A spike ran the real `pyeye.docs_facts` on Scrapy. The generic engine worked (binding, `generate`/`check`, the snapshot, the ledger, stale detection, `honest-claims`), but three seams crashed it:

- **F1:** `cli.plan` couldn't take extractors, so pyeye's own ran on Scrapy, and `edges` crashed on pyeye's linter file.
- **F2:** pyeye's reference pages were always built (`KeyError: 'tools.core'`).
- **F3:** pyeye-domain rules raised `KeyError` on absent facts.

Reading the code found a fourth:

- **F4:** the removed-name rules read `removed.json` from pyeye's own checkout (`rules._CHECKOUT`), not from the repository being checked.

**Decision:** coordinator-3, 2026-11-22. This is the shape-independent half, landed on its own. The per-repo config file that builds a Setup waits for the designer's ruling.

- **A `Setup`** names what docs-facts runs on one repository: `extractors`, `docs`, `rules`, `pages` and `changelog`. `None` for the changelog turns the release-dependent behaviour off. `cli.plan`, `generate`, `check` and `report_changed` take `setup=`. `pyeye_setup()` is pyeye's own, read from the module constants at call time, so replacing one (a test, a spike) is seen.
- **Rules declare what they read.** `Rule.requires` holds fact IDs, or prefixes ending in `.` that some fact must start with. `rules.run` runs only rules whose requirements are met. `rules.skipped` reports the others in `Plan.notes`, printed as `skipped rule <id>: needs <facts>`, which never fails the run. A rule is never run on half a fact set.
  - `static-ceiling` and `edge-ceiling` need `edge.` and `ceiling.`.
  - `edge-counts-prose` needs `edges.inspect_unmeasured`.
  - `env-name` needs `env.`; `server-command` needs `cli.script.`.
  - `honest-claims` needs nothing, so it always runs.
  - **A judgement call:** `absence-prose` reads no facts. But it enforces pyeye's own convention (an absent edge is unknown, not none), so it is tied to `edges.inspect_unmeasured`, pyeye's edge-domain marker. Unconditioned, it would fail another project's ordinary prose.
- **F4:** `_removed_names(root)` reads the checked root's `removed.json`, through `Page.root`. `_CHECKOUT` is gone.
- **pyeye's output is byte-identical:** with the default setup, `generate` writes nothing and `check` passes. Every existing monkeypatch seam still works.

**Anchor:** `pyeye.docs_facts.setup.Setup` / `pyeye_setup`; `pyeye.docs_facts.rules.Rule.requires` / `missing_facts` / `skipped` / `run` / `_removed_names`; `pyeye.docs_facts.cli.plan` / `Plan.notes`; #1091, #1083.

**Applies-to:** `pyeye.docs_facts.setup.Setup`, `pyeye.docs_facts.setup.pyeye_setup`, `pyeye.docs_facts.rules.Rule`, `pyeye.docs_facts.rules.missing_facts`, `pyeye.docs_facts.rules.skipped`, `pyeye.docs_facts.rules.run`, `pyeye.docs_facts.rules._removed_names`, `pyeye.docs_facts.cli.plan`, `pyeye.docs_facts.cli.generate`, `pyeye.docs_facts.cli.check`, `pyeye.docs_facts.cli.report_changed`, `pyeye.docs_facts.changed.bound_pages`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_portable.py` passes. It checks:

- on a foreign repository (one extractor, one page), only the setup's extractors and pages run;
- generate then check is clean;
- a hand edit and a code change are each stale;
- every pyeye rule except `honest-claims` is reported as skipped, and `honest-claims` still finds a planted claim;
- pyeye's own facts skip nothing;
- `removed.json` comes from the checked root.

`uv run python scripts/docs_facts.py generate` writes nothing on this repository, and `check` passes.
