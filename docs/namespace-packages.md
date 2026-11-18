# Namespace Packages and Scope Control

This guide explains how to configure and use namespace packages and scope control in the PyEye Server.

## Table of Contents

- [Overview](#overview)
- [Core Concepts](#core-concepts)
- [Configuration](#configuration)
- [Default Scopes for Plugin Tools](#default-scopes-for-plugin-tools)
- [Scope Specifications](#scope-specifications)
- [Performance Optimization](#performance-optimization)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Overview

The PyEye Server supports analyzing code spread across multiple repositories and namespace packages. This is particularly useful for:

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

Scopes control which code the plugin tools search through. A scope is one of
these forms:

<!-- fact:begin scopes.table -->
| Scope | Searches |
|---|---|
| `main` | the main project |
| `packages` | the configured packages only |
| `standalone` | the standalone script directories: those in the config's standalone.dirs, for scripts that aren't in any package |
| `namespace:<name>` | one namespace's package directories; namespace:a.b resolves under namespace a |
| `package:<path>` | that directory, if it exists: an absolute path, or one relative to the project (project\_path) |
| `all` | the main project, every configured package and namespace, and the standalone directories |
<!-- fact:end -->

You can also define custom aliases, named combinations of these forms, under
`scope_aliases`, and pass a list of scopes to search several at once.

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
      "find_pydantic_models": "namespace:company",
      "find_flask_routes": "my-services"
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

[tool.pyeye.scope_defaults]
global = "all"

[tool.pyeye.scope_defaults.methods]
find_flask_routes = "my-services"

[tool.pyeye.scope_aliases]
my-services = ["main", "namespace:company"]
```

## Default Scopes for Plugin Tools

The framework plugin tools (Pydantic, Django and Flask, e.g.
`find_pydantic_models`, `find_django_views`, `find_flask_routes`) take an
optional `scope` argument. When a call doesn't pass one, the scope comes from
<!-- fact:begin scope.default.plugin -->`scope_defaults.methods.<tool name>`, else `scope_defaults.global`, else `main`<!-- fact:end -->. The `<tool name>` is the MCP tool name, such as
`find_pydantic_models`, and the final fallback reflects that framework code
usually lives in the main project.

An explicit `scope` argument always wins, and `scope_aliases` are expanded in
both cases.

This is what makes a namespace project complete by default: an AI agent calling
`find_pydantic_models()` doesn't know the models live in `company-*` repos, but
the project config does.

```json
{
  "namespaces": { "company": ["../company-*"] },
  "scope_defaults": {
    "global": "main",
    "methods": {
      "find_pydantic_models": "namespace:company",
      "find_django_models": "all"
    }
  }
}
```

Notes:

- **Keys are tool names.** Older docs used method names such as `find_models`,
  which is ambiguous between Django and Pydantic, or `list_modules` and
  `find_subclasses`, which aren't plugin tools. Those keys never had an effect.
  pyeye now logs a warning naming any key that isn't a plugin tool.
- **Only the plugin tools use these defaults.** The core tools (`resolve`,
  `resolve_at`, `inspect`, `outline`, `expand`, `trace`) don't take a `scope`.
- **Defaults are read when the server starts.** Restart your MCP client after
  editing them.

## Scope Specifications

### Basic Scopes

```python
# Search only the main project
models = await find_pydantic_models(scope="main")

# Search everything
models = await find_django_models(scope="all")

# Search one namespace
models = await find_pydantic_models(scope="namespace:company")
```

### Combined Scopes

```python
# Search multiple scopes
routes = await find_flask_routes(scope=["main", "namespace:plugins", "packages"])
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
routes = await find_flask_routes(scope="backend")
```

## Performance Optimization

### Caching Strategy

See [Caching](architecture/caching.md) for the cache layers and their settings,
including the result TTL (`PYEYE_CACHE_TTL`).

### Performance Tips

1. **Use specific scopes when possible**

   ```python
   # Better - searches less code
   models = await find_pydantic_models(scope="namespace:company.models")

   # Slower - searches everything
   models = await find_pydantic_models(scope="all")
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
         "find_pydantic_models": "namespace:company.models"
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
      "find_pydantic_models": "all"
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
      "find_flask_routes": "production"
    }
  }
}
```

## Troubleshooting

### Debugging Scope Resolution

Call any plugin tool with `envelope=true` and read `searched` and
`unsearched_scopes` to see which configured scopes the call covered.
`rejected_paths` names any configured path the path check refused:

```python
result = await find_pydantic_models(scope="namespace:company", envelope=True)
```

See the [tools reference](reference/tools.md) for the `envelope` parameter.

### Validating Scopes

An unknown `namespace:<name>` scope logs `Namespace not found: <name>`. To see
every configured scope, call a plugin tool with `envelope=true` and read
`searched` / `unsearched_scopes`, as above.

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

**Solution**: Trace the import closure and look for a back-edge into the module
you started from:

```python
# via the MCP surface. Resolve first so the comparison below is against a
# canonical handle, not whatever string you happened to type.
start = (await resolve("mymodule"))["handle"]

# Raise max_depth or you will only see short cycles.
sub = await trace(start=start, follow=["imports"], max_depth=6)
cycles = [e for e in sub["edges"] if e["to"] == start]
```

`trace` visits each node once but still records edges back into already-visited
nodes, so an edge whose `to` is the start handle is exactly an `A -> ... -> A`
circular dependency. (Look in `edges`, not `nodes` — nodes are deduped, so the
start never literally reappears there.)

**Two limits, stated because the tool this replaced was removed for claiming
complete cycle detection it did not have:**

- **Bounded by two caps**, `max_depth` and `max_nodes` (defaults
  <!-- fact:begin tool.trace.param.max_depth -->`max_depth`: 3<!-- fact:end -->,
  <!-- fact:begin tool.trace.param.max_nodes -->`max_nodes`: 50<!-- fact:end -->). A cycle longer than the depth you pass, or one reached only after the
  node budget runs out, is simply not traversed — an empty `cycles` list means
  "no cycle within the caps", never "no cycles". Check `sub["truncated"]` and
  `sub["truncation_reasons"]` (`["max_depth"?, "max_nodes"?]`); if either fired,
  the result is a floor, not an answer.
- **Static imports only.** `importlib.import_module()`, plugin loaders and
  conditional imports are invisible, so a runtime cycle can exist with no static
  edge. Also check `sub["unresolved_imports"]` — a node listed there has an
  incomplete import set, so any cycle claim about it is unverified.

## Best Practices

1. **Start with conservative scopes** - Use `main` by default, expand as needed
2. **Define meaningful aliases** - Create aliases for common scope combinations
3. **Configure smart defaults** - Set defaults that match your workflow
4. **Use namespaces for logical grouping** - Group related packages together
5. **Monitor performance** - Check metrics regularly to optimize configuration
6. **Document your configuration** - explain the namespace structure in
   comments in `[tool.pyeye]` (pyproject.toml) or in your README; `.pyeye.json`
   is plain JSON and can't hold comments

## Migration Guide

See [migration-guide.md](migration-guide.md) for upgrading from older versions.

## API Reference

For detailed API documentation, see the [API Reference](api/README.md).
