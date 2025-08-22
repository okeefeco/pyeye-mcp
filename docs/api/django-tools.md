# Django Tools

Specialized tools for analyzing Django applications, models, views, and migrations. These 5 tools are automatically activated when Django is detected in your project.

## Table of Contents

1. [find_django_models](#find_django_models)
2. [find_django_views](#find_django_views)
3. [find_django_urls](#find_django_urls)
4. [find_django_templates](#find_django_templates)
5. [find_django_migrations](#find_django_migrations)

---

## find_django_models

Find all Django models in the project.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;                // Model class name
  file: string;               // File path
  line: number;               // Line number of class definition
  app: string;                // Django app name
  fields: Array<{
    name: string;             // Field name
    type: string;             // Field type (CharField, ForeignKey, etc.)
    max_length: number | null; // For CharField, TextField
    null: boolean;            // null=True
    blank: boolean;           // blank=True
    default: any;             // Default value
    unique: boolean;          // unique=True
    db_index: boolean;        // db_index=True
    related_name: string | null; // For relationship fields
    on_delete: string | null; // For ForeignKey/OneToOne
    validators: string[];     // Applied validators
    help_text: string;        // Help text
    verbose_name: string;     // Verbose name
  }>;
  meta: {
    abstract: boolean;         // Abstract model
    db_table: string | null;   // Custom table name
    ordering: string[];        // Default ordering
    unique_together: Array<string[]>; // Unique constraints
    indexes: Array<{
      fields: string[];
      name: string;
    }>;
    verbose_name: string;
    verbose_name_plural: string;
    app_label: string;
    managed: boolean;          // Managed by Django
    proxy: boolean;           // Proxy model
    permissions: Array<[string, string]>; // Custom permissions
  };
  methods: Array<{
    name: string;
    line: number;
    is_property: boolean;
    is_classmethod: boolean;
    is_staticmethod: boolean;
  }>;
  managers: Array<{           // Custom managers
    name: string;
    type: string;             // Manager class name
  }>;
  inheritance: string[];      // Parent model classes
  related_models: Array<{     // Models referenced via ForeignKey
    model: string;
    field: string;
    relation_type: string;    // ForeignKey, ManyToMany, OneToOne
  }>;
}>
```

### Examples

```python
# Find all Django models
models = find_django_models()
# Returns: [
#   {
#     "name": "User",
#     "file": "/project/accounts/models.py",
#     "line": 10,
#     "app": "accounts",
#     "fields": [
#       {
#         "name": "email",
#         "type": "EmailField",
#         "max_length": 255,
#         "null": false,
#         "blank": false,
#         "unique": true,
#         "db_index": true,
#         "validators": ["validate_email"],
#         "help_text": "User's email address",
#         "verbose_name": "email address"
#       },
#       {
#         "name": "profile",
#         "type": "OneToOneField",
#         "related_name": "user",
#         "on_delete": "CASCADE",
#         "null": true,
#         "blank": true
#       },
#       {
#         "name": "groups",
#         "type": "ManyToManyField",
#         "related_name": "users",
#         "blank": true
#       }
#     ],
#     "meta": {
#       "abstract": false,
#       "db_table": "auth_user",
#       "ordering": ["-created_at"],
#       "unique_together": [["email", "tenant"]],
#       "indexes": [
#         {"fields": ["email", "is_active"], "name": "email_active_idx"}
#       ],
#       "verbose_name": "user",
#       "verbose_name_plural": "users",
#       "managed": true,
#       "proxy": false,
#       "permissions": [
#         ["can_export", "Can export user data"]
#       ]
#     },
#     "methods": [
#       {"name": "get_full_name", "line": 45, "is_property": false},
#       {"name": "full_name", "line": 50, "is_property": true},
#       {"name": "__str__", "line": 55, "is_property": false}
#     ],
#     "managers": [
#       {"name": "objects", "type": "UserManager"}
#     ],
#     "inheritance": ["AbstractBaseUser", "PermissionsMixin"],
#     "related_models": [
#       {"model": "Profile", "field": "profile", "relation_type": "OneToOneField"},
#       {"model": "Group", "field": "groups", "relation_type": "ManyToManyField"}
#     ]
#   }
# ]

# Find abstract models
abstract_models = [m for m in models if m["meta"]["abstract"]]

# Find models with custom managers
custom_manager_models = [m for m in models if m["managers"]]

# Find models with relationships
related_models = [m for m in models if m["related_models"]]
```

### Error Conditions

- Returns empty array if no Django models found
- Requires Django to be installed
- May miss dynamically created models

### Performance Notes

- Scans models.py files in Django apps
- Parses model definitions and Meta classes
- Caches results per file

### Use Cases

- Model documentation generation
- Database schema overview
- Migration planning
- Relationship mapping
- Model complexity analysis

---

## find_django_views

Find all Django views (function-based and class-based).

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;                // View function/class name
  type: "function" | "class";  // View type
  file: string;               // File path
  line: number;               // Line number
  app: string;                // Django app name
  decorators: string[];        // Applied decorators

  // For function-based views
  parameters: string[];        // Function parameters
  is_async: boolean;          // Async view

  // For class-based views
  base_classes: string[];      // Parent classes (ListView, CreateView, etc.)
  mixins: string[];           // Applied mixins
  methods: Array<{
    name: string;             // Method name (get, post, etc.)
    line: number;
    is_async: boolean;
  }>;
  attributes: {
    model: string | null;      // Model class
    queryset: string | null;   // Queryset definition
    template_name: string | null; // Template path
    form_class: string | null; // Form class
    success_url: string | null; // Success URL
    permission_required: string[]; // Required permissions
    login_required: boolean;   // Requires authentication
  };

  urls: Array<{               // URL patterns using this view
    pattern: string;
    name: string;
    namespace: string | null;
  }>;

  templates_used: string[];    // Templates rendered
  context_data: string[];      // Context variables
  redirects: string[];         // Redirect targets
  http_methods: string[];      // Allowed HTTP methods
}>
```

### Examples

```python
# Find all Django views
views = find_django_views()
# Returns: [
#   {
#     "name": "UserListView",
#     "type": "class",
#     "file": "/project/accounts/views.py",
#     "line": 20,
#     "app": "accounts",
#     "decorators": ["@method_decorator(login_required)"],
#     "base_classes": ["ListView"],
#     "mixins": ["LoginRequiredMixin", "PermissionRequiredMixin"],
#     "methods": [
#       {"name": "get_queryset", "line": 30, "is_async": false},
#       {"name": "get_context_data", "line": 35, "is_async": false}
#     ],
#     "attributes": {
#       "model": "User",
#       "queryset": null,
#       "template_name": "accounts/user_list.html",
#       "form_class": null,
#       "success_url": null,
#       "permission_required": ["accounts.view_user"],
#       "login_required": true
#     },
#     "urls": [
#       {"pattern": "users/", "name": "user_list", "namespace": "accounts"}
#     ],
#     "templates_used": ["accounts/user_list.html"],
#     "context_data": ["users", "page_obj", "paginator"],
#     "http_methods": ["GET"]
#   },
#   {
#     "name": "user_profile",
#     "type": "function",
#     "file": "/project/accounts/views.py",
#     "line": 50,
#     "app": "accounts",
#     "decorators": ["@login_required", "@require_http_methods(['GET'])"],
#     "parameters": ["request", "user_id"],
#     "is_async": false,
#     "urls": [
#       {"pattern": "users/<int:user_id>/", "name": "user_profile", "namespace": "accounts"}
#     ],
#     "templates_used": ["accounts/profile.html"],
#     "context_data": ["user", "profile"],
#     "http_methods": ["GET"]
#   }
# ]

# Find class-based views
cbvs = [v for v in views if v["type"] == "class"]

# Find views requiring authentication
auth_views = [v for v in views
              if v.get("attributes", {}).get("login_required") or
              "@login_required" in v.get("decorators", [])]

# Find async views
async_views = [v for v in views if v.get("is_async")]
```

### Error Conditions

- May miss views not in views.py files
- Dynamic view creation not detected
- URL pattern matching is best-effort

### Performance Notes

- Scans views.py and related files
- Correlates with URL patterns
- Can be slow for large projects

### Use Cases

- View inventory
- Authentication audit
- Template usage tracking
- URL-view mapping
- Permission analysis

---

## find_django_urls

Find all Django URL patterns.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  pattern: string;             // URL pattern
  regex: string | null;        // Regex pattern if used
  name: string | null;         // URL name
  namespace: string | null;    // URL namespace
  file: string;               // File path
  line: number;               // Line number
  view: {
    type: "function" | "class" | "include";
    name: string;             // View name or module
    module: string;           // Import module
  };
  app_name: string | null;    // Django app name
  includes: Array<{           // For include() patterns
    module: string;
    namespace: string | null;
    patterns_count: number;
  }>;
  converters: Array<{         // Path converters
    name: string;             // Parameter name
    type: string;             // int, str, slug, uuid, path
  }>;
  kwargs: object;             // Extra kwargs passed to view
  decorators: string[];       // URL decorators
  is_api: boolean;           // Likely API endpoint
  is_admin: boolean;         // Admin URL
  is_static: boolean;        // Static/media file serving
}>
```

### Examples

```python
# Find all URL patterns
urls = find_django_urls()
# Returns: [
#   {
#     "pattern": "users/<int:pk>/",
#     "regex": null,
#     "name": "user-detail",
#     "namespace": "api",
#     "file": "/project/api/urls.py",
#     "line": 15,
#     "view": {
#       "type": "class",
#       "name": "UserDetailView",
#       "module": "api.views"
#     },
#     "app_name": "api",
#     "includes": [],
#     "converters": [
#       {"name": "pk", "type": "int"}
#     ],
#     "kwargs": {"permission": "view_user"},
#     "decorators": [],
#     "is_api": true,
#     "is_admin": false,
#     "is_static": false
#   },
#   {
#     "pattern": "api/",
#     "regex": null,
#     "name": null,
#     "namespace": "api",
#     "file": "/project/config/urls.py",
#     "line": 25,
#     "view": {
#       "type": "include",
#       "name": "api.urls",
#       "module": "api.urls"
#     },
#     "includes": [
#       {
#         "module": "api.urls",
#         "namespace": "api",
#         "patterns_count": 15
#       }
#     ],
#     "is_api": true,
#     "is_admin": false
#   }
# ]

# Find API endpoints
api_urls = [u for u in urls if u["is_api"]]

# Find admin URLs
admin_urls = [u for u in urls if u["is_admin"]]

# Find URLs with path converters
converter_urls = [u for u in urls if u["converters"]]

# Build URL tree
def build_url_tree(urls):
    tree = {}
    for url in urls:
        if url["view"]["type"] == "include":
            tree[url["pattern"]] = url["includes"]
    return tree
```

### Error Conditions

- May miss dynamically generated URLs
- Complex regex patterns might not parse fully
- Include chains tracked to reasonable depth

### Performance Notes

- Parses urls.py files recursively
- Follows include() chains
- Can be slow for complex URL structures

### Use Cases

- URL documentation
- API endpoint inventory
- URL namespace organization
- Route collision detection
- URL pattern optimization

---

## find_django_templates

Find all Django templates and their usage.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  template_path: string;       // Template file path
  relative_path: string;       // Path relative to template dir
  app: string | null;         // Django app if app template
  exists: boolean;            // File exists

  extends: string | null;      // Parent template
  includes: string[];         // Included templates
  blocks: Array<{             // Template blocks
    name: string;
    line: number;
    overrides: boolean;       // Overrides parent block
  }>;

  used_in: Array<{            // Where template is used
    type: "view" | "template" | "email";
    file: string;
    line: number;
    context: string;          // Code context
    view_name: string | null;
  }>;

  static_files: Array<{       // Static files referenced
    type: "css" | "js" | "image" | "other";
    path: string;
    tag: string;             // Template tag used
  }>;

  template_tags: Array<{      // Custom template tags used
    library: string;         // Tag library
    tags: string[];          // Tag names
  }>;

  context_variables: string[]; // Variables used in template
  filters: string[];          // Filters applied
  urls: Array<{              // {% url %} tags
    name: string;            // URL name
    namespace: string | null;
    args: string[];          // URL arguments
  }>;

  forms: Array<{             // Forms rendered
    variable: string;        // Form variable name
    fields: string[];        // Fields accessed
  }>;

  translations: boolean;      // Uses i18n/l10n
  csrf_token: boolean;       // Has {% csrf_token %}
}>
```

### Examples

```python
# Find all Django templates
templates = find_django_templates()
# Returns: [
#   {
#     "template_path": "/project/templates/accounts/user_list.html",
#     "relative_path": "accounts/user_list.html",
#     "app": "accounts",
#     "exists": true,
#     "extends": "base.html",
#     "includes": ["_pagination.html", "_user_row.html"],
#     "blocks": [
#       {"name": "title", "line": 5, "overrides": true},
#       {"name": "content", "line": 10, "overrides": true}
#     ],
#     "used_in": [
#       {
#         "type": "view",
#         "file": "/project/accounts/views.py",
#         "line": 25,
#         "context": "render(request, 'accounts/user_list.html', context)",
#         "view_name": "UserListView"
#       }
#     ],
#     "static_files": [
#       {"type": "css", "path": "css/users.css", "tag": "{% static %}"},
#       {"type": "js", "path": "js/user-list.js", "tag": "{% static %}"}
#     ],
#     "template_tags": [
#       {"library": "humanize", "tags": ["naturaltime", "intcomma"]}
#     ],
#     "context_variables": ["users", "page_obj", "search_query"],
#     "filters": ["date", "truncatewords", "default", "safe"],
#     "urls": [
#       {"name": "user_detail", "namespace": "accounts", "args": ["user.pk"]},
#       {"name": "user_edit", "namespace": "accounts", "args": ["user.pk"]}
#     ],
#     "forms": [
#       {"variable": "search_form", "fields": ["query", "filters"]}
#     ],
#     "translations": true,
#     "csrf_token": true
#   }
# ]

# Find orphaned templates
orphaned = [t for t in templates if not t["used_in"]]

# Find templates with forms
form_templates = [t for t in templates if t["forms"]]

# Build template inheritance tree
def build_template_hierarchy(templates):
    hierarchy = {}
    for template in templates:
        if template["extends"]:
            parent = template["extends"]
            if parent not in hierarchy:
                hierarchy[parent] = []
            hierarchy[parent].append(template["relative_path"])
    return hierarchy
```

### Error Conditions

- Template parsing is best-effort
- Dynamic template names not tracked
- Complex template tag logic might be missed

### Performance Notes

- Scans template directories
- Parses Django template syntax
- Can be slow for many templates

### Use Cases

- Template inventory
- Finding unused templates
- Static file usage audit
- Template inheritance mapping
- i18n coverage check

---

## find_django_migrations

Find all Django migrations.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;                // Migration name (e.g., "0001_initial")
  file: string;               // File path
  app: string;                // Django app name
  dependencies: Array<{        // Migration dependencies
    app: string;
    migration: string;
  }>;

  operations: Array<{          // Migration operations
    type: string;             // CreateModel, AddField, etc.
    model: string | null;     // Affected model
    field: string | null;     // Affected field
    details: object;          // Operation-specific details
    line: number;
  }>;

  run_before: string[];       // Migrations that must run before
  run_after: string[];        // Migrations that must run after
  is_initial: boolean;        // Initial migration
  is_squashed: boolean;       // Squashed migration
  replaces: string[];         // Replaced migrations (if squashed)

  models_created: string[];    // Models created
  models_deleted: string[];    // Models deleted
  models_altered: string[];    // Models altered

  fields_added: Array<{       // Fields added
    model: string;
    field: string;
    type: string;
  }>;

  fields_removed: Array<{     // Fields removed
    model: string;
    field: string;
  }>;

  fields_altered: Array<{     // Fields altered
    model: string;
    field: string;
    changes: string[];
  }>;

  indexes_created: Array<{    // Indexes created
    model: string;
    fields: string[];
    name: string;
  }>;

  custom_sql: boolean;        // Has RunSQL operations
  custom_python: boolean;     // Has RunPython operations
  data_migration: boolean;    // Likely data migration

  timestamp: string | null;   // Migration timestamp if in name
  applied: boolean | null;    // Applied status (if detectable)
}>
```

### Examples

```python
# Find all migrations
migrations = find_django_migrations()
# Returns: [
#   {
#     "name": "0001_initial",
#     "file": "/project/accounts/migrations/0001_initial.py",
#     "app": "accounts",
#     "dependencies": [],
#     "operations": [
#       {
#         "type": "CreateModel",
#         "model": "User",
#         "field": null,
#         "details": {
#           "fields": ["id", "email", "username", "created_at"],
#           "options": {"db_table": "auth_user"}
#         },
#         "line": 15
#       }
#     ],
#     "run_before": [],
#     "run_after": [],
#     "is_initial": true,
#     "is_squashed": false,
#     "replaces": [],
#     "models_created": ["User"],
#     "models_deleted": [],
#     "models_altered": [],
#     "fields_added": [],
#     "fields_removed": [],
#     "fields_altered": [],
#     "indexes_created": [],
#     "custom_sql": false,
#     "custom_python": false,
#     "data_migration": false,
#     "timestamp": null,
#     "applied": true
#   },
#   {
#     "name": "0002_add_user_profile",
#     "file": "/project/accounts/migrations/0002_add_user_profile.py",
#     "app": "accounts",
#     "dependencies": [
#       {"app": "accounts", "migration": "0001_initial"}
#     ],
#     "operations": [
#       {
#         "type": "AddField",
#         "model": "User",
#         "field": "profile",
#         "details": {
#           "field_type": "OneToOneField",
#           "related_model": "Profile"
#         },
#         "line": 20
#       }
#     ],
#     "is_initial": false,
#     "models_created": [],
#     "fields_added": [
#       {"model": "User", "field": "profile", "type": "OneToOneField"}
#     ]
#   }
# ]

# Find data migrations
data_migrations = [m for m in migrations if m["data_migration"]]

# Find migrations with custom SQL
sql_migrations = [m for m in migrations if m["custom_sql"]]

# Build migration dependency graph
def build_migration_graph(migrations):
    graph = {}
    for migration in migrations:
        key = f"{migration['app']}.{migration['name']}"
        graph[key] = {
            "dependencies": [f"{d['app']}.{d['migration']}" for d in migration["dependencies"]],
            "operations": len(migration["operations"]),
            "type": "initial" if migration["is_initial"] else "normal"
        }
    return graph

# Find migration chains
def find_migration_chains(app_name):
    app_migrations = [m for m in migrations if m["app"] == app_name]
    return sorted(app_migrations, key=lambda x: x["name"])
```

### Error Conditions

- Complex migrations might not parse fully
- Applied status requires database access
- Custom operations might not be detailed

### Performance Notes

- Scans migration directories
- Parses migration operations
- Can be slow for many migrations

### Use Cases

- Migration history overview
- Database schema evolution
- Finding unapplied migrations
- Migration optimization (squashing candidates)
- Data migration tracking

---

## Common Patterns

### Django Project Analysis

```python
# Comprehensive Django project analysis
def analyze_django_project():
    models = find_django_models()
    views = find_django_views()
    urls = find_django_urls()
    templates = find_django_templates()
    migrations = find_django_migrations()

    # App structure
    apps = {}
    for model in models:
        if model["app"] not in apps:
            apps[model["app"]] = {
                "models": [], "views": [], "urls": [],
                "templates": [], "migrations": []
            }
        apps[model["app"]]["models"].append(model["name"])

    for view in views:
        if view["app"] in apps:
            apps[view["app"]]["views"].append(view["name"])

    # URL coverage
    url_coverage = {
        "total": len(urls),
        "api": len([u for u in urls if u["is_api"]]),
        "admin": len([u for u in urls if u["is_admin"]]),
        "named": len([u for u in urls if u["name"]])
    }

    # Template usage
    template_stats = {
        "total": len(templates),
        "orphaned": len([t for t in templates if not t["used_in"]]),
        "with_forms": len([t for t in templates if t["forms"]]),
        "translatable": len([t for t in templates if t["translations"]])
    }

    # Migration status
    migration_stats = {
        "total": len(migrations),
        "by_app": {},
        "data_migrations": len([m for m in migrations if m["data_migration"]]),
        "custom_sql": len([m for m in migrations if m["custom_sql"]])
    }

    for migration in migrations:
        if migration["app"] not in migration_stats["by_app"]:
            migration_stats["by_app"][migration["app"]] = 0
        migration_stats["by_app"][migration["app"]] += 1

    return {
        "apps": apps,
        "url_coverage": url_coverage,
        "template_stats": template_stats,
        "migration_stats": migration_stats
    }
```

### Model Relationship Graph

```python
# Build model relationship graph
def build_model_graph():
    models = find_django_models()

    graph = {}
    for model in models:
        node = {
            "app": model["app"],
            "fields": len(model["fields"]),
            "relationships": {
                "foreign_keys": [],
                "many_to_many": [],
                "one_to_one": []
            }
        }

        for rel in model["related_models"]:
            rel_type = rel["relation_type"]
            if "ForeignKey" in rel_type:
                node["relationships"]["foreign_keys"].append(rel["model"])
            elif "ManyToMany" in rel_type:
                node["relationships"]["many_to_many"].append(rel["model"])
            elif "OneToOne" in rel_type:
                node["relationships"]["one_to_one"].append(rel["model"])

        graph[model["name"]] = node

    return graph
```

### View-Template-URL Mapping

```python
# Map views to templates and URLs
def map_view_template_url():
    views = find_django_views()
    templates = find_django_templates()
    urls = find_django_urls()

    mapping = []

    for view in views:
        view_map = {
            "view": view["name"],
            "type": view["type"],
            "templates": [],
            "urls": []
        }

        # Find templates used by this view
        if view["type"] == "class" and view["attributes"]["template_name"]:
            view_map["templates"].append(view["attributes"]["template_name"])
        else:
            for template in templates:
                for usage in template["used_in"]:
                    if usage["view_name"] == view["name"]:
                        view_map["templates"].append(template["relative_path"])

        # Find URLs pointing to this view
        for url in urls:
            if url["view"]["name"] == view["name"]:
                view_map["urls"].append({
                    "pattern": url["pattern"],
                    "name": url["name"],
                    "namespace": url["namespace"]
                })

        mapping.append(view_map)

    return mapping
```

### Migration Analysis

```python
# Analyze migration patterns
def analyze_migrations():
    migrations = find_django_migrations()

    analysis = {
        "apps": {},
        "operations_summary": {},
        "potential_issues": []
    }

    for migration in migrations:
        app = migration["app"]
        if app not in analysis["apps"]:
            analysis["apps"][app] = {
                "count": 0,
                "models_created": set(),
                "models_altered": set(),
                "has_data_migrations": False,
                "has_custom_sql": False
            }

        analysis["apps"][app]["count"] += 1
        analysis["apps"][app]["models_created"].update(migration["models_created"])
        analysis["apps"][app]["models_altered"].update(migration["models_altered"])

        if migration["data_migration"]:
            analysis["apps"][app]["has_data_migrations"] = True
        if migration["custom_sql"]:
            analysis["apps"][app]["has_custom_sql"] = True

        # Count operations
        for op in migration["operations"]:
            op_type = op["type"]
            if op_type not in analysis["operations_summary"]:
                analysis["operations_summary"][op_type] = 0
            analysis["operations_summary"][op_type] += 1

        # Check for potential issues
        if len(migration["operations"]) > 20:
            analysis["potential_issues"].append({
                "migration": f"{app}.{migration['name']}",
                "issue": "Large migration with many operations",
                "operations": len(migration["operations"])
            })

        if migration["custom_sql"] and migration["custom_python"]:
            analysis["potential_issues"].append({
                "migration": f"{app}.{migration['name']}",
                "issue": "Mixed SQL and Python operations"
            })

    # Convert sets to lists for JSON serialization
    for app in analysis["apps"]:
        analysis["apps"][app]["models_created"] = list(analysis["apps"][app]["models_created"])
        analysis["apps"][app]["models_altered"] = list(analysis["apps"][app]["models_altered"])

    return analysis
```

### Admin Interface Coverage

```python
# Check admin interface coverage
def check_admin_coverage():
    models = find_django_models()
    urls = find_django_urls()

    # Find admin URLs
    admin_urls = [u for u in urls if u["is_admin"]]

    # Extract model names from admin URLs
    admin_registered = set()
    for url in admin_urls:
        if "model" in url.get("kwargs", {}):
            admin_registered.add(url["kwargs"]["model"])

    # Check which models have admin
    coverage = {
        "registered": [],
        "not_registered": [],
        "abstract_skipped": []
    }

    for model in models:
        if model["meta"]["abstract"]:
            coverage["abstract_skipped"].append(model["name"])
        elif model["name"].lower() in admin_registered or \
             f"{model['app']}_{model['name']}".lower() in admin_registered:
            coverage["registered"].append(model["name"])
        else:
            coverage["not_registered"].append(model["name"])

    coverage["percentage"] = len(coverage["registered"]) / \
                            (len(coverage["registered"]) + len(coverage["not_registered"])) * 100 \
                            if (coverage["registered"] or coverage["not_registered"]) else 0

    return coverage
```

## Related Tools

- **Navigation**: Use [Core Navigation Tools](./core-navigation.md) to navigate to Django code
- **Module Analysis**: Use [Module Analysis Tools](./module-analysis.md) to analyze Django app modules
- **Python Models**: Django models are often enhanced with [Pydantic Tools](./pydantic-tools.md) for validation

## Best Practices

1. **Regular model audits** - Check for missing indexes, N+1 queries
2. **View organization** - Keep views organized by app and purpose
3. **URL namespace usage** - Always use namespaces for app URLs
4. **Template inheritance** - Use template inheritance to avoid duplication
5. **Migration hygiene** - Squash old migrations periodically
6. **Admin customization** - Ensure all models have appropriate admin interfaces
