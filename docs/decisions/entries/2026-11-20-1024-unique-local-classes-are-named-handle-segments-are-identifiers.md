---
date: "2026-11-20"
title: "Unique function-local classes are named; handle segments are any Python identifier (#1024)"
issues: [1024, 1011, 1006, 1022, 1025, 1026]
anchors: ["pyeye.analyzers.jedi_analyzer._named_classes", "pyeye.symbol_parser.validate_symbol_component", "pyeye.analyzers.project_graph.UNNAMED_AMBIGUOUS_LOCAL", "pyeye.analyzers.project_graph.UNNAMED_NESTED_LOCAL", "tests/unit/analyzers/test_local_class_naming.py"]
status: "active"
amends: ["2026-11-20-1006-handleless-subclasses-are-reported-the-class-graph-is-keyed-by-site.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — Unique function-local classes are named; handle segments are any Python identifier (#1024)

**Friction:** #1006 reported every function-local class as `function_local`, with no handle. Yet `resolve`, `resolve_at`, `inspect` and `callees` already named such classes `pkg.mod.func.Name` (#1011's investigation). The handle grammar was ASCII-only, so a non-ASCII identifier such as `Héllo` had no handle anywhere. On django, about 3,097 classes were handleless.

**Decision** (the maintainer's ruling on #1011, via designer, 2026-11-20; options 1 and 2 approved, 3 rejected, 4 deferred):

- **Segments are identifiers.** A handle segment is any `str.isidentifier()` name (PEP 3131), in `validate_symbol_component`, the grammar's one owner. `0001_initial` and `<locals>` are still rejected.
- **Unique local classes are named** in pyeye's existing notation: `pkg.mod.func.Name`, `pkg.mod.Cls.meth.Name`, and a class nested in one, `pkg.mod.func.Name.Inner`. They're named when one function level deep and their dotted name is unique in the file. Additive: no existing handle changes spelling.
- **The closed reason set** for `handleless_subclasses` replaces `function_local` with:
  - `ambiguous_local`: the dotted name is defined more than once, or an enclosing local class's is. That matches #1022, where such a name resolves to ambiguous.
  - `nested_local`: two or more function levels deep, which Jedi doesn't name (#1026).
  - `no_module_path` and `not_a_handle` are unchanged.
- **Not breaking:** `handleless_*` was never released (#1006 merged after v2.2.0). The unreleased `changes/1006.*` fragments were edited in place. The release gate is recorded on #1024.
- **Docs:** a handle is pyeye's name for a definition, not necessarily an importable path. That's stated in the `resolve` / `inspect` descriptions and the `python-explore` skill.
- **Rejected:** `<locals>` notation, which is breaking, non-unique, and which Jedi can't resolve. **Deferred:** non-identifier module names (migrations), which stay `no_module_path`.

**Anchor:** `pyeye.analyzers.jedi_analyzer._named_classes`; `pyeye.symbol_parser.validate_symbol_component`; `project_graph.UNNAMED_AMBIGUOUS_LOCAL` / `UNNAMED_NESTED_LOCAL`; #1024.

**Applies-to:**

- the grammar: `pyeye.symbol_parser.validate_symbol_component`, through `pyeye.handle.Handle`;
- the naming: `pyeye.analyzers.jedi_analyzer._named_classes`, `pyeye.analyzers.project_graph.ClassFact`;
- the reasons: `pyeye.analyzers.project_graph.UNNAMED_AMBIGUOUS_LOCAL`, `UNNAMED_NESTED_LOCAL`, the response linter's E.9 reason set, and the `expand` description and `python-explore` skill.

**Verify:** gold — `uv run pytest tests/unit/analyzers/test_local_class_naming.py` passes. It checks:

- the grammar both ways;
- named and handleless subclasses with their reasons;
- a class nested in a named local class;
- `function_local` gone;
- each newly named class round-tripping through `resolve` and `resolve_at` at the same location.

Partial for django: the pyeye-scenarios corpus check (pinned `cd385e6b8c`) round-trips every newly named class. It isn't in CI.
