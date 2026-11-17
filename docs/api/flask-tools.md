# Flask Tools

Tools for finding the parts of a Flask application: routes, blueprints, views,
templates, extensions, configuration files, error handlers and CLI commands.
They're available once Flask is detected in the project or in one of its
configured packages.

- **Parameters:** every tool takes `scope`, `envelope` and `project_path`
  ([Every plugin tool](README.md#every-plugin-tool)); the exact parameters and
  defaults are generated in [MCP tools](../reference/tools.md#flask).
- **Examples:** each example below runs in CI against a small Flask app, and its
  output is checked against the real response (`…` marks what's left out).
  A record that names a symbol carries a `handle` you can pass to `inspect`,
  `outline`, `expand` or `trace`.

The tools: <!-- fact:begin tools.plugin.flask -->`find_cli_commands`, `find_error_handlers`, `find_flask_blueprints`, `find_flask_config`, `find_flask_extensions`, `find_flask_routes`, `find_flask_templates`, `find_flask_views`<!-- fact:end -->.

## find_flask_routes

The route inventory: each decorated route with its URL path and methods. Use it
to see what an application serves, or to spot two handlers on one path.

```json pyeye-example tool=find_flask_routes
{}
```

```json pyeye-output
[{"name": "dashboard", "path": "/", "methods": ["GET"], "type": "route",
  "handle": "myapp.admin.dashboard", "…": "<omitted>"},
 {"name": "get_user", "path": "/users/<int:user_id>", "methods": ["GET"],
  "type": "route", "handle": "myapp.web.get_user", "…": "<omitted>"}]
```

## find_flask_blueprints

Each blueprint the application creates, with its URL prefix, so you can see how
the URL space is divided.

```json pyeye-example tool=find_flask_blueprints
{}
```

```json pyeye-output
[{"name": "admin", "blueprint_name": "admin", "url_prefix": "/admin",
  "type": "blueprint", "handle": "myapp.admin.admin", "…": "<omitted>"}]
```

## find_flask_views

The class-based views (`MethodView` subclasses). Function views are routes: see
`find_flask_routes`.

```json pyeye-example tool=find_flask_views
{}
```

```json pyeye-output
[{"name": "UserAdmin", "type": "method_view", "handle": "myapp.admin.UserAdmin",
  "…": "<omitted>"}]
```

## find_flask_templates

The template files, and every `render_template` call with the template it
names. Comparing the two finds a template nothing renders.

```json pyeye-example tool=find_flask_templates
{}
```

```json pyeye-output
[{"templates": [{"name": "admin.html", "type": "template", "…": "<omitted>"}],
  "render_calls": [{"template": "admin.html", "type": "render_call",
                    "…": "<omitted>"}]}]
```

## find_flask_extensions

The Flask extensions the application imports, from a list of well-known ones.
An extension module is outside the project, so its record is `unresolved` rather
than given a guessed handle.

```json pyeye-example tool=find_flask_extensions
{}
```

```json pyeye-output
[{"extension": "flask_login", "type": "import",
  "unresolved": {"reason": "unresolved", "…": "<omitted>"}, "…": "<omitted>"}]
```

## find_flask_config

The application's configuration files. A file isn't a symbol, so its record has
no `handle`.

```json pyeye-example tool=find_flask_config
{}
```

```json pyeye-output
[{"type": "config_file", "handle": "<absent>", "…": "<omitted>"}]
```

## find_error_handlers

The `errorhandler` functions, with the status code or exception each one
handles.

```json pyeye-example tool=find_error_handlers
{}
```

```json pyeye-output
[{"name": "not_found", "error_code": 404, "type": "error_handler",
  "handle": "myapp.admin.not_found", "…": "<omitted>"}]
```

## find_cli_commands

The application's CLI commands (`app.cli.command`).

```json pyeye-example tool=find_cli_commands
{}
```

```json pyeye-output
[{"name": "seed", "function": "seed", "type": "cli_command",
  "handle": "myapp.admin.seed", "…": "<omitted>"}]
```
