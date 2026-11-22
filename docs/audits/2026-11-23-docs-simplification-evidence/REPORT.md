---
date: "2026-11-23"
command: "python row1_removed.py <checkout of 55e35597>; python row3_ledger.py 55e35597; python row3_causes.py row3_ledger.json; python row4_findings.py; python row4_per_run.py (see Re-running)"
commit: "55e35597"
---

# Evidence for the docs-design simplification table

Read-only evidence for the table in "Current state (consolidated 2026-11-22)" of `docs/superpowers/specs/2026-11-17-docs-built-on-facts-design.md`. That section was read from PR #1097's branch `docs/818-design-c19-static-facts` at **44478ef6**, since the PR was still open.

- **Pinned commit for all repo data:** `main` at **55e35597**, 2026-11-22. Every hash in this record is shortened to 8 hex characters (see "Shortened hashes").
- **How:** every count below says how it was produced. The scripts and raw outputs are in this directory, next to this file; "Re-running" at the end says how to reproduce each one.
- **No edits:** nothing in the repository, its review state or its CI was changed.

Counts come first in each section. **Interpretation is kept separate**, at the end.

| Artefact in this directory | What it holds |
|---|---|
| `row1_removed.py` → `row1_removed.json` | the removed-name rule run at 55e35597, plus an all-`word` variant |
| `ci_failed_runs.json`, `ci_removed_hits.txt` | the failed CI runs scanned, and the matching log lines (none) |
| `row3_ledger.py` → `row3_ledger.json` | every revision of `uncovered.json` |
| `row3_causes.py` → `row3_causes.json` | why each entry left, and the fact counts at three commits |
| `row4_findings.py` → `row4_findings.json` | the findings files, by category and anchor kind |
| `row4_per_run.py` → `row4_per_run.json` | the same, per /docs-review run |
| `findings-copy/<run>/*.json`, `findings-copy.sha256` | the 68 findings files, copied from the review sessions, one directory per run (32 have shortened `page_hash` values; see "Shortened hashes") |
| `findings-copy/v2.2.0-prerelease/REPORT.txt` | that run's own report, as written |
| `found_findings_files.txt` | the 68 findings files used |
| `records/*.txt` | the #830 issue and the 15 #830 PR bodies and comments, as fetched from GitHub |

The captured text (`records/`, the pre-release report) is stored as `.txt`: it's data, kept verbatim, not documentation.

The JSON files are in the repository's JSON style (2-space indent, sorted keys, ASCII escapes; the `pretty-format-json` hook). Each findings file is JSON-equal to the file captured from its session, apart from the shortened `page_hash` values; `findings-copy.sha256` hashes the committed bytes.

## Shortened hashes

Every hex hash in this record is cut to its first **8** characters, because `detect-secrets` (the repository's pre-commit hook, with its baseline and configuration unchanged) flags longer ones as high-entropy secrets. They are public commit IDs and page content hashes, not secrets.

- **Changed:** this file (the pinned commit), `row1_removed.json` (`commit`), `ci_failed_runs.json` (the merge-queue branch names end in a commit ID), and the 32 `findings-copy/v2.2.0-prerelease/*.json` files (`page_hash`). `row1_removed.py` and the `ci_failed_runs.json` command in "Re-running" now emit 8 characters, so they reproduce the committed files.
- **Why 8:** the hook's flags, by hash length, measured on the files as captured with every hash of that kind cut to that length. Commit IDs reach zero at 10, `page_hash` values only at 8, and one rule keeps the record consistent:

  | Length | 40 | 12 | 11 | 10 | 9 | 8 |
  |---|---|---|---|---|---|---|
  | commit-ID flags (this file, `row1_removed.json`, `ci_failed_runs.json`) | 15 | 1 | 1 | 0 | 0 | **0** |

  | Length | 16 | 12 | 11 | 10 | 9 | 8 |
  |---|---|---|---|---|---|---|
  | `page_hash` flags (one per file, in 32 files) | 27 | 11 | 9 | 6 | 4 | **0** |

- **Still unique:** each of the 13 commit IDs resolves to its one full commit at 8 characters (8 with `git rev-parse --verify <id>^{commit}`, the 5 merge-queue commits with `gh api repos/okeefeco/pyeye-mcp/commits/<id>`). The 32 `page_hash` values stay distinct at 8.
- **Not byte-identical:** the 32 pre-release findings copies no longer match their captures byte for byte, and their `page_hash` no longer matches the 16-character hash `scripts/docs_review.py` writes. Everything else in them is unchanged. `findings-copy.sha256` was regenerated over the committed bytes.
- **Left verbatim:** `records/*.txt` is fetched GitHub text and keeps whatever hashes it quotes (none is flagged).

---

## Row 1: removed-name rules (mechanism 4)

### Counts

**1a. Entries in `docs/facts/removed.json`.** Source: `git show 55e35597:docs/facts/removed.json`.

| `match` level | Entries |
|---|---|
| `word` | 8 |
| `heading` | 7 |
| `code` | **0** |
| `none` | 4 |
| **total** | **19** |

**1b. History of `removed.json`.** Source: `git log 55e35597 -- docs/facts/removed.json`.

- One revision only: **77584a66** (2026-11-17, #826/#846) created all 19 entries.
- No entry has been added or removed since, and no `match` level has been edited.

**1c. What the rule matches today.** Source: `row1_removed.py`, run against a checkout of 55e35597 and importing that checkout's own `docs_facts` (`registry.build`, `removed.load`, `removed.mentions`); output in `row1_removed.json`.

- 57 live pages were scanned (registered `prose` and `skill` pages). The current major is 2.
- **15 mentions**, all at `word` level, **all marked** (the line says "removed"), so **0 failures**.
- The allow-lists (`DocEntry.allow["removed-name"]`) hold **15 entries on 4 pages**, one per marked mention.
- No removed name is live again, so none is skipped as live.

**1d. Allow-list churn.** Source: `git log -p 55e35597 -- src/pyeye/docs_facts/docs.py`, counting `+`/`-` lines containing `names removed`.

| Commit | Added | Removed | What |
|---|---|---|---|
| 77584a66 (2026-11-17, #826) | 23 | 0 | the rule's own commit: the seed baseline |
| a3e4bd49 (2026-11-18, #830/#902) | 0 | 8 | a page rewrite removed the mentions, so the ratchet required deleting the stale entries |
| **total** | **23** | **8** | 15 remain; **no entry was ever added after the seed** |

**1e. CI history.** Source: `gh run list --workflow ci.yml --status failure --created "2026-11-17..2026-11-22T12:45:00Z" --limit 1000` gave 55 failed runs, out of 578 `ci.yml` runs in the same window (`gh run list --workflow ci.yml --created "2026-11-17..2026-11-22T12:45:00Z" --limit 2000`). The capture was taken on 2026-11-22 between 12:41 and 12:50 UTC, so the window's end is pinned there. Each failed run's `gh run view <id> --log-failed` was then searched for the rule's three messages:

- `which was removed. Point readers`: an unmarked mention;
- `removed before this major release`: a mention after the sunset;
- `removed-name:`: the ratchet, new or stale.

Result: **0 matching lines in 0 runs** (`ci_removed_hits.txt` is empty).

**1f. Pre-commit history.** Not measurable: local pre-commit runs leave no central record.

- Proxy: the commit messages on `main` that mention the rule (`git log -i -E --grep="removed-name|removed name|removed\.json" 55e35597`) are the rule's introduction (77584a66), its design and migration commits (eb598b01, fc49ab5e), and a3e4bd49 (row 1d).
- No commit message records a fix prompted by the rule.

**1g. A plain word rule, measured.** The same script with every entry forced to `match: "word"` (`row1_removed.json`, `all_word_variant`):

- **47 mentions** (versus 15): 26 marked, **21 would fail**.
- All 21 failures are lines that today's levels deliberately don't scan:

| Name (real level) | Lines | Example |
|---|---|---|
| `lookup` (`none`) | 12 | "an exact-path lookup goes through one resolver" (docs/architecture/resolution.md:74) |
| `find_symbol` (`heading`) | 6 | `mock_analyzer.find_symbol.return_value` (docs/testing/CONVENTIONS.md:194) |
| `exclude_patterns` (`none`) | 3 | "`exclude_patterns` is deprecated and has no effect" (docs/TROUBLESHOOTING.md:230) |
| `get_type_info`, `list_modules`, `find_subclasses` (`heading`) | 3 | internal method names in .claude/instructions/07-validation.md:43 and docs/namespace-packages.md:164–165 |

**1h. Did the per-page ratchet ever catch something a word match wouldn't?**

- From 1d and 1e: the ratchet fired only in the **stale** direction, once (a3e4bd49, 8 entries), during an intentional page rewrite.
- It has never fired in the **new** direction (a new marked mention), locally on `main` or in CI.
- There is therefore no recorded case of it catching anything.

### Notes on what can't be counted

- Local pre-commit failures, and CI failures on branches whose runs have since been deleted, are not visible. `gh run list` returned runs back to 2026-11-17T20:11, which covers the rule's whole life.

---

## Row 2: dismissal lifecycles (mechanism 9)

### Counts

Source: `git log --all --name-only --format=` filtered on `review.state`, and `git log --all -- docs/facts/review-state.json`.

- **`docs/facts/review-state.json` has never been committed, on any branch.** The only paths matching "review state" in history are `src/pyeye/architecture_review/state.py` and its test, which belong to a different skill.
- `review.py`'s `STATE_PATH` has named that file since 93eaffb5 (2026-11-17, #829/#855). Source: `git log -S"review-state.json" -- src/pyeye/docs_facts/review.py`.

| Dismissal kind | Existing | Lapsed | Failed (orphaned) | Pruned |
|---|---|---|---|---|
| fact-pinned | 0 | 0 | 0 | 0 |
| symbol-pinned | 0 | 0 | 0 | 0 |
| subject-keyed | 0 | 0 | 0 | 0 |
| `code_bug` | 0 | 0 | 0 | 0 |
| section-pruned (`mark-fine`) | 0 | 0 | 0 | 0 |

- **Mirror:** `uncovered.json`'s mirrored `dismissed` section is **0 in every one of its 17 revisions** (row 3's script prints each revision's sizes).
- **Corroboration:** the 2026-11-19 pre-release run's own report says "no review state written (`lift-blocked`, `mark-fine` and `dismiss` were not run)" (`findings-copy/v2.2.0-prerelease/REPORT.txt`).
- **Outcomes:** the #830 slice PRs report that their findings were applied or decided, never dismissed (`records/pr866.txt`, `pr869.txt`, `pr876.txt`, `pr877.txt`, `pr880.txt`, `pr881.txt`).

---

## Row 3: uncovered-fact ledger (mechanism 6)

### Counts

Source: `row3_ledger.py 55e35597` → `row3_ledger.json`, which diffs every revision of `docs/facts/uncovered.json` (`git log --reverse 55e35597 -- docs/facts/uncovered.json`, 17 revisions). Causes come from `row3_causes.json`: a resolved ID still present in that commit's `docs/facts/facts.json` counts as covered, and one that isn't counts as its fact being removed.

| | Count |
|---|---|
| `baseline` at creation (77584a66, 2026-11-17) | 171 |
| `baseline` resolved since | **67**, all by covering prose (the fact still existed) |
| `baseline` entries added after creation | 0 |
| `baseline` open now | **104** |
| `new` entries ever added | 33, all on 2026-11-18 |
| `new` resolved | 1, by its fact being removed (85e68f99, #914) |
| `new` open now | **32**, all `first_seen: 2.2.0` |
| dismissed (mirrored), ever | 0 |

**Where the 67 baseline resolutions happened.** Source: the `events` list in `row3_ledger.json`.

| Commit | PR / issue | Resolved |
|---|---|---|
| eeed7be2 | #866 (#830 README) | 28 |
| 8664968a | #877 (#830 api/architecture) | 12 |
| 2d1fc367 | #881 (#830 skills, tool descriptions) | 10 |
| aab9ed93 | #886 (#830 skills) | 6 |
| 8e1188c7 | #867 (#830 SECURITY) | 2 |
| aa239589 | #880 (#830 guides) | 2 |
| 8ef763b5 | #876 (#830 CONTRIBUTING etc.) | 1 |
| b9e343c6 | #847 (#844, the honest-claims rule) | 2 |
| 85e68f99 | #918 (#914, metrics refactor) | 2 |
| 9bf4a7fd | #986 (#983, pre-release docs fixes) | 2 |
| **#830 slices** | | **61** |
| **other** | | **6** |

**How the baseline was triaged.** #830's scope says "Triage the ledger's `baseline` section once" (`records/issue830.txt`). The triage happened as page rewrites during the #830 slices: the 61 above, all by covering prose. **No baseline entry was dismissed.** No #830 record mentions a separate pass over the remaining 104.

**What is still open, and how old.** Age is measured from the commit that added the entry to the pinned date, 2026-11-22.

- **baseline, 104:** 85 `tool.*`, 11 `env.*`, 4 `review.*`, 2 `cli.*`, 1 `edges.*`, 1 `project.*`. All have been in the ledger since 77584a66 (2026-11-17), so 5 days.
- **new, 32:** 28 `precommit.*`, 3 `env.*`, 1 `tool.*`. All since 2026-11-18 (088e4f9b and 4 later commits), so 4 days.

**Facts entering since.** Source: the size of `docs/facts/facts.json`'s fact map.

- It was 210 at 77584a66, 282 at 088e4f9b and **289** at 55e35597.
- `git log 088e4f9b..55e35597 -- docs/facts/facts.json` lists 12 commits.
- **No new ledger entry was added after 2026-11-18**, so every fact added since was covered when it landed.

---

## Row 4: finding categories and anchor kinds (mechanism 9)

### Where the counts come from

`/docs-review` findings are written to scratch JSON files and validated with `scripts/docs_review.py validate`; **they are never committed**. The repo's only record is prose in PR bodies, which gives totals but no categories.

The per-category counts below come from the findings files that **survived in four review sessions' local scratch directories** on 2026-11-23. They are now committed here in `findings-copy/`, JSON-equal apart from the shortened `page_hash` values (`findings-copy.sha256`).

- Search: a recursive `grep -rl --include=*.json -E '"category"\s*:\s*"(fact_drift|uncovered_fact|code_contradiction|honest_claims|audience|style)"'` over the sessions' scratch directories found 68 files (`found_findings_files.txt`, under their committed names).
- All 68 were accepted by `row4_findings.py`: each is a list of objects with a closed category and an anchor object.
- The files were last written between 2026-11-18 and 2026-11-19 (their modification times when collected; a checkout doesn't keep them).

**The local files reconcile with the PR records.** Each session's total equals the totals its PRs state (`records/*.txt`):

| Run (`findings-copy/` directory) | Pages | Findings (files) | Stated in the PRs |
|---|---|---|---|
| #869 history pages (`830-history-pages`) | 4 | 38 | #869: "38 findings" |
| #866 + #876 + #881 (`830-readme-contrib-skills`) | 7 | 45 | 7 + (10 + 8) + 20 = 45 |
| #877 + #880 (`830-guides-api-architecture`) | 25 | 168 | 23 + 145 = 168 |
| v2.2.0 pre-release check (`v2.2.0-prerelease`) | 32 | 120 | its own report: 120, with the same category table |
| **total** | | **371** | |

PR #877 also mentions "about 14 code contradictions the skill couldn't categorise before #864". They aren't in the files, so they aren't counted here

### Counts per category. Source: `row4_per_run.json`

| Category | #830 slices (251) | Pre-release (120) | **All (371)** |
|---|---|---|---|
| `style` | 94 | 58 | **152** |
| `honest_claims` | 63 | 24 | **87** |
| `code_contradiction` | 32 | 19 | **51** |
| `audience` | 37 | 6 | **43** |
| `fact_drift` | 25 | 13 | **38** |
| `uncovered_fact` | 0 | 0 | **0** |
| page-level (`section: "*"`) | 0 | 0 | **0** |

`needs_decision`: 12 findings in total (#830 slices 9, pre-release 3).

### Counts per anchor kind. Source: `row4_findings.json`

| Anchor kind | Findings |
|---|---|
| `style_rule` | 152 |
| `claims_rule` | 87 |
| `symbol` | 51 |
| `audience_rule` | 43 |
| `fact` | 38 |
| `literal` | **0** |
| `task` | **0** |

Each category used exactly one anchor kind: `style`→`style_rule`, `honest_claims`→`claims_rule`, `code_contradiction`→`symbol`, `audience`→`audience_rule`, `fact_drift`→`fact`.

### Rule IDs. Source: `rule_ids` in `row4_per_run.json`, compared with `RULE_IDS` in `src/pyeye/docs_facts/review.py`@55e35597

- **Defined:** 21 rule IDs (6 claims, 6 audience, 9 style).
- **Used:** 20 of them. **Never used:** `bridge-problem-fix`.
- One more finding uses `duplication`, the ID's earlier name, which #891 (66534047) replaced with `duplicated-prose`.

| Rule ID | Uses | | Rule ID | Uses |
|---|---|---|---|---|
| `invalid-example` | 60 | | `broken-link` | 5 |
| `D12-absolute` | 43 | | `right-audience` | 4 |
| `link-not-restate` | 34 | | `duplicated-prose` | 3 (+1 as `duplication`) |
| `orphaned-text` | 31 | | `D12-volatile` | 3 |
| `missing-prerequisite` | 23 | | `D12-measurement`, `D12-number`, `contradictory-directive`, `human-explains`, `imprecise-limit` | 2 each |
| `D12-projection` | 22 | | `restated-example`, `claude-directs` | 1 each |
| `D12-comparison` | 15 | | `bridge-problem-fix` | **0** |
| `dated-claim` | 14 | | | |
| `restated-code` | 12 | | | |

Routes on `code_contradiction` findings: 39 `wording`, 11 `fact`, 1 `example`.

### Timeline: which features each run could use

Sources: `git log -1 --format="%h %ad" 66534047` and `gh pr view <n> --json mergedAt`.

- #891 (66534047, 2026-11-18 02:22 UTC) added `literal` anchors, page-level findings and `code_bug` routes.
- All five #830 slice PRs merged before it, between 2026-11-17 22:17 and 2026-11-18 01:04, so **those runs could not use them**.
- Only the 2026-11-19 pre-release run could, and it used **0 `literal` anchors, 0 page-level findings and 0 `code_bug` dismissals**.

---

## Row 5: task-based scoring (mechanism 11)

- **Not built.** #831 is **OPEN**, last updated 2026-11-17 (`gh issue view 831 --json state,updatedAt`).
- No scoring code or task set is on `main` (`git ls-tree -r --name-only 55e35597` has no scoring artefacts).
- There is nothing to measure.

---

## Interpretation (separate from the counts above)

These are readings of the counts, offered for the maintainer's decision, not conclusions.

1. **Removed names.**
   - In five days the rule has caught nothing: no CI failure, no new allowance, and no recorded fix.
   - Its only activity was required bookkeeping (8 stale allowances deleted).
   - The `match` levels do real work. A plain word rule would fail 21 lines today, all false positives: `lookup` as an English word, internal methods named like removed tools, and an ignored config key. So "one rule: word match plus the 'removed' exemption" would need those 21 lines either reworded or allow-listed, or the names dropped from scanning. Dropping them is what `heading` and `none` do now.
   - `code` has no entries, so it costs only its code path and tests.
   - Five days is a short window. Most removals happened before the rule existed, at 2.0, so its catch rate should rise only when names are removed in future.
2. **Dismissals.**
   - None of the five lifecycles has ever run on real data. No review state has ever been committed, and no run used `dismiss`, `mark-fine` or `lift-blocked`.
   - Their cost so far is design, code and tests only. There's no evidence for or against any one of them in use.
3. **Ledger.**
   - The baseline was worked down once, by 61 entries, as a side effect of the #830 page rewrites, not by reviewing the ledger.
   - Nothing has touched the remaining 104 since 2026-11-18. 85 of them are `tool.*` facts, probably parameter-level items that pages cover only as a group.
   - The `new` section filled in one day (28 `precommit.*` facts from #889) and hasn't moved.
   - New facts since then were covered at once. That suggests the ledger's live value is "nothing new slips through uncovered", and the baseline is static.
4. **Categories and anchors.**
   - Five of six categories have real findings; `uncovered_fact` has none, because the ledger, not the review, handles that work.
   - Five of seven anchor kinds are used. `literal` and `task` have none: `literal` landed after most runs and went unused in the one run that could use it, and `task` belongs to unbuilt scoring.
   - Page-level findings: none.
   - Rule IDs are well used (20 of 21), so the per-rule validation isn't idle.
   - Each category used exactly one anchor kind, which is the 1:1 pairing `CATEGORY_ANCHOR` enforces. If categories were folded together, their anchors would fold with them.
5. **Scoring.** Nothing to assess until #831 is built.

**Evidence quality.**

- Rows 1–3 are complete and reproducible from git and `gh` at the pinned commit.
- Row 4 relied on local scratch files from four sessions. They reconcile exactly with every total stated in the PRs, and are now committed in `findings-copy/` (#1110), so its counts reproduce from the repository.
- This page is registered as a D12 `record` (#1110), so other pages can link it to back a figure.

---

## Re-running

From this directory, in a clone of okeefeco/pyeye-mcp that has the pinned commits. Each regenerates its output file, and on 2026-11-23 each reproduced the outputs here exactly.

| Output | Command |
|---|---|
| `row1_removed.json` | `git worktree add --detach /some/dir 55e35597`, then `python row1_removed.py /some/dir > row1_removed.json` (it imports that checkout's own pyeye; the output records the commit) |
| `row3_ledger.json` | `python row3_ledger.py 55e35597 > row3_ledger.json` |
| `row3_causes.json` | `python row3_causes.py row3_ledger.json > row3_causes.json` |
| `row4_findings.json` | `python row4_findings.py > row4_findings.json` |
| `row4_per_run.json` | `python row4_per_run.py > row4_per_run.json` |
| `ci_failed_runs.json` | `gh run list --workflow ci.yml --status failure --created "2026-11-17..2026-11-22T12:45:00Z" --limit 1000 --json databaseId,createdAt,headBranch,event --jq '[.[] \| .headBranch \|= sub("(?<s>[0-9a-f]{8})[0-9a-f]{32}$"; "\\(.s)")]' \| python -m json.tool --sort-keys --indent 2` (the `--jq` shortens the merge-queue branch SHAs to 8). For the total, the same without `--status` and with `--limit 2000`, piped to `--jq length`. **Time-dependent:** keep the pinned `--created` end, or later runs are counted too. Runs older than GitHub's log retention can no longer be read |
| `ci_removed_hits.txt` | for each run ID, `gh run view <id> --log-failed`, searched for the three messages in row 1e |

The other counts are one-line `git` or `gh` commands, each named beside its number above. #1109 re-runs this record.
