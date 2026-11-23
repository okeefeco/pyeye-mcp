---
date: "2026-11-24"
title: "Decision references that drifted are carried forward to their current sites (#1182)"
issues: [1182, 462, 488, 505, 396, 544, 628, 495, 824, 825, 844, 921, 1035]
anchors: ["pyeye.decision_check.resolve_check", "scripts/decisions.py", "scripts.refresh_version.should_run", "pyeye.mcp.operations.trace._record_hop_losses", "pyeye.docs_facts.rules._removed_names", "pyeye.docs_facts.rules.edge_counts_claims", "pyeye.mcp.operations.edges.INSPECT_UNMEASURED_EDGES", "pyeye.resolver._step_private_stdlib", "pyeye.docs_facts.rules.env_name_claims", "pyeye.docs_facts.extractors.duplication", "pyeye.docs_facts.docs.for_repo", "pyeye.resolver.base_class_target", "pyeye.environment._finder_module_roots"]
status: "active"
amends: ["2026-06-22-462-git-state-hooks-are-pre-commit-managed-guard-on-pre-commit.md", "2026-06-28-488-trace-surfaces-interior-callee-resolution-loss-unresolved.md", "2026-08-09-505-the-last-three-legacy-tools-were-removed-not-shipped.md", "2026-10-29-396-shipped-prose-may-not-show-an-unmeasured-edge-inside-edge.md", "2026-11-15-544-stdlib-private-definitions-get-public-handles-os-path-is-located.md", "2026-11-15-628-v2-x-deprecate-documented-utilities-and-settings-mark-them.md", "2026-11-17-495-duplication-review-is-a-judgment-tool-keyed-on-family-locations.md", "2026-11-17-824-docs-facts-come-only-from-registered-extractors.md", "2026-11-17-825-docs-checks-run-over-the-registry-with-a-shrink-only-ratchet.md", "2026-11-17-844-docs-make-only-claims-the-code-or-a-record-backs.md", "2026-11-18-921-a-subscripted-base-names-its-class-a-non-class-base-is-unresolved.md", "2026-11-20-1035-editable-finders-are-read-as-text-never-run.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-24 — Decision references that drifted are carried forward to their current sites (#1182)

**Friction:** the first run of `decisions check --resolve` (#1182) over this repo's active entries found 21 references, in 12 entries, to code that is gone: 15 handles and 6 test files. Each rule still holds, but its `Anchor` or `Applies-to` named the code as it was. Some were renamed or split (`trace._single_hop`, `resolver._external`), one never had the name written (`environment._finder_roots`), and some were deleted or moved into the docs-facts registry (#837, #1127, #1141) or retired (#1139). An old entry's body is never rewritten, so the current sites are recorded here.

**Decision:** assigned by coordinator-3 (2026-11-24): one amending entry, since the 12 share a single cause. Each rule below is unchanged; only where it lives moved. This entry's `Applies-to` carries every rule's current sites, grouped by the entry it amends, so they stay checked now that the originals are `amended`.

| Amended entry | Gone | Now |
|---|---|---|
| #462, git-state hooks | `scripts.dogfooding_metrics._extract_issue`, the `start-metrics-session` hook | removed with the dogfooding metrics (#1139); the version-file hook remains |
| #488, interior trace losses | `pyeye.mcp.operations.trace._single_hop` | split by #621 (#657) into `pyeye.mcp.operations.trace._partition_hop`, `pyeye.mcp.operations.trace._record_hop_losses` and `pyeye.mcp.operations.trace._note_unsupported` |
| #505, legacy tools removed | `pyeye.mcp.server.find_references`, `pyeye.mcp.lookup`, `pyeye.mcp.lookup_builders` | removed by this very decision; it is enforced by the removed-names rule over `docs/facts/removed.json` |
| #396, unmeasured edges in prose | `tests/test_edge_counts_prose_conformance.py` | the rule `pyeye.docs_facts.rules.edge_counts_claims` (#837), whose set is `pyeye.mcp.operations.edges.INSPECT_UNMEASURED_EDGES` (#1127) |
| #544, stdlib private definitions | `pyeye.resolver._external` | the resolver's placement steps (#877) |
| #628, deprecated env vars | `tests/test_documented_env_vars.py` | the rule `pyeye.docs_facts.rules.env_name_claims` over the env extractor (#837) |
| #495, duplication review | `tests/test_duplication_review_skill_conformance.py` | the extractor `pyeye.docs_facts.extractors.duplication` (#837) |
| #824, registered extractors | `pyeye.docs_facts.docs.DOCS`, `tests/test_documented_env_vars.py`, `tests/test_documented_server_commands.py` | the registry is data, `docs/facts/docs.toml`, read by `pyeye.docs_facts.docs.for_repo` (#1141); the point checks are rules (#837) |
| #825, registry rules and ratchet | `pyeye.docs_facts.extractors.edges.inspect_unmeasured` | `pyeye.mcp.operations.edges.INSPECT_UNMEASURED_EDGES` (#1127) |
| #844, honest claims | `pyeye.docs_facts.docs.DOCS` | `pyeye.docs_facts.docs.for_repo` (#1141) |
| #921, subscripted bases | `pyeye.analyzers.jedi_analyzer.JediAnalyzer._get_ast_leaf_position` | `pyeye.resolver.base_class_target`, one base resolution for both edges (#1057, #1069) |
| #1035, editable finders | `pyeye.environment._finder_roots` | `pyeye.environment._finder_module_roots`, the name the code has always had |

**Anchor:** `pyeye.decision_check.resolve_check`; `scripts/decisions.py`; #1182.

**Applies-to:**

- **#462, git-state hooks are pre-commit-managed:** `scripts.refresh_version.should_run`, `scripts.refresh_version.main`, the `refresh-version-file` hook and `default_install_hook_types` in `.pre-commit-config.yaml`, guarded by `tests/test_precommit_hook_config.py`.
- **#488, trace surfaces interior callee-resolution loss:** `pyeye.mcp.operations.trace.trace`, `pyeye.mcp.operations.trace._partition_hop`, `pyeye.mcp.operations.trace._record_hop_losses`, `pyeye.mcp.operations.trace._note_unsupported`.
- **#505, the last legacy tools were removed:** the removed names' guard, `pyeye.docs_facts.rules._removed_names` (reading `docs/facts/removed.json`); kept: `pyeye.analyzers.jedi_analyzer.JediAnalyzer.find_importers`.
- **#396, shipped prose may not show an unmeasured edge:** `pyeye.docs_facts.rules.edge_counts_claims`, over `pyeye.mcp.operations.edges.INSPECT_UNMEASURED_EDGES`, with its cases in `tests/test_docs_facts_rules.py`.
- **#544, stdlib private definitions get public handles:** the resolver's external placement, `pyeye.resolver._step_private_stdlib`, `pyeye.resolver._step_external_module` and `pyeye.resolver._step_external_definition`, and the platform relocation in `pyeye.resolver.resolve_handle`. The rest of its sites are unchanged: `pyeye.mcp.operations.edges._handle_for_name`, `pyeye.mcp.operations.edges._stdlib_import_target`, `pyeye.mcp.operations.typeref._stdlib_binding_handle`, `pyeye.mcp.operations.stubs.build_stub`, `tests/unit/test_stdlib_static.py` and `tests/unit/test_stdlib_static_resolution.py`.
- **#628, deprecated utilities and settings are marked:** `pyeye.settings.DEPRECATED_ENV_VARS`; `pyeye.docs_facts.rules.env_name_claims`; `tests/unit/core/test_settings.py::TestDeprecatedSettings`; `tests/integration/test_scope_configuration.py::TestDeprecatedScopeUtilities`.
- **#495, duplication review keys on family locations:** `pyeye.duplication._FileFacts.majority_scope`, `pyeye.duplication._region`, `pyeye.duplication._FileFacts._record_function`, `scripts/duplicate_code_report.py`, `pyeye.duplication.review`, `pyeye.duplication.main`, `pyeye.duplication.find_clones`, `pyeye.duplication.apply_dismissals`, `pyeye.duplication.dismiss`, `pyeye.duplication.Family.key`, `pyeye.architecture_review.state.non_issue_key`, `pyeye.duplication.Review.as_dict`, `pyeye.duplication.Family.as_dict`, `pyeye.duplication.format_review`; the skill's documented interface is pinned by `pyeye.docs_facts.extractors.duplication` with `tests/test_docs_facts_skill_extractors.py`.
- **#824, docs facts come only from registered extractors:** `pyeye.docs_facts.registry.EXTRACTORS`, `pyeye.docs_facts.registry.build`, `pyeye.docs_facts.docs.for_repo`, `pyeye.docs_facts.docs.EXCLUDED_TREES`, `pyeye.docs_facts.binding.render`, `pyeye.docs_facts.pages.PAGES`, `pyeye.docs_facts.cli.generate`, `pyeye.docs_facts.cli.check`; the former point checks: `pyeye.docs_facts.rules.env_name_claims` and `pyeye.docs_facts.rules.server_command_claims`.
- **#825, docs checks run over the registry with a shrink-only ratchet:** `pyeye.docs_facts.rules.RULES`, `pyeye.docs_facts.rules.run`, `pyeye.docs_facts.cli.plan`, `pyeye.docs_facts.rules.ratchet`, `pyeye.docs_facts.rules.allow_problems`, `pyeye.docs_facts.docs.DocEntry`, `pyeye.docs_facts.rules._removed_names`, `pyeye.mcp.operations.edges.INSPECT_UNMEASURED_EDGES`, `tests/test_mcp_surface_conformance.py::TestMcpSurface`, `tests/test_plugin_tool_names_conformance.py`.
- **#844, docs make only claims the code or a record backs:** `pyeye.docs_facts.claims`, `pyeye.docs_facts.rules.honest_claims`, the record kind `pyeye.docs_facts.docs.Kind`, `pyeye.docs_facts.claims.record_problems`, `pyeye.docs_facts.claim_seeds.SEEDS`, `pyeye.docs_facts.docs.for_repo`, `pyeye.docs_facts.extractors.env`, `pyeye.docs_facts.rules.static_edges`, `pyeye.docs_facts.rules.STATIC_CEILINGS`, `pyeye.docs_facts.rules.released_blanked`.
- **#921, a subscripted base names its class:** `pyeye.analyzers.jedi_analyzer.JediAnalyzer._get_base_name_from_ast`, `pyeye.resolver.base_class_target`, `pyeye.mcp.operations.edges.superclass_bases`, `pyeye._ast_targets.unsubscripted`.
- **#1035, editable finders are read as text, never run:** `pyeye.environment._finder_module_roots`, `pyeye.environment._finder_targets`, `pyeye.environment._root_for`, `pyeye.environment._pth_paths`.

**Verify:** gold. `uv run python scripts/decisions.py check --resolve` passes: every handle above resolves through pyeye and every path exists. `uv run python scripts/decisions.py check` passes, so each amended entry links back here and has the status `amended`.
