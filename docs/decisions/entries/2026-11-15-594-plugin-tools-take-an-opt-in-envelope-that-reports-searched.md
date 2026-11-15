---
date: "2026-11-15"
title: "Plugin tools take an opt-in `envelope` that reports searched and unsearched scopes by path (#594)"
issues: [594, 644, 559]
anchors: ["pyeye.mcp.server._plugin_tool", "register_plugin_tools", "pyeye.plugins.base.AnalyzerPlugin.describe_scope", "configured_scopes", "_scope_paths", "tests/test_plugin_envelope.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-16-690-one-scope-to-paths-resolver-standalone-dirs-are-project.md"]
superseded_by: []
---

## 2026-11-15 — Plugin tools take an opt-in `envelope` that reports searched and unsearched scopes by path (#594)

**Friction:** A plugin tool returns a bare list, which reaches the client as one content item per result. An empty answer is zero items, and nothing says which scope was searched. "These are all the models" looks the same as "these are the main repo's models", and "searched, found none" looks the same as "returned nothing". The core primitives closed this gap in 2.0 (absence vs zero), but plugin tools still had it. Changing the default return from a list to an object would remove a documented shape, which is a breaking change, and #629 ships in 2.x.
**Decision:** Every plugin tool takes `envelope: bool = False`, added by one wrapper at registration (`pyeye.mcp.server._plugin_tool`, which also applies the #559 scope default). When it is true, the tool returns `{scope, searched, unsearched_scopes, results}`:

- `scope` is the scope as requested or defaulted, **before** alias expansion.
- `results` is exactly the tool's normal return value.
- `searched` and `unsearched_scopes` come from `AnalyzerPlugin.describe_scope`, over the configured scopes `main`, `packages` and each `namespace:<name>` (`configured_scopes`).
  - **Coverage is decided by path**, using the same resolution the search uses: a scope counts as searched only if all of its paths were searched.
  - Matching by name was rejected. `initialize_plugins` puts main and the namespace paths into `additional_paths`, so `scope="packages"` really searches main too. Name-matching would have reported `main` unsearched after it was read.
  - `packages` counts as configured only when packages add paths beyond main and the namespaces.
  - An unknown scope, an unconfigured namespace or a missing `package:` path appears in neither list, because it searches nothing.

When `envelope` is false the wrapper returns the tool's value untouched, and its return annotation is the tool's own type unioned with `dict[str, Any]`. Annotating `Any` was rejected: the SDK builds `structured_content` from the annotation, so the default wire output would have lost it. The pin test caught this.

The python-explore skill tells agents to always pass `envelope=true`. Rejected: switching the default now (breaking; #644, next major), and adding an envelope to some tools only.
**Anchor:** `pyeye.mcp.server._plugin_tool` / `register_plugin_tools`; `pyeye.plugins.base.AnalyzerPlugin.describe_scope` / `configured_scopes` / `_scope_paths`; `skills/python-explore/SKILL.md` "Framework plugin tools"; `tests/test_plugin_envelope.py`; #594, #644, #559.
**Applies-to:** every plugin tool registered through `register_plugin_tools`, which is all 20:

- Pydantic: `find_pydantic_models`, `get_model_schema`, `find_validators`, `find_field_validators`, `find_model_config`, `trace_model_inheritance`, `find_computed_fields`.
- Django: `find_django_models`, `find_django_views`, `find_django_urls`, `find_django_templates`, `find_django_migrations`.
- Flask: `find_flask_routes`, `find_flask_blueprints`, `find_flask_views`, `find_flask_templates`, `find_flask_extensions`, `find_flask_config`, `find_error_handlers`, `find_cli_commands`.

A future plugin tool gets the envelope automatically. `_plugin_tool` raises `TypeError` for a tool that has no `scope` parameter or that already declares `envelope`.
**Verify:** gold — `uv run pytest tests/test_plugin_envelope.py` passes. It sweeps the Applies-to sites with tests parametrized over all 20 tools (a test asserts there are exactly 20):

- `envelope` is an optional boolean defaulting to false in each tool's schema.
- With `envelope` omitted or false, each tool's `call_tool` content, `structured_content` and `is_error` equal the same method registered raw (the pre-#594 wire format).
- With `envelope=true`, each returns exactly the four keys, and `results` equals the bare answer.
- Scope cases, checked on Pydantic: `main`, `all`, a list, `packages` (which reports main and the namespaces as searched), an alias, a `scope_defaults` default, an unknown namespace, a single package path, one of several packages, and no packages configured.
- The skill contains `envelope=true` and `unsearched_scopes`.
