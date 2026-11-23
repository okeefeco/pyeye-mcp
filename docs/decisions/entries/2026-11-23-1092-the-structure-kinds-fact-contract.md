---
date: "2026-11-23"
title: "The structure kind's fact contract: deprecation is a flag, coverage looks past pyeye's scan, candidates are advice, curated pairs carry the duplicates (#1092)"
issues: [1092, 1083, 1091, 1108, 1074, 1081, 1082, 1106]
anchors: ["pyeye.docs_facts.extractors.structure.structure", "pyeye.docs_facts.extractors.structure.build", "pyeye.docs_facts.extractors.structure.cross_by_area", "pyeye.docs_facts.extractors.structure.coverage_rule", "pyeye.docs_facts.extractors.structure.layering_rule", "pyeye.docs_facts.structure.options.parse", "pyeye.docs_facts.rules.Rule", "pyeye.docs_facts.rules.run", "pyeye.docs_facts.registry.Extractor", "pyeye.docs_facts.registry.build", "pyeye.docs_facts.facts.Advisory", "pyeye.docs_facts.cli.plan", "pyeye.docs_facts.config.load", "tests/test_structure_extractor.py"]
status: "active"
amends: ["2026-11-22-1091-docs-facts-runs-on-any-repo-through-a-setup.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — The structure kind's fact contract: deprecation is a flag, coverage looks past pyeye's scan, candidates are advice, curated pairs carry the duplicates (#1092)

**Friction:** RFC #1083's architecture docs need facts about any codebase, and the trial built them with throwaway scripts. Three things in it would have lied as facts. Its first deprecation rule labelled three real Scrapy duplicates away, because a label removes a pair from the flags. Its coverage check trusted pyeye's own scan, which had skipped packages named `env`/`build`/`dist` (#1104). And a similarity score is a tunable judgement, so binding it would make a scoring tweak fail `check`. Measured on the pinned clones (Poetry 2.5.2 @ 4934abb, Scrapy 2.20.0 @ 4a421e4), the scorer alone also finds none of the duplicates that matter. 46 of the trial planner's 170 cross-area pairs share no word in their names (Poetry 29/103, Scrapy 17/67), so they are not candidates at any threshold. All four confirmed Poetry duplicates score below 0.6 (0.28, 0.36, 0.49, 0.60), against a top-150 cut at 0.91.

**Decision:** A generic built-in kind, `structure`, in its own module, with the maintainer's rulings Q1–Q6 as its contract.

- Fact IDs are kind first: `<p>.members.<handle>`, `<p>.imports.<module>`, `<p>.imported_by.<module>`, `<p>.cross.<area>`, `<p>.coverage.{gaps,unreadable,refused}`, where `<p>` is the `prefix` option.
- `imported_by` is the SET of importing top-level packages, never a count. `imports` records `measured`, so "imports nothing" and "couldn't read" differ.
- Only pyeye-backed labels (`delegates`, `override`, `sibling`) and unconditional-deprecation flags are facts. Deprecation is a flag on its side, never a label, because a deprecated copy is still a copy. A pair's sides are sorted, so a fact never depends on scan order.
- Scored candidates and their scores are advice. They appear only on an `Advisory` page. It opens "Judgment, not fact" and states its threshold and filters. `generate` writes it, `check` never compares it, and it can't be a registered doc, so it is never bound or on the site (designer, D12).
- The default `min_score` is 0.9, about the trial's top-150 cut: 68 candidates on Poetry, 165 on Scrapy. A planner's curated `pairs` (RFC step 4.2, given as data) are labelled whatever their score, and they are how the real duplicates get labelled: they are essential, not an extra. A curated pair naming a handle the dump lacks is a gap, never dropped.
- Coverage gaps are rule findings: `check` fails and `generate` still writes. The categories are missing, phantom, unparseable, unmapped, unresolved, skipped (files beside a dumped package that pyeye's scan left out), unidentifiable and unknown_pairs. Unreadable (#1074) is reported, not a gap.
- `areas` maps area IDs to module patterns. A module in two areas is an error, and an unmatched one is its own area.

Three engine additions, amending #1091's Setup contract.

- `Extractor.rules`: a kind brings rules built for its options, so `layering` and `structure-coverage` follow a custom `prefix` instead of going silently absent. A rule ID brought twice is a `ConfigError`, so one `structure` kind per repository.
- `Rule.audit(facts)`: a repository-wide check run once by `rules.run`. It may read the facts and nothing else. It gets a read-only `MappingProxyType` and no root, so it has no file reads and no imports (C19). Its problems belong to no page, so no allow-list holds them.
- `Advisory` pages, collected by `registry.build`'s optional `advisory` dict. Rejected: a second build entry point, which would bypass every test stub of `registry.build`.

**Anchor:** `pyeye.docs_facts.extractors.structure` (`structure`, `build`, `cross_by_area`, `layering_rule`, `coverage_rule`), `pyeye.docs_facts.structure.options.parse`, `pyeye.docs_facts.rules.Rule.audit`, `pyeye.docs_facts.registry.Extractor.rules`, `pyeye.docs_facts.facts.Advisory`; #1092, RFC #1083, PR #1105 (the core).

**Applies-to:**

- Every fact family the `structure` kind yields (`members`, `imports`, `imported_by`, `cross`, `coverage.*`).
- Every rule an `Extractor` brings: today `layering` and `structure-coverage` (`pyeye.docs_facts.rules.LAYERING`, `STRUCTURE_COVERAGE`).
- Every rule with an `audit`: today only `structure-coverage`.
- Every `Advisory` an extractor yields: today only the `structure` kind's `candidates_page`.
- The `pyeye-*` kinds (`pyeye.docs_facts.pyeye_kinds.PYEYE_KINDS`) bring no rules and yield no advisory pages. pyeye's own rules stay in `pyeye.docs_facts.rules.RULES`.

**Verify:** PARTIAL.

- Gold, every governed site: `uv run pytest tests/test_structure_extractor.py` checks each family's value and Markdown, labels, the flag, gaps and unknown pairs. It also checks both rules under a custom prefix, the second-kind refusal, that `audit` receives one read-only mapping and no root, and that `generate` writes an advisory page while `check` ignores a hand edit to it. An advisory path that is also a checked output is a problem.
- The acceptance (scratch harness, not committed) ran the kind with the trial's areas and its curated pairs through `pairs`.
  - Poetry: 26/103 delegates, the same pairs as the trial's measured callees; 4/4 confirmed duplicates unlabelled; no gaps; 682 MB, 209 s.
  - Scrapy: 14/67 delegates, the same pairs; 4/4 kept; no gaps (#1106 fixed `Spider.parse`); `call_later` unreadable (#1074); 1019 MB, 270 s.
  - Both ran under `MemoryMax=2G`. This is reproducible only with the clones and the trial's oracle files, so it is unverifiable in CI.
- That an audit does no file reads or imports is enforced only in so far as it receives no root. A rule author could still import inside one, which takes review.
