---
date: "2026-11-15"
title: "Bare name: an exact top-level module wins (#623)"
issues: [623, 602, 423, 508]
anchors: ["pyeye.resolver.resolve_name", "Ambiguous", "_top_level_shadow", "pyeye.mcp.operations.resolve._resolve_bare_name", "tests/integration/test_resolve_name.py", "tests/test_resolve_root_package.py", "pyeye.analyzers.project_graph.get_member_index", "tests/integration/test_resolve_bare_member.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — Bare name: an exact top-level module wins (#623)

**Friction:** `resolve` on a bare name searched only the project's name index, keyed by last segment. In a project with its own `functools` module (jaraco's `jaraco.functools`), `resolve("functools")` answered with the project module, silently and without `ambiguous`, though the bare name is exactly stdlib `functools` (#602 part b). In pyeye's own repo, `resolve("inspect")` was ambiguous between pyeye's `inspect` symbols while the `imports` edge emitted stdlib `inspect`, so the emitted handle didn't round-trip. #423's root-package promotion already applied "the exact top-level module wins" to the project's own package, but nowhere else.
**Decision:** `pyeye.resolver.resolve_name(bare) -> Resolved | Ambiguous | NotFound` applies, first rule wins:

1. **Shadow stays ambiguous** (#423): a top-level package or module of that name under more than one `TOP_LEVEL_PACKAGE` root (`<name>/` in the project and in `src/`).
2. **An exact top-level module wins**: the bare name is itself a complete top-level module (the project's own package, a PEP 420 namespace root, or an external module such as `functools`, `inspect`, `os`). It wins even when project definitions share the name. Those are reached by their dotted handles (`jaraco.functools`; `pyeye.mcp.operations.inspect` in this repo).
3. **Otherwise the name index**: every project definition named *bare*, each re-resolved through `resolve_handle`, so every candidate is canonical and an alias collapses onto its definition. One left is the answer; several are ambiguous.

- Extends #423's root-package promotion to every top-level module, per the user's 2026-11-15 confirmation on #623 ("exact match wins").
- Rejected: making `functools` ambiguous between stdlib and the project module, which leaves the obvious reading of the name unreachable by bare name; and preferring the project definition, which is the silent wrong answer this fixes.
- Consequence in this repo: `resolve("inspect")` is stdlib `inspect`. The python-explore skill says to use the dotted handle for a same-named project symbol.

**Amended 2026-11-15 (#508): rule 4, members as a fallback.** A bare method name (`_get_jedi_mro`) was `unresolved`, the same answer as a name that exists nowhere, because methods and class-body attributes are never in the name index (#457). Rule 4 runs **only when rules 1–3 find nothing**. It looks the name up in a member index (`project_graph.get_member_index`): methods and class-body attributes, built in the same pass as the name index and invalidated with it. Each hit is re-resolved through `resolve_handle`, the same as rule 3. One hit is the answer; several are `Ambiguous`.

- The response shapes don't change. A unique member is a fact, so `Resolved`; several are `Ambiguous`; none is `unresolved`. No new not-found reason is added to #626's closed set.
- It's a fallback, so a top-level name hides same-named members: `resolve("helper")` is the top-level `helper`, and `Class.helper` is not listed.
- Dunder names are never members here (`__init__` is defined by 31 classes in `src/pyeye`). A bare dunder miss's `detail` points at the class's dotted handle and `expand(<class>, "members")`.
- Function locals and `self.x =` targets are never offered.
- `Ambiguous` stays uncapped. A cap belongs to the shared completeness envelope (#435), which has the measured counts.
- Rejected:
  - a new not-found reason (`requires_qualification`), when the existing shapes already distinguish the cases;
  - indexing members in the name index itself, which would make every common method name ambiguous with top-level definitions and break #457's index contract.

**Anchor:** `pyeye.resolver.resolve_name` / `Ambiguous` / `_top_level_shadow`; `pyeye.mcp.operations.resolve._resolve_bare_name`; `tests/integration/test_resolve_name.py`; `tests/test_resolve_root_package.py`; #623, #602, #423.
**Applies-to:** `resolve` on a bare (dot-free) identifier, its only bare-name entry point: `pyeye.resolver.resolve_name` rules 1–4 and `pyeye.mcp.operations.resolve._resolve_bare_name`. Rule 4 also covers `JediAnalyzer.find_member_definitions` and `project_graph.get_member_index` / `_is_bare_name_member`. Dotted handles go through `resolve_handle` (see the canonical-resolver entry below).
**Verify:** gold. `uv run pytest tests/integration/test_resolve_name.py tests/test_resolve_root_package.py tests/integration/test_resolve_bare_member.py tests/unit/analyzers/test_project_graph.py` passes:

- `functools` (a project module shares the name), `inspect` (a project function shares it) and `os` resolve to the stdlib module, not ambiguous;
- the project definitions stay reachable by dotted handle;
- two project definitions stay ambiguous, and every candidate round-trips through `inspect`;
- an alias and its definition collapse to one canonical answer;
- a top-level package promotes over a deeper same-named symbol;
- a shadow across two roots stays ambiguous.
- #508: a unique method or class attribute resolves to its canonical handle and round-trips through `inspect`; one shared by two classes is ambiguous; a top-level name hides a same-named method; a dunder stays `unresolved` with the members hint; locals and `self.x` targets stay plainly `unresolved`; the member index holds only methods and class attributes and is invalidated with the name index.
