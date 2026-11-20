---
date: "2026-11-20"
title: "Subclasses with no handle are reported, and the class graph is keyed by definition site (#1006)"
issues: [1006, 445, 435, 397, 1011]
anchors: ["pyeye.analyzers.project_graph.ClassFact", "pyeye.mcp.operations.edges.resolve_subclasses", "pyeye.mcp.operations.edges.EdgeResult", "pyeye.mcp.operations.expand.expand_resolved", "tests/unit/mcp/operations/test_handleless_subclasses.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-20-1024-unique-local-classes-are-named-handle-segments-are-identifiers.md"]
superseded_by: []
---

## 2026-11-20 — Subclasses with no handle are reported, and the class graph is keyed by definition site (#1006)

**Friction:** the `subclasses` edge under-reported and gave no sign of it. `JediAnalyzer._class_inventory` keyed classes by `module.Name`, so a same-named class nested in a function or class overwrote the module-level one and took its handle, a false answer. Every file with no module path fell back to its file stem, so same-named classes across apps collapsed into one. The resolver then skipped every subclass whose name couldn't become a handle (`_try_handle(...) is None → continue`). On django, the measurement in #1006 found a large share of `Model`, `ModelAdmin`, `Form` and `Migration` subclasses missing, and Pyright's base references matched an independent AST tally.

**Decision** (the maintainer's option A, via designer, 2026-11-20):

- **Key by site.** The class inventory and `ClassGraph.classes` / `children_by_key` are keyed by `file:line:column`. `ClassFact` carries `full_name` (`module.Outer.Inner` for a class in a class) or `None` with `unnamed_reason`: `function_local`, `no_module_path` or `not_a_handle`, checked in that order.
- **Never a false handle.** A class with no handle never gets someone else's.
- **Report, don't drop.** `expand(…, "subclasses")` always carries `handleless_subclass_count`, which is complete, and `handleless_subclasses`: `[{name, file, line, reason}]`, sorted by file then line. That list is capped by `max_stubs` as its own budget, separate from `stubs`' `truncated` / `total`, so a cut shows as `count > len(list)`. `trace` following `subclasses` carries `handleless_subclass_counts`, `{handle: count}`, present iff `subclasses` was walked; nodes with none are omitted.
- **Named for what they are,** not `unresolved_*`: these classes were found and resolved as subclasses; only the handle is missing. The response linter groups them with the other loss fields by name (E.9, T.12).
- **The handle grammar is unchanged** (ASCII identifiers). `not_a_handle` covers the rest. Handles in Python's own notation are investigated separately in #1011.
- **Rejected:** option B, counts only (the agent couldn't `Read` them), and option C, stubs without a handle (breaks the stub contract).

**Anchor:** `pyeye.analyzers.project_graph.ClassFact`; `pyeye.mcp.operations.edges.resolve_subclasses`, `EdgeResult.handleless_subclasses`; `pyeye.mcp.operations.expand.expand_resolved`; #1006.

**Applies-to:**

- the inventory and graph: `pyeye.analyzers.jedi_analyzer.JediAnalyzer._class_inventory`, `_build_class_graph`, `find_subclasses`, and `pyeye.analyzers.project_graph.ClassFact` / `ClassGraph`;
- the edge: `pyeye.mcp.operations.edges.resolve_subclasses`, `pyeye.mcp.operations.expand.expand_resolved` and `pyeye.mcp.operations.trace.trace`;
- consumers of `find_subclasses`: `pyeye.plugins.django.DjangoPlugin._indirect_class_views` (an unnamed view is reported by site and not walked);
- the `expand` and `trace` tool descriptions and the `python-explore` skill.

**Verify:** gold — `uv run pytest tests/unit/analyzers/test_class_inventory_sites.py tests/unit/mcp/operations/test_handleless_subclasses.py tests/conformance/test_linter_adversarial_expand.py tests/conformance/test_linter_adversarial_trace.py` passes. It checks:

- nested and function-local same-name classes, two `0001_initial.py` files and a non-ASCII name, each counted once with the right reason;
- no false handle;
- the sorted list, its separate cap and the complete count;
- the `trace` map, present only when `subclasses` is walked;
- the E.9 / T.12 response shapes.

Partial for django: the corpus check (pyeye-scenarios, pinned `cd385e6b8c`) gives direct counts equal to Pyright's base references for `Model`, `ModelAdmin`, `Form`, `Migration` and `View`. It isn't in CI.
