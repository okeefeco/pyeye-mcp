# Flask Tools

Specialized tools for analyzing Flask applications, routes, blueprints, and extensions. These 8 tools are automatically activated when Flask is detected in your project.

## Table of Contents

1. [find_routes](#find_routes)
2. [find_blueprints](#find_blueprints)
3. [find_views](#find_views)
4. [find_templates](#find_templates)
5. [find_extensions](#find_extensions)
6. [find_config](#find_config)
7. [find_error_handlers](#find_error_handlers)
8. [find_cli_commands](#find_cli_commands)

---

## find_routes

Find all Flask routes in the project.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  route: string;               // URL pattern (e.g., "/api/users/<int:id>")
  endpoint: string;            // Endpoint name
  function: string;            // View function name
  file: string;               // File path
  line: number;               // Line number of route decorator
  methods: string[];          // HTTP methods (GET, POST, etc.)
  blueprint: string | null;    // Blueprint name if applicable
  decorators: string[];       // Other decorators applied
  url_params: Array<{         // URL parameters
    name: string;
    type: string;             // int, string, path, etc.
    required: boolean;
  }>;
  query_params: string[];     // Query parameters used in function
  is_async: boolean;          // Async view function
  auth_required: boolean;     // Has auth decorator detected
}>
```

### Examples

```python
# Find all routes
routes = find_routes()
# Returns: [
#   {
#     "route": "/api/users/<int:user_id>",
#     "endpoint": "get_user",
#     "function": "get_user",
#     "file": "/project/app/api/users.py",
#     "line": 25,
#     "methods": ["GET"],
#     "blueprint": "api",
#     "decorators": ["@login_required", "@cache(timeout=300)"],
#     "url_params": [
#       {"name": "user_id", "type": "int", "required": true}
#     ],
#     "query_params": ["include_profile", "format"],
#     "is_async": false,
#     "auth_required": true
#   },
#   {
#     "route": "/api/users",
#     "endpoint": "create_user",
#     "function": "create_user",
#     "file": "/project/app/api/users.py",
#     "line": 40,
#     "methods": ["POST"],
#     "blueprint": "api",
#     "decorators": ["@login_required", "@validate_json"],
#     "url_params": [],
#     "query_params": [],
#     "is_async": true,
#     "auth_required": true
#   }
# ]

# Find all POST routes
post_routes = [r for r in routes if "POST" in r["methods"]]

# Find routes without authentication
public_routes = [r for r in routes if not r["auth_required"]]

# Find async routes
async_routes = [r for r in routes if r["is_async"]]
```

### Error Conditions

- Returns empty array if no routes found
- May miss dynamically registered routes
- Detects common auth decorators

### Performance Notes

- Scans all Python files for Flask decorators
- Caches results until files change
- Auto-activated when Flask imported

### Use Cases

- API documentation generation
- Route inventory
- Security audit (finding unprotected routes)
- URL collision detection
- Migration planning

---

## find_blueprints

Find all Flask blueprints in the project.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;                // Blueprint name
  import_name: string;         // Import name passed to Blueprint()
  file: string;               // File where blueprint is defined
  line: number;               // Line number of Blueprint() call
  url_prefix: string | null;   // URL prefix if set
  subdomain: string | null;    // Subdomain if set
  static_folder: string | null; // Static folder path
  template_folder: string | null; // Template folder path
  routes: Array<{             // Routes registered to this blueprint
    route: string;
    methods: string[];
    function: string;
  }>;
  before_request_funcs: string[]; // Before request handlers
  after_request_funcs: string[];  // After request handlers
  error_handlers: object;       // Error handlers by code/exception
  registered_in: Array<{       // Where blueprint is registered
    file: string;
    line: number;
    app_name: string;          // App variable name
    url_prefix: string;        // Registration prefix
  }>;
}>
```

### Examples

```python
# Find all blueprints
blueprints = find_blueprints()
# Returns: [
#   {
#     "name": "api",
#     "import_name": "app.api",
#     "file": "/project/app/api/__init__.py",
#     "line": 10,
#     "url_prefix": "/api/v1",
#     "subdomain": null,
#     "static_folder": null,
#     "template_folder": "templates/api",
#     "routes": [
#       {"route": "/users", "methods": ["GET", "POST"], "function": "users"},
#       {"route": "/users/<int:id>", "methods": ["GET", "PUT", "DELETE"], "function": "user_detail"}
#     ],
#     "before_request_funcs": ["check_api_token"],
#     "after_request_funcs": ["add_cors_headers"],
#     "error_handlers": {
#       "404": "handle_not_found",
#       "ValidationError": "handle_validation_error"
#     },
#     "registered_in": [
#       {
#         "file": "/project/app/__init__.py",
#         "line": 45,
#         "app_name": "app",
#         "url_prefix": "/api/v1"
#       }
#     ]
#   },
#   {
#     "name": "auth",
#     "import_name": "app.auth",
#     "file": "/project/app/auth/__init__.py",
#     "line": 8,
#     "url_prefix": "/auth",
#     "routes": [...]
#   }
# ]

# Find blueprints with most routes
sorted_blueprints = sorted(blueprints, key=lambda x: len(x["routes"]), reverse=True)

# Find blueprints with error handlers
error_handling_blueprints = [b for b in blueprints if b["error_handlers"]]
```

### Error Conditions

- Returns empty array if no blueprints found
- May miss blueprints created dynamically
- Registration tracking requires app context

### Performance Notes

- Scans for Blueprint() instantiations
- Correlates routes with blueprints
- Moderate performance impact

### Use Cases

- Application structure overview
- Blueprint organization audit
- Route grouping analysis
- Middleware review
- Modularization planning

---

## find_views

Find all Flask view functions and classes.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;                // View function/class name
  type: "function" | "class";  // View type
  file: string;               // File path
  line: number;               // Line number
  routes: Array<{             // Associated routes
    route: string;
    methods: string[];
    blueprint: string | null;
  }>;
  decorators: string[];        // Applied decorators
  is_async: boolean;          // Async view
  parameters: Array<{         // Function parameters
    name: string;
    type_hint: string;
    default: any;
  }>;
  returns: string;            // Return type hint
  class_info?: {              // For MethodView classes
    base_class: string;       // Usually MethodView
    methods: Array<{          // HTTP method implementations
      name: string;           // get, post, put, etc.
      is_async: boolean;
      parameters: string[];
    }>;
    decorators: string[];     // Class-level decorators
    init_every_request: boolean;
  };
  template_renders: Array<{   // Templates rendered
    template: string;
    line: number;
  }>;
  json_responses: boolean;    // Returns JSON responses
}>
```

### Examples

```python
# Find all views
views = find_views()
# Returns: [
#   {
#     "name": "index",
#     "type": "function",
#     "file": "/project/app/views.py",
#     "line": 15,
#     "routes": [
#       {"route": "/", "methods": ["GET"], "blueprint": null},
#       {"route": "/home", "methods": ["GET"], "blueprint": null}
#     ],
#     "decorators": ["@cache(timeout=60)"],
#     "is_async": false,
#     "parameters": [],
#     "returns": "str",
#     "template_renders": [
#       {"template": "index.html", "line": 18}
#     ],
#     "json_responses": false
#   },
#   {
#     "name": "UserAPI",
#     "type": "class",
#     "file": "/project/app/api/users.py",
#     "line": 25,
#     "routes": [
#       {"route": "/api/users", "methods": ["GET", "POST"], "blueprint": "api"}
#     ],
#     "decorators": ["@login_required"],
#     "class_info": {
#       "base_class": "MethodView",
#       "methods": [
#         {"name": "get", "is_async": false, "parameters": ["self"]},
#         {"name": "post", "is_async": true, "parameters": ["self"]}
#       ],
#       "decorators": ["@login_required"],
#       "init_every_request": false
#     },
#     "json_responses": true
#   }
# ]

# Find class-based views
class_views = [v for v in views if v["type"] == "class"]

# Find views that render templates
template_views = [v for v in views if v.get("template_renders")]

# Find async views
async_views = [v for v in views if v["is_async"]]
```

### Error Conditions

- May miss views not decorated with @app.route
- Class detection requires MethodView inheritance
- Template detection based on render_template calls

### Performance Notes

- Correlates routes with functions
- Parses function/class definitions
- Can be slow for large codebases

### Use Cases

- View inventory
- Finding unused views
- Template usage audit
- API vs template view analysis
- Async adoption tracking

---

## find_templates

Find all Flask templates and render_template calls.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  template_file: string;       // Template file path
  exists: boolean;            // Whether template file exists
  rendered_in: Array<{        // Where template is rendered
    file: string;             // Python file
    line: number;             // Line number
    function: string;         // Function name
    context_vars: string[];   // Variables passed to template
    dynamic: boolean;         // Dynamic template name
  }>;
  extends: string | null;      // Parent template (from {% extends %})
  includes: string[];         // Included templates (from {% include %})
  blocks: string[];           // Block names defined
  uses_blocks: string[];      // Blocks used from parent
  static_files: string[];     // Static files referenced
  url_for_calls: Array<{      // url_for() calls in template
    endpoint: string;
    line: number;
  }>;
  filters_used: string[];     // Jinja2 filters used
  has_forms: boolean;         // Contains form elements
  javascript_files: string[]; // JS files included
  css_files: string[];        // CSS files included
}>
```

### Examples

```python
# Find all templates
templates = find_templates()
# Returns: [
#   {
#     "template_file": "/project/templates/index.html",
#     "exists": true,
#     "rendered_in": [
#       {
#         "file": "/project/app/views.py",
#         "line": 20,
#         "function": "index",
#         "context_vars": ["user", "posts", "pagination"],
#         "dynamic": false
#       },
#       {
#         "file": "/project/app/views.py",
#         "line": 35,
#         "function": "home",
#         "context_vars": ["user"],
#         "dynamic": false
#       }
#     ],
#     "extends": "base.html",
#     "includes": ["_navbar.html", "_footer.html"],
#     "blocks": ["content", "scripts"],
#     "uses_blocks": ["title", "content"],
#     "static_files": ["/static/css/main.css", "/static/js/app.js"],
#     "url_for_calls": [
#       {"endpoint": "auth.login", "line": 15},
#       {"endpoint": "auth.logout", "line": 18}
#     ],
#     "filters_used": ["safe", "truncate", "date"],
#     "has_forms": true,
#     "javascript_files": ["app.js", "vendor/jquery.js"],
#     "css_files": ["main.css", "bootstrap.css"]
#   }
# ]

# Find orphaned templates (not rendered anywhere)
orphaned = [t for t in templates if not t["rendered_in"]]

# Find templates with forms
form_templates = [t for t in templates if t["has_forms"]]

# Find template inheritance tree
base_templates = [t for t in templates if not t["extends"]]
child_templates = [t for t in templates if t["extends"]]
```

### Error Conditions

- Template parsing is best-effort
- May miss dynamic template names
- Requires template files to exist for full analysis

### Performance Notes

- Scans Python files and template files
- Template parsing can be expensive
- Results cached per file

### Use Cases

- Template inventory
- Finding unused templates
- Template inheritance mapping
- Static asset tracking
- Form location audit

---

## find_extensions

Find Flask extensions in use.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;                // Extension name (e.g., "Flask-SQLAlchemy")
  import_name: string;         // Import statement
  variable_name: string;       // Variable name (e.g., "db")
  file: string;               // File where initialized
  line: number;               // Line number
  initialization: {
    init_app_calls: Array<{   // init_app() calls
      file: string;
      line: number;
      app_var: string;
    }>;
    config_keys: string[];     // Config keys used
    direct_init: boolean;      // Initialized with app directly
  };
  usage: Array<{              // Where extension is used
    file: string;
    line: number;
    method: string;           // Method called
    context: string;          // Code context
  }>;
  common_extensions: {        // Detected common extensions
    sqlalchemy: boolean;
    migrate: boolean;
    login: boolean;
    cors: boolean;
    mail: boolean;
    cache: boolean;
    limiter: boolean;
    socketio: boolean;
    restful: boolean;
    marshmallow: boolean;
    jwt: boolean;
    babel: boolean;
  };
}>
```

### Examples

```python
# Find all extensions
extensions = find_extensions()
# Returns: [
#   {
#     "name": "Flask-SQLAlchemy",
#     "import_name": "from flask_sqlalchemy import SQLAlchemy",
#     "variable_name": "db",
#     "file": "/project/app/extensions.py",
#     "line": 3,
#     "initialization": {
#       "init_app_calls": [
#         {"file": "/project/app/__init__.py", "line": 25, "app_var": "app"}
#       ],
#       "config_keys": ["SQLALCHEMY_DATABASE_URI", "SQLALCHEMY_TRACK_MODIFICATIONS"],
#       "direct_init": false
#     },
#     "usage": [
#       {"file": "/project/app/models.py", "line": 10, "method": "Model", "context": "class User(db.Model):"},
#       {"file": "/project/app/views.py", "line": 45, "method": "session.commit", "context": "db.session.commit()"}
#     ],
#     "common_extensions": {
#       "sqlalchemy": true,
#       "migrate": false,
#       "login": false,
#       ...
#     }
#   },
#   {
#     "name": "Flask-Login",
#     "import_name": "from flask_login import LoginManager",
#     "variable_name": "login_manager",
#     "file": "/project/app/auth.py",
#     "line": 5,
#     ...
#   }
# ]

# Find most used extensions
usage_count = {}
for ext in extensions:
    usage_count[ext["name"]] = len(ext["usage"])
most_used = sorted(usage_count.items(), key=lambda x: x[1], reverse=True)

# Check for security extensions
security_extensions = ["cors", "limiter", "jwt"]
has_security = any(
    ext["common_extensions"].get(sec, False)
    for ext in extensions
    for sec in security_extensions
)
```

### Error Conditions

- May miss custom or uncommon extensions
- Dynamic imports not detected
- Best-effort config key detection

### Performance Notes

- Scans imports and usage patterns
- Correlates with known extension patterns
- Moderate performance impact

### Use Cases

- Dependency audit
- Security review
- Migration planning
- Extension compatibility check
- Configuration validation

---

## find_config

Find Flask configuration files and app.config usage.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  type: "file" | "class" | "dict" | "env";  // Config type
  location: string;           // File path or description
  line: number;               // Line number (if applicable)
  config_values: {            // Configuration key-value pairs
    [key: string]: {
      value: any;             // Config value
      type: string;           // Value type
      line: number;           // Line where defined
      overridden: boolean;    // Overridden elsewhere
      env_var: string | null; // Environment variable if used
    };
  };
  environments: string[];      // Environments (dev, prod, test)
  inherits_from: string | null; // Parent config class
  uses_env_vars: boolean;     // Uses environment variables
  secret_keys: string[];      // Detected secret/sensitive keys
  database_config: {          // Database configuration
    uri: string;
    driver: string;
    host: string;
    database: string;
  } | null;
  app_config_updates: Array<{ // app.config updates
    file: string;
    line: number;
    key: string;
    value: any;
    method: string;           // update(), from_object(), etc.
  }>;
  config_access: Array<{      // Where config is accessed
    file: string;
    line: number;
    key: string;
    context: string;
  }>;
}>
```

### Examples

```python
# Find all configuration
configs = find_config()
# Returns: [
#   {
#     "type": "class",
#     "location": "/project/config.py",
#     "line": 10,
#     "config_values": {
#       "SECRET_KEY": {
#         "value": "os.environ.get('SECRET_KEY')",
#         "type": "str",
#         "line": 12,
#         "overridden": false,
#         "env_var": "SECRET_KEY"
#       },
#       "SQLALCHEMY_DATABASE_URI": {
#         "value": "sqlite:///app.db",
#         "type": "str",
#         "line": 13,
#         "overridden": true,
#         "env_var": null
#       },
#       "DEBUG": {
#         "value": false,
#         "type": "bool",
#         "line": 14,
#         "overridden": false,
#         "env_var": null
#       }
#     },
#     "environments": ["development", "production", "testing"],
#     "inherits_from": "Config",
#     "uses_env_vars": true,
#     "secret_keys": ["SECRET_KEY", "DATABASE_PASSWORD", "API_KEY"],
#     "database_config": {
#       "uri": "sqlite:///app.db",
#       "driver": "sqlite",
#       "host": null,
#       "database": "app.db"
#     },
#     "app_config_updates": [
#       {
#         "file": "/project/app/__init__.py",
#         "line": 20,
#         "key": null,
#         "value": "config.DevelopmentConfig",
#         "method": "from_object"
#       }
#     ],
#     "config_access": [
#       {
#         "file": "/project/app/views.py",
#         "line": 30,
#         "key": "DEBUG",
#         "context": "if app.config['DEBUG']:"
#       }
#     ]
#   }
# ]

# Find sensitive configuration
sensitive_configs = []
for config in configs:
    if config["secret_keys"]:
        sensitive_configs.append({
            "location": config["location"],
            "secrets": config["secret_keys"]
        })

# Find environment-specific configs
env_configs = [c for c in configs if len(c["environments"]) > 1]
```

### Error Conditions

- Complex config patterns may not be fully parsed
- Environment variable resolution is static
- Dynamic config updates tracked separately

### Performance Notes

- Parses configuration files and classes
- Tracks config usage throughout codebase
- Can be slow for many config accesses

### Use Cases

- Configuration audit
- Security review (exposed secrets)
- Environment setup documentation
- Config migration
- Deployment preparation

---

## find_error_handlers

Find error handler functions.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  handler: string;             // Handler function name
  file: string;               // File path
  line: number;               // Line number
  error_type: string | number; // Error code or exception class
  blueprint: string | null;    // Blueprint if applicable
  decorator: string;          // Full decorator string
  is_async: boolean;          // Async handler
  returns_json: boolean;      // Returns JSON response
  custom_response: {          // Custom response details
    status_code: number;
    headers: object;
    template: string | null;
  } | null;
  logged: boolean;            // Whether error is logged
  scope: "app" | "blueprint"; // Handler scope
}>
```

### Examples

```python
# Find all error handlers
handlers = find_error_handlers()
# Returns: [
#   {
#     "handler": "handle_404",
#     "file": "/project/app/errors.py",
#     "line": 10,
#     "error_type": 404,
#     "blueprint": null,
#     "decorator": "@app.errorhandler(404)",
#     "is_async": false,
#     "returns_json": false,
#     "custom_response": {
#       "status_code": 404,
#       "headers": {},
#       "template": "errors/404.html"
#     },
#     "logged": true,
#     "scope": "app"
#   },
#   {
#     "handler": "handle_validation_error",
#     "file": "/project/app/api/errors.py",
#     "line": 15,
#     "error_type": "ValidationError",
#     "blueprint": "api",
#     "decorator": "@api.errorhandler(ValidationError)",
#     "is_async": true,
#     "returns_json": true,
#     "custom_response": {
#       "status_code": 400,
#       "headers": {"Content-Type": "application/json"},
#       "template": null
#     },
#     "logged": true,
#     "scope": "blueprint"
#   }
# ]

# Find handlers by error code
error_404_handlers = [h for h in handlers if h["error_type"] == 404]

# Find exception handlers
exception_handlers = [h for h in handlers if isinstance(h["error_type"], str)]

# Find handlers that return JSON
api_handlers = [h for h in handlers if h["returns_json"]]
```

### Error Conditions

- May miss dynamically registered handlers
- Exception class names resolved statically
- Custom response detection is best-effort

### Performance Notes

- Scans for errorhandler decorators
- Lightweight operation
- Results cached

### Use Cases

- Error handling audit
- Finding missing error handlers
- API vs HTML error responses
- Logging verification
- User experience review

---

## find_cli_commands

Find Flask CLI commands.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;                // Command name
  function: string;            // Function name
  file: string;               // File path
  line: number;               // Line number
  group: string | null;        // Command group if applicable
  decorator: string;          // Full decorator string
  help_text: string;          // Help text from decorator or docstring
  arguments: Array<{          // CLI arguments
    name: string;
    type: string;             // Argument type
    required: boolean;
    default: any;
    help: string;
  }>;
  options: Array<{            // CLI options/flags
    names: string[];          // Option names (e.g., ["-v", "--verbose"])
    type: string;
    default: any;
    help: string;
    is_flag: boolean;
  }>;
  is_async: boolean;          // Async command function
  uses_app_context: boolean;  // Uses with app.app_context()
  subcommands: string[];      // Subcommands if group
}>
```

### Examples

```python
# Find all CLI commands
commands = find_cli_commands()
# Returns: [
#   {
#     "name": "init-db",
#     "function": "init_database",
#     "file": "/project/app/commands.py",
#     "line": 15,
#     "group": null,
#     "decorator": "@app.cli.command('init-db')",
#     "help_text": "Initialize the database with default data",
#     "arguments": [],
#     "options": [
#       {
#         "names": ["--drop", "-d"],
#         "type": "bool",
#         "default": false,
#         "help": "Drop existing tables before creating",
#         "is_flag": true
#       },
#       {
#         "names": ["--seed"],
#         "type": "bool",
#         "default": false,
#         "help": "Seed with sample data",
#         "is_flag": true
#       }
#     ],
#     "is_async": false,
#     "uses_app_context": true,
#     "subcommands": []
#   },
#   {
#     "name": "user",
#     "function": "user_group",
#     "file": "/project/app/commands.py",
#     "line": 40,
#     "group": "user",
#     "decorator": "@app.cli.group()",
#     "help_text": "User management commands",
#     "arguments": [],
#     "options": [],
#     "is_async": false,
#     "uses_app_context": false,
#     "subcommands": ["create", "delete", "list"]
#   }
# ]

# Find command groups
groups = [c for c in commands if c["subcommands"]]

# Find async commands
async_commands = [c for c in commands if c["is_async"]]

# Generate CLI documentation
for cmd in commands:
    print(f"flask {cmd['name']} - {cmd['help_text']}")
    for opt in cmd["options"]:
        print(f"  {', '.join(opt['names'])}: {opt['help']}")
```

### Error Conditions

- May miss commands registered differently
- Click integration detected separately
- Argument parsing is best-effort

### Performance Notes

- Scans for cli.command decorators
- Parses function signatures
- Lightweight operation

### Use Cases

- CLI documentation generation
- Command inventory
- Migration script tracking
- DevOps integration
- Command testing coverage

---

## Common Patterns

### Complete Flask App Analysis

```python
# Comprehensive Flask application analysis
def analyze_flask_app():
    routes = find_routes()
    blueprints = find_blueprints()
    extensions = find_extensions()
    config = find_config()

    analysis = {
        "routes": {
            "total": len(routes),
            "by_method": {},
            "auth_required": len([r for r in routes if r["auth_required"]]),
            "public": len([r for r in routes if not r["auth_required"]])
        },
        "blueprints": {
            "total": len(blueprints),
            "names": [b["name"] for b in blueprints]
        },
        "extensions": {
            "total": len(extensions),
            "security": ["cors", "limiter", "jwt"],
            "database": ["sqlalchemy", "migrate"],
            "auth": ["login", "jwt"]
        },
        "config": {
            "environments": [],
            "uses_env_vars": False,
            "has_secrets": False
        }
    }

    # Count routes by method
    for route in routes:
        for method in route["methods"]:
            analysis["routes"]["by_method"][method] = \
                analysis["routes"]["by_method"].get(method, 0) + 1

    # Check extensions
    for ext in extensions:
        for category in ["security", "database", "auth"]:
            for ext_name in analysis["extensions"][category]:
                if ext["common_extensions"].get(ext_name, False):
                    analysis["extensions"][f"has_{ext_name}"] = True

    # Check config
    for cfg in config:
        analysis["config"]["environments"].extend(cfg["environments"])
        if cfg["uses_env_vars"]:
            analysis["config"]["uses_env_vars"] = True
        if cfg["secret_keys"]:
            analysis["config"]["has_secrets"] = True

    return analysis
```

### Route Documentation Generator

```python
# Generate OpenAPI/Swagger documentation
def generate_api_docs():
    routes = find_routes()

    openapi = {
        "openapi": "3.0.0",
        "info": {
            "title": "API Documentation",
            "version": "1.0.0"
        },
        "paths": {}
    }

    for route in routes:
        if not route["route"].startswith("/api"):
            continue

        path = route["route"].replace("<int:", "{").replace("<", "{").replace(">", "}")

        if path not in openapi["paths"]:
            openapi["paths"][path] = {}

        for method in route["methods"]:
            openapi["paths"][path][method.lower()] = {
                "summary": route["function"],
                "operationId": route["endpoint"],
                "parameters": [
                    {
                        "name": param["name"],
                        "in": "path",
                        "required": param["required"],
                        "schema": {"type": param["type"]}
                    }
                    for param in route["url_params"]
                ],
                "responses": {
                    "200": {"description": "Success"}
                }
            }

            if route["auth_required"]:
                openapi["paths"][path][method.lower()]["security"] = [
                    {"bearerAuth": []}
                ]

    return openapi
```

### Security Audit

```python
# Security audit for Flask app
def security_audit():
    routes = find_routes()
    config = find_config()
    extensions = find_extensions()
    error_handlers = find_error_handlers()

    issues = []

    # Check for unprotected routes
    public_routes = [r for r in routes if not r["auth_required"]]
    sensitive_public = [r for r in public_routes
                       if any(m in ["POST", "PUT", "DELETE"]
                             for m in r["methods"])]
    if sensitive_public:
        issues.append({
            "severity": "high",
            "issue": "Unprotected state-changing routes",
            "details": [r["route"] for r in sensitive_public]
        })

    # Check for exposed secrets
    for cfg in config:
        if cfg["secret_keys"]:
            for key in cfg["secret_keys"]:
                if cfg["config_values"].get(key, {}).get("env_var") is None:
                    issues.append({
                        "severity": "critical",
                        "issue": f"Hardcoded secret: {key}",
                        "location": cfg["location"]
                    })

    # Check for security extensions
    has_cors = any(e["common_extensions"]["cors"] for e in extensions)
    has_limiter = any(e["common_extensions"]["limiter"] for e in extensions)

    if not has_cors:
        issues.append({
            "severity": "medium",
            "issue": "No CORS configuration detected"
        })

    if not has_limiter:
        issues.append({
            "severity": "medium",
            "issue": "No rate limiting detected"
        })

    # Check error handling
    error_codes = [h["error_type"] for h in error_handlers
                  if isinstance(h["error_type"], int)]
    missing_handlers = set([400, 401, 403, 404, 500]) - set(error_codes)
    if missing_handlers:
        issues.append({
            "severity": "low",
            "issue": "Missing error handlers",
            "codes": list(missing_handlers)
        })

    return issues
```

### Blueprint Dependency Graph

```python
# Build blueprint dependency graph
def blueprint_dependencies():
    blueprints = find_blueprints()
    templates = find_templates()

    graph = {}

    for bp in blueprints:
        graph[bp["name"]] = {
            "imports": [],
            "templates": [],
            "calls": []
        }

        # Find template dependencies
        for route in bp["routes"]:
            for template in templates:
                for render in template["rendered_in"]:
                    if render["function"] == route["function"]:
                        graph[bp["name"]]["templates"].append(
                            template["template_file"]
                        )

        # Find URL references to other blueprints
        for template in graph[bp["name"]]["templates"]:
            template_data = next((t for t in templates
                                 if t["template_file"] == template), None)
            if template_data:
                for url_call in template_data["url_for_calls"]:
                    endpoint_bp = url_call["endpoint"].split(".")[0]
                    if endpoint_bp != bp["name"] and endpoint_bp in graph:
                        graph[bp["name"]]["calls"].append(endpoint_bp)

    return graph
```

## Related Tools

- **Navigation**: Use [Core Navigation Tools](./core-navigation.md) to navigate to route definitions
- **Module Analysis**: Use [Module Analysis Tools](./module-analysis.md) to analyze Flask modules
- **Template Analysis**: Templates often use Jinja2, correlate with [find_templates](#find_templates)

## Best Practices

1. **Regular route audits** - Use `find_routes` to ensure all routes are protected
2. **Blueprint organization** - Keep related routes in same blueprint
3. **Template tracking** - Use `find_templates` to find orphaned templates
4. **Extension inventory** - Document all extensions and their configs
5. **Error handler coverage** - Ensure all error codes have handlers
6. **CLI documentation** - Keep CLI commands documented with help text
