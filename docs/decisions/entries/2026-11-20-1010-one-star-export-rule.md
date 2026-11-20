---
date: "2026-11-20"
title: "One star-export rule for resolve, the class graph and the re-export binding index (#1010)"
issues: [1010, 1007, 405, 712]
anchors: ["pyeye.star_exports.star_exported_from", "pyeye.star_exports.build_star_sources", "pyeye.star_exports.bound_names", "pyeye.analyzers.base_resolution.resolve_base", "pyeye.canonicalization._star_bindings", "tests/test_one_star_rule.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — One star-export rule for resolve, the class graph and the re-export binding index (#1010)

**Friction:** after #1007, three places read `from x import *` three ways. `resolve` used `pyeye.star_exports` (the source's static `__all__`, else names not starting with `_`). The class graph's base resolution (`base_resolution._follow`, #405) followed every star for any name. The binding index behind `re_exports` didn't follow stars, so `inspect("django.forms.forms.Form").re_exports` was `[]`, although `django.forms` re-exports `Form` through `from django.forms.forms import *`.

**Decision:** approved via coordinator-3 (2026-11-20; issue #1010 and its comment). The visible changes are added `re_exports` entries, and subclass results that honour `__all__`. No keys are added.

- **The rule stays in `pyeye.star_exports`.** `star_exported_from(listed, name)` applies it to a precomputed `static_all`, and `star_exported` calls it. `build_star_sources` moved there from `base_resolution`, which re-exports it, so the index doesn't import the analyzers layer. `bound_names(tree)` gives a module's own module-scope bindings, the candidates when there's no static `__all__`.
- **Class graph:** `ClassGraph.star_alls` holds each module's static `__all__`, and `resolve_base` takes it. `_follow` tries a star source only when it star-exports the leaf. Otherwise the AST doesn't commit, and the base goes to the Jedi `goto` fallback, as for any base the AST can't settle.
- **Binding index:** `_star_bindings` computes, for each module in the package, the names its stars bind: each source's static `__all__`, else its public `bound_names` plus what its own stars bring in (recursively, with a cycle guard). As in `resolve`, a name the module binds itself beats a star, and the first source that exports a name wins. Each becomes a binding `source.N -> M.N`, so the existing BFS follows it, and `_is_public_binding` decides whether it is reported. A public plain module star-importing a private one counts, by rule 3 of #712.
- `canonicalization._static_all` is gone. It couldn't tell "no `__all__`" from an empty one. `_is_public_binding`'s rule 2 reads `static_all` instead. One small difference: an `__all__` that mixes a literal assignment with a dynamic one now counts as dynamic, so it lists nothing for rule 2, where before the literal part counted.
- **Not covered:** a star source outside the scanned package isn't read (the index is per top-level package, as for explicit imports). Python's order-dependence, where a later star rebinds a name, isn't modelled, as in #1007.
- **Measured on django `cd385e6b8c`:** none of the 9,724 class bases' AST answers changed (`scripts/measure_subclass_fallback.py` also uses the rule now: still 647 fallbacks). The class graph build time didn't change. Measured alone (no other capped job at the start or end of any run), three runs each against #1031's base `afecc699`, the medians were 101.46 s on main and 101.16 s with this change. `Form`'s `re_exports` went from `[]` to `["django.contrib.gis.forms.Form", "django.forms.Form"]`.

**Anchor:** `pyeye.star_exports`; `pyeye.analyzers.base_resolution.resolve_base`; `pyeye.canonicalization._star_bindings`; `tests/test_one_star_rule.py`; #1010.

**Applies-to:**

- `pyeye.star_exports.star_exported_from`, `pyeye.star_exports.build_star_sources`, `pyeye.star_exports.bound_names`;
- `pyeye.analyzers.base_resolution.resolve_base`, `pyeye.analyzers.base_resolution._follow`, `pyeye.analyzers.project_graph.ClassGraph`, and `pyeye.analyzers.jedi_analyzer.JediAnalyzer._build_ast_resolution_tables`;
- `pyeye.canonicalization._build_binding_index`, `pyeye.canonicalization._star_bindings`, `pyeye.canonicalization._is_public_binding`, and through them `inspect`'s `re_exports` and `expand(handle, "re_exports")`;
- `scripts/measure_subclass_fallback.py`.

**Verify:** gold — `uv run pytest tests/test_one_star_rule.py` passes. It checks:

- `re_exports` lists a name in a static `__all__`, a public name with no `__all__`, a star of a star, a dynamic `__all__`'s public name, and a private source behind a public module;
- it doesn't list a name outside `__all__`, an underscore name, or a name the module binds explicitly;
- a star cycle ends; `inspect` and the edge agree; every listed spelling resolves back to the definition;
- `resolve_base` follows a star only for a name the source exports; the class graph carries the static `__all__`s;
- the shared helpers, and `resolver._follow_star`'s defensive branches (hop limit, unparseable module, external and unparseable sources).
