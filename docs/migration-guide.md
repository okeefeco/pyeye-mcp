# Migration Guide

This guide helps you upgrade to the latest version of Python Code Intelligence MCP Server with enhanced namespace and scope support.

## Table of Contents

- [Version 0.2.0 Migration](#version-020-migration)
- [Breaking Changes](#breaking-changes)
- [New Features](#new-features)
- [Configuration Changes](#configuration-changes)
- [API Changes](#api-changes)
- [Performance Improvements](#performance-improvements)

## Version 0.2.0 Migration

### From 0.1.x to 0.2.0

Version 0.2.0 introduces smart defaults, scope aliases, and performance optimizations.

#### What's New

1. **Smart Defaults**: Methods now have intelligent default scopes
2. **Scope Aliases**: Define custom scope combinations
3. **Scoped Caching**: Separate caches per scope
4. **Parallel Search**: Concurrent path searching
5. **Lazy Loading**: On-demand namespace loading

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
         "list_modules": "main"
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

   ```python
   from pyeye.scope_utils import ScopeValidator

   validator = ScopeValidator(namespace_paths, additional_paths, scope_aliases)
   available = validator.list_available_scopes()
   print(available)
   ```

## Breaking Changes

### Version 0.2.0

1. **Scope parameter type change**

   - **Before**: `scope: str | list[str]` (required)
   - **After**: `scope: Optional[str | list[str]]` (optional, uses smart defaults)

   **Impact**: Minimal - existing code continues to work

2. **Cache invalidation**

   - **Before**: Single global cache
   - **After**: Scoped caches

   **Impact**: Cache invalidation now per-scope:

   ```python
   # Old
   cache.invalidate_all()

   # New
   scoped_cache.invalidate_scope("main")
   scoped_cache.invalidate_all()  # Still available
   ```

## New Features

### Smart Defaults

Methods now have intelligent defaults based on their purpose:

```python
# These search everywhere by default
await analyzer.find_references(...)  # scope="all"
await analyzer.find_subclasses(...)  # scope="all"

# These search main project by default
await analyzer.list_modules(...)     # scope="main"
await analyzer.find_routes(...)      # scope="main"
```

Override defaults in configuration:

```json
{
  "scope_defaults": {
    "methods": {
      "list_modules": "all",
      "find_routes": "namespace:api"
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

Use in code:

```python
routes = await analyzer.find_routes(scope="backend")
```

### Performance Features

1. **Parallel Search**: Automatically searches multiple paths concurrently
2. **Scoped Caching**: Separate caches prevent unnecessary invalidation
3. **Lazy Loading**: Namespaces loaded only when needed

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
      "list_modules": "main",
      "find_models": "namespace:company"
    }
  },
  "scope_aliases": {
    "services": ["namespace:company.api", "namespace:company.auth"],
    "libraries": ["packages", "namespace:company.lib"]
  }
}
```

### Environment Variables

New environment variables supported:

- `PYEYE_DEFAULT_SCOPE`: Global default scope
- `PYEYE_CACHE_TTL`: Cache TTL in seconds (default: 300)
- `PYEYE_MAX_CONCURRENT`: Max concurrent searches (default: 10)

## API Changes

### Analyzer Methods

All analyzer methods now support optional scope:

```python
# Before (required scope)
async def find_subclasses(base_class: str, scope: Scope) -> list[dict]

# After (optional scope with smart default)
async def find_subclasses(
    base_class: str,
    scope: Optional[Scope] = None
) -> list[dict]
```

### New Utilities

```python
from pyeye.scope_utils import (
    SmartScopeResolver,    # Smart defaults
    ScopeValidator,        # Validate scopes
    ScopeDebugger,        # Debug scope resolution
    ScopedCache,          # Scoped caching
    LazyNamespaceLoader,  # Lazy loading
    parallel_search       # Parallel file search
)
```

## Performance Improvements

### Benchmarks

Typical improvements in 0.2.0:

| Operation | v0.1.x | v0.2.0 | Improvement |
|-----------|--------|--------|-------------|
| find_symbol (cold) | 500ms | 200ms | 2.5x faster |
| find_symbol (cached) | 50ms | 5ms | 10x faster |
| find_subclasses | 2000ms | 800ms | 2.5x faster |
| Large namespace search | 5000ms | 2000ms | 2.5x faster |

### Memory Usage

- **Lazy loading**: 50% reduction in memory for large namespace configurations
- **Scoped caching**: Better cache utilization, less memory churn

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
symbols = await find_symbol("User", scope=scope)
refs = await find_references(..., scope=scope)
```

### Issue: Performance regression

**Cause**: Searching too broad a scope

**Solution**: Use specific scopes and aliases:

```python
# Instead of
results = await find_models(scope="all")

# Use
results = await find_models(scope="namespace:company.models")
```

## Rollback Procedure

If you need to rollback to 0.1.x:

1. **Restore previous version**:

   ```bash
   pip install pyeye-mcp==0.1.x
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

## Future Deprecations

The following may be deprecated in future versions:

1. **String-only scopes**: Use lists for multiple scopes instead of "all"
2. **Global scope "all"**: Use specific aliases instead
3. **Synchronous configuration loading**: Will become async-only

Plan accordingly to future-proof your configuration.
