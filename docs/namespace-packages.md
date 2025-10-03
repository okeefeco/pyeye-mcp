# Namespace Packages and Scope Control

This guide explains how to configure and use namespace packages and scope control in the Python Code Intelligence MCP Server.

## Table of Contents

- [Overview](#overview)
- [Core Concepts](#core-concepts)
- [Configuration](#configuration)
- [Smart Defaults](#smart-defaults)
- [Scope Specifications](#scope-specifications)
- [Performance Optimization](#performance-optimization)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Overview

The Python Code Intelligence MCP Server supports analyzing code spread across multiple repositories and namespace packages. This is particularly useful for:

- **Monorepos**: Large codebases with multiple packages
- **Microservices**: Services distributed across multiple repositories
- **Namespace Packages**: Python packages split across multiple directories/repos
- **Plugin Systems**: Extensible architectures with external plugins

## Core Concepts

### Namespace Packages

[PEP 420](https://www.python.org/dev/peps/pep-0420/) introduced implicit namespace packages, allowing Python packages to be split across multiple directories. For example:

```text
company-auth/
  └── company/
      └── auth/
          └── models.py

company-api/
  └── company/
      └── api/
          └── views.py
```

Both repositories contribute to the `company` namespace package.

### Scopes

Scopes control which code the analyzer searches through:

- **`main`**: Only the main project directory
- **`all`**: Everything (main + packages + namespaces)
- **`packages`**: Additional configured packages only
- **`namespace:name`**: Specific namespace (e.g., `namespace:company`)
- **Custom aliases**: User-defined scope combinations

## Configuration

### Basic Configuration (.pyeye.json)

```json
{
  "packages": [
    "../my-library",
    "~/repos/shared-utils"
  ],
  "namespaces": {
    "company": [
      "~/repos/company-auth",
      "~/repos/company-api",
      "~/repos/company-utils"
    ],
    "plugins": [
      "../plugin-oauth",
      "../plugin-analytics"
    ]
  }
}
```

### Advanced Configuration with Scope Control

```json
{
  "namespaces": {
    "company": ["../company-*"]
  },
  "scope_defaults": {
    "global": "all",
    "methods": {
      "list_modules": "main",
      "find_models": "namespace:company",
      "find_subclasses": "all"
    }
  },
  "scope_aliases": {
    "my-services": ["main", "namespace:company"],
    "external": ["namespace:third-party", "packages"],
    "testing": ["main", "namespace:company.tests"]
  }
}
```

### Configuration in pyproject.toml

```toml
[tool.pyeye]
packages = ["../shared-lib"]

[tool.pyeye.namespaces]
company = ["~/repos/company-*"]

[tool.pycodemcp.scope_defaults]
global = "all"

[tool.pycodemcp.scope_defaults.methods]
list_modules = "main"
find_routes = "my-services"

[tool.pycodemcp.scope_aliases]
my-services = ["main", "namespace:company"]
```

## Smart Defaults

The server uses intelligent defaults based on the method being called:

### Methods that search everywhere by default

These methods need to find references across all code:

- `find_subclasses` - Find all implementations
- `find_references` - Find all usages
- `analyze_dependencies` - Understand full dependency graph
- `find_imports` - Track module usage
- `get_call_hierarchy` - Trace execution paths

### Methods that search main project by default

These methods typically focus on the current project:

- `list_modules` - Project structure
- `list_packages` - Package organization
- `get_module_info` - Module details
- Framework-specific methods (`find_routes`, `find_models`, etc.)

### Overriding Defaults

You can override defaults globally or per-method:

```json
{
  "scope_defaults": {
    "global": "my-services",
    "methods": {
      "list_modules": "all",
      "find_models": "namespace:company.models"
    }
  }
}
```

## Scope Specifications

### Basic Scopes

```python
# Search only main project
symbols = await analyzer.find_symbol("MyClass", scope="main")

# Search everything
refs = await analyzer.find_references(file, line, col, scope="all")

# Search specific namespace
models = await analyzer.find_models(scope="namespace:company")
```

### Combined Scopes

```python
# Search multiple scopes
results = await analyzer.find_subclasses(
    "BasePlugin",
    scope=["main", "namespace:plugins", "packages"]
)
```

### Using Aliases

```json
{
  "scope_aliases": {
    "backend": ["namespace:api", "namespace:auth", "namespace:db"],
    "frontend": ["namespace:ui", "namespace:components"]
  }
}
```

```python
# Use the alias
routes = await analyzer.find_routes(scope="backend")
```

## Performance Optimization

### Caching Strategy

The server implements multiple caching layers:

1. **Scoped Cache**: Separate caches per scope
2. **Result Cache**: 5-minute TTL for analysis results
3. **File Watch Cache**: Automatic invalidation on file changes

### Lazy Loading

Namespace packages are loaded on-demand:

```python
# Only loads the auth namespace when needed
auth_models = await analyzer.find_models(scope="namespace:company.auth")
```

### Parallel Search

The server searches multiple paths concurrently:

```python
# Searches all namespace paths in parallel
results = await analyzer.find_symbol("User", scope="all")
```

### Performance Tips

1. **Use specific scopes when possible**

   ```python
   # Better - searches less code
   models = await find_models(scope="namespace:company.models")

   # Slower - searches everything
   models = await find_models(scope="all")
   ```

2. **Leverage scope aliases for common patterns**

   ```json
   {
     "scope_aliases": {
       "models": ["namespace:company.models", "namespace:shared.models"]
     }
   }
   ```

3. **Configure smart defaults for your workflow**

   ```json
   {
     "scope_defaults": {
       "methods": {
         "find_models": "namespace:company.models"
       }
     }
   }
   ```

## Examples

### Monorepo Configuration

```json
{
  "packages": [
    "./packages/*"
  ],
  "scope_defaults": {
    "global": "all"
  }
}
```

### Microservices Configuration

```json
{
  "namespaces": {
    "services": [
      "../auth-service",
      "../api-service",
      "../worker-service"
    ]
  },
  "scope_aliases": {
    "api-layer": ["namespace:services.api", "namespace:services.auth"],
    "workers": ["namespace:services.worker"]
  }
}
```

### Plugin System Configuration

```json
{
  "namespaces": {
    "core": ["./"],
    "plugins": ["../plugins/*"]
  },
  "scope_defaults": {
    "methods": {
      "find_subclasses": "all",
      "list_modules": "main"
    }
  }
}
```

### Enterprise Configuration

```json
{
  "namespaces": {
    "company": ["~/repos/company-*"],
    "vendor": ["~/repos/vendor-*"],
    "internal": ["~/repos/internal-*"]
  },
  "scope_aliases": {
    "first-party": ["main", "namespace:company", "namespace:internal"],
    "third-party": ["namespace:vendor", "packages"],
    "production": ["namespace:company", "namespace:internal"]
  },
  "scope_defaults": {
    "global": "first-party",
    "methods": {
      "find_references": "all",
      "analyze_dependencies": "production"
    }
  }
}
```

## Troubleshooting

### Debugging Scope Resolution

Use the debug tools to understand scope resolution:

```python
from pyeye.scope_utils import ScopeDebugger

debugger = ScopeDebugger(analyzer._resolve_scope_to_paths)

# See what a scope resolves to
explanation = await debugger.explain_scope("namespace:company")
print(explanation)

# Debug a search
debug_info = await debugger.debug_file_search(
    "*.py",
    scope="my-services",
    search_time_ms=150,
    files_found=42
)
```

### Validating Scopes

```python
from pyeye.scope_utils import ScopeValidator

validator = ScopeValidator(namespace_paths, additional_paths, scope_aliases)

# List available scopes
available = validator.list_available_scopes()
print(available)

# Validate a scope
if not validator.validate_scope("namespace:unknown"):
    print("Invalid scope!")

# Get suggestions
suggestions = validator.suggest_scope("name")  # Returns ["namespace:..."]
```

### Common Issues

#### 1. Namespace not found

**Problem**: `namespace:company` returns no results

**Solution**: Check namespace configuration:

```bash
cat .pyeye.json | jq '.namespaces'
```

Ensure paths exist and contain Python files.

#### 2. Slow searches

**Problem**: Searches taking too long

**Solutions**:

- Use more specific scopes
- Configure smart defaults
- Enable parallel search (automatic in v0.2+)
- Check cache configuration

#### 3. Missing dependencies

**Problem**: Can't find imported modules

**Solution**: Add dependency paths:

```json
{
  "packages": [
    "~/.venv/lib/python3.11/site-packages"
  ]
}
```

#### 4. Circular dependencies

**Problem**: Circular import detected

**Solution**: Use `analyze_dependencies` to identify cycles:

```python
deps = await analyzer.analyze_dependencies("mymodule", scope="all")
print(deps["circular_dependencies"])
```

### Performance Monitoring

Monitor performance using the built-in metrics:

```python
metrics = await get_performance_metrics()

# Check cache hit rates
cache_stats = metrics["cache_hit_rate"]

# Check search times
search_times = metrics["find_symbol"]["avg_time_ms"]
```

## Best Practices

1. **Start with conservative scopes** - Use `main` by default, expand as needed
2. **Define meaningful aliases** - Create aliases for common scope combinations
3. **Configure smart defaults** - Set defaults that match your workflow
4. **Use namespaces for logical grouping** - Group related packages together
5. **Monitor performance** - Check metrics regularly to optimize configuration
6. **Document your configuration** - Add comments explaining namespace structure

## Migration Guide

See [migration-guide.md](migration-guide.md) for upgrading from older versions.

## API Reference

For detailed API documentation, see the [API Reference](api/README.md).
