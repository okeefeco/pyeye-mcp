---
date: "2026-11-15"
title: "One goto-disambiguation policy; inspect's superclasses field reads the edge (#624)"
issues: [624]
anchors: ["pyeye._goto.goto_target", "pick_target", "pyeye.mcp.operations.edges.superclass_bases"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — One goto-disambiguation policy; inspect's superclasses field reads the edge (#624)

**Friction:** Four call sites picked among Jedi `goto` results with four rules. Callees and imports took the first result with a `full_name`; superclasses (edge, plus a copy in inspect) preferred a class, then took the first; typeref required exactly one. A first-match guess is a confident answer to an ambiguous question: the same `.clear()` resolved to `collections.OrderedDict.clear` in one file and `typing.MutableMapping.clear` in another. inspect's `superclasses` field and the `superclasses` edge were separate implementations that already disagreed: declaration order versus sorted by handle, and raw text for an unresolved base versus a silent drop. typeref carried a byte-for-byte copy of `attr_target_position`.

**Decision:** `pyeye._goto.goto_target(script, line, col, prefer=None)` is the only picker: exactly one distinct `full_name`, or, with `prefer`, exactly one of that kind; otherwise `None`.

- Every caller reports `None` honestly: `unresolved_call_sites`, `unresolved_imports`, the new `unresolved_superclasses`, or a typeref without a handle. No heuristic was added.
- Measured before deciding, over the #614 corpora and src/pyeye: 10 of 3,752 call sites and 1 of 500 imports changed from a guess to unresolved; no superclass did. Every case was a real ambiguity: union receivers, `try`/`except ImportError` fallback bindings, and inference splits.
- `edges.superclass_bases` is the one walk over a class's declared bases. The edge keeps the resolved bases in DECLARATION order (the start of the MRO; previously sorted by handle) and lists the rest in `unresolved_superclasses`, by source text, mirroring #494's `unresolved_imports`. inspect's field is built from the same walk: handles where resolved, text where not, so it is unchanged for clients. `inspect._resolve_base_class_via_jedi` and typeref's `_attribute_target_position` are deleted.
- Rejected: keeping a smarter tie-break (prefer project scope, or prefer the first `try` branch), which would be a guess presented as an answer; and leaving the field independent of the edge (the #330 drift).
- Not changed here: typeref forward refs (`x: "Foo"`) still use a project-wide bare-name search and can disagree with `x: Foo`. #623 slice 5 moves them onto the shared resolver; a strict xfail pins the gap.
- Noted, not changed: a base written as a call (`class C(make_base())`) resolves to the factory function's handle, in both the field and the edge, because goto lands on the call's name.
- The inheritance edges agree on scope (#669, same PR): `subclasses` searches `edges._project_search_scope` (the main project, `packages`, and every configured namespace), the scope `project` stubs and the `superclasses` edge resolve into. Standalone script directories are excluded: they are not configured project code. Configured paths are normalised once, where every consumer reads them (#668): `ProjectConfig._normalise_config_path` (`~` expanded, anchored to the project, `..` collapsed) serves both `get_namespaces()` and package paths, so `ProjectManager`, plugins and `configure_packages` agree and the file↔module mapper can place files under a `../repo` namespace.

**Anchor:** `pyeye._goto.goto_target` / `pick_target`; `pyeye.mcp.operations.edges.superclass_bases`; response_linter rule E.6.
**Applies-to:** every place that picks a `goto` result for an edge or a type:

- `edges._resolve_call_target` (the callees and imports edges);
- `edges.superclass_bases` (the superclasses edge, `edge_counts.superclasses`, and inspect's `superclasses` field);
- `typeref._resolve_head_via_jedi`.
- The `subclasses` edge's search scope (`edges._project_search_scope`, #669).
- Configured namespace and package path normalisation (`ProjectConfig._normalise_config_path`, #668).

Out of scope: `resolve.py`'s position goto and `resolver.py` (#623), and the dead `JediAnalyzer` goto paths (#628).

**Verify:** gold. `uv run pytest tests/unit/mcp/operations/test_goto_policy.py tests/test_cross_tool_invariants.py::test_superclasses_field_is_the_edge tests/conformance/test_linter_adversarial_expand.py::TestExpandUnresolvedSuperclassesRule tests/test_import_layers_fitness.py` passes:

- the no-guess rule on synthetic `goto` results, and the regression fixture (union receiver, `try`/`except` fallback binding) now reports unresolved;
- an AST scan finds no direct `.goto(` call in `edges.py`, `inspect.py` or `typeref.py`, and no attr-position copy in typeref;
- the field equals the edge (declaration order, plus unresolved text) for every class in every #614 corpus;
- `_goto` imports neither `jedi` nor `pyeye.mcp`.
