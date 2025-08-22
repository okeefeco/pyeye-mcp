# Python Code Intelligence MCP - Quick Reference

A concise cheatsheet for all 35 MCP tools organized by common use cases.

## 🔍 Finding Code

### Find Symbols

```python
find_symbol(name="MyClass")                    # Find class/function/variable
find_symbol(name="MyCls", fuzzy=True)         # Fuzzy search
find_symbol_multi(name="User", project_paths=[".", "../lib"])  # Multi-project
```

### Navigate to Definitions

```python
goto_definition(file="app.py", line=42, column=10)  # Jump to definition
find_references(file="models.py", line=15, column=4)  # Find all usages
get_type_info(file="utils.py", line=100, column=20)  # Get type hints
```

### Track Imports

```python
find_imports(module_name="models.user")        # Who imports this module
get_call_hierarchy(function_name="process")    # Function call tree
```

## 📦 Project Structure

### List Components

```python
list_project_structure(max_depth=3)           # Directory tree
list_packages()                                # All Python packages
list_modules()                                 # All modules with metrics
```

### Analyze Dependencies

```python
analyze_dependencies(module_path="app.core")   # Import analysis + circular deps
get_module_info(module_path="app.models")     # Detailed module info
```

## 🔧 Multi-Project Setup

### Configure Packages

```python
configure_packages(
    packages=["../lib", "~/repos/shared"],
    namespaces={"company": ["~/repos/company-*"]}
)
```

### Namespace Packages

```python
configure_namespace_package(
    namespace="company",
    repo_paths=["~/repos/company-auth", "~/repos/company-api"]
)
find_in_namespace("company.auth.User", namespace_repos=[...])
```

## 🎯 Framework-Specific Tools

### Pydantic (7 tools)

```python
find_models()                                  # All Pydantic models
get_model_schema("UserModel")                 # Model schema/fields
find_validators()                              # All validators
find_field_validators()                        # Field-specific validators
find_model_config()                           # Model configurations
trace_model_inheritance("BaseModel")          # Inheritance tree
find_computed_fields()                         # Properties/computed fields
```

### Flask (8 tools)

```python
find_routes()                                  # All routes/endpoints
find_blueprints()                             # Blueprint organization
find_views()                                   # View functions/classes
find_templates()                               # Template usage
find_extensions()                              # Flask extensions
find_config()                                  # Configuration
find_error_handlers()                          # Error handling
find_cli_commands()                            # CLI commands
```

### Django (5 tools)

```python
find_django_models()                           # Django models
find_django_views()                            # Views (FBV/CBV)
find_django_urls()                             # URL patterns
find_django_templates()                        # Template usage
find_django_migrations()                       # Migration history
```

## 📊 Common Workflows

### Code Review Checklist

```python
# 1. Find the symbol
symbols = find_symbol("ReviewClass")

# 2. Check its definition
definition = goto_definition(file=symbols[0]["file"], line=symbols[0]["line"], column=0)

# 3. Find all references
refs = find_references(file=symbols[0]["file"], line=symbols[0]["line"], column=0)

# 4. Analyze dependencies
deps = analyze_dependencies("app.review")

# 5. Check for circular dependencies
if deps["circular_dependencies"]:
    print("WARNING: Circular dependencies found!")
```

### API Documentation

```python
# Flask API
routes = find_routes()
api_routes = [r for r in routes if r["route"].startswith("/api")]

# Django API
urls = find_django_urls()
api_urls = [u for u in urls if u["is_api"]]

# Pydantic schemas
models = find_models()
for model in models:
    schema = get_model_schema(model["name"])
```

### Security Audit

```python
# Find unprotected routes (Flask)
routes = find_routes()
public_routes = [r for r in routes if not r["auth_required"]]

# Check configuration
configs = find_config()
secrets = [c for c in configs if c["secret_keys"]]

# Error handling coverage
handlers = find_error_handlers()
codes = [h["error_type"] for h in handlers if isinstance(h["error_type"], int)]
missing = set([400, 401, 403, 404, 500]) - set(codes)
```

### Refactoring Planning

```python
# Find complex modules
modules = list_modules()
complex = [m for m in modules if m["metrics"]["complexity"] > 15]

# Check coupling
for module in complex:
    deps = analyze_dependencies(module["module_path"])
    print(f"{module}: coupling={deps['metrics']['coupling']}")

# Find inheritance chains
hierarchy = trace_model_inheritance("BaseClass")
```

## 🚀 Performance Tips

### Batch Operations

```python
# Good: Single call for multiple projects
results = find_symbol_multi("User", project_paths=[".", "../lib", "../api"])

# Bad: Multiple individual calls
# result1 = find_symbol("User", project_path=".")
# result2 = find_symbol("User", project_path="../lib")
```

### Use Specific Tools

```python
# Good: Use specific tool
models = find_pydantic_models()

# Bad: Generic search
symbols = find_symbol("BaseModel")
models = [s for s in symbols if "pydantic" in s["file"]]
```

### Cache Configuration

```python
# Configure once at start
configure_packages(packages=["../lib"], save=True)

# Subsequent calls use cached config
symbols = find_symbol("SharedClass")  # Uses configured packages
```

## 📝 Parameter Reference

### Common Parameters

- `project_path`: Root directory (default: ".")
- `file`: File path for position-based tools
- `line`: Line number (1-indexed, like editors)
- `column`: Column number (0-indexed, like LSP)
- `fuzzy`: Enable fuzzy matching (default: false)

### Return Patterns

- **Location**: `{file, line, column}`
- **Symbol**: `{name, type, file, line, column}`
- **Module**: `{module_path, file_path, exports, classes, functions}`
- **Dependency**: `{imports, imported_by, circular_dependencies}`

## 🎨 Tool Categories Summary

| Category | Tools | Primary Use |
|----------|-------|-------------|
| **Core Navigation** | 11 | Finding and navigating code |
| **Module Analysis** | 4 | Understanding project structure |
| **Pydantic** | 7 | Model validation and schemas |
| **Flask** | 8 | Web routes and templates |
| **Django** | 5 | Django app structure |

## 🔗 Quick Links

- [Core Navigation Tools](./core-navigation.md) - Detailed navigation API
- [Module Analysis Tools](./module-analysis.md) - Project structure analysis
- [Pydantic Tools](./pydantic-tools.md) - Pydantic model analysis
- [Flask Tools](./flask-tools.md) - Flask application analysis
- [Django Tools](./django-tools.md) - Django project analysis

## 💡 Pro Tips

1. **Auto-activation**: Framework tools activate automatically when framework is detected
2. **File watching**: Changes are detected automatically - no need to restart
3. **Cross-project**: Configure multiple projects once, search across all
4. **Caching**: Results cached for 5 minutes (configurable via `PYCODEMCP_CACHE_TTL`)
5. **Performance**: Use `PYCODEMCP_MAX_WORKERS` for parallel processing

## 🚨 Common Issues

### No results found

```python
# Check configuration includes your packages
config = configure_packages()
print(config["packages"])  # Should list your packages
```

### Slow performance

```bash
# Adjust performance settings
export PYCODEMCP_MAX_PROJECTS=5      # Fewer cached projects
export PYCODEMCP_MAX_WORKERS=8       # More parallel workers
export PYCODEMCP_CACHE_TTL=600       # Longer cache (10 min)
```

### Framework tools not appearing

```python
# Framework must be imported in project
# Check if detected:
import flask  # or django, pydantic
# Tools will auto-activate
```
