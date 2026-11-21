---
date: "2026-11-22"
title: "TYPE_CHECKING-only imports are marked type_only: true, on the stub in expand and on the edge in trace (#1081)"
issues: [1081, 360, 1083, 619]
anchors: ["pyeye._module_scope.iter_module_scope_imports_guarded", "pyeye.mcp.operations.edges.resolve_imports", "pyeye.mcp.operations.trace.trace", "tests/unit/mcp/operations/test_type_only_imports.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-22 — TYPE_CHECKING-only imports are marked type_only: true, on the stub in expand and on the edge in trace (#1081)

**Friction:** `expand(module, "imports")` returns every module-scope import, guarded ones included (#360), with no way to tell a type-checking dependency from a runtime one. A layering check built on it reported `pyeye.plugins.handles` → `pyeye.analyzers` as a violation, though `JediAnalyzer` is imported only under `if TYPE_CHECKING:`. The architecture-facts trial (#1083) had to re-parse the AST to filter it.

**Decision** (coordinator-3, user-approved, 2026-11-22):

- **`type_only: true`, absent otherwise:** the absent-not-false convention of outline's `truncated` (O.2). It's always measured, since the walk sees every import, so absence is a measured "no". The always-present rulings cover measured loss lists and counts, not per-node flags, so they don't clash.
- **On the stub in `expand`, on the EDGE in `trace`:** `{from, to, kind: "imports", type_only: true}`. This refines the issue's "same for trace stubs". Trace nodes are deduped by handle, and one module can be imported type-only by one node and at runtime by another, so a node-level flag would be wrong for one importer. Type-only is a property of the import, not of the module.
- **Computed in #360's one walk:** `pyeye._module_scope.iter_module_scope_imports_guarded` yields each import with its flag, and `iter_module_scope_imports` is a wrapper over it, so `members` and `imports` still share one walk.
  - Type-only means inside the body of an `if` on the guard, at any depth below it (a nested `if`, a `try`).
  - The `else`/`elif` branch is runtime, and `if not TYPE_CHECKING:` swaps them.
  - The guard is the bare `TYPE_CHECKING`, an alias imported from `typing` or `typing_extensions` (`from typing import TYPE_CHECKING as TC`), or `<module>.TYPE_CHECKING` for any name either module is imported as (`import typing as t`).
- **Any runtime import wins:** a target imported both ways, or collapsed onto one canonical handle with a runtime import (`_canonical_import_targets`), is not type-only.
- **A documented limit:** a module that defines its own `TYPE_CHECKING = False` isn't recognised as a guard.

**Anchor:** `pyeye._module_scope.iter_module_scope_imports_guarded`; `pyeye.mcp.operations.edges.resolve_imports`; `pyeye.mcp.operations.trace.trace`; #1081.

**Applies-to:**

- `pyeye._module_scope.iter_module_scope_imports_guarded` and `iter_module_scope_imports`;
- `pyeye.mcp.operations.edges.resolve_imports` and `_canonical_import_targets`;
- `pyeye.mcp.operations.trace.trace`, `_split_type_only` and `_edge`;
- the `expand` and `trace` descriptions, the `python-explore` skill's imports row, and the response linter's E.12 and T.14.

**Verify:** gold. `uv run pytest tests/unit/mcp/operations/test_type_only_imports.py tests/conformance/test_linter_adversarial_expand.py tests/conformance/test_linter_adversarial_trace.py` passes. It covers each guard form (bare, `typing.`, the aliases, `typing_extensions`, else, `not`, nested `if`, `try` inside, other guards, `elif`); the plain walk equalling the guarded one; the acceptance fixture (only the type-only target is marked, never `false`); no other edge carrying it; the flag on the trace edge and never the node, with a second runtime importer of the same module; and E.12 and T.14.
