---
date: "2026-10-29"
title: "Shipped prose may not show an unmeasured edge inside `edge_counts`; checked structurally, not as free text (#396)"
issues: [396, 395]
anchors: ["tests/test_edge_counts_prose_conformance.py::unmeasured_edge_claims", "SHIPPED_SURFACES", "tests/conformance/response_linter.py::_PHASE4_UNMEASURED_EDGES", "c092261"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-24-1182-anchors-that-drifted-are-carried-to-their-current-sites.md"]
superseded_by: []
---

## 2026-10-29 — Shipped prose may not show an unmeasured edge inside `edge_counts`; checked structurally, not as free text (#396)

**Friction:** In #392 / PR #395, `subclasses` was correctly dropped from `inspect`'s `edge_counts`, but three skill examples and two `server.py` docstrings still showed it there. CI passed because the skill conformance test checks only the supported-edge *list*, never example prose; a reviewer caught it by hand.
**Decision:** Add a structural scan over shipped surfaces (`python-explore` SKILL.md, `server.py` source, README). Within any paragraph mentioning `edge_counts`, after stripping backticks and line wraps, an edge counts as *claimed present* only as a brace key, as dotted or subscript access, or as an `<edge>: <n>` count. If it is in the response linter's `_PHASE4_UNMEASURED_EDGES`, the test fails. That set is the one already enforced on live responses, so prose and responses share one definition of "measured". Rejected:

- **Marked example blocks:** exact, but needs authoring discipline, and misses unmarked text (the #395 miss included a comment).
- **A bare-name free-text scan:** it would flag correct omission prose like "`edge_counts` omits `callers`".

Known residue: claims phrased entirely in free prose ("0 subclasses") are not caught.
**Anchor:** #396 ; `tests/test_edge_counts_prose_conformance.py::unmeasured_edge_claims` / `SHIPPED_SURFACES` ; `tests/conformance/response_linter.py::_PHASE4_UNMEASURED_EDGES` ; regression baseline is the parent of `c092261` (PR #395).
**Verify:** gold — `uv run pytest tests/test_edge_counts_prose_conformance.py` passes on current surfaces, and its embedded verbatim pre-#395 lines are each flagged. Running `unmeasured_edge_claims` on `git show c092261^:skills/python-explore/SKILL.md` and `…:src/pyeye/mcp/server.py` flags `subclasses` in both (checked at authoring time; the replay uses today's unmeasured set, so it also flags `callers`, which was still measured then). PARTIAL residue: free-prose claims need human review.
