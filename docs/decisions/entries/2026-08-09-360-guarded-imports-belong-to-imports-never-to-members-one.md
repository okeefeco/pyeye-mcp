---
date: "2026-08-09"
title: "guarded imports belong to `imports`, never to `members` — one shared module-scope walk (#360)"
issues: [360, 630, 353]
anchors: ["pyeye._module_scope.iter_module_scope_imports", "SCOPE_BOUNDARY_NODES", "edges", "_iter_module_scope_imports", "mypackage._core.guarded_imports_fixture", "deep_guarded_imports_fixture"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-08-09 — guarded imports belong to `imports`, never to `members` — one shared module-scope walk (#360)

**Friction:** `outline("pyeye.mcp.operations.edges")` listed `JediAnalyzer` as a child of a module that does not define it — it is imported under `if TYPE_CHECKING:`. `_module_members` built its import-subtraction set from `tree.body` only, so guarded imports never entered it and survived Jedi's module-scope `get_names` as members; `inspect.edge_counts.members` over-counted in lockstep. Probing the fixture project showed the leak is not TYPE_CHECKING-specific (a `try`/`except ImportError` shim leaks identically) and that `resolve_imports` carried the SAME `tree.body`-only scan — so fixing `members` alone would have moved a real dependency from "misfiled" to "invisible on every edge".

**Decision:** One shared walk, `_iter_module_scope_imports`, consumed by both edges — `members` SUBTRACTS what it yields, `imports` EMITS it — so the two cannot drift apart again. The rule is BINDING scope, not nesting: descend every statement-bearing construct (`if`/`else`, `try`/`except`/`else`/`finally`, `with`, `for`, `while`, `match`) and stop only at `def` / `class` / `lambda`, whose imports bind a local or class attribute rather than a module name. Rejected: special-casing `if TYPE_CHECKING:` (would have left the `try`/`except` and version-guard forms leaking, and needs a new case per guard), and the issue's stated members-only scope (see Friction). Both branches of an either/or shim are emitted — each is statically present and which one runs is a runtime fact. Accepted consequence: guarded imports of C-extension symbols now reach `unresolved_imports` (stdlib `os`'s `from posix/nt import _exit`); suppressing unresolved reporting for guarded imports was rejected as a re-introduction of the #494 silent drop, so the affected trace test moved to a project-only seed instead.

**Amended 2026-11-15 (#630):** the walk moved to the leaf module `pyeye/_module_scope.py` (imports only `ast`) so `analyzers/` can share it without importing `pyeye.mcp`, and it gained `include_guarded`. **`True` (the default) is the rule above**, used wherever the question is "is this name bound at module scope" (the edges). **`False` yields only unguarded statements directly in `tree.body`**, for callers that commit to *which object* a name is bound to: a guarded binding may never run, and in a try/except shim either branch may win. `analyzers.base_resolution` relies on it for its "never a wrong answer; `None` means ask Jedi" contract, so switching it to `True` there would make subclasses commit to bases that may not be the ones bound.

**Anchor:** `pyeye._module_scope.iter_module_scope_imports` (+ `SCOPE_BOUNDARY_NODES`; `edges` imports it as `_iter_module_scope_imports`); fixtures `mypackage._core.guarded_imports_fixture` / `deep_guarded_imports_fixture`; #360, #630. Adjacent, still open: #353 (labelling imported vs locally-defined names).

**Applies-to:** every caller. `include_guarded=True`: `edges._module_members`, `edges.resolve_imports`. `include_guarded=False`: `base_resolution.build_import_table`, `build_star_sources`, `build_module_defines`.

**Verify:** gold — for `mypackage._core.guarded_imports_fixture`, `resolve_members` returns exactly `{_FEATURE_FLAG, DEFAULT_NAME, make_widget, guarded_consumer, load_default, Holder, guarded_function}`; `widgets.{Widget,Premium,Deluxe,Config}` appear in `resolve_imports().handles` and in no member handle; `widgets.DEFAULT_NAME` (imported inside a `def`) and `widgets.make_widget` (imported inside a `class` body) appear in NEITHER edge, while the same-named module-level definitions remain members; `imports ∩ members == ∅`. Covered by `tests/unit/mcp/operations/test_edges.py::TestGuardedImportsExcludedFromMembers` and `::TestGuardedImportsIncludedInImports`. `inspect.edge_counts.members` follows for free — `_count_module_members` delegates to `resolve_members`. For `include_guarded=False` (#630): `tests/unit/analyzers/test_base_resolution.py` pins that guarded imports stay out of all three base_resolution tables and that a guarded base resolves to `None` (4 of those tests fail with `True`). The ratchet `tests/test_decision_invariants_fitness.py::test_module_scope_import_walk_is_shared` allows no other `tree.body` import walk (its allow-list is empty).
