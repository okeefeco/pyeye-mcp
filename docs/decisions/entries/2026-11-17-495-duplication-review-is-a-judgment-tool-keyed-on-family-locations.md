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
- **The occurrence cap is in the shared `find_clones`.** A window seen more than `DEFAULT_MAX_OCCURRENCES = 50` times is never paired, so at most N²/2 pairs are examined per window. The ratchet gets it too. A copy containing such a window is still found from its other windows.
- **Review is a judgment, stated as one.** `python -m pyeye.duplication review` takes a **required** scope. Its defaults are 35 tokens and cap 50, with two filters always on:
  - a function filter (more than half of one region's lines inside a `def`);
  - a signature/stub guard (≥60 % of both regions' lines are decorators, signatures or stub defs).
  It ranks families, which are connected components over `file::qualname`. A cross-class pair folds its methods into their class; an intra-class pair keeps its method endpoints unless one of them is also in a cross-class pair.
- **No source content.** Every result is a pointer: file, line range, qualname, token count. Each output carries `judgment: true` with the thresholds and filters.
- **Dismissal identity (option A).** It reuses `architecture_review.state`: `key = non_issue_key(sorted member locations, "duplication")`, persisted with `load_state` / `save_state` in a caller-chosen committed file.
  - A family whose locations are a **subset** of one dismissal stays suppressed: cosmetic edits, drift between members, a member removed.
  - A location no dismissal covers **re-surfaces the family**, showing only the new locations. That covers a new member, a rename and a move.
  - A dismissal records a closed-vocabulary reason and a caller-supplied date. An optional `review_after` re-surfaces it as `review-due` once the caller's `today` reaches it. There's no expiry by default and no clock is read.

**Rejected:**

- **An MCP tool.** It would put a tunable judgment next to Tier-1 facts, which #495 argues against.
- **The data-literal guard.** It added almost nothing on top of the function filter.
- **A lower default threshold.** At 25 tokens the extra sites were about 20 % real.
- **MinHash or embeddings.** Exact match is at its ceiling on precision; MinHash is deferred as a recall fix for async near-twins, and embeddings would be non-deterministic and send content to a model.

**Anchor:** `pyeye.duplication` (`find_clones`, `DEFAULT_MAX_OCCURRENCES`, `build_sites`, `build_families`, `apply_dismissals`, `dismiss`, `Family.key`); `pyeye.architecture_review.state.non_issue_key`; `skills/duplication-review/SKILL.md`; #495 (spike comments 6928993057, 6929214559, 6929732914, 6929998690), #616, #636.
**Applies-to:**

- **Every caller of the detector:** `scripts/duplicate_code_report.py` (the ratchet) and `pyeye.duplication.review` / `main` (the review CLI). Both go through `pyeye.duplication.find_clones`, so both get the cap.
- **Every site that decides whether a duplication family was dismissed:** `apply_dismissals` and `dismiss`, both keyed by `Family.key` via `architecture_review.state.non_issue_key`.
- **Every producer of review output:** `Review.as_dict`, `Family.as_dict` and `format_review`, which emit pointers and counts only.
- **The documented interface:** `skills/duplication-review/SKILL.md`, whose flags, defaults, reasons and thresholds are pinned by `tests/test_duplication_review_skill_conformance.py`.

**Verify:** gold.

- `uv run pytest tests/test_duplication.py tests/test_duplication_review_skill_conformance.py tests/test_duplicate_code_report.py` covers:
  - the cap: work is counted (`FindStats.pairs_examined`) on a 2,000-repeat table, with a quadratic contrast on a small input;
  - a real copy found next to a capped table;
  - the function filter, the signature/`@overload`/`Protocol` guards, and cross-class against intra-class families;
  - dismissal: round-trip, cosmetic edits and drift staying suppressed, a removed member staying suppressed, a new member, rename and move each re-surfacing with only the new location, re-dismissal replacing the old entry, `review_after`, no expiry, and input validation;
  - the no-content check, a required scope, and the CLI;
  - the ratchet's exact BASELINE, which is unchanged.
- The ratchet's byte-identical output was checked by hand at the time of the move, not by a test: `duplicate_code_report.py --report-only --min-tokens {35,25,15}` before and after.
