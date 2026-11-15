---
date: "2026-11-15"
title: "One canonical handle resolver; every tool echoes the canonical handle (#623)"
issues: [623, 602, 431, 429, 454, 457]
anchors: ["pyeye.resolver.resolve_handle", "Resolved", "NotFound", "_synthetic_import", "scope_for", "pyeye.project_layout.file_for_module", "find_namespace_package_dirs", "tests/unit/test_resolver.py", "tests/integration/test_canonical_resolver.py", "tests/integration/test_resolve_on_resolver.py"]
status: "amended"
amends: ["2026-10-29-506-dotted-handles-are-placed-by-definition-lookup-never-by.md", "2026-06-21-444-namespace-packages-anchored-through-resolve-inspect.md", "2026-06-21-454-edge-stub-scope-reconciles-to-the-project-definition-site.md"]
supersedes: []
amended_by: ["2026-11-15-544-stdlib-private-definitions-get-public-handles-os-path-is-located.md", "2026-11-16-704-an-internal-failure-is-a-crash-or-an-item-s-unknown-never.md"]
superseded_by: []
---

## 2026-11-15 — One canonical handle resolver; every tool echoes the canonical handle (#623)

**Friction:** Turning a handle into a definition was implemented about four times, each with its own strategy order and acceptance check. inspect's `_find_jedi_name_for_handle` (shared by inspect, outline, expand and trace roots) had 5 strategies, including the banned capped `project.search` (#457), plus an anchor post-step (#429) and a retry wrapper (#431). It kept a synthetic-import copy whose `full_name == handle` check rejected legitimate external re-exports, while the other two copies checked `name == leaf` (#546, #566). inspect and outline echoed an alias input while expand and trace echoed the canonical handle, and inspect couldn't find an external module such as `logging` (#602).
**Decision:** `pyeye.resolver.resolve_handle(path) -> Resolved | NotFound` is the one exact-path resolver. It sits below `pyeye.mcp` and is never ambiguous; bare-name search (`resolve_name`) comes later in #623. Strategy order, first hit wins:

1. project module (`project_layout.file_for_module`);
2. PEP 420 namespace directory (#444's anchoring, now in the resolver);
3. external module, through a Jedi module import;
4. definition placement in the **deepest** project module along the path, matching `full_name`, else matching the head by name and following it with `goto` (this covers both a re-export alias and a flaky `full_name` match). There is no fallback to shallower modules after a miss;
5. guarded inference, last and only for handles outside the project boundary (#506). It accepts a result only when its name equals the leaf.

Steps 3 and 5 read one synthetic import (`resolver._synthetic_import`, the only file-less `jedi.Script`).

- On success, callers echo `Resolved.handle`, the canonical definition-site handle. On not-found they echo the input (#545).
- Supersedes the #431 alias-retry wrapper: aliases are followed inside placement.
- Amends the 2026-10-29 #506/#544 entry: inference lives only in the resolver, with the `name == leaf` check. inspect's `full_name == handle` check is dropped.
- Amends the #444 entry: namespace anchoring is strategy 2.
- **Slice 3 amendment (scope; also amends the 2026-06-21 #454 entry):**
  - The resolver owns scope. `resolver.scope_for` (`classify_scope`, then the #454 reconciliation of an installed copy back to the project, then file-less namespace packages) is the one rule, shared by `Resolved.scope` and every edge stub (`stubs.build_stub`).
  - `RootsBoundary.SCOPE` is the `NAMESPACE_PORTIONS` boundary, by name. Everything the user configured, packages and namespaces, is `project`; site-packages and the stdlib stay `external` because `classify_scope` rules them out before any root test. Rejected: a three-valued scope (project / sibling / external), which is a vocabulary change for #594.
  - `project_layout.file_for_module` also searches a configured PEP 420 package's portion directories, so a namespace repo outside the project root is placeable. That fixes a slice-2 regression: those modules were in the boundary but had no file, so strategy 4 missed them. `find_namespace_package_dirs` / `dir_shallow_qualifies` moved down into `project_layout` (pure path logic) for it.
  - `resolve_at` is not-found when the resolver can't place the position's definition; returning Jedi's raw `full_name` is rejected (audit row 3).
  - `resolve_canonical`'s external branch calls the resolver through a lazy import, a temporary bridge removed with `resolve_canonical` in slice 5.
- **Slice 5 amendment (closes #602):**
  - **External definition placement.** Strategy 5 first takes Jedi's goto target, through the one picker `pyeye._goto.goto_target` (#624), when it is the definition at **exactly** the requested path and has a file. Only then does it fall back to the `name == leaf` guarded inference. This is #506's "placed by definition lookup" applied to externals: `typing.TYPE_CHECKING`, `typing.Dict`, `__future__.annotations` and `typing.ClassVar` are their own canonical handles (kind from the definition, so `typing.Dict` is a `variable`, not the inferred class `typing.dict`). A goto target at a different path is refused, so a re-export never becomes canonical this way: `collections.abc.Mapping` → `typing.Mapping` stays not-found, as the #506/#544 entry decided.
  - **`imports` emits canonical targets.** An external target is re-resolved and emitted under its canonical handle (`_datetime.datetime` → `datetime.datetime`); a self-edge (`io` → `io`) is dropped; duplicates collapse. Other edges emit definition-site handles by construction (a project definition's Jedi `full_name`). That is enforced for every edge by the #614 round-trip test, not by per-edge canonicalisation, which would touch the edges `inspect.edge_counts` counts (#599). `imports` isn't one of them.
  - **Typeref forward refs** resolve lexically: `<annotation's module>.<name>`, then `builtins.<name>`, then the name as an absolute path. So `x: "Foo"` names what `x: Foo` names, and a same-named class elsewhere in the project is never picked.
  - **`JediAnalyzer.find_subclasses`** canonicalises bases through `resolve_handle`.
  - **`canonicalization.resolve_canonical` is deleted**, with its chain walk, class-member and project-search fallbacks and the lazy bridge. `canonicalization` keeps re-export collection and `find_module_file`. It sits below the resolver, so it may not import `pyeye.resolver` (import-layer fitness).
- Rejected:
  - keeping inspect's shorten-after-a-miss walk, which only inspect had (audit §4.2);
  - caching synthetic-import results to speed up a repeated inspect of an external class (~0.4 s warm), which would add cross-call state for a modest gain.

**Anchor:** `pyeye.resolver.resolve_handle` / `Resolved` / `NotFound` / `_synthetic_import` / `scope_for`; `pyeye.project_layout.file_for_module` / `find_namespace_package_dirs`; `tests/unit/test_resolver.py`; `tests/integration/test_canonical_resolver.py`; `tests/integration/test_resolve_on_resolver.py`; #623, #602, #431, #429, #454, #457.
**Applies-to:** every exact-path handle lookup in `src/pyeye`:

- `inspect`;
- `outline` root;
- `expand` source;
- `trace` roots;
- `resolve` dotted names, and every bare-name candidate (`resolve_name`, see "Bare name: an exact top-level module wins");
- `resolve_at` (the position's definition is canonicalized through the resolver);
- `trace` interior nodes (one hop = one `expand`, #621);
- typeref forward-ref heads (`typeref._resolve_head_in_scope`);
- `imports` edge targets outside the project (`edges._canonical_import_targets`);
- `JediAnalyzer.find_subclasses` base canonicalisation.

Scope: every `Resolved` and every edge stub (`scope_for`), and every `classify_scope` caller (the widened `SCOPE` boundary).
**Verify:** gold. `uv run pytest tests/unit/test_resolver.py tests/integration/test_canonical_resolver.py tests/integration/test_resolve_on_resolver.py tests/test_decision_invariants_fitness.py tests/test_import_layers_fitness.py tests/test_cross_tool_invariants.py` passes:

- each strategy resolves its case;
- a project path never reaches inference; an external name is placed at its own definition (`typing.TYPE_CHECKING`), while a definition elsewhere or a mismatched inference (`collections.abc.Mapping`, `os.sep`) is not-found;
- placement stops at the deepest module;
- an alias and its canonical handle give identical `inspect` nodes;
- inspect, outline, expand and trace all echo `pkg._impl.Thing` for `pkg.Thing`;
- the AST scan finds `jedi.Script(code=...)` only in `resolver._synthetic_import`, and no `project.search` outside the #628 dead code;
- `resolver` doesn't import `pyeye.mcp`, and `canonicalization` doesn't import `pyeye.resolver`, statically or at import time;
- `x: "Foo"` and `x: Foo` name the same class (`test_goto_policy.py::TestTyperefForwardRef`);
- `resolve` finds `os`, `io`, `logging`, `os.path` and agrees with `inspect` on handle, kind and scope; `resolve_at` is not-found when the resolver misses;
- a configured namespace repo outside the project root resolves in every tool with scope `project`, while site-packages under a configured root stays `external`;
- the `xns_repo` cross-tool corpus round-trips and agrees with no allow-list entries;
- `#614` KNOWN_GAPS hold no #602 / #623 entries for the default corpora.
