---
date: "2026-11-20"
title: "A dotted name shared by several local definitions is ambiguous, never the first one (#1022)"
issues: [1022, 1011, 857, 623, 1025, 1026]
anchors: ["pyeye.resolver.resolve_handle", "pyeye.resolver.NotFound", "pyeye.resolver._shared_local_definitions", "pyeye.mcp.operations.resolve.resolve_at", "tests/unit/mcp/operations/test_same_name_locals.py"]
status: "amended"
amends: ["2026-11-15-623-one-canonical-handle-resolver-every-tool-echoes-the.md"]
supersedes: []
amended_by: ["2026-11-20-1025-members-of-a-local-class-are-named-after-it.md"]
superseded_by: []
---

## 2026-11-20 — A dotted name shared by several local definitions is ambiguous, never the first one (#1022)

**Friction:** Jedi names a function-local definition `pkg.mod.outer.Twin`, so two `class Twin` in one function (`if`/`else` branches, or a plain redefinition) share one dotted name. The resolver placed it with `_anchor_on_bindings`, whose last rule keeps the first binding (#857's rule, written for module-level names). The results were false answers:

- `resolve_at` on the second definition, or on a use after the branches, returned the first definition's location;
- `resolve`, `inspect` and `expand` described one class for a name that names two. Found in #1011's investigation.

**Decision** (coordinator-assigned; no new keys or reasons):

- **Detected in the resolver.** When the matches for a dotted path are two or more distinct definitions, all inside a function at any depth, `_place_definition` returns every one. `resolve_handle` answers `NotFound(unresolved)` with a detail that says so, and carries them as `NotFound.candidates`, an internal field, not a response key.
- **`resolve(dotted)`** answers `ambiguous` with every definition as a candidate, as a bare name does (capped by `max_candidates`).
- **`resolve_at`** answers with the definition `goto` landed on, at its own location. On a use that could be either, it answers `ambiguous` with both.
- **The handle-taking tools** (`inspect`, `expand`, `outline`, `trace`) answer not-found rather than describe one of them. `NotFound.honest_detail` lets them show the reason, as they already did for #999's restricted refusals.
- **Module-level names are unchanged:** #857's binding rules still apply.

**Anchor:** `pyeye.resolver.resolve_handle`, `NotFound.candidates`, `NotFound.honest_detail`, `_shared_local_definitions`; `pyeye.mcp.operations.resolve.resolve_at`; #1022.

**Applies-to:**

- the resolver: `pyeye.resolver.resolve_handle`, `pyeye.resolver.NotFound`, `pyeye.resolver._place_definition`, `pyeye.resolver._shared_local_definitions`;
- the operations: `pyeye.mcp.operations.resolve.resolve`, `pyeye.mcp.operations.resolve.resolve_at`, `pyeye.mcp.operations.inspect.inspect`, `pyeye.mcp.operations.expand.expand`, `pyeye.mcp.operations.outline.outline`.

**Verify:** gold — `uv run pytest tests/unit/mcp/operations/test_same_name_locals.py` passes. It checks:

- `resolve` is ambiguous for both collision kinds (branches, redefinition);
- `resolve_at` gives each definition its own location, and is ambiguous at a use;
- `inspect` and `expand` are not-found, with a detail naming the count;
- a unique local still resolves;
- a module-level `if`/`else` keeps the first binding.

Out of scope, filed separately with repros: a local class's members are measured as `0` (#1025), and a class two function levels deep gets `no_symbol_at_position` (#1026).
