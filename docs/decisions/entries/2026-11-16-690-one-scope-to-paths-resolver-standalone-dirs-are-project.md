---
date: "2026-11-16"
title: "One scope→paths resolver for the analyzer and the plugins; standalone dirs are project (#690)"
issues: [690, 594, 623]
anchors: ["pyeye.scope_utils.resolve_scope_paths", "ScopeLayout", "ScopeLayout.from_parts", "ScopeLayout.configured_scopes", "pyeye.analyzers.jedi_analyzer.JediAnalyzer._resolve_scope_to_paths", "pyeye.plugins.base.AnalyzerPlugin._scope_paths", "describe_scope", "pyeye.config.ProjectConfig.get_standalone_paths", "pyeye.project_layout.RootsBoundary.SCOPE"]
status: "amended"
amends: ["2026-11-15-594-plugin-tools-take-an-opt-in-envelope-that-reports-searched.md"]
supersedes: []
amended_by: ["2026-11-21-1041-a-standalone-script-is-named-from-its-dir-unless-shadowed.md"]
superseded_by: []
---

## 2026-11-16 — One scope→paths resolver for the analyzer and the plugins; standalone dirs are project (#690)

**Friction:** `JediAnalyzer._resolve_scope_to_paths` and `AnalyzerPlugin._scope_paths` resolved the same scope names differently.

- The plugin copy didn't know `standalone`, left standalone dirs out of `all`, and had no sub-namespaces.
- Its `packages` searched the main project and every namespace, because `ProjectConfig.get_package_paths` mixes both in (#594). The #594 envelope reported that honestly but didn't change it.
- Separately, `scope="all"` searches standalone dirs while `classify_scope` labelled their files `external`.
- A first probe missed that: without explicit `packages`, config auto-discovery happened to pick the sibling `scripts/` dir up as a package. With explicit `packages` it reproduces.

**Decision:**

- **One resolver.** `pyeye.scope_utils.resolve_scope_paths(scope, layout)` is the one implementation. The analyzer and every plugin delegate to it over a `ScopeLayout` built by `ScopeLayout.from_parts`, which subtracts the main project and the namespace roots from the packages.
  - `all` is exactly main + packages + the union of every `namespace:<name>` scope + standalone, so it covers each namespace scope by construction.
  - `config.get_standalone_paths()` is the one standalone source, for `ProjectManager` and the plugins.
- **Envelope (amends #594).** `describe_scope` reads `ScopeLayout.configured_scopes()`, which comes from the same resolver and adds `standalone`. It decides coverage by subtree (a path under a searched root is searched), so `searched` can't claim more than was read or less than was covered.
- **Standalone is project.** `RootsBoundary.SCOPE` = the namespace-portion roots + `standalone_paths`. This follows #623's rule that what the user configured is project (configured namespaces already are), so the search boundary and the classifier agree.
- `SmartScopeResolver` is not a third copy. It does scope SELECTION (defaults, alias expansion) before resolution, on both paths. `ScopeValidator` and `ScopeDebugger` are deprecated and unused (#628).
- Contract: a v2.x Fixed. Plugin `scope="packages"` NARROWS to the configured packages; no scope name, argument or field is removed.

**Anchor:** `pyeye.scope_utils.resolve_scope_paths`, `ScopeLayout`; `JediAnalyzer._resolve_scope_to_paths`; `AnalyzerPlugin._scope_paths` / `configured_scopes` / `describe_scope`; `ProjectConfig.get_standalone_paths`; `pyeye.project_layout.RootsBoundary.SCOPE`; #690, #594, #623.
**Applies-to:**

- the resolver `pyeye.scope_utils.resolve_scope_paths` and its two delegates, `pyeye.analyzers.jedi_analyzer.JediAnalyzer._resolve_scope_to_paths` and `pyeye.plugins.base.AnalyzerPlugin._scope_paths`;
- the #594 envelope, `AnalyzerPlugin.configured_scopes` / `describe_scope`;
- the layout sources, `ScopeLayout.from_parts`, `ProjectConfig.get_standalone_paths`, `pyeye.project_manager.ProjectManager.get_analyzer` and `pyeye.mcp.server._apply_plugin_paths`;
- the classifier boundary, `pyeye.project_layout.RootsBoundary.SCOPE` (`project_roots`, via `pyeye.scope.classify_scope`);
- the tests `tests/unit/test_scope_paths_single_resolver.py` and `tests/test_plugin_envelope.py`.

**Verify:** gold. `uv run pytest tests/unit/test_scope_paths_single_resolver.py tests/test_plugin_envelope.py` passes:

- the analyzer and a plugin resolve `main`, `all`, `packages`, `standalone`, `namespace:acme` and `namespace:acme.tools` to identical paths;
- `packages` is only the configured package;
- the envelope reports `packages` / `standalone` honestly;
- every `.py` under every root `all` searches classifies as `project`.
