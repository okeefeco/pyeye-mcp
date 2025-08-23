"""Scope utilities for intelligent defaults and resolution."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from .async_utils import rglob_async
from .config import ProjectConfig

logger = logging.getLogger(__name__)

# Type alias for scope specification
Scope = str | list[str]


class SmartScopeResolver:
    """Intelligent scope resolution with method-specific defaults."""

    # Method-specific smart defaults
    SMART_DEFAULTS: dict[str, str] = {
        # Methods that should see everything by default
        "find_subclasses": "all",
        "find_references": "all",
        "analyze_dependencies": "all",
        "find_imports": "all",
        "get_call_hierarchy": "all",
        # Methods that typically want main project only
        "list_modules": "main",
        "list_packages": "main",
        "list_project_structure": "main",
        "get_module_info": "main",
        # Plugin methods default to main (faster, more focused)
        "find_routes": "main",
        "find_models": "main",
        "find_views": "main",
        "find_blueprints": "main",
        "find_templates": "main",
        "find_validators": "main",
        "find_field_validators": "main",
        "find_model_config": "main",
        "find_computed_fields": "main",
        "find_extensions": "main",
        "find_config": "main",
        "find_error_handlers": "main",
        "find_cli_commands": "main",
        # Symbol finding defaults to all (want to find everywhere)
        "find_symbol": "all",
        "find_symbol_multi": "all",
        "goto_definition": "all",
        "get_type_info": "all",
        # Namespace-specific methods
        "configure_namespace_package": "all",
        "find_in_namespace": "all",
    }

    def __init__(self, config: ProjectConfig | None = None):
        """Initialize the smart scope resolver.

        Args:
            config: Project configuration (for user overrides)
        """
        self.config = config
        # Create instance copy of defaults to avoid modifying class-level dict
        self.smart_defaults = self.SMART_DEFAULTS.copy()
        self._load_user_defaults()

    def _load_user_defaults(self) -> None:
        """Load user-configured scope defaults."""
        if not self.config:
            return

        # Load global default override
        self.global_default = self.config.config.get("scope_defaults", {}).get("global")

        # Load method-specific overrides (modify instance copy, not class dict)
        method_overrides = self.config.config.get("scope_defaults", {}).get("methods", {})
        for method, scope in method_overrides.items():
            self.smart_defaults[method] = scope

        # Load scope aliases
        self.scope_aliases = self.config.config.get("scope_aliases", {})

    def get_smart_default(self, method_name: str) -> str:
        """Get intelligent default scope for a method.

        Args:
            method_name: Name of the method being called

        Returns:
            Default scope for this method
        """
        # Check method-specific default (use instance copy)
        if method_name in self.smart_defaults:
            return self.smart_defaults[method_name]

        # Fall back to global default if configured
        if hasattr(self, "global_default") and self.global_default:
            return str(self.global_default)

        # Ultimate fallback
        return "all"

    def resolve_aliases(self, scope: Scope) -> Scope:
        """Resolve scope aliases to their actual values.

        Args:
            scope: Scope specification (possibly with aliases)

        Returns:
            Resolved scope specification
        """
        if not hasattr(self, "scope_aliases"):
            return scope

        # Handle single string scope
        if isinstance(scope, str):
            if scope in self.scope_aliases:
                alias_val = self.scope_aliases[scope]
                if isinstance(alias_val, list):
                    return alias_val
                return str(alias_val)
            return scope

        # Handle list of scopes
        resolved = []
        for s in scope:
            if s in self.scope_aliases:
                alias_value = self.scope_aliases[s]
                if isinstance(alias_value, list):
                    resolved.extend(alias_value)
                else:
                    resolved.append(alias_value)
            else:
                resolved.append(s)

        return resolved


class ScopeValidator:
    """Validate and discover available scopes."""

    def __init__(
        self,
        namespace_paths: dict[str, list[Path]],
        additional_paths: list[Path],
        scope_aliases: dict[str, str | list[str]] | None = None,
    ):
        """Initialize the scope validator.

        Args:
            namespace_paths: Configured namespace packages
            additional_paths: Additional package paths
            scope_aliases: User-defined scope aliases
        """
        self.namespace_paths = namespace_paths
        self.additional_paths = additional_paths
        self.scope_aliases = scope_aliases or {}

    def list_available_scopes(self) -> dict[str, list[str]]:
        """List all available scopes for user reference.

        Returns:
            Dictionary categorizing available scopes
        """
        return {
            "predefined": ["main", "all", "packages", "namespaces"],
            "namespaces": [f"namespace:{ns}" for ns in self.namespace_paths],
            "packages": [f"package:{p}" for p in self.additional_paths],
            "aliases": list(self.scope_aliases.keys()),
        }

    def validate_scope(self, scope: Scope) -> bool:
        """Check if a scope specification is valid.

        Args:
            scope: Scope to validate

        Returns:
            True if valid, False otherwise
        """
        scopes = [scope] if isinstance(scope, str) else scope

        for s in scopes:
            if s in ["main", "all", "packages", "namespaces"]:
                continue
            elif s.startswith("namespace:"):
                ns_name = s[10:]
                if ns_name not in self.namespace_paths:
                    return False
            elif s.startswith("package:"):
                # Package paths are dynamic, harder to validate
                continue
            elif s in self.scope_aliases:
                continue
            else:
                return False

        return True

    def suggest_scope(self, partial: str) -> list[str]:
        """Suggest scopes based on partial input.

        Args:
            partial: Partial scope string

        Returns:
            List of suggested scopes
        """
        suggestions = []
        all_scopes = []

        # Collect all available scopes
        all_scopes.extend(["main", "all", "packages", "namespaces"])
        all_scopes.extend([f"namespace:{ns}" for ns in self.namespace_paths])
        all_scopes.extend(self.scope_aliases.keys())

        # Filter by partial match
        partial_lower = partial.lower()
        for scope in all_scopes:
            if scope.lower().startswith(partial_lower):
                suggestions.append(scope)

        return suggestions


class ScopeDebugger:
    """Help users understand scope resolution."""

    def __init__(self, resolver_func: Any) -> None:
        """Initialize the scope debugger.

        Args:
            resolver_func: Function that resolves scope to paths
        """
        self._resolve_scope_to_paths = resolver_func

    async def explain_scope(self, scope: Scope) -> str:
        """Explain what a scope resolves to.

        Args:
            scope: Scope to explain

        Returns:
            Human-readable explanation
        """
        paths = await self._resolve_scope_to_paths(scope)

        explanation = f"Scope: {scope}\n"
        explanation += f"Resolves to {len(paths)} paths:\n"

        for path in sorted(paths):
            explanation += f"  - {path.as_posix()}\n"

        return explanation

    async def debug_file_search(
        self,
        pattern: str,
        scope: Scope,
        search_time_ms: float | None = None,
        files_found: int | None = None,
        cache_hit: bool = False,
    ) -> dict[str, Any]:
        """Debug information for file searches.

        Args:
            pattern: Search pattern
            scope: Search scope
            search_time_ms: Time taken for search (milliseconds)
            files_found: Number of files found
            cache_hit: Whether cache was used

        Returns:
            Debug information dictionary
        """
        resolved_paths = await self._resolve_scope_to_paths(scope)

        return {
            "pattern": pattern,
            "scope": scope,
            "resolved_paths": [p.as_posix() for p in resolved_paths],
            "path_count": len(resolved_paths),
            "files_found": files_found,
            "search_time_ms": search_time_ms,
            "cache_hit": cache_hit,
        }


class ScopedCache:
    """Cache that maintains separate caches per scope."""

    def __init__(self, ttl_seconds: int = 300):
        """Initialize the scoped cache.

        Args:
            ttl_seconds: Time-to-live for cache entries
        """
        self.caches: dict[str, dict[str, Any]] = {
            "main": {},
            "all": {},
            # Dynamic caches for namespaces and other scopes
        }
        self.ttl = ttl_seconds
        self.timestamps: dict[str, dict[str, float]] = {
            "main": {},
            "all": {},
        }

    def _normalize_scope(self, scope: Scope) -> str:
        """Normalize scope to a cache key.

        Args:
            scope: Scope specification

        Returns:
            Normalized cache key
        """
        if isinstance(scope, str):
            return scope
        else:
            # Sort for consistent key
            return "|".join(sorted(scope))

    def get(self, key: str, scope: Scope) -> Any | None:
        """Get from appropriate cache based on scope.

        Args:
            key: Cache key
            scope: Scope for this cache entry

        Returns:
            Cached value or None if not found/expired
        """
        scope_key = self._normalize_scope(scope)

        # Ensure cache exists for this scope
        if scope_key not in self.caches:
            return None

        # Check if key exists
        if key not in self.caches[scope_key]:
            return None

        # Check TTL
        if scope_key in self.timestamps and key in self.timestamps[scope_key]:
            age = time.time() - self.timestamps[scope_key][key]
            if age > self.ttl:
                # Expired
                del self.caches[scope_key][key]
                del self.timestamps[scope_key][key]
                return None

        return self.caches[scope_key][key]

    def set(self, key: str, value: Any, scope: Scope) -> None:
        """Set cache value for a specific scope.

        Args:
            key: Cache key
            value: Value to cache
            scope: Scope for this cache entry
        """
        scope_key = self._normalize_scope(scope)

        # Ensure cache exists for this scope
        if scope_key not in self.caches:
            self.caches[scope_key] = {}
            self.timestamps[scope_key] = {}

        self.caches[scope_key][key] = value
        self.timestamps[scope_key][key] = time.time()

    def invalidate_scope(self, scope: Scope) -> None:
        """Invalidate just one scope's cache.

        Args:
            scope: Scope to invalidate
        """
        scope_key = self._normalize_scope(scope)

        if scope_key in self.caches:
            self.caches[scope_key] = {}

        if scope_key in self.timestamps:
            self.timestamps[scope_key] = {}

    def invalidate_all(self) -> None:
        """Invalidate all caches."""
        for scope_key in list(self.caches.keys()):
            self.caches[scope_key] = {}

        for scope_key in list(self.timestamps.keys()):
            self.timestamps[scope_key] = {}

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary of cache statistics
        """
        stats: dict[str, Any] = {
            "scope_count": len(self.caches),
            "scopes": {},
        }

        for scope_key, cache in self.caches.items():
            scope_stats: dict[str, Any] = {
                "entry_count": len(cache),
                "size_bytes": sum(len(str(v)) for v in cache.values()),
            }
            stats["scopes"][scope_key] = scope_stats

        return stats


class LazyNamespaceLoader:
    """Load namespace paths only when needed."""

    def __init__(self) -> None:
        """Initialize the lazy namespace loader."""
        self._loaded_namespaces: dict[str, list[Path]] = {}
        self._loading_locks: dict[str, asyncio.Lock] = {}

    async def get_namespace_files(
        self, namespace: str, namespace_paths: dict[str, list[Path]]
    ) -> list[Path]:
        """Load namespace files on demand.

        Args:
            namespace: Namespace to load
            namespace_paths: Configured namespace paths

        Returns:
            List of Python files in this namespace
        """
        # Check if already loaded
        if namespace in self._loaded_namespaces:
            return self._loaded_namespaces[namespace]

        # Ensure we have a lock for this namespace
        if namespace not in self._loading_locks:
            self._loading_locks[namespace] = asyncio.Lock()

        # Load with lock to prevent duplicate loading
        async with self._loading_locks[namespace]:
            # Double-check after acquiring lock
            if namespace in self._loaded_namespaces:
                return self._loaded_namespaces[namespace]

            # Load the namespace
            files = await self._load_namespace(namespace, namespace_paths)
            self._loaded_namespaces[namespace] = files
            return files

    async def _load_namespace(
        self, namespace: str, namespace_paths: dict[str, list[Path]]
    ) -> list[Path]:
        """Actually load namespace files.

        Args:
            namespace: Namespace to load
            namespace_paths: Configured namespace paths

        Returns:
            List of Python files
        """
        all_files: list[Path] = []

        if namespace not in namespace_paths:
            return all_files

        # Search all paths for this namespace
        for ns_path in namespace_paths[namespace]:
            try:
                files = await rglob_async("*.py", ns_path)
                all_files.extend(files)
            except Exception as e:
                logger.warning(
                    f"Error loading namespace {namespace} from {ns_path.as_posix()}: {e}"
                )

        return all_files

    def invalidate(self, namespace: str | None = None) -> None:
        """Invalidate cached namespace data.

        Args:
            namespace: Specific namespace to invalidate, or None for all
        """
        if namespace:
            if namespace in self._loaded_namespaces:
                del self._loaded_namespaces[namespace]
        else:
            self._loaded_namespaces.clear()


async def parallel_search(
    pattern: str, search_paths: list[Path], max_concurrent: int = 10
) -> list[Path]:
    """Search multiple paths in parallel for better performance.

    Args:
        pattern: File pattern to search for
        search_paths: Paths to search
        max_concurrent: Maximum concurrent searches

    Returns:
        List of matching files
    """
    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def search_with_limit(path: Path) -> list[Path]:
        """Search a single path with concurrency limit."""
        async with semaphore:
            try:
                return await rglob_async(pattern, path)
            except Exception as e:
                logger.warning(f"Error searching {path.as_posix()}: {e}")
                return []

    # Search all paths concurrently
    tasks = [search_with_limit(path) for path in search_paths]
    results = await asyncio.gather(*tasks)

    # Flatten results and remove duplicates
    all_files = []
    seen = set()

    for file_list in results:
        for file_path in file_list:
            if file_path not in seen:
                seen.add(file_path)
                all_files.append(file_path)

    return all_files
