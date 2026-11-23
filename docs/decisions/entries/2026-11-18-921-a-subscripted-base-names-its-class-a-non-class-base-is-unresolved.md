---
date: "2026-11-18"
title: "A subscripted base names its class; a non-class base is unresolved (#921, #922)"
issues: [921, 922, 624, 417, 505]
anchors: ["pyeye._ast_targets.unsubscripted", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._get_base_name_from_ast", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._get_ast_leaf_position", "pyeye.mcp.operations.edges.superclass_bases"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-24-1182-anchors-that-drifted-are-carried-to-their-current-sites.md"]
superseded_by: []
---

## 2026-11-18 — A subscripted base names its class; a non-class base is unresolved (#921, #922)

**Friction:** the class graph dropped every base that wasn't a plain name or attribute, so `class IntBox(Box[int])` was missing from `Box`'s subclasses and `class Ids(RootModel[list[int]])` from `find_pydantic_models`. In the other direction, the `superclasses` edge resolved any base expression by goto at its start. That reported the function `make_base` for `class M(make_base())`, django's `BaseManager` for `Manager(BaseManager.from_queryset(QuerySet))`, and the module `typing` for `typing.Generic[T]`. These answers were confidently wrong, the failure #505 removed tools for.

**Decision:** this defines what the `subclasses` and `superclasses` edges count.

- **A subscripted base names the class it subscripts:** `Box[int]` and `Box[int][str]` name `Box`, and `pydantic.RootModel[list[int]]` names `pydantic.RootModel`. Only the subscripted value counts. A class named inside the type arguments (`Generic[Box[int]]`) is not a base. This is still within the `literal_subclassing` ceiling, because the class statement names the class.
- **A base that isn't a class reference is unresolved, never reported as a superclass.** That covers:
  - a call;
  - a conditional;
  - any other non-name expression, after subscripts are removed;
  - a name whose goto lands on something other than a class (a function, a variable).

  It goes to `unresolved_superclasses` with its source text. The class graph already skipped such bases, so they add no subclass entries.
- **One helper, `pyeye._ast_targets.unsubscripted`,** is used by the class graph and by `superclass_bases`, so the two directions can't disagree on what a base names.
- **Classified `Fixed`:** missing subclasses appear, and wrong superclasses become unresolved. On django at the pinned commit the probe suite and round-trip are unchanged. The visible diffs are all corrections (PR #930).

**Anchor:** `pyeye._ast_targets.unsubscripted`; `pyeye.analyzers.jedi_analyzer.JediAnalyzer._get_base_name_from_ast`, `_get_ast_leaf_position`; `pyeye.mcp.operations.edges.superclass_bases`; #921, #922, #624, #417, #505.
**Applies-to:**

- the class graph, and so the `subclasses` edge, `trace` and `find_pydantic_models`: `pyeye.analyzers.jedi_analyzer.JediAnalyzer._get_base_name_from_ast`, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._get_ast_leaf_position`;
- the `superclasses` edge and `inspect`'s `superclasses` field: `pyeye.mcp.operations.edges.superclass_bases`;
- the shared rule: `pyeye._ast_targets.unsubscripted`.

**Verify:** GOLD. `uv run pytest tests/test_subscripted_bases.py tests/test_superclasses_non_class_bases.py` covers:

- subscripted bases under subclasses (expand and trace) and in `find_pydantic_models`;
- type arguments excluded;
- a qualified subscripted superclass, with the handle per interpreter;
- call, conditional, function, variable and subscripted-call bases unresolved, and a class base unchanged.
