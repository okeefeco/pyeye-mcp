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
   entry under its key. Two plugins declaring the same name is a `ValueError`,
   not a silent shadow (#555).
4. **Re-detection.** After `configure_packages`, plugins whose framework the new
   layout brings in are activated and their tools registered. This is add-only:
   nothing already registered is removed or renamed, and no
   `tools/list_changed` is sent (#770).

## What every plugin tool gets

Each tool is wrapped (`_plugin_tool`) so that all plugin tools behave alike:

- **`scope`**: required on every plugin tool function. When the caller omits
  it, the default comes from the project's `scope_defaults`, and
  `scope_aliases` are expanded either way (#559).
- **`envelope: bool = False`**: when true, the tool returns
  `{scope, searched, unsearched_scopes, results}` instead of the bare result
  (#594).
- **`project_path`**: selects the project to analyse. A plugin tool runs
  against that project even if its framework wasn't detected there, so `[]` is
  a measured empty, never a refusal (#665).
- Results carry canonical handles, scope and absolute locations (#627), with
  paths in the caller's spelling (#717).

A plugin tool function must not declare `envelope` or `project_path` itself;
registration raises `TypeError` if it does.

## Built-in plugins

The tool names below are the `register_tools()` keys.

**Pydantic** (`pyeye.plugins.pydantic`). Detects `import pydantic` /
`from pydantic import` in any project file, or `pydantic` in
`requirements.txt`, `pyproject.toml` or `Pipfile`. Tools:
`find_pydantic_models`, `get_model_schema`, `find_validators`,
`find_field_validators`, `find_model_config`, `trace_model_inheritance`,
`find_computed_fields`.

**Django** (`pyeye.plugins.django`). Detects `manage.py` at the root, `django`
in `requirements.txt`, `requirements/base.txt` or `Pipfile`, or a Django import
in a top-level `.py` file. Tools: `find_django_models`, `find_django_views`,
`find_django_urls`, `find_django_templates`, `find_django_migrations`.

**Flask** (`pyeye.plugins.flask`). Detects a Flask import in `app.py`,
`application.py`, `wsgi.py` or `run.py`, `flask` in a requirements file or
`pyproject.toml`, or a Flask import in any project file. Tools:
`find_flask_routes`, `find_flask_blueprints`, `find_flask_views`,
`find_flask_templates`, `find_flask_extensions`, `find_flask_config`,
`find_error_handlers`, `find_cli_commands`.

## Adding a plugin

Plugins are built in: there is no dynamic loading. To add one:

1. Subclass `AnalyzerPlugin` in `src/pyeye/plugins/`, implementing `name()`,
   `detect()` and `register_tools()`. Give each tool function a `scope`
   parameter.
2. Name tools after the framework (`find_<framework>_<thing>`) so they can't
   collide with another plugin's.
3. Add the class to `_PLUGIN_CLASSES` in `pyeye.mcp.server`.
4. Add tests: positive and negative detection, the declared tool names, and each
   tool against a fixture project.
