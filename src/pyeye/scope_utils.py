"""Scope utilities for intelligent defaults and resolution."""

import asyncio
import logging
import threading
import time
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .async_utils import rglob_async
from .config import ProjectConfig
from .exceptions import ValidationError
from .metrics import metrics
from .path_utils import anchor, normalize_path
from .validation import PathValidator

logger = logging.getLogger(__name__)

# Type alias for scope specification
Scope = str | list[str]


@dataclass(frozen=True)
class ScopeForm:
    """One form of the scope grammar :func:`resolve_scope_paths` accepts (#827).

    Attributes:
        name: Short name, used in fact IDs (``scope.option.<name>``).
        syntax: How a caller writes it; a ``<...>`` part is filled in by the caller.
        meaning: What it searches, in one sentence.
    """

    name: str
    syntax: str
    meaning: str

    @property
    def prefix(self) -> str | None:
        """The literal prefix of a parameterised form (``"namespace:"``), else ``None``."""
        return self.syntax.split("<", 1)[0] if "<" in self.syntax else None


#: The scope grammar, in documentation order: the one list (#827). The docs and
#: the plugin tool descriptions take it from here, through the docs-facts
#: ``scope`` extractor. ``tests/test_docs_facts_scopes.py`` checks it against
#: :func:`resolve_scope_paths`, which implements it.
SCOPE_FORMS: tuple[ScopeForm, ...] = (
    ScopeForm("main", "main", "the main project"),
    ScopeForm("packages", "packages", "the configured packages only"),
    ScopeForm(
        "standalone",
        "standalone",
        "the standalone script directories: those in the config's standalone.dirs, "
        "for scripts that aren't in any package",
    ),
    ScopeForm(
        "namespace",
        "namespace:<name>",
        "one namespace's package directories; namespace:a.b resolves under namespace a",
    ),
    ScopeForm(
        "package",
        "package:<path>",
        "that directory, if it exists: an absolute path, or one relative to the project "
        "(project_path)",
    ),
    ScopeForm(
        "all",
        "all",
        "the main project, every configured package and namespace, and the standalone directories",
    ),
)

#: The scope a plugin tool searches when neither the call nor ``scope_defaults``
#: names one (#559): framework code usually lives in the main project.
PLUGIN_FALLBACK_SCOPE = "main"


@dataclass(frozen=True)
class ScopeLayout:
    """What a search scope can name: the one layout every scope→paths call reads (#690).

    Attributes:
        project_path: The main project.
        packages: Configured packages, excluding the main project and the
            namespace roots (``ProjectConfig.get_package_paths`` mixes both in,
            which made ``scope="packages"`` search them too, #594).
        namespace_paths: Namespace name → its repository roots.
        standalone_paths: Standalone script directories.
    """

    project_path: Path
    packages: tuple[Path, ...] = ()
    namespace_paths: Mapping[str, tuple[Path, ...]] = field(default_factory=dict)
    standalone_paths: tuple[Path, ...] = ()

    @classmethod
    def from_parts(
        cls,
        project_path: Path,
        additional_paths: Iterable[Path] = (),
        namespace_paths: Mapping[str, Iterable[Path]] | None = None,
        standalone_paths: Iterable[Path] = (),
    ) -> "ScopeLayout":
        """Normalise an owner's layout attributes into a :class:`ScopeLayout`."""
        namespaces = {
            ns: tuple(Path(p) for p in paths) for ns, paths in (namespace_paths or {}).items()
        }
        not_packages = {_resolved(project_path)} | {
            _resolved(p) for paths in namespaces.values() for p in paths
        }
        packages: list[Path] = []
        seen: set[Path] = set()
        for p in additional_paths:
            key = _resolved(Path(p))
            if key not in not_packages and key not in seen:
                seen.add(key)
                packages.append(Path(p))
        return cls(
            project_path=Path(project_path),
            packages=tuple(packages),
            namespace_paths=namespaces,
            standalone_paths=tuple(Path(p) for p in standalone_paths),
        )

    def configured_scopes(self) -> dict[str, set[Path]]:
        """Every configured scope and the paths it covers, in a stable order.

        ``main`` always; ``packages`` and ``standalone`` when configured; then one
        ``namespace:<name>`` per namespace, sorted. Each entry is exactly what
        :func:`resolve_scope_paths` returns for that scope.
        """
        names = ["main"]
        if self.packages:
            names.append("packages")
        if self.standalone_paths:
            names.append("standalone")
        names.extend(f"namespace:{ns}" for ns in sorted(self.namespace_paths))
        return {name: resolve_scope_paths(name, self, warn=False) for name in names}


def resolve_scope_paths(
    scope: "Scope", layout: ScopeLayout, *, warn: bool = True, owner: str = ""
) -> set[Path]:
    """Resolve a search scope to the directories it covers: the ONE implementation (#690).

    ``JediAnalyzer`` and every ``AnalyzerPlugin`` delegate here, so a scope
    means the same thing for every tool:

    - ``main``: the main project.
    - ``packages``: configured packages only (not main, not namespaces).
    - ``standalone``: standalone script directories.
    - ``namespace:<name>``: a namespace's package directories; a dotted
      ``namespace:a.b`` resolves under namespace ``a``.
    - ``package:<path>``: that directory, if it exists. A relative path is
      relative to ``layout.project_path``, never the server's cwd
      (:func:`package_scope_path`, #842).
    - ``all``: main + packages + every namespace + standalone.

    Args:
        scope: A scope or list of scopes, aliases already expanded.
        layout: The owner's :class:`ScopeLayout`.
        warn: Log unknown scopes and missing paths.
        owner: Prefix for warnings (e.g. ``"Plugin Pydantic: "``).

    Returns:
        The set of directories to search.
    """
    paths: set[Path] = set()
    for s in [scope] if isinstance(scope, str) else scope:
        if s == "main":
            paths.add(layout.project_path)
        elif s == "all":
            paths.add(layout.project_path)
            paths.update(layout.packages)
            # Exactly the union of every ``namespace:<name>`` scope, so ``all``
            # covers each namespace scope by construction (the #594 envelope).
            for ns in layout.namespace_paths:
                paths.update(_namespace_scope_paths(ns, layout))
            paths.update(layout.standalone_paths)
        elif s == "packages":
            paths.update(layout.packages)
        elif s == "standalone":
            paths.update(layout.standalone_paths)
        elif s.startswith("namespace:"):
            found = _namespace_scope_paths(s[len("namespace:") :], layout)
            if not found and warn:
                logger.warning(f"{owner}Namespace not found: {s[len('namespace:'):]}")
            paths.update(found)
        elif s.startswith("package:"):
            pkg_path = package_scope_path(s, layout)
            if pkg_path.exists():
                paths.add(pkg_path)
            elif warn:
                logger.warning(f"{owner}Package path does not exist: {pkg_path.as_posix()}")
        elif warn:
            logger.warning(f"{owner}Unknown scope specification: {s}")
    # Every directory a scope names is checked in its final form, whichever
    # form produced it (main, packages, namespaces, aliases, package:), so no
    # scope spelling can skip the check (#856 review). Each is a scan root, so an
    # ancestor of a restricted directory ("/") is refused too (#856 ruling).
    for path in paths:
        try:
            PathValidator.validate_scan_root(path, layout.project_path)
        except ValidationError as error:
            raise ValidationError(f"Invalid scope {scope!r}: {error}", parameter="scope") from error
    return paths


def package_scope_path(scope: str, layout: ScopeLayout) -> Path:
    """The directory a ``package:<path>`` scope names (#842).

    A relative path is anchored on ``layout.project_path`` (the project the
    caller passed), an absolute one is used as given. The one place this is
    decided, so the search and the envelope's report can't disagree.

    Raises:
        ValidationError: If the path, in that final form, lands in a restricted
            location (#856). A path that merely doesn't exist is not an error: the
            envelope lists it in ``unsearched_scopes`` (#842).
    """
    raw = scope[len("package:") :]
    try:
        PathValidator.validate_scan_root(raw, layout.project_path)
    except ValidationError as error:
        raise ValidationError(f"Invalid scope {scope!r}: {error}", parameter="scope") from error
    return anchor(raw, layout.project_path)


def _namespace_scope_paths(namespace: str, layout: ScopeLayout) -> set[Path]:
    """The directories of *namespace* (``"aac"`` or a sub-namespace ``"aac.tools"``)."""
    paths: set[Path] = set()
    for ns_path in layout.namespace_paths.get(namespace, ()):
        paths.update(namespace_directory_structure(ns_path))
    parts = namespace.split(".")
    # A sub-namespace is a dotted Python name: every part an identifier. Anything
    # else ("ns./etc") would join onto the base as a path, and an absolute part
    # replaces the base entirely (#856 review).
    if not all(part.isidentifier() for part in parts[1:]):
        raise ValidationError(
            f"Invalid scope 'namespace:{namespace}': a sub-namespace must be a dotted "
            "Python name",
            parameter="scope",
        )
    for i in range(len(parts)):
        parent_ns = ".".join(parts[: i + 1])
        sub_parts = parts[i + 1 :]
        for ns_path in layout.namespace_paths.get(parent_ns, ()):
            base_path = namespace_base_path(ns_path, parent_ns)
            if not sub_parts:
                paths.add(base_path)
            elif (base_path / Path(*sub_parts)).exists():
                paths.add(base_path / Path(*sub_parts))
    return paths


def namespace_directory_structure(ns_path: Path) -> set[Path]:
    """The package directories in a namespace repository (``repo`` → ``repo/aac``).

    The repository itself when it holds Python files, plus each non-hidden
    subdirectory that does; the repository root as a fallback.
    """
    paths: set[Path] = set()
    if (ns_path / "__init__.py").exists() or any(ns_path.glob("*.py")):
        paths.add(ns_path)
    if ns_path.is_dir():
        for subdir in ns_path.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("."):
                if (subdir / "__init__.py").exists() or any(subdir.glob("*.py")):
                    paths.add(subdir)
    return paths or {ns_path}


def namespace_base_path(ns_path: Path, namespace: str) -> Path:
    """The directory of *namespace* inside repository *ns_path* (the root if absent)."""
    ns_parts = namespace.split(".")
    potential_path = ns_path / ns_parts[0]
    if potential_path.is_dir():
        return potential_path / Path(*ns_parts[1:]) if len(ns_parts) > 1 else potential_path
    return ns_path


def _resolved(path: Path) -> Path:
    try:
        return normalize_path(path)
    except OSError:
        return Path(path)


class SmartScopeResolver:
    """Intelligent scope resolution with method-specific defaults."""

    # Method-specific smart defaults.
    #
    # Every key MUST name a real ``JediAnalyzer`` (or plugin) method — a key for
    # a method that no longer exists is dead config that reads as a live
    # capability.  ``tests/test_scope_defaults_conformance.py`` enforces this
    # for the analyzer half.
    SMART_DEFAULTS: dict[str, str] = {
        # Methods that should see everything by default
        "find_subclasses": "all",
        # Plugin tools are NOT listed here: they resolve through
        # plugin_tool_default(), keyed on the MCP tool name (#559).
        # Symbol finding defaults to all (want to find everywhere)
        "find_symbol": "all",
    }

    def __init__(self, config: ProjectConfig | None = None):
        """Initialize the smart scope resolver.

        Args:
            config: Project configuration (for user overrides)
        """
        self.config = config
        # Create instance copy of defaults to avoid modifying class-level dict
        self.smart_defaults = self.SMART_DEFAULTS.copy()
        self.global_default: Scope | None = None
        self.user_method_defaults: dict[str, Scope] = {}
        self._load_user_defaults()

    def _load_user_defaults(self) -> None:
        """Load user-configured scope defaults."""
        if not self.config:
            return

        # Load global default override
        self.global_default = self.config.config.get("scope_defaults", {}).get("global")

        # Load method-specific overrides (modify instance copy, not class dict)
        method_overrides = self.config.config.get("scope_defaults", {}).get("methods", {})
        self.user_method_defaults = dict(method_overrides)
        for method, scope in method_overrides.items():
            self.smart_defaults[method] = scope

        # Load scope aliases
        self.scope_aliases = self.config.config.get("scope_aliases", {})

    def plugin_tool_default(self, tool_name: str) -> Scope:
        """Default scope for a plugin tool called without ``scope`` (#559).

        Order: ``scope_defaults.methods.<tool_name>`` (the MCP tool name, e.g.
        ``find_pydantic_models``), then ``scope_defaults.global``, then
        ``"main"``, since framework code usually lives in the main project.
        """
        if tool_name in self.user_method_defaults:
            return self.user_method_defaults[tool_name]
        if self.global_default:
            return self.global_default
        return PLUGIN_FALLBACK_SCOPE

    def ignored_method_keys(self, tool_names: set[str]) -> list[str]:
        """Configured ``scope_defaults.methods`` keys that aren't plugin tool names.

        No 2.x tool other than the plugin tools consults these defaults, so a
        key such as ``find_models`` (an old method name, ambiguous between
        Django and Pydantic) or ``list_modules`` has no effect.
        """
        return sorted(key for key in self.user_method_defaults if key not in tool_names)

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
        if self.global_default:
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


def _warn_deprecated_class(name: str) -> None:
    """Warn that the scope utility *name* is deprecated (#628)."""
    warnings.warn(
        f"pyeye.scope_utils.{name} is deprecated: nothing in pyeye uses it (#628). "
        "It will be removed in v3.0.",
        DeprecationWarning,
        stacklevel=3,
    )


class ScopeValidator:
    """Validate and discover available scopes.

    .. deprecated:: 2.x
        Nothing in pyeye uses it (#628); it will be removed in v3.0.
    """

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
        _warn_deprecated_class("ScopeValidator")
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
    """Help users understand scope resolution.

    .. deprecated:: 2.x
        Nothing in pyeye uses it (#628); it will be removed in v3.0.
    """

    def __init__(self, resolver_func: Any) -> None:
        """Initialize the scope debugger.

        Args:
            resolver_func: Function that resolves scope to paths
        """
        _warn_deprecated_class("ScopeDebugger")
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


_MISSING = object()


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
        # Bumped by every invalidate_all (#817). One cache per analyzer, so the
        # epoch is per project: another project's invalidation never moves it.
        self._epoch = 0
        # Makes set()'s epoch check and store atomic against invalidate_all.
        self._write_lock = threading.Lock()

    def epoch(self) -> int:
        """The current invalidation epoch: take it BEFORE computing a value to set (#817)."""
        return self._epoch

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

        # Thread safety without a lock (#617): the file watcher clears this cache
        # from its own thread. Invalidation swaps in fresh dicts rather than
        # mutating them, and every read below is one atomic dict.get on a dict
        # reference taken once, so a concurrent clear can't raise KeyError.
        # This relies on single dict operations being atomic under the GIL:
        # revisit (add a lock) before running on free-threaded Python.
        entries = self.caches.get(scope_key)
        value = entries.get(key, _MISSING) if entries is not None else _MISSING
        if value is _MISSING:
            metrics.record_cache_miss()
            return None

        # Check TTL
        stamps = self.timestamps.get(scope_key)
        stamp = stamps.get(key) if stamps is not None else None
        # >= so a TTL of 0 disables caching even when set() and get() land on
        # the same clock tick (Windows' clock is coarse, ~15 ms).
        if stamp is not None and time.time() - stamp >= self.ttl:
            # Expired
            entries.pop(key, None)  # type: ignore[union-attr]
            if stamps is not None:
                stamps.pop(key, None)
            metrics.record_cache_miss()
            return None

        metrics.record_cache_hit()
        return value

    def get_recent(self, key: str, scope: Scope) -> Any | None:
        """:meth:`get`, and mark a hit most recently used, for a scope set with ``max_entries``.

        The move happens under the write lock, and only if the entry is still the
        one just read, so it can't resurrect a value ``invalidate_all`` dropped.
        """
        value = self.get(key, scope)
        if value is None:
            return None
        scope_key = self._normalize_scope(scope)
        with self._write_lock:
            entries = self.caches.get(scope_key)
            stamps = self.timestamps.get(scope_key)
            if entries is not None and entries.get(key, _MISSING) is value:
                entries[key] = entries.pop(key)
                if stamps is not None and key in stamps:
                    stamps[key] = stamps.pop(key)
        return value

    def set(
        self,
        key: str,
        value: Any,
        scope: Scope,
        *,
        epoch: int | None = None,
        max_entries: int | None = None,
    ) -> bool:
        """Set cache value for a specific scope.

        Args:
            key: Cache key
            value: Value to cache
            scope: Scope for this cache entry
            epoch: The :meth:`epoch` taken before *value* was computed. If the
                cache was invalidated since, *value* may predate the change, so
                it is not stored (#817, the #617 pattern). ``None`` always stores.
            max_entries: Bound *scope* to this many entries, evicting the least
                recently used (read through :meth:`get_recent`) first (#925).
                ``None`` leaves the scope unbounded.

        Returns:
            Whether *value* was stored.
        """
        scope_key = self._normalize_scope(scope)

        with self._write_lock:
            if epoch is not None and epoch != self._epoch:
                return False
            # setdefault, not check-then-index: get() is lock-free and may run
            # while invalidate_all swaps the dicts (#617).
            stamps = self.timestamps.setdefault(scope_key, {})
            entries = self.caches.setdefault(scope_key, {})
            # pop first, so a re-set key moves to the most recent end.
            stamps.pop(key, None)
            entries.pop(key, None)
            stamps[key] = time.time()
            entries[key] = value
            if max_entries is not None:
                while len(entries) > max_entries:
                    oldest = next(iter(entries))
                    del entries[oldest]
                    stamps.pop(oldest, None)
        return True

    def invalidate_all(self) -> None:
        """Invalidate all caches, and bump the epoch so a value computed before this isn't stored."""
        with self._write_lock:
            self._epoch += 1
            for scope_key in list(self.caches.keys()):
                self.caches[scope_key] = {}

            for scope_key in list(self.timestamps.keys()):
                self.timestamps[scope_key] = {}


class LazyNamespaceLoader:
    """Load namespace paths only when needed.

    .. deprecated:: 2.x
        Nothing in pyeye uses it (#628); it will be removed in v3.0.
    """

    def __init__(self) -> None:
        """Initialize the lazy namespace loader."""
        _warn_deprecated_class("LazyNamespaceLoader")
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
