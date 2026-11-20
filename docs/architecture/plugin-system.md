# Plugin System

Plugins add framework-specific tools (Pydantic, Django, Flask) beside the core
`resolve` / `inspect` / `outline` / `expand` / `trace` operations. Each plugin
is a subclass of `pyeye.plugins.base.AnalyzerPlugin` and declares its tools by
name. The wiring lives in `pyeye.mcp.server`.

## The plugin interface

`AnalyzerPlugin(project_path)` is an abstract base class. A plugin implements
two abstract methods and usually overrides a third:

| Method | Purpose |
|---|---|
| `name() -> str` | The plugin's name, for logging. Abstract. |
| `detect() -> bool` | Whether the project uses this framework. Abstract. |
| `register_tools() -> dict[str, Callable]` | The plugin's MCP tools. **The keys are the tool names.** Defaults to `{}`. |

The base class also carries the configured layout:
`set_additional_paths`, `set_namespace_paths` and `set_standalone_paths` store
the project's packages, namespaces and standalone script directories, and
`get_project_files(pattern, scope)` / `describe_scope(scope)` turn a `scope`
into the files to scan. Unreadable files and unparseable source are warned
about and skipped through the shared `_read_source` / `_parse_source` helpers;
anything else propagates (#622, #637).

## Lifecycle

1. **Detection.** At startup the server tries each class in `_PLUGIN_CLASSES`
   (`PydanticPlugin`, `DjangoPlugin`, `FlaskPlugin`). A plugin activates if
   `detect()` succeeds on the project root **or** on any configured package or
   namespace directory (#659). A detector that raises is logged with its
   traceback and the plugin is skipped; it never stops the server.
2. **Configuration.** An active plugin gets the project's package, namespace and
   standalone paths (`_apply_plugin_paths`, shared with `configure_packages`,
   #618).
3. **Registration.** `register_plugin_tools` registers every `register_tools()`
   entry under its key. Two plugins registered together that declare the same
   name raise `ValueError` rather than silently shadowing each other (#555). The
   built-in names are pinned by `tests/test_plugin_tool_names_conformance.py`,
   which is what stops a re-detected plugin's tool being skipped because its
   name is already taken.
4. **Re-detection.** When `configure_packages` reconfigures the project the
   server started in, plugins whose framework the new layout brings in are
   activated and their tools registered; the result names them (see
   [`configure_packages`](../reference/tools.md#configure_packages)). Other
   projects aren't re-detected. This is add-only: nothing already registered is
   removed or renamed. The call that activates a plugin sends one tools-changed
   event, so a client that honours it re-lists its tools (#770).

## What every plugin tool gets

Each tool is wrapped (`_plugin_tool`) so that all plugin tools behave alike: a
plugin implements only the search, and the wrapper adds the parameters every
plugin tool shares. Every plugin tool takes `scope`, `envelope` and
`project_path`; their types and defaults are in
[MCP tools](../reference/tools.md#plugin-tools), and the scope forms in
[the plugin tools guide](../api/README.md). Results carry canonical handles,
scope and absolute locations (#627), with paths in the caller's spelling (#717).

A plugin's tools are registered only once its framework is detected in the
project the server started in. After that, `project_path` can point a tool at
any project, and an empty result there is a measured empty, not a refusal
(#665).

A plugin tool function must declare `scope` itself and must not declare
`envelope` or `project_path`; the wrapper supplies those, and registration
raises `TypeError` if a function declares them.

## Built-in plugins

Each plugin's `detect()` is a text heuristic over the project's imports and
dependency files: it looks for the framework being imported or required, so a
project that uses the framework is found without running any of its code. The
exact files each one checks are in its `detect()`, linked below.

- **Pydantic** ([`pyeye.plugins.pydantic`](../../src/pyeye/plugins/pydantic.py)):
  <!-- fact:begin tools.plugin.pydantic -->`find_computed_fields`, `find_field_validators`, `find_model_config`, `find_pydantic_models`, `find_validators`, `get_model_schema`, `trace_model_inheritance`<!-- fact:end -->
- **Django** ([`pyeye.plugins.django`](../../src/pyeye/plugins/django.py)):
  <!-- fact:begin tools.plugin.django -->`find_django_migrations`, `find_django_models`, `find_django_templates`, `find_django_urls`, `find_django_views`<!-- fact:end -->
- **Flask** ([`pyeye.plugins.flask`](../../src/pyeye/plugins/flask.py)):
  <!-- fact:begin tools.plugin.flask -->`find_cli_commands`, `find_error_handlers`, `find_flask_blueprints`, `find_flask_config`, `find_flask_extensions`, `find_flask_routes`, `find_flask_templates`, `find_flask_views`<!-- fact:end -->

Each tool's parameters are in [MCP tools](../reference/tools.md#plugin-tools),
and what it finds is shown by an example in [docs/api](../api/README.md).

## Adding a plugin

Plugins are built in: there is no dynamic loading. To add one:

1. Subclass `AnalyzerPlugin` in `src/pyeye/plugins/`, implementing `name()`,
   `detect()` and `register_tools()`. Give each tool function a `scope`
   parameter.
2. Prefer names that carry the framework (`find_<framework>_<thing>`). A name
   another plugin already declares fails registration with `ValueError`.
3. Add the class to `_PLUGIN_CLASSES` in `pyeye.mcp.server`.
4. Add tests: positive and negative detection, each tool against a fixture
   project, and the new names in `tests/test_plugin_tool_names_conformance.py`.
