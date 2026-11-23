---
date: "2026-11-17"
title: "Facts reach the docs only through registered extractors, marker blocks and generated pages, over one doc registry (#824)"
issues: [824, 818]
anchors: ["pyeye.docs_facts.registry.EXTRACTORS", "pyeye.docs_facts.registry.build", "pyeye.docs_facts.docs.DOCS", "pyeye.docs_facts.binding.render", "pyeye.docs_facts.pages.PAGES", "pyeye.docs_facts.cli.check", "tests/test_docs_facts_registry.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-24-1182-anchors-that-drifted-are-carried-to-their-current-sites.md"]
superseded_by: []
---

## 2026-11-17 — Facts reach the docs only through registered extractors, marker blocks and generated pages, over one doc registry (#824)

**Friction:** #818's sweep found 183 doc findings (61 WRONG, 60 STALE). Ten point checks existed, but each covered one invariant over its own private list of files, and the drift sat in the gaps between them. For example, the removed-tool guard scanned only `.md` and `.json`, so the Sphinx `.rst` tree drifted unseen, and `07-validation.md` still listed Python 3.10–3.12 after CI moved to 3.11–3.14.

**Decision:**

- **One fact source.** Every reference fact in the docs (tools and parameters, edges and ceilings, `PYEYE_*` variables, entry points, CI values) comes from an extractor in `EXTRACTORS`. Each extractor owns its ID prefixes, and `build` rejects a shared prefix, a stray ID, a duplicate or a view over an unknown fact. A fact has a stable dotted ID and one Markdown rendering; group IDs (`tool.trace.params`, `edges.table`) are views over item facts (C3).
- **One binding.** Prose names a fact in a `<!-- fact:begin ID -->…<!-- fact:end -->` block (block or inline form) and never restates it. Large tables are fully generated pages under `docs/reference/` with a do-not-edit header (`PAGES` is their one list). Approach A of the design: no `cog`, and no templates beside their output.
- **One doc registry.** `DOCS` lists every in-scope `.md` file with its audience and kind (`prose`, `reference`, `skill`, `history`). Every docs check iterates it and none globs for itself. A test fails if a tracked or untracked `.md` file outside the excluded trees (`docs/superpowers|decisions|audits/`, `tests/fixtures/`) is unregistered. `changes/*.md` is the one pattern entry, because fragments churn every PR.
- **Caught at commit time (D3).** Pre-commit runs `generate`. CI's required `pre-commit` job runs `check`, which fails on a stale or hand-edited block, page or snapshot, an unknown ID (a removed fact, D4), a malformed marker or a missing registered file. No bot regeneration PRs. `docs/facts/facts.json` records every item fact's value, so a fact change shows in the PR diff (C4).
- **Rejected:** keeping per-test file lists, which is the gap #818 found; regenerating in a bot PR, which leaves the drift on `main` in between; parsing `ci.yml` with PyYAML, which isn't a dependency (C4: no new dependency). The CI extractor uses anchored patterns and fails if one stops matching.

**Anchor:** `pyeye.docs_facts.registry.EXTRACTORS` / `build`; `pyeye.docs_facts.docs.DOCS`; `pyeye.docs_facts.binding.render`; `pyeye.docs_facts.pages.PAGES`; `pyeye.docs_facts.cli.check`; `scripts/docs_facts.py`; design `docs/superpowers/specs/2026-11-17-docs-built-on-facts-design.md` (#822) D2, D3, D11, C1, C3, C4; #824, #818.
**Applies-to:**

- the extractor list and its builder: `pyeye.docs_facts.registry.EXTRACTORS`, `pyeye.docs_facts.registry.build`;
- the doc registry: `pyeye.docs_facts.docs.DOCS`, `pyeye.docs_facts.docs.EXCLUDED_TREES`;
- the binding and the pages: `pyeye.docs_facts.binding.render`, `pyeye.docs_facts.pages.PAGES`;
- the gates: `pyeye.docs_facts.cli.generate` (pre-commit `docs-facts-generate`), `pyeye.docs_facts.cli.check` (CI `pre-commit` job);
- the ten existing point checks (`tests/test_documented_env_vars.py`, `tests/test_documented_server_commands.py` and the rest), which move onto `DOCS` in #818's sub-issue 3.

**Verify:** PARTIAL. Gold: `uv run python scripts/docs_facts.py check` exits 0 on `main`, and `uv run pytest tests/test_docs_facts_registry.py tests/test_docs_facts_extractors.py tests/test_docs_facts_binding.py` passes. Together they cover the registry completeness, every extractor against the code read another way, and every malformed-marker and stale case. Unverifiable for now: "no check keeps a private file list". The ten older checks still do until sub-issue 3 migrates them, and a later rule (sub-issue 3) will make it checkable.
