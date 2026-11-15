---
date: "2026-06-28"
title: "Reverse references are a sanctioned LSP handoff, not a dead-end deferral (#489)"
issues: [489, 333]
anchors: []
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-28 — Reverse references are a sanctioned LSP handoff, not a dead-end deferral (#489)

**Friction:** The python-explore skill's headline honest-limits rule told the agent reverse references "cannot be answered reliably yet" (deferred to #333) and offered only forward edges — a dead end. But the harness almost always already carries a Pyright/Pylance-backed LSP tool that answers exactly "who calls / references this," and pyeye's `resolve`/`inspect`/`resolve_at` already emit the def-site `location` (`file:line:column`) an LSP reference query needs. Treating the deferral as a hard wall left a real, composable capability unused — and an agent with no sanctioned path is the one most tempted to cheat with grep or the legacy reference tools.
**Decision:** Reframe pyeye's reverse-reference deferral as a sanctioned *handoff*: pyeye drives orientation/structure/forward facts; delegate the inbound questions to the editor's LSP via `resolve` → def-site `location` → LSP `findReferences` / `incomingCalls` / `goToImplementation` → `resolve_at` to map results back into handle space. Delegation is explicitly *not* faking; the grep + legacy-tool (`find_references`/`get_call_hierarchy`) ban and the absence-vs-zero (`edge_counts` omits, never `0`) rule stay intact. Added a "roles, not redundancy" rule: never consult pyeye and the LSP for the *same* fact (Jedi vs Pyright infer independently and can disagree — two oracles voting erodes the trust a single honest answer is for). When no LSP is in reach, fall back to the prior honest refusal + forward edges (`callees`/`imported_by`/`imports`). Rejected: keeping the flat "not available yet" wall (leaves the capability unused and invites grep cheats).
**Anchor:** `skills/python-explore/SKILL.md` ("Honest Limits — pyeye Has No Reverse References (Delegate to Your LSP)") ; #489 (refs #333).
**Verify:** PARTIAL — gold: `tests/test_python_explore_skill_conformance.py` (6/6) guards the skill's supported-edge list against the live edge registry, so the reverse edges stay documented-as-deferred and the absence-vs-zero invariant holds. The behavioural claim — that an agent actually delegates to the LSP rather than grepping — is human-observed [unverifiable mechanically].
