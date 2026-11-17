# Migration Guide

This is a historical guide: it covers the upgrade from 0.1.x to 0.2.0. Some APIs it shows were later changed or removed, so for the current tools and configuration see the [README](../README.md) and [namespace-packages.md](namespace-packages.md).

## Table of Contents

- [Version 0.2.0 Migration](#version-020-migration)
- [Breaking Changes](#breaking-changes)
- [New Features](#new-features)
- [Configuration Changes](#configuration-changes)
- [API Changes](#api-changes)

## Version 0.2.0 Migration

### From 0.1.x to 0.2.0

Version 0.2.0 introduces smart defaults, scope aliases, and performance optimizations.

#### What's New

1. **Smart Defaults**: Methods now have intelligent default scopes
2. **Scope Aliases**: Define custom scope combinations
3. **Scoped Caching**: Separate caches per scope
4. **Parallel Search**: Concurrent path searching
5. **Lazy Loading**: On-demand namespace loading (no longer used; the class is deprecated, see #628)

#### Migration Steps

1. **Review your current configuration**

   Check your existing `.pyeye.json`:

   ```bash
   cat .pyeye.json
   ```

2. **Update configuration format** (optional)

   Old format still works, but you can now add:

   ```json
   {
     "scope_defaults": {
       "global": "all",
       "methods": {
         "find_pydantic_models": "main"
       }
     },
     "scope_aliases": {
       "my-project": ["main", "namespace:company"]
     }
   }
   ```

3. **Update method calls** (optional)

   Methods now accept `None` for scope to use smart defaults:

   ```python
   # Old - explicit scope required
   results = await analyzer.find_subclasses("Base", scope="all")

   # New - uses smart default ("all" for find_subclasses)
   results = await analyzer.find_subclasses("Base")
   ```

4. **Test your configuration**

   Validate scopes work as expected:

   > **Deprecated:** `ScopeValidator` is unused by pyeye and will be removed in v3.0 (#628);
   > constructing it emits a `DeprecationWarning`.

   ```python
   from pyeye.scope_utils import ScopeValidator

   validator = ScopeValidator(namespace_paths, additional_paths, scope_aliases)
   available = validator.list_available_scopes()
   print(available)
   ```

## Breaking Changes

### Version 0.2.0

1. **Scope defaults**: before 0.2.0, each method had a fixed default scope. From 0.2.0, an omitted scope resolves through the smart defaults and any `scope_defaults` you configure. **Impact**: minimal, because existing calls keep working.

2. **Cache invalidation**

   - **Before**: Single global cache
   - **After**: Scoped caches

## New Features

### Smart Defaults

In 0.2.0, methods gained a default scope suited to their purpose; the current per-tool defaults are in [Default Scopes for Plugin Tools](namespace-packages.md#default-scopes-for-plugin-tools).

Override the default for framework plugin tools in configuration. Keys are MCP
tool names (see [Default Scopes for Plugin Tools](namespace-packages.md#default-scopes-for-plugin-tools)):

```json
{
  "scope_defaults": {
    "methods": {
      "find_flask_routes": "namespace:api"
    }
  }
}
```

### Scope Aliases

Define reusable scope combinations:

```json
{
  "scope_aliases": {
    "backend": ["namespace:api", "namespace:db"],
    "frontend": ["namespace:ui", "namespace:components"]
  }
}
```

Use the alias as the scope of a plugin tool call, e.g. `find_flask_routes(scope="backend")`.

### Performance Features

1. **Parallel Search**: Automatically searches multiple paths concurrently
2. **Scoped Caching**: Separate caches prevent unnecessary invalidation
3. **Lazy Loading**: Namespaces loaded only when needed (no longer used; the class is deprecated, see #628)

## Configuration Changes

### Before (0.1.x)

```json
{
  "packages": ["../lib"],
  "namespaces": {
    "company": ["../company-api", "../company-auth"]
  }
}
```

### After (0.2.0)

```json
{
  "packages": ["../lib"],
  "namespaces": {
    "company": ["../company-api", "../company-auth"]
  },
  "scope_defaults": {
    "global": "all",
    "methods": {
      "find_pydantic_models": "namespace:company"
    }
  },
  "scope_aliases": {
    "services": ["namespace:company.api", "namespace:company.auth"],
    "libraries": ["packages", "namespace:company.lib"]
  }
}
```

### Environment Variables

- `PYEYE_CACHE_TTL`: Seconds a cached scope file list or lookup result lives (default: 300)

Default scopes for the framework plugin tools are set in the config file
(`scope_defaults`), not through the environment. The full list of environment variables is in the README's
[Performance Settings](../README.md#performance-settings).

## API Changes

### Analyzer Methods

In 0.2.0, the scope-taking analyzer methods let you omit `scope`, which then resolves through the smart defaults.

### New Utilities

```python
from pyeye.scope_utils import (
    SmartScopeResolver,    # Smart defaults
    ScopeValidator,        # Validate scopes (deprecated, removed in v3.0)
    ScopeDebugger,        # Debug scope resolution (deprecated, removed in v3.0)
    ScopedCache,          # Scoped caching
    LazyNamespaceLoader,  # Lazy loading (deprecated, removed in v3.0)
    parallel_search       # Parallel file search
)
```

## Troubleshooting Migration

### Issue: Methods returning different results

**Cause**: Smart defaults may search different scopes than before

**Solution**: Explicitly specify scope or configure defaults:

```json
{
  "scope_defaults": {
    "global": "all"
  }
}
```

### Issue: Cache not working as expected

**Cause**: Scoped caching separates caches

**Solution**: Ensure consistent scope usage:

```python
# Always use same scope for related operations
scope = "namespace:company"
symbols = await analyzer.find_symbol("User", scope=scope)
subclasses = await analyzer.find_subclasses("User", scope=scope)
```

### Issue: Performance regression

**Cause**: Searching too broad a scope

**Solution**: Use specific scopes and aliases:

```python
# Instead of
results = await find_pydantic_models(scope="all")

# Use
results = await find_pydantic_models(scope="namespace:company.models")
```

## Rollback Procedure

If you need to rollback to 0.1.x:

1. **Restore previous version**:

   ```bash
   pip install "pyeye-mcp<0.2"
   ```

2. **Remove new configuration keys**:
   - Remove `scope_defaults`
   - Remove `scope_aliases`

3. **Update code to use explicit scopes**:

   ```python
   # Add explicit scope to all calls
   results = await analyzer.find_subclasses("Base", scope="all")
   ```

## Getting Help

- **Documentation**: See [namespace-packages.md](namespace-packages.md)
- **Examples**: Check `examples/configurations/`
- **Issues**: Report at [GitHub Issues](https://github.com/okeefeco/pyeye-mcp/issues)
