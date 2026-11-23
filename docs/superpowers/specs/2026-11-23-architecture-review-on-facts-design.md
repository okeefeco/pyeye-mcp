# Architecture review on facts: design (#1132)

Status: approved by the maintainer 2026-11-23 · design session

## Intent

The shipped `architecture-review` skill works out how a codebase diverges from itself with no recorded architecture to compare against ("here are N ways your code does X, you decide"). The 2026-11-23 audit on Scrapy's `spidermiddlewares` (#1132) found its four findings accurate, but:

- **cost:** about 600k tokens for about 4 actionable items in 962 lines;
- **plugin users can't run it:** it's a Python API with hand-built callbacks, no state path, and a baseline that assumes pyeye's own setup;
- **the gate measures the wrong thing:** it measures handle-set stability, not whether a finding reproduces, and costs about 3× the audit;
- **ranking:** importer-count blast is meaningless for string-loaded components, and the one actionable item ranked 12th of 13.

**The maintainer's direction:** the review compares the code against **facts and the recorded architecture**, reporting **adherence, deviation, decisions needed and ambiguity**.

- It runs **on demand**. Commit-time checking stays with the facts system: bound values, removed names, honest claims, coverage gaps and layering rules such as #1092's `CHECK no-import`.
- **The loop:**
  1. an on-demand review;
  2. the maintainer decides;
  3. a decision entry is written;
  4. where the decision can be stated mechanically, it becomes a rule, and the commit checks enforce it from then on.
- **The aim:** each run leaves less to judge next time. The skill's main output is decisions, and rules derived from them.

## Goals

1. A review of an area **reads the recorded architecture**, not the whole source: architecture facts (#1092), rules, and decision entries (read through `pyeye.decisions`, or the repo's convention documents if it has none).
2. **Every finding is one of four outcomes,** each anchored:
   - **adherence:** the code follows a recorded decision or rule. Reported as a confirmation, with no action;
   - **deviation:** the code contradicts a recorded decision or rule. The anchor is that record, and the finding carries a recommendation;
   - **decision needed:** no record covers it, but one pattern is clearly the norm. The finding says so, with its evidence, and asks for a decision;
   - **ambiguity:** several patterns, with no record choosing between them. The finding gives options with costs and an assessment, anchored or labelled "unanchored: judgment only".
3. **A decided item becomes a decision entry,** and where it's mechanically checkable, the skill drafts the **rule as config data** for the commit checks.
4. **Plugin users can run it** wherever a docs-facts config exists (#1091). Without architecture facts, it says so ("no recorded architecture for this area; run /arch-facts first") rather than guessing.
5. **Cost:** an order of magnitude below the audited run on the same scope, measured and recorded (D12) on Scrapy's `spidermiddlewares` as the acceptance case.

## Non-goals

- Commit-time checking. That's the facts system's job: rules run in `docs_facts check`.
- Duplicate detection. That stays with `/duplication-review` and #1092's curated pairs.
- Writing the architecture map. That's `/arch-facts` (RFC #1083 slice 4).

## Anti-goals

- **The tool decides.** No rule or decision entry is written without the maintainer (the review principle, #818 D8).
- **Unanchored deviations.** A deviation must name the record it deviates from. Without a record, the finding is "decision needed" or "ambiguity".
- **Prevalence as correctness.** "Most sites do X" is evidence for "decision needed", never a verdict (the existing honesty invariant, kept).
- **Re-reading the whole source.** The review spends judgment only where facts and records don't settle a question.

## Approaches considered

- **A. Rebuild on the facts engine. Chosen.** It reads architecture facts, rules and decisions; runs one reviewer pass per area; uses `/docs-review`'s finding shape and validator; and drafts rules as data. It fixes cost, plugin use, the gate and ranking at the root.
- **B. A review mode inside `/arch-facts`.** One skill, shared planner, but "map my system" and "review against my architecture" are different requests with different triggers. Rejected.
- **C. Patch the current skill** (a CLI, default callbacks, a finding-level gate, re-ranking). It keeps the premise of finding divergence without a record, and most of the cost. Rejected.

## Design

### 1. Inputs

- **Architecture facts** from the structure kind (#1092, merged in #1161; `arch.members.*`, `arch.imports.*`, `arch.imported_by.*` as importing areas, `arch.cross.*`, coverage gaps), read from the repo's snapshot.
- **Rules** configured in docs-facts (e.g. `CHECK no-import`), with their current pass or fail state.
- **Decision entries** with their `Applies-to:` anchors, through `pyeye.decisions`. For a repo without one, its configured convention documents (e.g. AGENTS.md, CONTRIBUTING) are read as prose anchors.
- **Code pointers** from pyeye (`inspect` and `expand` on the handles the facts name), used only as evidence for judgment findings.

### 2. Flow, per caller-supplied area

1. **Plan** (cheap): gather the area's facts, the rules that apply and the decisions that apply.
2. **Mechanical pass** (no model judgment):
   - each rule that applies → adherence or deviation;
   - each decision whose `Applies-to:` names a site in the area → a candidate for the reviewer to confirm (decisions are prose, so confirming one needs judgment).
3. **Reviewer pass**, one fresh-context reviewer per area, given only the plan's packet:
   - confirms or refutes each decision candidate, as adherence or deviation;
   - reports conventions no record covers, as decision needed or ambiguity, using fact-based prevalence as evidence.
4. **Validate** with the shared finding validator (#829):
   - an anchor resolves;
   - a deviation's anchor is a rule or a decision;
   - evidence items check against pyeye (the C15 evidence rule);
   - the outcome is one of the four.
5. **Report**, ranked:
   1. deviations from rules;
   2. deviations from decisions;
   3. decisions needed;
   4. ambiguities;
   5. adherence, summarised as a count with expandable detail.

   The importer-count blast radius is dropped.
6. **Codify** (on the maintainer's decision): the skill drafts a decision entry (through the `decision-log` skill) and, where the decision can be expressed with an existing rule kind, a rule as config data. Nothing is written without the maintainer.

### 3. What it replaces

- **Removed:** the auditor fan-out, the reproduction gate (`gate.py`), the cross-derivation guard (`guard.py`), the axis taxonomy and its grading (`taxonomy.py`), and the stakes ranking (`ranking.py`). No user docs import `pyeye.architecture_review` (checked 2026-11-23), so under the #628 rule it isn't a documented interface and can be removed, not deprecated.
- **Kept:** `state.py`, the shared dismissal state, which `/duplication-review` and `/docs-review` also use. Dismissals stay frozen (#818 C21) unless real use appears.
- **The skill** keeps its name, `architecture-review`, so existing triggers still work. Its description and body are rewritten for the new premise.

### 4. Rule kinds the codify step can target

The first version targets only rule kinds that already exist (layering `no-import`, and any added by #1092 or #1091's built-ins). A decision that no existing rule kind can express stays a decision entry checked by future reviews, not a new rule kind. New rule kinds are their own issues, added when a real decision needs one.

## Constraints

- **C19:** no runtime facts; the review reads facts and uses pyeye's static analysis.
- **dev01:** at most two heavy jobs at a time, memory-capped. The acceptance run counts as heavy.
- **2.x:** `no-breaking` stays 0. A rewritten shipped skill and a removed undocumented module are `changed` and `removed` fragments, not breaking ones.
- Each sub-issue's PR carries a fragment and, where it sets a contract, a decision entry.

## Proposed sub-issues

1. **The review engine:** plan, mechanical pass, packet, validation through the shared validator, and ranked report, with a CLI entry point, tested on a fixture repo with rules and decisions.
2. **The skill rewrite** (`architecture-review`): the reviewer prompt for the four outcomes and the codify step through `decision-log`, plus a conformance test. This is a shipped skill, so it needs the maintainer's direct approval for the `.claude/` and `skills` edits.
3. **Acceptance on Scrapy's `spidermiddlewares`:** reproduce the audit's 4 actionable findings, and record the cost against the audited run as a dated record.
4. **Remove the old engine** (`gate.py`, `guard.py`, `taxonomy.py`, `ranking.py`) and its tests, keeping `state.py`.

The order is 1 → 2 → 3 → 4. Sub-issue 3 also waits for #1173 (R1). Nothing is removed until the acceptance run shows the new review finds what the old one did.

## Settled after the builder check (Claude's calls; correct any)

- **R1. Dependencies and order** (updated 2026-11-23). #1092's structure kind has merged (#1161): areas, pairs, `min_score`, the `arch.*` facts, and the layering and coverage rules. `/arch-facts` is #1173, with prerequisites #1175 (curated pairs, areas and pairs data files, the unassigned-module gap, `imported_by` by area) and #1176 (the prose-handle rule). So:
  - **the engine (sub-issue 1)** is built and tested on real `arch.*` facts from a fixture repo, plus hand-written facts for edge cases;
  - **acceptance (sub-issue 3)** depends on **#1173** producing Scrapy's map. It measures **the review alone**, and the cost of building the map is recorded separately.
- **R2. "A rule as config data" means a `CHECK` line in the area's architecture doc,** the mechanism #1092 already parses (`structure/layering.py`). There's no new parameterised rules schema. The mechanical pass reads the same `CHECK` lines and their pass or fail state. A decision that no existing `CHECK` form can express stays a decision entry (§4).
- **R3. An area** is an area ID from the repo's committed areas data file (#1173 ruling 2). With no areas file, it's a module prefix treated as one implicit area. An unassigned module is a coverage gap, not its own area (#1173 ruling C), and the review reports it as such. The CLI's main argument is the area. A decision's `Applies-to:` sites match an area when they fall inside its module globs.
- **R4. Acceptance on Scrapy.**
  - Scrapy has no decision entries, so **its `AGENTS.md` is the prose anchor**, the fallback in goal 1. The audit's logging-style and module-docstring findings were anchored on it, so they become **deviations**.
  - **Passing means** all four audited items appear, each in an outcome its evidence supports, anchored wherever a record exists. Items with no record are "decision needed" or "ambiguity".
  - The cost target (an order of magnitude below the audited run) covers the review only.
- **R5. The decisions library already exists.** `pyeye.decisions` ships in the package (#1093/#1095), with `parse`, `load` and `applies_to()`, and `scripts/decisions.py` wraps it. What's left is matching `Applies-to:` sites to an area's module globs, which belongs in the engine (sub-issue 1). The former sub-issue 0 is dropped.
- **R6. The validator is generalised in place.** `docs_facts/review.py`'s category and anchor sets become per review kind (`docs`, `architecture`), adding the `rule` and `decision` anchor kinds and the four outcomes. `/docs-review`'s behaviour and skill text stay unchanged, and its tests must pass untouched.
- **R7. No dismissals; every resolution is a decision entry.**
  - When the maintainer answers a "decision needed" or "ambiguity" item, including "both patterns are acceptable here", the answer becomes a decision entry.
  - The next run then reports adherence to it instead of re-asking. That's the loop, and it fits the dismissal freeze (#818 C21).
  - An item the maintainer defers is simply re-reported. Deferral isn't recorded.

## Left to the builder

- The packet format and the CLI's flags.
- How convention documents (AGENTS.md, CONTRIBUTING) are configured as prose anchors for repos without a decisions index.
- The exact ranking within each tier.
