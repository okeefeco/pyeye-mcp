---
date: "2026-11-17"
title: "Docs make only claims the code or a record backs: the honest-claims rule (#844)"
issues: [844, 825, 818]
anchors: ["pyeye.docs_facts.claims.claims", "pyeye.docs_facts.claims.PATTERNS", "pyeye.docs_facts.claims.record_problems", "pyeye.docs_facts.rules.honest_claims", "pyeye.docs_facts.claim_seeds.SEEDS", "tests/test_docs_facts_claims.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — Docs make only claims the code or a record backs: the honest-claims rule (#844)

**Friction:** #818's sweep found docs that boasted or stated figures nothing backs. `migration-guide.md` gave a "2.5x faster" table with no source. Dogfooding pages set adoption targets for weeks 1–4. The project layout claimed "17+ core tools" on a server that registers 7. `DOCUMENTATION.md` gave a 10 MB file-size limit for a setting that is deprecated with a 1 MB default. The maintainer called this critical: one unbacked "X% faster" undermines trust in every fact the docs state.

**Decision:**

- **One rule over every registered page,** history pages included (D12): `honest-claims`. Released `CHANGELOG.md` sections are exempt, as a historical record (the note at the top of the changelog that C10 asks for awaits a ruling on the "never edit CHANGELOG.md in a feature PR" rule). `[Unreleased]` and the fragments must comply (C10 Q1).
- **What it matches** (`PATTERNS`, C10 Q7): percentages, multipliers, durations, sizes, "as of", "currently N", "N+ things" and token-savings phrasing. Bare counts are left to review, because a pattern can't judge their scope.
- **Prose only** (C10 Q4). It skips code and `markdown` fences (plain-text fences such as a file tree are still read), inline code, URLs and link targets, badges, HTML comments and version strings.
- **Three ways a claim passes:**
  - inside a fact block. Defaults became bindable inline (`env.<NAME>.default`), so "default 0.5 s" is now bound to the code;
  - on a line that links a registered `record` page, whose front matter must give `date`, `command` and `commit` (`check` fails otherwise; C10 Q5);
  - on a line that links an external primary source (C10 Q2).
  Anything else is bound or deleted, not reworded.
- **Unenforced policy numbers are removed, not bound** (C10 Q3). ">90% new-code coverage" is removed from CONTRIBUTING, the PR template and `.claude/instructions/01`, `07` and `11`. The bare 85% figures in `.claude/instructions/11` and `.claude/agents/smart-commit.md` are bound to `ci.coverage_threshold`. Commands drop the number, because `pyproject.toml`'s pytest `addopts` sets `--cov-fail-under`. These are Claude's own instructions, so they were edited only on the maintainer's direct approval in the working session, not on a peer's relay.
- **Seeds, not a flag day.** The 188 claims that predate the rule are seeded in `claim_seeds.SEEDS`, merged into each page's `allow`. Each seed is keyed on the claim's kind and matched text (`unbacked duration '0.5 s'`), one per occurrence, so it covers that claim only. #830 binds or deletes each claim and removes its seed. The report still prints the whole line.
- **The #417 static set comes from the ceiling facts (C12).** The static-surface caveat is required for the edges whose `edge.*` fact has the ceiling `static_definitions` or `literal_subclassing` (`rules.static_edges`), not for edge names listed in `rules.py`. A new edge with one of those ceilings is covered with no code change. Stating each exposed edge's own ceiling meaning is #827's.
- **Rejected:** a per-page count of violating lines (C10 Q6's wording). #837's review showed it lets a fix pay for a new claim. Also rejected: keying seeds on the full line, which would make every unrelated edit to a seeded line fail.

**Anchor:** `pyeye.docs_facts.claims.claims` / `PATTERNS` / `record_problems` / `code_free`; `pyeye.docs_facts.rules.honest_claims`; `pyeye.docs_facts.claim_seeds.SEEDS`; `pyeye.docs_facts.docs.DOCS`; design `docs/superpowers/specs/2026-11-17-docs-built-on-facts-design.md` D12, C10, C11, C12; #844, #825, #830, #818.
**Applies-to:**

- the rule: `pyeye.docs_facts.claims`, `pyeye.docs_facts.rules.honest_claims` (in `pyeye.docs_facts.rules.RULES`);
- the record kind: `pyeye.docs_facts.docs.Kind` (`record`), `pyeye.docs_facts.claims.record_problems`;
- the seeds: `pyeye.docs_facts.claim_seeds.SEEDS`, merged by `pyeye.docs_facts.docs.DOCS`;
- the inline defaults: `env.<NAME>.default` views from `pyeye.docs_facts.extractors.env`;
- the #417 static set: `pyeye.docs_facts.rules.static_edges`, `pyeye.docs_facts.rules.STATIC_CEILINGS`;
- the released-section exemption: `pyeye.docs_facts.rules.released_blanked`.

**Verify:** PARTIAL. Gold: `uv run python scripts/docs_facts.py check` exits 0, and `uv run pytest tests/test_docs_facts_claims.py` passes. That covers each pattern, each skip, each backing, record front matter, released-changelog exemption, seeds covering only their own claim, and every seeded page being registered. Unverifiable: overclaims no pattern catches ("finds ALL usages", "complete"). Those are left to #829's review checklist.
