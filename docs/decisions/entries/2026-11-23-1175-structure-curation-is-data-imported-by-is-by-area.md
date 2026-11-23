---
date: "2026-11-23"
title: "The structure kind's curation is committed data: every curated pair is a fact, an unassigned module is a gap, imported_by is by area (#1175)"
issues: [1175, 1173, 1092, 1083]
anchors: ["pyeye.docs_facts.extractors.structure.pairs_by_area", "pyeye.docs_facts.extractors.structure.importing_areas", "pyeye.docs_facts.extractors.structure.unassigned", "pyeye.docs_facts.extractors.structure.extract", "pyeye.docs_facts.extractors.structure.GAP_CATEGORIES", "pyeye.docs_facts.structure.options.parse", "pyeye.docs_facts.structure.options.load", "tests/test_structure_curation.py"]
status: "active"
amends: ["2026-11-23-1092-the-structure-kinds-fact-contract.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — The structure kind's curation is committed data: every curated pair is a fact, an unassigned module is a gap, imported_by is by area (#1175)

**Friction:**

- **No footer for the duplicates.** `/arch-facts` (#1173) needs an area doc's "Similar elsewhere" footer bound to facts. `arch.cross.<area>` holds only the pairs pyeye's facts label. All 8 confirmed duplicates on Poetry and Scrapy came out unlabelled, so a footer bound to it showed none of them.
- **Curation buried in config.** The planner's areas and pairs were inline in it, so a re-curation was a config edit, not a reviewable data diff.
- **No memory of a rejection.** Nothing stopped a planner re-run from re-adding a pair the user had rejected.
- **An unassigned module passed silently.** A module no area matched became its own area by design (#1092 ruling A).
- **imported_by said nothing on one package.** As top-level packages (Q6), it is always `["poetry"]` / `["scrapy"]` on a single-package repository.

**Decision:** The maintainer's rulings on #1173 (2026-11-23, via designer).

- **(A) `<p>.pairs.<area>`.** Every curated pair touching an area is a fact, labelled `delegates` / `override` / `sibling` or "possible duplicate (unverified)", with its deprecated sides and `measured`. Curated pairs are committed planner data, not a score, so this stays within Q2(c). The scored candidates remain advice on the judgment page only.
- **Data files.** `areas` and `pairs` may each name a committed TOML/JSON/YAML file in the repository (`[areas]`; `[[pair]]` with `a`, `b`, optional `rejected`). It is read through `pyeye._data_files`, never run (C19).
  - A file path is kept at parse time and read at extract time, because a kind's factory gets no root. A bad file is an `ExtractionError` that names it.
  - A rejected pair (`rejected = "<reason>"`, plain data, not the dismissal machinery) is never labelled, never in `arch.pairs`, and never listed as a candidate again. One naming a handle the dump lacks is an `unknown_pairs` gap, so stale rejections get cleaned.
- **(C) No `require_areas` option.** With areas configured, a module no area matches is always an `unassigned` coverage gap (exit 1, never a stop): the signal to re-run the planner. It still gets facts as its own area. A module in two areas stays an `ExtractionError`.
- **(D) `imported_by` by area, amending Q6.** With areas configured, `<p>.imported_by.<module>` is the set of areas whose modules import it. Without areas it stays the set of top-level packages. It is never a count; raw counts come from pyeye's `expand(imported_by)`. An importer outside the collected scope (e.g. an excluded test) is in no area, so it isn't listed.

**Anchor:** `pyeye.docs_facts.extractors.structure` (`pairs_by_area`, `importing_areas`, `unassigned`, `extract`, `GAP_CATEGORIES`), `pyeye.docs_facts.structure.options` (`parse`, `load`); #1175, #1173, amending #1092's entry (Q6).

**Applies-to:**

- Every curated pair: inline `pairs` entries and every `[[pair]]` in a pairs file, accepted or rejected.
- Every module in the dump: its `imported_by` fact, and its area assignment when `areas` is configured.
- Every `structure` option that names a file: `areas`, `pairs` and `candidates_page`, all validated by `options._path`.
- The `structure-coverage` rule, which now also reports `unassigned`.
- Not governed: the scored candidates and their scores, which stay advisory (#1092).

**Verify:** PARTIAL.

- Gold: `uv run pytest tests/test_structure_curation.py`, on a fixture repo with an areas TOML file and a pairs JSON file. It checks:
  - both formats plus YAML, and path and format errors naming the file;
  - accepted and rejected pairs, inline and in files;
  - the pairs fact in both areas of a pair, a rejected scored candidate gone from every fact and the page, and a stale rejection as a gap;
  - unassigned modules as gaps through `check`;
  - `imported_by` as areas, and as packages without areas.
- The #1161 acceptance, rerun with the trial's areas and pairs as data files (scratch harness, not in CI; MemoryMax=2G):
  - Poetry: delegates 26/103 (same pairs), all 103 curated pairs in `arch.pairs` with the 4 confirmed duplicates "possible duplicate (unverified)", no gaps, none unassigned, `imported_by` measured 193/193, 684 MB / 209 s;
  - Scrapy: 14/67, 67/67, 4/4, no gaps, 199/199, 1021 MB / 278 s.
- The Scrapy candidates page listed 164 scored candidates against #1161's 165. Signature rendering changed on main in between (#1128, #1158), and signatures feed the parameter term. This is not bisected, so it's unverified.
