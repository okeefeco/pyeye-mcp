# Flask Tools

Tools for finding the parts of a Flask application: routes, blueprints, views,
templates, extensions, configuration files, error handlers and CLI commands.

The [plugin tools overview](README.md) says when these tools are available and
what every plugin tool shares: its parameters, its records and how the examples
work. Each tool's exact parameters are in
[MCP tools](../reference/tools.md#flask). The examples below run against a small Flask app.

The tools: <!-- fact:begin tools.plugin.flask -->`find_cli_commands`, `find_error_handlers`, `find_flask_blueprints`, `find_flask_config`, `find_flask_extensions`, `find_flask_routes`, `find_flask_templates`, `find_flask_views`<!-- fact:end -->.

## find_flask_routes

The route inventory: each decorated route with its methods, its own `path` as
the decorator writes it, and `urls`, the URLs it's served at once its
blueprint's prefixes are applied the way Flask applies them (a registration's
`url_prefix` overrides the blueprint's own; a nested blueprint adds its
parent's). Use `urls` to see what an application serves, or to spot two
handlers on one URL. `urls` is a list, because a blueprint registered twice
serves each route twice. It is absent when a prefix isn't a literal, the
blueprint isn't registered in the searched scope, or a registration can't be
read (#952).

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

Each blueprint the application creates, with the `url_prefix` its constructor
gives and `url_prefixes`, the prefixes it's actually served under after
registration and nesting, so you can see how the URL space is divided.
`url_prefixes` is absent under the same conditions as a route's `urls`.

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

The application's configuration files, and each access to `app.config` or
`current_app.config` (also through an attribute, such as `self.app.config`).
Configuration files are looked for at most one directory below each searched
root, so a config module nested deeper isn't listed. A file isn't a symbol, so
its record has no `handle`.

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
