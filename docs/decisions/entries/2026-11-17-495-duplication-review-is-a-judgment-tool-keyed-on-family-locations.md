---
date: "2026-11-17"
title: "Duplication review is a judgment tool over exact-match clone families, keyed on member locations; the shared detector caps repeated windows (#495)"
issues: [495, 492, 498, 616, 636, 629]
anchors: ["pyeye.duplication.find_clones", "pyeye.duplication.DEFAULT_MAX_OCCURRENCES", "pyeye.duplication.build_sites", "pyeye.duplication.build_families", "pyeye.duplication.apply_dismissals", "pyeye.duplication.dismiss", "pyeye.duplication.Family.key", "pyeye.architecture_review.state.non_issue_key", "skills/duplication-review/SKILL.md"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-17 — Duplication review is a judgment tool over exact-match clone families, keyed on member locations; the shared detector caps repeated windows (#495)

**Friction:** The #492 spike showed that the fact-grounded auditor can't see duplication. "Two bodies are near-identical" is a tunable threshold: a graded judgment, not a Tier-1 fact. The #616 ratchet already had an exact-match AST-token detector, but it served only this repository. Three measure-only rounds on #495 found:

- **Run raw**, the detector's top results on django were 43 % real copies, mostly data tables.
- **Repeated data windows made the pair loop quadratic.** On rich's `_emoji_codes.py` alone it was OOM-killed at a 1.5 GB cap.
- **With a function filter, a signature/stub guard and families,** the top 30 families were 77 % / 73 % real on pydantic (two blind adjudicators, κ ≈ 0.73) and 67 % on django, with almost no unrelated pairs.

**Decision:**

- **The core moves to `pyeye.duplication`.** `scripts/duplicate_code_report.py` becomes a thin ratchet wrapper with the same exact-match behaviour. Its `--report-only` output on this tree was byte-identical before and after, at 35, 25 and 15 tokens.
- **The occurrence cap is in the shared `find_clones`.** A window seen more than `DEFAULT_MAX_OCCURRENCES = 50` times is paired with its next occurrence only, so it costs `k - 1` pairs rather than `k(k-1)/2`. Every copy is still reported and connects into one family, so a 51-way copy fails the ratchet like a 2-way one. Skipping such windows outright was rejected: a block copied 51 times then gave zero clones while 50 copies gave 1,225, so the most-copied code vanished silently. Reported runs are stored as disjoint, sorted intervals per (stream pair, offset), checked by bisect: one O(log n) lookup per pair, neither a per-token set nor a linear scan. The ratchet's output on this tree stays byte-identical.
- **Unreadable files never stop the run or leak source.** A file that fails to read, decode or parse is skipped and listed in `unparseable_files`. The ratchet fails on one, because it would hide that file's copies.
- **Review is a judgment, stated as one.** `python -m pyeye.duplication review` takes a **required** scope. Its defaults are 35 tokens and cap 50, with two filters always on:
  - a function filter (more than half of one region's lines inside a `def`);
  - a signature/stub guard (≥60 % of both regions' lines are decorators, signatures or stub defs).
  - The signature/stub guard covers `@overload`, `@abstractmethod` and stub bodies. A concrete method of an ABC or `Protocol` is real code, so it isn't a stub.
  - A region is named after the scope holding **most of its AST tokens**, not where its first token falls: copies often start in the previous function's tail, and naming them after that neighbour would break dismissal identity. Physical lines were rejected because comments and blank lines would count, so a comment-only edit could rename a site.
  - It ranks families, which are connected components over `file::qualname`. A pair between two **different classes** folds its methods into their classes. An intra-class pair keeps its method endpoints unless one of them is also in a cross-class pair. A location that is part of a cross-class pair is always its class node, whatever its other sites' ends are, so every location is in exactly one family. A function or module-level end is otherwise never folded. Module-level ends are keyed by start line, so unrelated module-level regions of one file don't merge.
  - Scopes outside `--root` are rejected, so every key is root-relative and shareable. Bad arguments and bad state files exit 2 with a message before any scan.
- **No source content.** Every result is a pointer: file, line range, qualname, token count. Each output carries `judgment: true` with the thresholds and filters.
- **Dismissal identity (option A).** It reuses `architecture_review.state`: `key = non_issue_key(sorted member locations, "duplication")`, persisted with `load_state` / `save_state` in a caller-chosen committed file.
  - Coverage is decided **per site**: a site is covered when both its locations lie in one dismissal. A family touches a dismissal through a shared location other than `file::<module>` (which unrelated module-level code shares), or through a covered site.
  - A family whose sites are all covered stays suppressed: cosmetic edits, drift between members, a member removed.
  - An uncovered site **re-surfaces the family**, showing only the uncovered sites. That covers a new member, a rename, a move, and a new copy bridging two dismissed families, where no location is new but the site is.
  - A dismissal records a closed-vocabulary reason and a caller-supplied date. An optional `review_after` re-surfaces it as `review-due` once the caller's `today` reaches it. There's no expiry by default and no clock is read.

**Rejected:**

- **An MCP tool.** It would put a tunable judgment next to Tier-1 facts, which #495 argues against.
- **The data-literal guard.** It added almost nothing on top of the function filter.
- **A lower default threshold.** At 25 tokens the extra sites were about 20 % real.
- **MinHash or embeddings.** Exact match is at its ceiling on precision; MinHash is deferred as a recall fix for async near-twins, and embeddings would be non-deterministic and send content to a model.

**Anchor:** `pyeye.duplication` (`find_clones`, `DEFAULT_MAX_OCCURRENCES`, `build_sites`, `build_families`, `apply_dismissals`, `dismiss`, `Family.key`); `pyeye.architecture_review.state.non_issue_key`; `skills/duplication-review/SKILL.md`; #495 (spike comments 6928993057, 6929214559, 6929732914, 6929998690), #616, #636.
**Applies-to:**

- **Region naming and stub facts:** `_FileFacts.majority_scope` (via `_region`) and `_FileFacts._record_function`.

- **Every caller of the detector:** `scripts/duplicate_code_report.py` (the ratchet) and `pyeye.duplication.review` / `main` (the review CLI). Both go through `pyeye.duplication.find_clones`, so both get the cap.
- **Every site that decides whether a duplication family was dismissed:** `apply_dismissals` and `dismiss`, both keyed by `Family.key` via `architecture_review.state.non_issue_key`.
- **Every producer of review output:** `Review.as_dict`, `Family.as_dict` and `format_review`, which emit pointers and counts only.
- **The documented interface:** `skills/duplication-review/SKILL.md`, whose flags, defaults, reasons and thresholds are pinned by `tests/test_duplication_review_skill_conformance.py`.

**Verify:** gold.

- `uv run pytest tests/test_duplication.py tests/test_duplication_review_skill_conformance.py tests/test_duplicate_code_report.py` covers:
  - the cap: work is counted (`FindStats.pairs_examined`): at most one pair per indexed position on a 2,000-repeat table, with a quadratic contrast on a small input; 50, 51 and 120 copies each forming one family; a 51-way copy failing the ratchet;
  - a real copy found next to a capped table; unparseable files skipped without printing source, and the ratchet failing on them;
  - token-weighted naming, including a neighbour edit and a comment-only edit that both keep a dismissal;
  - coverage as one bounded lookup per pair on an input holding many disjoint runs per offset (a work count, not timing);
  - every location in exactly one family;
  - concrete ABC/`Protocol` methods kept; module-level regions and class-to-function pairs not merged; `if`/`else` twins as one location;
  - CLI validation before scanning: bad state, thresholds, dates and out-of-root scopes;
  - the function filter, the signature/`@overload`/`Protocol` guards, and cross-class against intra-class families;
  - dismissal: round-trip, cosmetic edits and drift staying suppressed, a removed member staying suppressed, a new member, rename, move and bridging copy each re-surfacing with only the new site, re-dismissal replacing the old entry, `review_after`, no expiry, and input validation;
  - the no-content check, a required scope, and the CLI;
  - the ratchet's exact BASELINE, which is unchanged.
- The ratchet's byte-identical output was checked by hand at the time of the move and again after the #820 review fixes, not by a test: `duplicate_code_report.py --report-only --min-tokens {35,25,15}` before and after.
