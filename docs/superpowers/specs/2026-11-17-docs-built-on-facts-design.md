# Documentation built on facts: design (#818)

Status: approved by the maintainer 2026-11-17 · design session · sub-issues #823–#831

## Intent

pyeye's documentation drifted badly from its code. The sweep of main `95c7b40b` (in the #818 comments) found 183 findings: 61 WRONG, 60 STALE, 33 MISSING and 29 nits. Ten hand-written point checks exist, but each covers one invariant over its own list of files, and drift lives in the gaps between them. For example, the removed-tool guard scans only `.md` and `.json`, so the `.rst` Sphinx tree drifted unseen.

The goal is documentation that is **built on facts**, so a code change cannot silently leave the docs wrong, and that **stays usable** for each audience. That is two layers joined by a binding:

- **The fact layer.** Its source of truth is the code. Generation and CI keep it right. It is never edited by hand.
- **The presentation layer.** Its source of truth is the reader. A judgment review keeps it right. It is edited by hand.
- **The binding.** Prose references facts and never restates them.

## Goals

1. Every reference fact in the docs (tool names, parameters, response shapes, edges, env vars, CLI commands, defaults, limits, CI facts) comes from one extraction mechanism. None is hand-maintained.
2. A code change that invalidates a documented fact fails CI in the same PR.
3. A new fact the prose doesn't cover becomes a visible, tracked item that doesn't block the PR.
4. Documented examples are executed, not trusted.
5. The prose is reviewed for usability when facts change, on demand, and before each major or minor release. The release pass includes task-based scoring against a recorded baseline.
6. The sweep's WRONG and STALE findings are resolved. Most disappear by generation, and the rest are fixed as prose.

## Non-goals

- Generating prose. Explanation, ordering and examples stay hand-written.
- An umbrella `/review` that runs architecture, duplication and docs together. It is a later sub-issue (see Follow-ups).
- Historical records: `docs/superpowers/**`, `docs/decisions/**` and `docs/audits/**` are not bound or reviewed (as in the sweep).
- A published docs site.

## Anti-goals (failure even if it "works")

- **The tool decides.** No review applies, codifies or dismisses anything without a person. Recommendations are informed assessments that name their anchor. Where something is genuinely ambiguous, the review says so and asks for a decision.
- **Findings without a way forward.** Every `/docs-review` finding carries proposed text or concrete options with a recommendation. The reviewer must never have to work out the fix themselves.
- **A second copy of a page** (templates beside their output) or generated text someone has to hand-edit.
- **Code PRs stalled** by prose work for a newly added fact.
- **Docs that boast or state unverified facts** (D12). One unbacked "X% faster" undermines trust in every fact the docs state.
- **A parallel list of files.** If a check can scan a list of files other than the registry's, the `.rst` blind spot can come back.

## Decisions taken in the session

| # | Decision | By |
|---|---|---|
| D1 | **Retire the Sphinx tree** (`docs/source/**`), its workflow, the `docs` dependency group and Dependabot's `sphinx*` group, and unpublish Pages. Port `architecture/resolution.rst` (current, and linked from the `python-explore` skill) and the still-correct parts of `plugin-system.rst` and `caching-strategy.rst` to `docs/architecture/*.md`. Delete the rest: it duplicates the README, CONTRIBUTING and `docs/`, and it teaches the v1 API. | Maintainer |
| D2 | **The binding is named marker blocks in Markdown, filled by our own stdlib script, plus fully generated reference pages** under `docs/reference/`. | Maintainer (approach A) |
| D3 | **Fact drift is caught at commit time.** A pre-commit hook regenerates, and CI fails if the committed blocks differ from fresh ones. No bot regeneration PRs. | Claude's call, not contested |
| D4 | **A removed or renamed fact that prose still names fails CI.** | Claude's call, not contested |
| D5 | **A new uncovered fact goes to a committed ledger** (`docs/facts/uncovered.json`). It shows in the PR diff and does not block. `/docs-review` works it down. | Maintainer |
| D6 | **When `/docs-review` runs:** on pages bound to facts that changed, on demand, and in a full pass (review plus task scoring) before every major and minor release. Patch releases skip it. There is no other periodic sweep. | Maintainer |
| D7 | **`/docs-review` sits beside `/architecture-review` and `/duplication-review`** and reuses their machinery: scope, findings labelled as judgments, the result states and dismissal state (`src/pyeye/architecture_review/state.py`, as #495 does). | Maintainer |
| D8 | **`/docs-review` reports findings with recommendations or options and never applies them.** A recommendation names its anchor: the fact, the failed task or the audience. | Maintainer |
| D9 | **MCP tool descriptions take their fact parts from the same extractors** when `server.py` loads: edge lists, scope options, parameter lists. The prose parts stay hand-written. | Claude's call |
| D10 | **Code blocks marked as runnable are executed in CI** against a fixture project, and their responses are checked by `tests/conformance/response_linter.py`. | Claude's call |
| D12 | **Docs make only claims the code or a record can back. This is the same honesty contract as the code layer (absence-vs-zero, #568).** It applies to EVERY registered page, history pages included.<br>• **Numbers and comparisons** ("40% faster", "finds 90% of bugs", "50 ms", "100 MB", "saves N tokens") appear only as a bound fact, with its provenance, or as a link to a dated, reproducible record that gives the command that produced it. Anything else is deleted, not reworded.<br>• **Volatile status** ("currently", "as of <date>", "latest version", current coverage, "17+ tools") is a bound fact or removed. Live prose never holds a snapshot. Example: the coverage *threshold* is the `ci.coverage_threshold` fact. A *current coverage* figure isn't a code fact, so it is removed, and the live codecov badge is the source.<br>• **Absolute claims** ("finds ALL usages", "complete", "never misses") appear only where the code makes that guarantee, stated with its scope.<br>• **Projections and targets** ("expected 90% fewer bugs") are not allowed in live docs.<br>**Enforced** mechanically, as a #825 prose rule: a pattern rule for percentages, multipliers, durations, sizes, "as of <date>" and "currently N", with a shrink-only allow-list. A match passes only inside a fact block or on a line that links a record. Overclaims a pattern can't catch are left to judgment, in #829's review checklist; each finding names the missing anchor and proposes honest wording or deletion. | Maintainer ("critical": docs that boast or state false facts undermine the whole purpose) |
| D11 | **Audiences.** One fact layer, three presentations: human docs (README, `docs/`), Claude docs (`.claude/instructions/`, `skills/`, tool descriptions) and bridge docs (`Audience: Both`). Each page is registered with its audience, and review and scoring tasks are set per audience. | Claude's call, per `00-documentation-system.md` |

## Approaches considered (for the binding)

- **A. Named marker blocks plus our own script. Chosen.** The block ID is the fact ID, so the fact→page index, the change-triggered review and the uncovered ledger all come from it. Pages still render normally on GitHub. Dependency-free, in the style of the existing conformance tests.
- **B. `cog` (cogapp).** Less of our own code, but every page carries Python generator code, fact IDs are implicit, and we would still have to build the fact→page index ourselves.
- **C. Jinja templates rendered to committed `.md`.** Two copies of every page, and people edit the wrong one. Rejected (anti-goal).

The chosen approach adds **fully generated reference pages** for large tables. Prose links to them and does not inline them.

## Design

### 1. The fact layer

**The fact registry** (`src/pyeye/docs_facts/`, see C4):

- **Facts.** A fact has a stable dotted ID (`tool.trace.params`, `edge.registry`, `env.PYEYE_MAX_FILE_SIZE`, `ci.coverage_threshold`, `ci.python_versions`), a value and a renderer to Markdown.
- **Extractors.** Each fact comes from exactly one extractor, and the extractors are listed in one place. Starting set, taken from what the sweep found wrong:
  - **MCP surface:** core, admin and plugin tool names, parameters and defaults, from the live registration. This replaces `test_mcp_surface_conformance` and `test_plugin_tool_names_conformance`.
  - **Edges:** the registry in `pyeye.mcp.operations.edges`, the measured and unmeasured sets in `response_linter`, and the `submodules` and `re_exports` edges.
  - **Scope options and plugin tool defaults:** from `SmartScopeResolver` (the pre-#690 drift).
  - **Env vars:** from `settings.py`, including `DEPRECATED_ENV_VARS`, with the "loaded *and* used" rule from `test_documented_env_vars`.
  - **CLI and server entry points:** console scripts and module entry points (`test_documented_server_commands`).
  - **CI facts:** the coverage threshold and Python matrix from `ci.yml` and `pyproject.toml`.
  - **Review taxonomies:** architecture-review axes and grades, from `architecture_review.taxonomy`.
- **The doc registry.** One list of every documentation file in scope, each with its audience (D11) and its kind (prose, reference or skill). Every check reads this list, and no check may glob on its own. A test fails if a `.md` file outside the excluded history trees is missing from the registry, which closes the `.rst` blind spot.

**Two kinds of check.** The ten existing point checks split into two kinds, and both move onto the registry:

1. **Fact checks.** They compare documented values with extracted ones and become marker blocks plus `docs_facts check`: env vars, server commands, removed tools, plugin tool names, skill edge lists, taxonomy axes.
2. **Prose rules.** They require or forbid phrasing and are not facts: the static-surface ceiling marker (#417), absence-vs-zero prose (#568), structural `edge_counts` claims (#396), the removed-tool mention guard (#509). They become named rules run over the doc registry, each with its own allow-list. Like #629's ratchets, an allow-list only shrinks.

Each existing test is either deleted (its check now lives in the registry) or reduced to a thin parametrised test over the registry. Nothing keeps a private file list.

### 2. The binding

Inline facts in prose:

```markdown
<!-- fact:begin tool.trace.edges -->
`callees`, `imports`, `imported_by`, `submodules`, `re_exports`
<!-- fact:end -->
```

- `docs_facts generate` rewrites the inside of every block from its fact. `docs_facts check` fails if any block differs, if a block names an unknown fact ID (a removed fact, D4), or if a block was hand-edited (that's the same check).
- **Fully generated pages** under `docs/reference/` (tools, edges, env vars, CLI). Each carries a header saying it's generated and must not be edited. Prose links to them.
- **Mentions outside blocks.** A removed tool, parameter, edge or env var named in prose anywhere in the registry fails CI (D4). This generalises #509's guard using the extractors' history: names that existed and no longer do. Mentions on lines marked deprecated (#628) are allowed.
- **Pre-commit** runs `generate`. **CI** runs `check`.

### 3. Cross-layer flags

- **The fact→page index.** Built from the marker blocks plus each fact's declared "covered by" prose sections. The page registry may name, per page, which facts its prose explains.
- **New facts.** A fact with no covering prose section is written by `generate` into `docs/facts/uncovered.json` (sorted, stable, one entry per fact ID with its first-seen version). The entry appears in the PR diff and does not block (D5). It leaves the ledger when prose covers the fact, or when `/docs-review` records a dismissal ("deliberately not covered: reason"), stored with the review dismissal state.
- **Changed facts.** `check` emits the IDs of facts whose value changed against the merge base, mapped to bound pages. That list is the scope for the change-triggered `/docs-review` (D6). It's surfaced as a CI summary or job output, not as a failure.
- **Removed facts:** a CI failure (D4), never a flag.

### 4. Executed examples (D10)

- Fenced code blocks tagged as runnable (for example ` ```json pyeye-example tool=inspect `, the exact syntax left to the builder) in `docs/api/*`, `docs/reference/*` and the skills run against a small fixture project. Their responses are checked by the existing response linter. Where an example shows its output, the output must match the real output's structure (keys and kinds, not volatile values).
- Untagged examples are prose and fall to review.

### 5. Tool descriptions (D9)

The docstrings and descriptions registered in `src/pyeye/mcp/server.py` and the plugins assemble their fact parts from the extractors when the module loads (edge lists, scope options, parameter names). The prose parts stay hand-written. A conformance test asserts that no description hard-codes a fact the registry owns, by the same mentions rule.

### 6. The presentation layer: `/docs-review`

- **A skill beside `/architecture-review` and `/duplication-review` (#495)**, reusing their machinery: caller-supplied scope (pages, or "pages bound to these changed facts"), findings labelled as judgments, the result states and dismissal state ("this section is fine", remembered until its bound facts change).
- **Finding shape:**
  - what's wrong;
  - the anchor (the fact ID, the failed scoring task, or the audience rule);
  - either proposed replacement text, or two or three options with costs and a recommended one;
  - for genuine ambiguity, an explicit "needs your decision".
- **Nothing is applied automatically** (D8).
- **Inputs.** The uncovered ledger, the changed-fact list, the doc registry with audiences, and the sweep's style checklist (the nit categories).
- **Task-based scoring**, modelled on `pyeye-verify`'s agent-consumption rubric:
  - Each audience has a committed task set (for example, human: "configure a namespace package"; Claude: "find what imports X").
  - A fresh agent gets only that audience's docs (Claude: the skills, instructions and tool descriptions; human: the README and `docs/`) and is scored on each task.
  - Results are recorded as a baseline, and the release pass compares against the previous baseline. Regressions become findings.
- **Triggers (D6):**
  1. Change-triggered: scope is the changed-fact list plus the ledger's new entries.
  2. On demand: any scope.
  3. Release: `scripts/changelog.py prepare X.Y.Z` with a major or minor bump requires a recorded full pass (review plus scoring) for the version, or prints the command to run it. The builder decides whether a missing pass blocks `prepare` or only warns; the default is to warn and record.

### 7. Retiring Sphinx (D1)

Delete `docs/source/**`, `docs/Makefile`, `.github/workflows/build-deploy-docs.yml`, the `docs` dependency group in `pyproject.toml` and `uv.lock`, and Dependabot's `sphinx*` group. Update the `python-explore` link to the ported `docs/architecture/resolution.md`. Update `.claude/instructions` references to `--group docs`. Unpublish Pages, a repo setting for the maintainer. Record a decision entry.

## Constraints

- No new dependency (C4). The checks import pyeye itself; everything else is stdlib, in the style of the existing conformance tests.
- Cross-platform: paths in the registry and the ledger use `.as_posix()`, and comparison goes through `path_utils` (#717).
- 2.x compatibility: `python scripts/changelog.py no-breaking` must still print `0`. Retiring Sphinx is a docs-only change, not a breaking API change.
- Each sub-issue PR carries a changelog fragment. Contracts set here become decision entries (below).
- dev01: the scoring pass is agent-heavy. At most two heavy jobs run machine-wide, memory-capped.

## Sequencing and proposed sub-issues

Ordered so that nothing generation will produce gets hand-fixed:

1. **Retire the Sphinx tree; port the architecture pages to Markdown** (D1). Independent; can go first.
2. **The fact registry, the doc registry and the binding** (`docs_facts generate|check`, marker blocks, `docs/reference/` pages, pre-commit and CI). Includes the "every doc is registered" test.
3. **Migrate the ten point checks onto the registry** as fact checks or prose rules; delete the private file lists. Depends on 2.
4. **Removed-fact mentions and the uncovered ledger** (D4, D5, the cross-layer flags). Depends on 2.
5. **Tool descriptions from extractors** (D9). Depends on 2.
6. **Executed examples** (D10). Depends on 2.
7. **`/docs-review` as an internal skill** in `.claude/skills/docs-review/`, not shipped. It reuses the dismissal state and has the finding shape and the change-triggered and on-demand modes. It reuses #495's shipped machinery. Any Python it needs stays internal: no MCP tool or public surface before v2.2, so it adds no `added` fragment. Depends on 2 and 4.
8. **Fix-up of the remaining sweep findings, driven by the internal `/docs-review`.** Re-check the list (C6), then rewrite the prose that generation didn't remove, rebasing `docs/api/*` on the generated reference pages and examples. This is the skill's first real run, and it triages the ledger's `baseline` section (C3). `fixed` fragments. Depends on 2–7.
9. **Promote `/docs-review` to the shipped `skills/`,** with its conformance test, plus task-based scoring, the per-audience task sets and the release hook in `changelog.py prepare`. `added` fragment. Depends on 8.

### Release split (maintainer)

- **v2.1.1 (patch)** = sub-issues 1–8. The docs are fixed and can't drift. Every fragment is `fixed` (or none, for internal tooling). Under D6 no full pass is needed. If an unrelated `added` fragment merges in the meantime, that release must be v2.2.0 instead, and `prepare` enforces it.
- **v2.2.0 (minor)** = sub-issue 9: `/docs-review` ships. The first full pass before it records the scoring baseline.

## Decision entries to write

- Sphinx retired; Markdown under `docs/` is the only docs tree (D1).
- Docs make only claims the code or a record can back (D12).
- Facts reach the docs only through registered extractors and marker blocks or generated pages; one doc registry, with no private file lists (D2, D3, D11).
- Removed facts fail; new facts go to the ledger (D4, D5).
- Review principle: tools never decide; a recommendation is an anchored assessment; ambiguity asks for a decision. `/docs-review` always recommends or gives options (D8). This deliberately differs from `/architecture-review`'s rule of withholding a recommendation when no anchor exists.
- When review runs: change-triggered, on demand, and major/minor releases (D6).

## Settled after the builder check (Claude's calls; correct any)

- **C1. History pages.** The doc registry has a `history` kind, for pages that must name removed things: `CHANGELOG.md`, `changes/*.md`, `docs/migration-guide.md`, `docs/api-redesign.md`. A history page is registered, so nothing can escape the list. Fact blocks and the honest-claims rule (D12) still apply to it; the removed-name rule (D4) and the other prose rules do not. Example: `migration-guide.md`'s unsourced "2.5x faster" table fails D12. `docs/superpowers/**`, `docs/decisions/**` and `docs/audits/**` stay unregistered, as before.
- **C2. Where removed names come from.** `docs/facts/removed.json` is committed. It is seeded from #509's `GONE_ENTIRELY` and `SURVIVES_AS_INTERNAL_METHOD` (the v1 names, which no extractor can produce) and from today's removed env vars and server commands. `generate` appends to it whenever a fact that's in the committed snapshot (C4) disappears, so a removal is caught in the same PR. Entries are never deleted.
- **C3. One fact per item, and what "covered" means.** There is one fact per parameter, edge, env var, tool, CLI command and CI value. Group IDs (`tool.trace.params`) are views over item facts, used by marker blocks. A fact is "covered" only when a prose section declares it in the page registry. A link to its `docs/reference/` entry doesn't count, because the reference page covers every fact and would make the ledger meaningless. **Day one:** facts that exist when the ledger is first created are recorded as the `baseline` section of `uncovered.json`. That section is triaged once, in the sweep fix-up (sub-issue 8), and isn't left as standing noise. Only facts added later appear as new entries.
- **C4. Environment and change detection.** The extractors live in `src/pyeye/docs_facts/` and import the pyeye in the PR, in the normal `uv` environment, as the mypy hook already does. "Stdlib only" means **no new dependency**. `generate` also writes a committed snapshot, `docs/facts/facts.json`. The changed-fact list (§3) is the diff of that snapshot against the merge base's copy, so no second environment is needed. The snapshot diff shows in the PR, which is also the reviewer's signal.
- **C5. Scoring variance.** The model is pinned for each baseline and recorded with it. Each task runs 3 times. A task's score is pass or fail by majority, plus the tally. A regression is a task that passed in the baseline and fails by majority now. A worse tally on a task that still passes by majority is reported as "weaker", not as a regression. A coordinator-assigned worker runs it at release time, under the dev01 cap (≤2 heavy jobs, memory-capped). A model change starts a new baseline, so it's never compared across models.
- **C6. The sweep list is stale.** It was taken against `95c7b40b`, and v2.1.0 and #495 have landed since. Sub-issue 8 starts by re-checking the 183 findings against current `main` (still wrong / fixed / generated away). It doesn't run a fresh sweep: the internal `/docs-review` run over the fix-up scope serves as that.
- **C8. Removed-name matching (#826, settled with the maintainer).**
  - **Q1.** Each `removed.json` entry has a `match` field: `word` (any mention fails), `heading` (only an API heading fails, for names that live on as internal methods, such as `find_symbol`) or `none` (recorded, not scanned in prose). The defaults are `word` for tools and env vars and `none` for parameters, and the field is the only hand-edited part of an entry. Removed parameters are caught in runnable examples by #828.
  - **Q2.** A live-page line that names a removed name passes only if it also says "removed". On top of that:
    - **A ratchet:** the count of such lines per page is recorded in the registry and can only shrink.
    - **A sunset:** each entry records the release that removed it. From the next major release after that, live-page mentions fail outright, and only history pages may name it. The v2.0 removals leave live pages by v3.0.
  - **Q3.** The surface tests read the removed tool names from `removed.json`. The analyzer-method and module checks keep their own lists, because those aren't doc facts.
- **C9. Registry kinds (#824).**
  - `tests/fixtures/**` is excluded (test input).
  - `changes/*.md` is one history entry; `changes/README.md` is prose.
  - `docs/COVERAGE.md` is **prose**, not history: it's a live guide, and its threshold is bound to `ci.coverage_threshold`.
  - `docs/METRICS_BASELINE.md` and `benchmarks/BASELINE_RESULTS.md` are history, but D12 still applies to them, so their projections and unsourced figures go.
  - `TOKEN_SAVINGS_VERIFICATION.md` is **deleted** (maintainer). Its 40–90% claim concerns a removed tool and a deleted test, and can't be reproduced. #830, or an earlier docs PR, removes it, its registry entry and any links to it.
- **C10. Worker rulings (maintainer, 2026-11-17).**
  - **#825, the honest-claims rule (D12):**
    - Released `## [x.y.z]` CHANGELOG sections are exempt as a historical record, with a note at the top of the changelog. `[Unreleased]` and all fragments must comply.
    - Code constants become extracted facts. An external fact passes on a line that links a primary source.
    - Unenforced policy numbers (">90% new-code coverage") are **removed**, not bound. Enforcing diff coverage would be a separate issue.
    - Prose-only scanning; URLs, badges, inline code, version strings and commands are skipped.
    - A `record` kind, with `date`, `command` and `commit` in front matter. A line passes only by linking a registered record.
    - A shrink-only allow-list keyed on the exact finding message, one entry per occurrence, with the snippets printed on failure (as amended by C12).
    - The patterns are units, multipliers, %, "as of", "currently N", "N+ noun" and token-savings phrasing. Bare counts are left to review.
  - **#825, what the prose rules scan:**
    - registered docs;
    - the live MCP tool descriptions;
    - the **hint and note strings returned to the model in responses** (from `operations/*`), collected without a file list. Comments are not scanned.
    - Operation docstrings keep a thin test by imported object. The #417 ceiling check is driven by facts (`EDGE_CEILINGS`).
  - **#825:** `PYEYE_SCENARIO_DIR` is renamed to `SCENARIO_DIR`, because the prefix falsely suggests a pyeye setting.
  - **#826:**
    - A fourth `match` level, `code`: only a backticked mention fails. It's the default for edge names.
    - `cli.*` defaults to `word`. Value facts are never added to `removed.json`.
    - Each page has `covers: tuple[str, ...]` (views expand to their members). A fact in a marker block on a prose or skill page counts as covered. An unknown ID in `covers` fails `check`.
  - **#828, shown output may be trimmed:**
    - `"<absent>"` asserts that a key really is absent.
    - Every object level that leaves out keys carries `"…": "<omitted>"`, and a shortened array ends with `"<omitted>"`. The checker fails an unmarked omission, so an example never passes itself off as the whole response (D12).
- **C11. Two corrections from #837's mutation tests (maintainer, 2026-11-17).** They amend C1 and C10.
  - **Comments are scanned.** The phrasing rules (absence-vs-zero, `edge_counts`) also scan the `COMMENT` tokens of the modules whose strings they scan. The original #395 miss was a `server.py` comment. This replaces C10's "comments are not scanned".
  - **Fact rules apply to history pages.** The env-var and server-command rules apply to `history` pages too, such as `migration-guide.md`. A gone name passes there only on a line that says "removed" (C8). Released CHANGELOG sections stay exempt. This narrows C1: history exempts a page from the phrasing rules and from the plain removed-name scan, not from the fact rules.
- **C12. Ratchet shape and per-edge ceilings (2026-11-18).**
  - **Every allow-list is keyed on the exact finding message,** one entry per occurrence, and only shrinks. This applies to the prose rules, D12 and #826. A per-page count would let a fix be traded for a new violation (found by #837's mutation tests).
  - **#417, the maintainer's option (c):**
    - #825 derives the "Static-surface ceiling" marker set from the ceiling facts (edges whose ceiling is `static_definitions` or `literal_subclassing`), not from a hand list of edge names.
    - #827 makes every tool description state the ceiling meaning of each edge it exposes, taken from that edge's `EDGE_CEILINGS` fact, with a check that no exposed edge lacks one. That text and its check land together in **one PR (827-2)**, because a check without the text would turn CI red: tool descriptions have no allowance (maintainer, 2026-11-18).
    - The derivation in #825 yields the same two edges as before (`members`, `subclasses`), so it widens nothing and doesn't depend on 827-2.
- **C13. #829, the internal `/docs-review` (maintainer, 2026-11-18).**
  - **Where "deliberately not covered" is stored:**
    - Once, in `docs/facts/review-state.json`, as a dismissal with its reason.
    - `docs_facts generate` reads it, leaves dismissed facts out of the uncovered entries, and writes them into a read-only `dismissed` section of `uncovered.json` (`{fact_id: {reason, date}}`), so every dismissal shows in the ledger diff. Hand edits to that section are overwritten.
    - A dismissal lapses when the fact's value changes.
  - **The finding contract under ambiguity:**
    - Under `needs_decision`, options are mandatory, each with its costs (C14: only there).
    - A recommendation is required whenever an anchor exists, and the finding names the anchor.
    - Under `needs_decision` with no anchor, the finding still gives an assessment labelled "unanchored: judgment only" and states the question it needs answered.
    - A finding is never silent, never presents the assessment as settled, and the tool never decides (D8, the review principle).
- **C14. Two C13 clarifications (maintainer, 2026-11-18).**
  - **Orphaned dismissals fail.** `check` fails on a dismissal in `review-state.json` whose fact ID no longer exists, matching D4's unknown-ID rule. The PR that removes or renames the fact deletes the dismissal or moves it to the new ID. A rename is a removal plus an addition: the new ID enters the uncovered ledger unless the dismissal is deliberately carried over.
  - **Options only under ambiguity.** A finding with one clear fix (e.g. fact drift) carries a single proposed replacement text with its anchor, and no options, as D8 says. Options are mandatory only on `needs_decision` findings.
- **C15. Prose must not state code facts (maintainer, 2026-11-18).** This is the binding rule ("prose references facts, never restates them") applied to statements of behaviour.
  - **The rule.** A statement of what the code does or exposes may not be hand-written prose. That covers subprocesses started, files written and where, what the validator rejects, what `configure_packages` saves, and response shapes. It must come from a bound fact or from an executed example (#828). Prose keeps the why, the how-to and the concepts.
  - **The main route is to add facts.** The first candidates come from #859: the subprocesses the server starts, the paths it writes, and the validator's deny-list. Each gets an extractor, so `fact_drift` and CI cover it.
  - **`code_contradiction` is a narrow fallback,** only for behaviour claims that genuinely can't be a fact or an executed example (e.g. "re-exports collapse to their definition"):
    - Its finding first recommends converting the claim to a fact or example. Only when that's impossible does it propose replacement wording.
    - Its anchor is a code symbol, by its canonical pyeye handle, never `path:line`. `validate` checks that the handle resolves.
    - It must carry **evidence** of what the code does, from pyeye for that handle (`inspect`'s signature, a docstring excerpt, or edge lists). `validate` checks each item against pyeye.
  - **Symbol dismissals** are pinned to the symbol's signature and docstring as `inspect` reports them. A change to either brings the finding back; body edits don't. A handle that no longer resolves is an orphan (C14).
  - **Non-fact dismissals** (style, claims, audience rules) key on a required `subject`: the exact text quoted from the page, checked to occur in the section. When the subject no longer occurs, `check` fails the dismissal as an orphan (C14). If the whole section is gone, the dismissal is pruned, and the text is reviewed fresh under its new heading.
  - **#830 sequencing:**
    1. `SECURITY.md` by hand (#859, done).
    2. Facts for #859's three candidates, which then replace that page's hand-written behaviour statements.
    3. The rest through `/docs-review`, with code statements converted to facts or examples, not reworded.
- **C7. #495 has merged** (`skills/duplication-review/`, `src/pyeye/duplication.py`, v2.1.0), so D7's reuse is against shipped code.

## Left to the builder

- The registry's file format. (The location is settled by C4: `src/pyeye/docs_facts/`, with a thin `scripts/docs_facts.py` entry point.)
- The exact marker and runnable-example syntax, and the fixture project for the examples.
- The ledger's exact schema, beyond fact ID and first-seen version.
- Which existing tests are deleted vs reduced to thin parametrised tests.
- Whether a missing release pass blocks or warns in `prepare` (default: warn).
- Task set contents per audience (seeded from the sweep's MISSING items and the `pyeye-verify` rubric).

## Follow-ups (outside #818)

- **Umbrella `/review`** running architecture, duplication and docs over one scope, with findings labelled by kind (D7, later).
- **Architecture review's assessment when unanchored.** Under the review principle above, it could give an assessment labelled with what it rests on, instead of withholding one. It would still never decide. For the coordinator and maintainer to weigh.
- **Documented conventions as claims** `/architecture-review` can test ("the docs say X; N sites do Y"), from #818 Q6.
