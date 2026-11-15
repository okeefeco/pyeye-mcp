---
date: "2026-11-15"
title: "The #622 read/parse contract covers every plugin, plus detection and file discovery (#637)"
issues: [622, 637]
anchors: ["pyeye.plugins.base.AnalyzerPlugin._read_text_or_skip", "_read_source", "_parse_source", "get_project_files", "pyeye.mcp.server.initialize_plugins", "tests/unit/plugins/test_plugin_error_contract.py"]
status: "active"
amends: ["2026-11-15-622-flask-plugin-ast-tools-skip-only-unreadable-or-unparseable.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-15 — The #622 read/parse contract covers every plugin, plus detection and file discovery (#637)

**Friction:** After #632 the Pydantic and Django AST tools, `AnalyzerPlugin.get_project_files` and every plugin's `detect()` still had broad `except Exception` blocks. An internal error read as "nothing found" (`[]`) or "not this framework" (`False`). Pydantic logged it only at debug. A file-discovery failure emptied **every** plugin tool.
**Decision:** This amends the #622 entry below; it is the same rule, not a new one. Its Applies-to now covers every plugin, and its out-of-scope clause is resolved.

- **One copy:** the read/parse helpers move onto `AnalyzerPlugin` (`_read_text_or_skip`, `_read_source`, `_parse_source`). Flask's private copies are deleted.
- **AST tools:** an unreadable or unparseable file is warned about (no longer debug) and skipped; any other error propagates.
- **Detection:** `detect()` raises on anything but an unreadable file. `initialize_plugins` keeps its per-plugin boundary, because plugins are optional and one bug must not stop the server. It now logs the failure with `logger.exception` (ERROR plus traceback) instead of a one-line warning. Rejected: letting detection errors abort startup (one plugin bug would take down every core tool).
- **File discovery:** `get_project_files` no longer catches anything per search path, so a discovery error reaches the tool caller as an MCP error. A missing configured path is not an error; it yields no files, because `rglob` of a missing directory is empty. Rejected: returning a reported error inside the result, because plugin tools return bare lists and changing that shape belongs to #594/#627.
**Anchor:** `pyeye.plugins.base.AnalyzerPlugin._read_text_or_skip` / `_read_source` / `_parse_source` / `get_project_files`; `pyeye.mcp.server.initialize_plugins`; `tests/unit/plugins/test_plugin_error_contract.py`; #637, #622.
**Applies-to:** every `AnalyzerPlugin` file read and AST walk:
- Pydantic `find_models`, `find_validators`, `find_model_config`, `find_computed_fields`. `get_model_schema`, `find_field_validators` and `trace_model_inheritance` delegate to these.
- Django `find_models`, `find_views`.
- The 8 Flask tools listed in the #622 entry.
- `detect()` of all three plugins, and Flask `get_framework_components`.
- `AnalyzerPlugin.get_project_files`.

Not covered: `JediAnalyzer` (not a plugin). Django `find_urls`/`find_templates`/`find_migrations` and `get_framework_components` only glob, with no read or except.
**Verify:** gold — `uv run pytest tests/unit/plugins/test_plugin_error_contract.py tests/unit/plugins/test_plugin_removed_ast_nodes.py` passes. Both files sweep the sites, parametrized per tool or plugin:

- A broken `ast.walk` raises from every Pydantic and Django AST tool. A fixture guard checks that each tool finds results on the fixture, so a pass can't come from an empty result.
- Syntax-error and undecodable files are skipped with a WARNING naming the file.
- A broken `rglob_async` raises from a tool.
- For each plugin's `detect()`: an internal error raises, and an unreadable file is skipped with a warning.
- `initialize_plugins` logs a failed `detect()` at ERROR with `exc_info`.
- Flask `get_framework_components` skips unreadable files and raises on other errors.
- No plugin subclass redefines `_read_source`/`_parse_source`.
