---
date: "2026-11-20"
title: "A namespace package is declared by its portions' __init__.pyi, as Jedi reads it; no package changes classification (#1004)"
issues: [1004, 933, 444, 885]
anchors: ["pyeye.project_layout.is_namespace_stub_init", "pyeye.project_layout.is_module_file", "pyeye.project_layout.namespace_stub_inits", "pyeye.project_layout.dir_shallow_qualifies", "pyeye.project_layout.mark_stub", "pyeye.resolver._place_in_namespace_stubs", "pyeye.mcp.operations.edges._module_members", "pyeye.mcp.operations.resolve._resolve_file_only", "tests/test_stub_namespace_packages.py"]
status: "active"
amends: ["2026-11-20-933-a-stub-only-module-has-handles-at-its-stub.md", "2026-06-21-444-namespace-packages-anchored-through-resolve-inspect.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — A namespace package is declared by its portions' __init__.pyi, as Jedi reads it; no package changes classification (#1004)

**Friction:** a directory with `__init__.pyi` and no `__init__.py` broke the handle round trip. `stubpkg.X` resolved, `enclosing_scope` of it emitted `stubpkg`, and `resolve("stubpkg")` rejected that.

The #933 work had left these packages out on purpose. The candidate fix in #1004 was to anchor them at the stub as regular packages, which would make a directory with `__init__.pyi` plus `.py` submodules stop being a PEP 420 namespace.

Measured before building, Jedi does not do that. It reports `stubpkg`, `mixed` (`__init__.pyi` plus `mixed/mod.py`) and a configured namespace `acme` with one stub portion all as `type == "namespace"`. It merges each portion's `__init__.pyi` declarations into the namespace (`stubpkg.X`, `mixed.M` and `acme.B` resolve to the `.pyi`), and it keeps every portion's submodules. That is runtime PEP 420 too, and PEP 561 says a namespace stub package must not rely on `__init__.pyi`.

Against that, `main` had two gaps:

- __A stub-only package didn't qualify as a namespace.__ `dir_shallow_qualifies` counted only `.py` files.
- __A namespace's `members` ignored its portions' `__init__.pyi`.__ That was a FALSE measured zero, and `pkg.M` declared there didn't resolve.

**Decision:** ruled by coordinator-3 (2026-11-21) as additive and matching Jedi and PEP 420. No designer ruling was needed, since no layout changes classification.

- __A portion's stub names its package.__ `is_namespace_stub_init` matches an `__init__.pyi` with no `__init__.py` beside it. `is_module_file` accepts it, so `module_name_for_file` names it as the package (`mixed`), and its declarations get handles (`mixed.M`).
  - The mapper is one-way here: `file_for_module("mixed")` is still `None`. A namespace package has no file; it is anchored at its directory (#444). The file form of the stub (`resolve("mixed/__init__.pyi")`) answers as the dotted name does.
- __A stub counts as namespace content.__ `dir_shallow_qualifies` rule (a) accepts a stub-only `.pyi` module and a namespace stub init beside `.py`. So a stub-only package is a namespace package like `mixed`, and the submodules enumerator, which shares the filter, lists its `.pyi` modules.
- __A namespace's members are its portions' declarations.__ `edges._module_members` reads each portion's `__init__.pyi` (`namespace_stub_inits`, portion order), with imports excluded as for a module. `inspect`'s count goes through the same function, so the two agree. `resolver._place_in_namespace_stubs` places `pkg.M` in them.
  - __Portion order is sys.path order.__ A name two portions declare is the first portion's, listed once (`_collect_members` keeps the first per handle), as Jedi resolves it.
- __The package node is never a stub node.__ `mark_stub` leaves `stub` off a `module` node whose file is a namespace stub init. The package has no single definition file, and it is located at its directory. The members, located at the `.pyi`, carry `stub: true`. So Check D's D.2 ("present exactly when `location.file` is `.pyi`") holds for both kinds of node.
- **Unchanged:**
  - a directory with `__init__.py` is a regular package, even with an `__init__.pyi` beside it (#885: the source is the module);
  - a directory with neither `.py` nor stub content is still not a namespace;
  - `imported_by` still reads only `.py` (#933).

**Amends #933:** "a stub-only package isn't supported" no longer holds. Its file form resolves; it was #933's honest miss, and `test_resolve_pyi_stubs` pins the new answer. __Amends #444:__ a namespace package now has members, declared in its portions' stubs, where before it had none.

**Anchor:** `pyeye.project_layout.is_namespace_stub_init` / `namespace_stub_inits` / `dir_shallow_qualifies` / `mark_stub`; `pyeye.resolver._place_in_namespace_stubs`; `pyeye.mcp.operations.edges._module_members`; #1004.

**Applies-to:**

- `pyeye.project_layout.is_namespace_stub_init`, `pyeye.project_layout.is_module_file` and through it `pyeye.project_layout.module_name_for_file`, `pyeye.project_layout.iter_module_files` and `pyeye.analyzers.jedi_analyzer.JediAnalyzer.get_module_files`;
- `pyeye.project_layout.dir_shallow_qualifies`, and through it `pyeye.project_layout.find_namespace_package_dirs` and the `submodules` enumerator;
- `pyeye.project_layout.namespace_stub_inits`, `pyeye.resolver._place_in_namespace_stubs` (called from `pyeye.resolver._place_definition`) and `pyeye.mcp.operations.edges._module_members` (and `inspect`'s member count through it);
- `pyeye.project_layout.mark_stub`;
- `pyeye.mcp.operations.resolve._resolve_file_only`.

**Verify:** gold. `uv run pytest tests/test_stub_namespace_packages.py tests/test_resolve_pyi_stubs.py tests/test_stub_only_modules.py tests/conformance` passes. It checks:

- a stub-only package resolves as a namespace at its directory with no `stub` flag, and `enclosing_scope` of its declaration emits it, also with no flag (round trip);
- its `.pyi` modules are its submodules;
- the stub's declarations are `members` (`stub: true`), and `inspect` counts them;
- a declaration resolves, inspects and has the package as `enclosing_scope`;
- the mixed package keeps its `.py` submodules;
- a configured namespace keeps every portion and resolves names from both portions' stubs;
- a name two portions declare comes from the first, listed once;
- a regular package with a stub beside its `__init__.py` is unchanged;
- a portion's stub file resolves exactly as its package's dotted name;
- every response passes the conformance linter, including Check D.
