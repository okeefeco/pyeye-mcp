---
date: "2026-11-15"
title: "Stdlib private definitions get public handles; os.path is located at its platform branch (#544, #329)"
issues: [544, 329, 623, 624, 506]
anchors: ["pyeye._stdlib_static.stdlib_definition", "public_handle", "public_reexporter", "platform_decision_point", "PlatformAnchor", "relocate_platform", "PLATFORM_ALTERNATIVES", "pyeye.resolver._external", "pyeye.resolver.resolve_handle", "pyeye.mcp.operations.edges._handle_for_name", "_stdlib_import_target", "pyeye.mcp.operations.stubs.build_stub", "pyeye.mcp.operations.typeref._stdlib_binding_handle", "pyeye._goto.binding_target", "pyeye.scope.is_stdlib_source"]
status: "active"
amends: ["2026-11-15-623-one-canonical-handle-resolver-every-tool-echoes-the.md", "2026-10-29-506-dotted-handles-are-placed-by-definition-lookup-never-by.md", "2026-11-15-624-one-goto-disambiguation-policy-inspect-s-superclasses-field.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — Stdlib private definitions get public handles; os.path is located at its platform branch (#544, #329)

**Friction:** Jedi sees the standard library through typeshed, which misleads an agent in two ways.

- **#544.** Typeshed declares `collections.abc.Mapping` as a re-export of `typing.Mapping`, the reverse of the real source. So `resolve`/`inspect` were an honest not-found, while `imports` and typerefs emitted `typing.Mapping`, a different object.
- **#329.** Jedi follows typeshed's first `sys.platform` branch, so `os.path.join` was located in `ntpath.py` on Linux.

A runtime rule (`__module__.__qualname__` from the running interpreter) was built and then withdrawn by the user: pyeye resolves **statically**, picking the answer that lets agents reason best.

**Decision:** two narrow, static rules in one lower-layer module, `pyeye._stdlib_static`. It reads `.py`/`.pyi` sources with the AST through #360's one import walk, imports nothing and evaluates nothing.

- **Private definition, public handle (#544).**
  - The resolver follows the real `.py` chain (`collections/abc.py`: `from _collections_abc import *`) to the `class`/`def`.
  - When that definition is in a **private** (`_`-prefixed) stdlib module that exactly **one** public stdlib module re-exports, the handle is the public one: `collections.abc.Mapping`, located in `_collections_abc.py`. `_collections_abc.Mapping` resolves to the same handle.
  - A re-export is `from _X import *`, or an explicit import of a name listed in the public module's literal `__all__`. A usage import is not one (`pathlib` imports `Sequence` to use it). Zero or several re-exporters means no change.
  - This is a deliberate exception to "re-exports collapse to the definition site" (#623, #506). Project and third-party code keep the collapse rule.
- **Platform decision point (#329).**
  - A handle in `PLATFORM_ALTERNATIVES` (`os.path`: `posixpath` | `ntpath`) is located at the `if sys.platform …` block in typeshed's `os/path.pyi`, the same on every OS. The handle is unchanged.
  - `PlatformAnchor` reports that span and delegates kind, signature and goto to Jedi's `Name`.
  - This adds a fact to #624's goto policy rather than a guess: Jedi still names one target, and pyeye relocates only a name the explicit table lists.
- **One emission rule everywhere.**
  - The resolver applies both rules.
  - The edges build every Name-derived handle through one builder, `_handle_for_name`, guarded by `scope.is_stdlib_source` so a project package that shadows a stdlib name is never renamed.
  - Stubs are relocated in `build_stub`.
  - `imports` and typerefs place a stdlib import by its IMPORTED path through `resolve_handle`, using `_goto.binding_target`, so they stop emitting typeshed's `typing.Mapping`.
- Rejected:
  - the runtime rule (user decision; it imports stdlib code to answer a lookup);
  - typeshed's `typing.Mapping` (a different object);
  - the private handle `_collections_abc.Mapping`, which steers agents to private imports;
  - pointing `os.path` at the host's implementation, which is platform-dependent and misleads code written for both.

**Anchor:** `pyeye._stdlib_static` (`stdlib_definition`, `public_handle`, `public_reexporter`, `platform_decision_point`, `PlatformAnchor`, `relocate_platform`, `PLATFORM_ALTERNATIVES`); `pyeye.resolver._external` / `resolve_handle`; `pyeye.mcp.operations.edges._handle_for_name`, `_stdlib_import_target`; `pyeye.mcp.operations.stubs.build_stub`; `pyeye.mcp.operations.typeref._stdlib_binding_handle`; `pyeye._goto.binding_target`; `pyeye.scope.is_stdlib_source`; #544, #329.
**Applies-to:**

- the resolver's external placement, `pyeye.resolver._external`, and the platform relocation in `pyeye.resolver.resolve_handle`;
- the edges' one Name→handle builder, `pyeye.mcp.operations.edges._handle_for_name`, at all five emission sites: `_class_members`, `_module_members`, `_resolve_call_target` (callees and imports goto), `superclass_bases` (the `superclasses` edge and inspect's `superclasses` field), `resolve_enclosing_scope`;
- `imports`' stdlib targets, `pyeye.mcp.operations.edges._stdlib_import_target`;
- typeref heads, `pyeye.mcp.operations.typeref._stdlib_binding_handle`, via `pyeye._goto.binding_target`;
- stub locations, `pyeye.mcp.operations.stubs.build_stub`;
- the tests `tests/unit/test_stdlib_static.py` and `tests/unit/test_stdlib_static_resolution.py`.

**Verify:** gold. `uv run pytest tests/unit/test_stdlib_static.py tests/unit/test_stdlib_static_resolution.py` passes, with identical expectations on every OS:

- `collections.abc.{Mapping,…}` and `_collections_abc.Mapping` resolve as classes with handle `collections.abc.*`, located in `_collections_abc.py`;
- members, superclasses, enclosing_scope, `imports` and parameter typerefs emit the same handles, and each round-trips through `resolve_handle`; count==expand holds;
- `os.path` / `os.path.join` from `resolve`, `inspect` and a callee stub are all at the `if sys.platform` block of `os/path.pyi`;
- a project `json` package is untouched; `json`, `pathlib`, `datetime` and `asyncio` are unchanged;
- a lookup adds nothing to `sys.modules`.

Limit: the stdlib sources read are those of the interpreter pyeye runs on, the same root `pyeye.scope` classifies as stdlib.
