---
date: "2026-11-15"
title: "Flask plugin AST tools skip only unreadable or unparseable files; walk errors propagate (#622)"
issues: [622, 632]
anchors: ["pyeye.plugins.flask.FlaskPlugin._read_source", "_parse_source", "pyeye.plugins.flask._str_value", "tests/unit/plugins/test_plugin_removed_ast_nodes.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-15-637-the-622-read-parse-contract-covers-every-plugin-plus.md"]
superseded_by: []
---

## 2026-11-15 — Flask plugin AST tools skip only unreadable or unparseable files; walk errors propagate (#622)

**Friction:** Python 3.14 removed `ast.Str` and `ast.Num`, which the Flask plugin referenced inside per-file `except Exception` blocks. On 3.14 each reference would raise `AttributeError`, the file would be skipped, and every Flask tool would return `[]`, a silent false "nothing found" rather than a failure. An AST-API change and genuinely broken user code were treated the same.
**Decision:** A Flask AST tool catches only read errors (`OSError`, `UnicodeDecodeError`, in `FlaskPlugin._read_source`) and parse errors (`SyntaxError`, `ValueError`, `RecursionError`, in `FlaskPlugin._parse_source`). It warns and skips that file, which is the existing contract for broken user code. Anything raised while walking a parsed tree propagates to the caller. String literals are read only through `ast.Constant` plus a `str` check (`pyeye.plugins.flask._str_value`). Rejected: keeping the broad except but logging at error level, because the caller still gets `[]` and can't tell a failure from no results. Out of scope: the pydantic and django plugins still wrap their AST walks in broad `except Exception` (pydantic's `find_validators` logs only at debug). A follow-up issue is pending.
**Anchor:** `pyeye.plugins.flask.FlaskPlugin._read_source` / `_parse_source`; `pyeye.plugins.flask._str_value`; `tests/unit/plugins/test_plugin_removed_ast_nodes.py`; #622, PR #632.
**Applies-to:** `FlaskPlugin.find_routes`, `find_blueprints`, `find_views`, `find_templates`, `find_extensions`, `find_config`, `find_error_handlers`, `find_cli_commands`. These are the 8 Flask AST-walking tools (MCP names `find_flask_routes`, `find_flask_blueprints`, `find_flask_views`, `find_flask_templates`, `find_flask_extensions`, `find_flask_config`, `find_error_handlers`, `find_cli_commands`). The pydantic and django plugins are not covered.
**Verify:** gold — `uv run pytest tests/unit/plugins/test_plugin_removed_ast_nodes.py` passes. This runs on CI Pythons (3.11–3.13) by giving the plugin a copy of `ast` without the removed classes, so it does not need 3.14. It checks:

- With the 3.14-shaped `ast`, each string-literal path returns results: routes and methods, blueprint name and `url_prefix`, `render_template` names, error-handler codes, CLI command names.
- Syntax-error and undecodable files are still skipped while the other files are found.
- `test_analysis_errors_propagate_instead_of_returning_empty` is parametrized over all 8 Applies-to tools: an error raised during the walk reaches the caller.
- `test_no_removed_ast_nodes_referenced_in_src` finds no `ast.Str`/`Num`/`Bytes`/`NameConstant`/`Ellipsis` anywhere in `src/`.
