---
date: "2026-11-20"
title: "Members of a function-local class are measured and named after it (#1025)"
issues: [1025, 1022, 1011, 1026, 392]
anchors: ["pyeye.resolver.local_member_full_name", "pyeye.resolver._local_class_member", "pyeye.mcp.operations.edges._class_members", "tests/unit/mcp/operations/test_local_class_members.py"]
status: "amended"
amends: ["2026-11-20-1022-a-name-shared-by-local-definitions-is-ambiguous-never-the-first.md"]
supersedes: []
amended_by: ["2026-11-21-1071-edge-stub-handles-round-trip-through-resolve.md"]
superseded_by: []
---

## 2026-11-20 — Members of a function-local class are measured and named after it (#1025)

**Friction:** Jedi names a function-local class (`pkg.mod.outer.Local`) but gives its members, and the scope wrappers `parent()` returns, `full_name=None`. The `members` edge filtered on `full_name`, so a local class with a body reported `members: 0` and `expand(members)` `[]`, a false zero, and its members' handles resolved nowhere. #1011 option 2 will name about 2,825 such classes on django, so this had to come first.

**Decision** (coordinator-approved as within the maintainer's #1011 ruling: existing notation, additive, no new keys or reasons):

- **Measured from the class.** For a function-local class, `_class_members` reads the class's own scope (`defined_names()`) instead of filtering on `full_name`.
- **Named after the class.** A member is named `<class handle>.<name>` (`local_member_full_name`), recursively for a class nested in one. That's built from the module and the scope chain, because Jedi's wrappers are unnamed. Only members of a class, with at most one function in the chain, are named. A class in a nested function stays unnamed (#1026, #1011's `nested_local`).
- **Resolvable.** On a miss, the resolver places `X.name` as a member of `X` when `X` resolves to ONE function-local class (`_local_class_member`); `resolve_at` names the definition the same way. A member of a class name several local classes share (#1022) stays unresolved. A member defined twice in one local class is ambiguous, by #1022's rule.
- **Additive:** these handles resolved nowhere before. Module-level classes are unchanged.

**Anchor:** `pyeye.resolver.local_member_full_name`, `_local_class_member`; `pyeye.mcp.operations.edges._class_members`; #1025.

**Applies-to:**

- the resolver: `pyeye.resolver.local_member_full_name`, `pyeye.resolver.is_function_local`, `pyeye.resolver._local_class_member`, `pyeye.resolver._place_definition`;
- the edge: `pyeye.mcp.operations.edges.resolve_members`, `pyeye.mcp.operations.edges._class_members`;
- the position lookup: `pyeye.mcp.operations.resolve.resolve_at`.

**Verify:** gold — `uv run pytest tests/unit/mcp/operations/test_local_class_members.py` passes. It checks:

- a local class's members, and a nested class's, listed by `expand` and counted the same by `inspect`;
- each member handle resolving, and `resolve_at` naming it the same, at its own line;
- members of a colliding local class staying unresolved;
- a member of a class in a nested function staying unnamed;
- a module-level class unchanged.
