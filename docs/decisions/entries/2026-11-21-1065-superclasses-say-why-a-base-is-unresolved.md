---
date: "2026-11-21"
title: "superclasses says why each unresolved base didn't resolve: unresolved_superclass_details (#1065)"
issues: [1065, 1057, 1006, 624, 999]
anchors: ["pyeye.resolver.base_class_lookup", "pyeye.resolver.BaseLookup", "pyeye.mcp.operations.edges.superclass_bases", "pyeye.mcp.operations.edges.resolve_superclasses", "tests/unit/mcp/operations/test_unresolved_superclass_details.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-21 — superclasses says why each unresolved base didn't resolve: unresolved_superclass_details (#1065)

**Friction:** `unresolved_superclasses` lists the unresolved bases' source text, but not why. After #1057, a base bound through a try/except shim is unresolved, and the agent can't tell that apart from a typo, a call, or a class it may not see, nor which classes it could be.

**Decision** (the maintainer's ruling on #1065's write-up, via designer, 2026-11-21, Q1–Q5 as proposed):

- **`unresolved_superclass_details`**: always present on `superclasses` and absent elsewhere. It is parallel to `unresolved_superclasses`, same order, `details[i]["base"] == unresolved_superclasses[i]`. Changing the existing list to objects would have been breaking.
- **Six reasons:** `not_a_name` (a call or other expression), `unresolvable` (no target, or a Jedi error), `ambiguous` (several distinct targets, or a name bound at two places in one file), `not_a_class`, `restricted` (#999) and `no_handle` (found, but no handle names it).
- **`ambiguous` adds `candidates` and `candidate_count`.** `candidates` are the handles of the candidates that are classes with a handle, sorted. `candidate_count` counts every distinct target. A restricted, handleless or non-class candidate is counted, never listed, so `candidate_count > len(candidates)` says some can't be shown. That's #1006's count-versus-list idiom.
- **No cap; `expand` only.** `inspect`'s `superclasses` field and `trace` are unchanged.
- **One lookup decides both.** `pyeye.resolver.base_class_lookup` (#1069's resolution) returns the target or the reason. `base_class_target`, which the class graph behind `subclasses` uses, is its target, so the lookup that decides resolved-or-not also says why. The restricted filtering of candidates is inside it too. Only `no_handle` for a target with a dotted name is decided at the edge, which builds the handle.
- **Deferred (Q6):** an `ambiguous_subclass_count` on the base side.

**Anchor:** `pyeye.resolver.base_class_lookup`, `BaseLookup`; `pyeye.mcp.operations.edges.superclass_bases`, `resolve_superclasses`; #1065.

**Applies-to:**

- `pyeye.resolver.base_class_lookup` and `base_class_target`;
- `pyeye.mcp.operations.edges.superclass_bases`, `_base_detail` and `resolve_superclasses`, and `EdgeResult`;
- `pyeye.mcp.operations.expand.expand_resolved`;
- `superclass_bases`' other callers, which ignore the detail: `pyeye.mcp.operations.inspect` and `pyeye.plugins.pydantic`;
- the `expand` description, the `python-explore` skill, and the response linter's E.10.

**Verify:** gold. `uv run pytest tests/unit/mcp/operations/test_unresolved_superclass_details.py tests/conformance/test_linter_adversarial_expand.py` passes. It covers each reason on a real fixture; the shim's sorted candidates; a restricted sole target and a restricted candidate counted but not listed; order parallel to `unresolved_superclasses`; a measured `[]`; candidates only on `ambiguous`; absence on other edges; the lookup shared with `base_class_target`; and E.10's shape rules.

Not covered by a fixture: a C module's class (`_thread._local`) is `unresolvable` here, because Jedi sees no definition of it in pyeye's environment. A shim whose branches include one has been seen to resolve to its Python branch, so `candidate_count > len(candidates)` is exercised only through a restricted candidate.
