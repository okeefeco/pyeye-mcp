---
date: "2026-11-20"
title: "resolve follows `from x import *` re-exports of project names, by one shared star-export rule (#1007)"
issues: [1007, 1010, 405, 431]
anchors: ["pyeye.resolver._place_definition", "pyeye.resolver._follow_star", "pyeye.star_exports.star_exported", "pyeye.star_exports.static_all", "tests/test_resolve_star_reexports.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — resolve follows `from x import *` re-exports of project names, by one shared star-export rule (#1007)

**Friction:** `resolve("django.forms.Form")` was not found (django at the pinned `cd385e6b8c`), although `django/forms/__init__.py` re-exports it through `from django.forms.forms import *`. For a project handle the resolver only places the path in the deepest project module (`definition_placement`), and `_follow_alias` follows an EXPLICIT binding by name. A star import binds no name there, so nothing matched, and there's no fallback. External handles never had the gap, because they go through Jedi inference. The class graph's base resolution already followed stars (#405, `base_resolution._follow`), but without `__all__`. The re-export binding index doesn't follow them at all.

**Decision:** approved via coordinator-3 (2026-11-20). The only visible change is that such names are now found.

- **Where:** `_place_definition`, after `_follow_alias` finds no explicit binding. `_follow_star` tries the deepest module's `from x import *` sources in source order (`base_resolution.build_star_sources`: module scope, unguarded, relative made absolute by `import_analyzer.resolve_relative_import`). For each project source that star-exports the head, it resolves `<source>.<rest>` through the same `_resolve`. The first that resolves wins.
- **The rule, in ONE helper:** `pyeye.star_exports.star_exported(tree, name)`, which is Python's rule, read statically. It's the source's `__all__` when `static_all` can read it (module-scope `=`, `:` or `+=` of a list or tuple of string literals; an empty literal exports nothing), else any name not starting with `_`. A `__all__` built any other way can't be read without running the module, so the default rule applies. `canonicalization._static_all` returns a set either way and can't tell "none" from "empty", so it isn't reused. #1010 switches `base_resolution` and the binding index onto `star_exports`. `base_resolution` is NOT changed here, because that would alter subclass results.
- **Precedence:** an explicit binding of the name wins over a star, as Python lets a later explicit import shadow one. (Python's exact order-dependence, where a star after an explicit import rebinds, isn't modelled: the explicit binding always wins.)
- **Bounds:** the existing `_MAX_ALIAS_HOPS` limit, plus a per-resolution seen-set of `(source, name)` in a `ContextVar`, so a star cycle ends without re-trying a branch.
- **Not followed:** a star from a non-project module (external handles resolve through Jedi anyway), and a source the server's Python can't parse.
- **Not changed:** `re_exports` doesn't list star aliases yet; that's #1010, a separate visible addition.

**Anchor:** `pyeye.resolver._place_definition` / `_follow_star`; `pyeye.star_exports`; `tests/test_resolve_star_reexports.py`; #1007.

**Applies-to:**

- `pyeye.resolver._place_definition` and `pyeye.resolver._follow_star`, and through them every handle consumer of `pyeye.resolver.resolve_handle`;
- `pyeye.star_exports.static_all` and `pyeye.star_exports.star_exported`, the rule #1010 will reuse in `pyeye.analyzers.base_resolution` and `pyeye.canonicalization`;
- the `resolver.strategy` docs fact (`definition_placement`'s description) and `docs/architecture/resolution.md`.

**Verify:** gold — `uv run pytest tests/test_resolve_star_reexports.py` passes. It checks:

- a name in a static `__all__`, a public name with no `__all__`, a star of a star, an absolute star source, and a path under the alias all resolve to the definition;
- a defined name outside `__all__`, an underscore name, and a missing name aren't found;
- an explicit binding beats a star;
- a star cycle ends;
- `inspect` takes the alias;
- the rule itself: a static, `+=`-extended, missing, dynamic or empty `__all__`, and a listed underscore name.
