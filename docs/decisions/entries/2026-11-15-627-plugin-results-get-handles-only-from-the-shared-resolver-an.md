---
date: "2026-11-15"
title: "Plugin results get handles only from the shared resolver; an unplaceable symbol says so and has no handle (#627)"
issues: [627, 623, 594]
anchors: ["pyeye.plugins.handles.enrich", "pyeye.plugins.handles.SYMBOLS", "pyeye.plugins.handles._qualname", "pyeye.mcp.server._plugin_tool", "pyeye.resolver.resolve_handle", "tests/test_plugin_handles.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — Plugin results get handles only from the shared resolver; an unplaceable symbol says so and has no handle (#627)

**Friction:** Framework plugins (Pydantic, Django, Flask) find things by walking ASTs and returned `{name, file, line}` only. A result couldn't be passed to `inspect` without an ambiguous `resolve(name)`. It had no scope, and `file` was relative to wherever the server started. The obvious fix, building a handle from the file's module plus the name, would have been a fifth canonicalisation copy. It would also have reported handles nothing could inspect: a re-exported model's alias, or a route defined inside an app factory, which has no dotted path at all.
**Decision:**

- Every plugin result record gains `location`, in the primitives' `Location` shape (`pyeye._jedi_location`, total=False), and `scope`. For a placed symbol, `location` is built from the resolver's anchor with `location_from_name`, exactly as `inspect` builds it. Otherwise it is the `{file, line_start, line_end}` or `{file}` subset. `file` is absolute posix. An earlier draft used `{file, line}`, a second shape; it was caught before merge.
- A record that names a symbol gets a `handle` **only** from `pyeye.resolver.resolve_handle`. Its input is `project_layout.module_name_for_file(file)` + the definition's qualified name at the record's line in the cached AST (`Model.validator`). Re-exports, aliases and canonical spelling are the resolver's job.
- When the symbol can't be placed (defined inside a function body, a file outside every root, the resolver's `NotFound`), the record carries `unresolved: {reason, detail}` from `NotFound` and **no `handle`**. A handle is never guessed.
- A record with neither key doesn't name a symbol (template files, `urls.py`, `app.config` accesses), and that is fixed per tool.
- The enrichment runs once, in `server._plugin_tool` before the #594 envelope, so the bare list and `results` agree.
- `name`, `file` and `line` are unchanged (additive in 2.x).
- Rejected:
  - Plugins returning handles themselves: 20 tools, three plugins, three copies.
  - Echoing a constructed dotted path without resolving it: that fabricates handles for aliases and nested definitions.
  - `handle: null` for misses: `unresolved` says why.
**Anchor:** `pyeye.plugins.handles.enrich` / `SYMBOLS` / `_qualname`; `pyeye.mcp.server._plugin_tool`; `pyeye.resolver.resolve_handle`; `tests/test_plugin_handles.py`; #627, #623, #594.
**Applies-to:** every plugin tool through `handles.SYMBOLS`.
- Symbol tools:
  - Pydantic: `find_pydantic_models`, `get_model_schema`, `find_validators`, `find_field_validators`, `find_model_config` (enclosing class), `trace_model_inheritance` (plus its `children`), `find_computed_fields`.
  - Django: `find_django_models`, `find_django_views`.
  - Flask: `find_flask_routes`, `find_flask_blueprints`, `find_flask_views`, `find_flask_extensions` (module), `find_error_handlers`, `find_cli_commands`.
- Location and scope only: `find_django_urls`, `find_django_templates`, `find_django_migrations`, `find_flask_templates`, `find_flask_config`.
- A new plugin tool gets `location`/`scope` automatically. It gets handles only through a `SYMBOLS` entry.
**Verify:** gold — `uv run pytest tests/test_plugin_handles.py` passes. It checks:
- **Round trip:** for each symbol tool, the record's `handle` equals the expected canonical handle, and `inspect(handle)` finds it and echoes the same handle. The record's `location` **equals** `inspect(handle)["location"]`, the drift guard for the shape. A re-export (`shop.Product`) gets the definition-site handle `shop._models.Product`.
- **Nested route:** a route defined inside `create_app()` has `unresolved.reason == "unresolved"` and no `handle`, but still has `location` and `scope`.
- Also: file-only records carry neither key; `name`/`file`/`line` are byte-unchanged; envelope `results` equal the bare list.
