---
date: "2026-11-21"
title: "Every edge stub handle round-trips through resolve: edges name a definition by resolve's rules, or not at all (#1071)"
issues: [1071, 1070, 1065, 1049, 1025, 1024, 1022, 1057]
anchors: ["pyeye.resolver.local_definition_handle", "pyeye.mcp.operations.edges._handle_for_name", "pyeye.resolver.base_class_lookup", "pyeye._goto.pick_target", "tests/unit/mcp/operations/test_edge_stub_round_trip.py"]
status: "active"
amends: ["2026-11-21-1065-superclasses-say-why-a-base-is-unresolved.md", "2026-11-20-1025-members-of-a-local-class-are-named-after-it.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-21 — Every edge stub handle round-trips through resolve: edges name a definition by resolve's rules, or not at all (#1071)

**Friction:** found while building #1065 (PR #1070). Edges named stubs from Jedi's `full_name` alone (`edges._handle_for_name`), while `resolve` had grown its own naming rules. Two gaps followed.

- **(a) An unnamed class.** `resolve` names a class nested in a function-local class `pkg.m.f.Outer.Inner` (#1025), but Jedi's `full_name` is `None` there. `superclasses` reported such a base as `no_handle`, and `subclasses` on it returned a measured `[]`.
- **(b) A handle resolve calls ambiguous.** In `def g(X): class X; class D(X)`, D's base was emitted as `pkg.m.g.X`, and `resolve` answers that `ambiguous`, because the parameter binds `X` too (#1049). The same went for #1022's two `class Twin` statements, which appeared as an `ambiguous` candidate.

**Decision:** coordinator-3's assignment, 2026-11-21. Every stub handle round-trips uniquely, and an edge that can't name a definition uniquely reports an honest loss.

- **Name as resolve names.** A definition with no Jedi `full_name` is named by `resolver.local_member_full_name` (#1025) in:
  - `_handle_for_name`, the stub builder;
  - the base lookup (`pick_target(..., name_of=local_member_full_name)`; `pick_target` takes a naming function and stays in the lower `_goto` layer);
  - the class graph's base key;
  - the `subclasses` source.
- **Keep a function-local handle only if resolve gives it back.** `resolver.local_definition_handle(name, handle, analyzer)` returns the handle only when `resolve_item` answers that same handle at the same file and line; otherwise `None`. This enforces the round trip directly instead of re-deriving #1049's binding count, so the edges can't drift from `resolve` (#1022, #1024, #1049).
  - **Loss reporting:** a stub without a handle is dropped. A base without one becomes `unresolved_superclasses`, with reason `no_handle`, or `ambiguous` with that candidate left out, as #1065's `candidate_count > len(candidates)` rule allows. The class graph gives it no key.
- **Amends #1065:** `no_handle` no longer covers a class in a local class, which now resolves. It means "found, but no handle names it uniquely": a name the function binds twice, or a class in a nested function.
- **Amends #1025:** the edges, not only `resolve` and `members`, now name a class nested in a local class.
- **Cost:** the check runs only for function-local definitions, which is one Jedi `parent()` walk per stub (`is_function_local`). The `ast`-tier `re_exports` edge skips it for its own source (`check_local=False`), because that handle came from `resolve`. The #452 no-Jedi conformance check holds this.

**Anchor:** `pyeye.resolver.local_definition_handle`; `pyeye.resolver.local_member_full_name`; `pyeye.resolver.base_class_lookup`; `pyeye._goto.pick_target`; `pyeye.mcp.operations.edges._handle_for_name` / `resolve_subclasses` / `resolve_re_exports`; `pyeye.analyzers.jedi_analyzer.JediAnalyzer._base_target_name`; #1071, #1065, #1049, #1025.

**Applies-to:** `pyeye.resolver.local_definition_handle`, `pyeye.resolver.base_class_lookup`, `pyeye._goto.pick_target`, `pyeye.mcp.operations.edges._handle_for_name`, `pyeye.mcp.operations.edges.resolve_subclasses`, `pyeye.mcp.operations.edges.resolve_re_exports`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._base_target_name`.

**Verify:** gold. `uv run pytest tests/unit/mcp/operations/test_edge_stub_round_trip.py tests/unit/mcp/operations/test_unresolved_superclass_details.py tests/test_edge_determinism.py` passes. It checks:

- `C(Outer.Inner)`'s superclass is `app.m.f.Outer.Inner`, and that class's subclasses are `[app.m.f.C]`;
- `D(X)` with a parameter `X` has `no_handle` and no stub;
- `E(Twin)` is `ambiguous` with `candidates: []` and `candidate_count: 2`;
- a unique local base keeps its handle both ways;
- every stub from `members`, `superclasses`, `subclasses` and `enclosing_scope` on the fixture resolves, unambiguously, to the same handle and line;
- the `re_exports` no-Jedi check still holds.
