---
date: "2026-11-15"
title: "v2.x release classification: contract-conforming corrections are `Fixed`, not breaking; a major is reserved for removals and renames (#629)"
issues: [629, 623, 626, 627, 628, 594, 505]
anchors: ["scripts/changelog.py", "_BREAKING", "prepare", "docs/RELEASE.md"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — v2.x release classification: contract-conforming corrections are `Fixed`, not breaking; a major is reserved for removals and renames (#629)

**Friction:** The #629 drift audit found many responses that break the documented v2 contract: unresolvable stdlib handles, an echoed alias instead of the canonical handle, `kind: "namespace"`, measured `[]` for edges that don't apply, "never raises" tools that raise, and a documented `PYEYE_CACHE_TTL` that does nothing. Fixing them changes visible output. If each such change is called breaking, the epic forces a v3 weeks after v2.0, for clients that are mostly agents guided by the python-explore skill shipped in the same plugin, which upgrade in lockstep. `changelog.py prepare` refuses a minor bump when notes contain `### BREAKING CHANGES`, so one mislabelled entry would force a major by accident.
**Decision:**

- A change that makes output match the documented contract (spec, tool docstrings, absence-vs-zero, DECISIONS) is `### Fixed` (patch), even when clients see different answers. v2.0's own removals (#505) set this precedent: confidently wrong answers are bugs.
- A new response field is `### Added` (minor).
- Only removing or renaming a field, tool, argument or documented setting is `### BREAKING CHANGES` (major). Those changes are deferred and batched; the deprecation warning ships in 2.x first.

Applied to the #629 children:

- #626: wrong-kind becomes `unsupported`, raising becomes `found: false`, and `handle`/`detail` are added to resolve's not-found response. Fixed/Added.
- #627: plugin results keep `name`/`file`/`line` and gain `handle`/`scope`/absolute path. Added.
- #628: `PYEYE_CACHE_TTL` is wired to the live cache (Fixed). The four settings that are read but unused (#592) get a deprecation warning now and are removed only in a real major.
- #594 is to be re-checked for an additive form before it keeps its `!`.

Rejected: a v3 for the epic, which is churn with no protected client; holding every visible change for a major, which would ship known-wrong answers for longer.
**Anchor:** `scripts/changelog.py` (`_BREAKING`, `prepare` under-bump check); `docs/RELEASE.md` "Semantic Versioning"; epic #629 and children #623, #626, #627, #628; #594; #505.
**Verify:** PARTIAL — gold: while the next release is 2.x, `awk '/^## \[Unreleased\]/{f=1;next} /^## /{f=0} f' CHANGELOG.md | grep -c '^### BREAKING CHANGES'` prints 0, and `python scripts/changelog.py prepare 2.<x>.<y>` does not refuse. Unverifiable without human review: whether a given entry is truly contract-conforming (that needs reading the documented contract), and whether a removal was mislabelled `Fixed` to dodge the major.
