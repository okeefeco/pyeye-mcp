---
date: "2026-11-21"
title: "A local name's bindings follow the Python reference's Naming and binding, for resolve and the class graph alike (#1049)"
issues: [1049, 1022, 1024, 1025]
anchors: ["pyeye._bindings.binding_sites", "pyeye.resolver._shared_local_definitions", "pyeye.resolver._local_binding_sites", "pyeye.analyzers.jedi_analyzer._named_classes", "tests/unit/test_bindings.py"]
status: "active"
amends: ["2026-11-20-1022-a-name-shared-by-local-definitions-is-ambiguous-never-the-first.md", "2026-11-20-1024-unique-local-classes-are-named-handle-segments-are-identifiers.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-21 — A local name's bindings follow the Python reference's Naming and binding, for resolve and the class graph alike (#1049)

**Friction:** #1022 called a function-local name ambiguous when Jedi listed two or more definitions for it. Jedi's list isn't Python's:

- a `del` target counted, but a parameter (no `full_name`) and an import (named after its target, `os`) didn't;
- match captures and type parameters weren't listed at all;
- a lambda's or comprehension's names were reported under the enclosing function.

\#1024's graph rule mirrored that list, so `class X` beside `def f(X)` or `import os as X` got a handle that named two things.

**Decision** (the maintainer's ruling, via designer, 2026-11-21):

- **One rule, from the AST:** `pyeye._bindings.binding_sites(scope)` lists every binding of each name in one scope, per the Python language reference, "Naming and binding". The sources of a binding are:
  - formal parameters (positional-only, keyword-only, `*args`, `**kwargs`);
  - imports (a dotted `import a.b` binds `a`);
  - `def` and `class`;
  - assignment, augmented and annotated targets;
  - `:=` targets (one inside a comprehension binds in the enclosing scope);
  - `for` targets;
  - `as` names in `with`, `except` and `match`, and match captures;
  - `type` statements and the scope's own type parameters;
  - and `del`, which the ruling keeps.

  These are not bindings of the scope: names in a nested function, class, lambda or comprehension, attribute and subscript targets, a star import, and `global`/`nonlocal`.
- **resolve** (#1022): a function-local name is ambiguous when its scope binds it two or more times, or Jedi lists two or more definitions of it. `candidates` stay the definitions Jedi can anchor, so a class shadowed by a parameter gives one. The response keys are unchanged. The not-found `detail` names every site and its form, in text only.
- **The class graph** (#1024): a function-local class is `ambiguous_local` when its dotted name is bound more than once, counted by the same function. So the two can't disagree, which `TestTheGraphNamesOnlyWhatResolveResolves` pins case by case.

**Anchor:** `pyeye._bindings.binding_sites`; `pyeye.resolver._shared_local_definitions` and `_local_binding_sites`; `pyeye.analyzers.jedi_analyzer._named_classes`; #1049.

**Applies-to:**

- `pyeye.resolver._shared_local_definitions`, `pyeye.resolver._local_binding_sites`, `pyeye.resolver._shared_local` (the detail);
- `pyeye.analyzers.jedi_analyzer._named_classes`;
- the `expand` description's `ambiguous_local`, and the `python-explore` skill's handleless-subclasses line.

**Verify:** gold. `uv run pytest tests/unit/test_bindings.py tests/unit/analyzers/test_local_class_naming.py tests/unit/mcp/operations/test_same_name_locals.py` passes. It covers:

- one case per binding form, and one per non-binding form (the `type` statement and type parameters on Python 3.12+);
- the graph and `resolve` agreeing for every rebinding;
- `resolve` keeping #1022's shape, and the detail naming each site.

Not covered: `global X` followed by `class X` in a function binds a module-level name, but Jedi still calls it `f.X`. It's rare, and left as it is.
