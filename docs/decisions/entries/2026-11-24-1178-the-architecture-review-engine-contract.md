---
date: "2026-11-24"
title: "The architecture review engine: an area against its recorded architecture, four anchored outcomes (#1178)"
issues: [1178, 1132, 1092, 1182]
anchors: ["pyeye.docs_facts.architecture.plan", "pyeye.docs_facts.architecture.problems", "pyeye.docs_facts.architecture.report", "pyeye.docs_facts.architecture.Area", "pyeye.docs_facts.review.architecture_problems", "pyeye.docs_facts.review.finding_problems", "pyeye.docs_facts.review.finding_key", "tests/test_architecture_review_engine.py", "tests/test_architecture_review_findings.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-24 — The architecture review engine: an area against its recorded architecture, four anchored outcomes (#1178)

**Friction:** the audited `architecture-review` (#1132, on Scrapy's `spidermiddlewares`) cost about 600k tokens for about 4 actionable items. It looked for divergence with no record to compare against, and ranked by an importer-count blast that meant nothing there. The maintainer's direction: compare the code with the facts and the recorded architecture, and report adherence, deviation, decisions needed and ambiguity. #1132's design settles R1–R7. This entry records sub-issue 1's engine and the builder's calls the design left open.

**Decision:** assigned by coordinator-3 (2026-11-23). The plan was approved, with category = outcome agreed by designer; the resolver question was ruled by the user.

- **Where:** `pyeye.docs_facts.architecture`, because it reads the docs-facts setup and snapshot. It runs as `python -m pyeye.docs_facts architecture plan|validate|report` through `cli.main`, whose other commands are unchanged.
- **Inputs:**
  - `arch.*` facts come from the snapshot files, and no extraction runs.
  - Rules are the `CHECK no-import` lines on registered prose and skill pages, read as the `layering` rule reads them (R2).
  - Decisions come from `pyeye.decisions.load`, active and amended entries only (`--decisions-dir` points elsewhere).
  - Convention documents (R4's prose anchors, e.g. AGENTS.md) come from a repeatable `--convention PATH`, with no config schema change.
- **Area (R3):** a configured `structure` `areas` ID uses its fnmatch patterns. Otherwise the name is a module prefix, `[P, P.*]`. A handle is in an area when it, or a dotted prefix of it, matches. Modules no configured area holds are listed as `unassigned`, a coverage gap, never their own area.
- **Mechanical pass, no judgment:**
  - A check governs the area when its `A` names one of the area's modules, and it runs on those modules only.
  - Each check gives an adherence or a deviation, anchored on the rule (`no-import: A -> B`), with the importing modules as evidence.
  - An unmeasured module gives an **unverified rule**, never an adherence.
  - A decision whose `Applies-to` sites resolve, through pyeye's resolver, to a canonical handle in the area is a **candidate** for the reviewer (see the decision-sites entry). An unresolved site is listed in the packet with its reason.
- **The validator, generalised in place (R6):**
  - `finding_problems` dispatches on `review`. An absent `review` and `review: "docs"` both mean a docs finding, whose rules, keys and tests are unchanged.
  - An architecture finding's `category` is its outcome: `adherence`, `deviation`, `decision_needed` or `ambiguity`.
  - **Anchors by outcome:** an adherence or deviation rests on a record (`rule`, `decision`, `convention` as `PATH#slug`). A decision-needed or ambiguity finding rests on its evidence (`fact`, `symbol`), never on a record.
  - **Way forward by outcome:** a deviation carries a `recommendation`. A decision-needed finding carries its `question` and one `proposal`. An ambiguity has 2–3 options with costs, and a recommended option with its anchor or an unanchored assessment.
  - **Evidence** is canonical handles (C15), required for every outcome but adherence.
  - **Identity:** an architecture finding's key is its area, outcome, anchor and evidence.
- **Packet checks** (`architecture.problems`):
  - the finding names the packet's area, and its evidence is in that area;
  - a `rule` anchor comes only from the mechanical pass;
  - a `decision` anchor is one of the area's candidates;
  - a `convention` anchor is a section of one of the packet's documents;
  - a `fact` anchor is one of its facts.
- **Report:** rule deviations, then decision and convention deviations, decisions needed, ambiguities, and adherence as a count. Within a tier, more evidence ranks first, then the anchor. There is no importer-count blast. An invalid or repeated reviewer finding is listed under `rejected` with why. Unverified rules, unresolved sites, unassigned modules and gaps are reported beside the tiers.
- **No recorded architecture:** with no structure kind, no `arch.*` facts, or no module in the area, the plan says "no recorded architecture for this area; run /arch-facts first" and makes no finding (goal 4).
- **No dismissals (R7)** and no clock. Static only (C19).
- **Not here:** the reviewer prompt and the codify step (sub-issue 2), acceptance on Scrapy (sub-issue 3), and removing the old engine (sub-issue 4).

**Anchor:** `pyeye.docs_facts.architecture.plan` / `problems` / `report` / `Area`; `pyeye.docs_facts.review.architecture_problems`, `finding_problems`, `finding_key`; `tests/test_architecture_review_engine.py`, `tests/test_architecture_review_findings.py`; #1178, #1132.

**Applies-to:**

- the engine: `pyeye.docs_facts.architecture` (plan, mechanical pass, packet checks, report, CLI) and its entry in `pyeye.docs_facts.cli.main`;
- the shared validator's architecture kind: `pyeye.docs_facts.review.architecture_problems` and the `review` dispatch in `pyeye.docs_facts.review.finding_problems` and `pyeye.docs_facts.review.finding_key`. The docs kind is unchanged; its tests in `tests/test_docs_facts_review.py` are untouched.

**Verify:** gold. `uv run pytest tests/test_architecture_review_engine.py tests/test_architecture_review_findings.py tests/test_docs_facts_review.py` passes. It checks:

- on real `arch.*` facts from the fixture repository, each outcome, each anchor kind, the rule pass (broken, holding, type-only, unresolved, unmeasured), candidates and unresolved sites, the no-architecture notes, the packet checks, the report's tiers and ranking, and the command line;
- the docs review's tests pass unchanged.
