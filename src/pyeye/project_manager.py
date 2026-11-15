"""Multi-project management for PyEye."""

import contextlib
import logging
import threading
from pathlib import Path

import jedi

from . import settings
from .analyzers.jedi_analyzer import JediAnalyzer
from .cache import CodebaseWatcher, GranularCache
from .connection_pool import ProjectConnectionPool
from .namespace_resolver import NamespaceResolver

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages multiple Python projects simultaneously."""

    def __init__(self, max_projects: int | None = None):
        """Initialize the project manager.

        Args:
            max_projects: Maximum number of projects to keep in memory.
                         If None, uses value from settings.
        """
        self.projects: dict[Path, jedi.Project] = {}
        # One watcher per resolved root, shared by every project whose layout
        # includes that root; ``_watch_users`` records who uses each (#617).
        self.watchers: dict[Path, CodebaseWatcher] = {}
        self._watch_users: dict[Path, set[Path]] = {}
        # Guards watchers/_watch_users: the watchdog thread reads them while
        # analysis threads register and drop projects.
        self._watch_lock = threading.RLock()
        self.caches: dict[Path, GranularCache] = {}
        self.analyzers: dict[Path, JediAnalyzer] = {}  # Analyzer instance cache
        self.access_order: list[Path] = []  # LRU tracking
        self.max_projects = (
            max_projects if max_projects is not None else settings.settings.max_projects
        )

        # Project dependencies - maps project to its dependencies
        self.dependencies: dict[Path, set[Path]] = {}

        # Standalone script directories - maps project to its standalone dirs
        self.standalone_dirs: dict[Path, set[Path]] = {}

        # Namespace resolver for distributed packages
        self.namespace_resolver = NamespaceResolver()

        # Initialize connection pool if enabled
        self.connection_pool: ProjectConnectionPool | None = None
        if settings.settings.enable_connection_pooling:
            self.connection_pool = ProjectConnectionPool(
                max_connections=settings.settings.pool_max_connections,
                ttl_seconds=settings.settings.pool_ttl,
            )
            logger.info("Connection pooling enabled")

    def get_project(
        self, project_path: str, include_paths: list[str] | None = None
    ) -> jedi.Project:
        """Get or create a Jedi project.

        Args:
            project_path: Main project path
            include_paths: Additional paths to include (e.g., local packages)

        Returns:
            Jedi project configured with all paths
        """
        main_path = Path(project_path).resolve()

        # Track access for LRU
        if main_path in self.access_order:
            self.access_order.remove(main_path)
        self.access_order.append(main_path)

        # Use connection pool if available
        if self.connection_pool:
            # Convert include_paths to resolved Path objects
            additional_paths = []
            if include_paths:
                for path in include_paths:
                    resolved = Path(path).resolve()
                    if resolved.exists() and resolved.is_dir():
                        additional_paths.append(resolved)

            # Get pooled connection
            project = self.connection_pool.get_connection(main_path, additional_paths)

            # Store in projects dict for backward compatibility
            self.projects[main_path] = project

            # Update dependencies tracking for compatibility
            self.dependencies[main_path] = set(additional_paths)

            # Ensure cache exists
            if main_path not in self.caches:
                self.caches[main_path] = GranularCache(ttl_seconds=settings.settings.cache_ttl)

            self._watch(main_path, main_path)
            for dep_path in additional_paths:
                self._watch(dep_path, main_path)

            # Don't apply LRU eviction when using connection pool
            # Pool handles its own eviction
            return project

        # Fall back to original implementation if pooling is disabled
        if main_path not in self.projects or self._needs_update(main_path, include_paths):
            self._create_project(main_path, include_paths)

        # Only evict old projects if connection pooling is disabled
        # When pooling is enabled, the pool manages its own eviction
        if not self.connection_pool:
            self._evict_if_needed()

        return self.projects[main_path]

    def _needs_update(self, main_path: Path, include_paths: list[str] | None = None) -> bool:
        """Check if project configuration has changed."""
        if main_path not in self.dependencies:
            return True

        current_deps = self.dependencies[main_path]
        new_deps = {Path(p).resolve() for p in (include_paths or [])}

        return current_deps != new_deps

    def _create_project(self, main_path: Path, include_paths: list[str] | None = None) -> None:
        """Create a new project with watchers and cache."""
        logger.info(f"Creating project for {main_path.as_posix()}")

        # Clean up old project if exists
        if main_path in self.projects:
            self._cleanup_project(main_path)

        # Configure project paths
        all_paths = [main_path]
        dep_paths = set()

        if include_paths:
            for path in include_paths:
                resolved = Path(path).resolve()
                if resolved.exists() and resolved.is_dir():
                    all_paths.append(resolved)
                    dep_paths.add(resolved)
                    logger.info(f"  Including dependency: {resolved}")

        # Create Jedi project with all paths
        # Jedi's added_sys_path allows searching in multiple locations
        self.projects[main_path] = jedi.Project(path=main_path, added_sys_path=all_paths)

        # Store dependencies
        self.dependencies[main_path] = dep_paths

        # Create granular cache with configurable TTL
        self.caches[main_path] = GranularCache(ttl_seconds=settings.settings.cache_ttl)

        self._watch(main_path, main_path)
        for dep_path in dep_paths:
            self._watch(dep_path, main_path)

    def _cleanup_project(self, project_path: Path) -> None:
        """Clean up a project's resources."""
        logger.info(f"Cleaning up project {project_path.as_posix()}")

        # Stop the watchers no other project still uses
        self._unwatch_project(project_path)

        # Clear cache
        if project_path in self.caches:
            del self.caches[project_path]

        # Drop cached analyzer
        self.analyzers.pop(project_path, None)

        # Remove project
        if project_path in self.projects:
            del self.projects[project_path]

        # Clear dependencies
        if project_path in self.dependencies:
            del self.dependencies[project_path]

        # Clear standalone directories
        if project_path in self.standalone_dirs:
            del self.standalone_dirs[project_path]

        # Drop the project's non-evicting name index so an evicted project does
        # not leak its index. The store canonicalises the key (project_graph.
        # _normalize), so this resolved path matches the analyzer's build key
        # even for a symlinked/relative root. #457.
        from pyeye.analyzers import project_graph

        project_graph.invalidate(project_path.as_posix())

    def _evict_if_needed(self) -> None:
        """Evict least recently used projects if over limit.

        Checks both ``self.projects`` and ``self.analyzers`` so that the
        analyzer-only path (``get_analyzer`` called without a prior
        ``get_project``) is also bounded by ``max_projects``.
        """
        while max(len(self.projects), len(self.analyzers)) > self.max_projects:
            # Remove least recently used
            lru_path = self.access_order.pop(0)
            logger.info(f"Evicting LRU project: {lru_path.as_posix()}")
            self._cleanup_project(lru_path)

    def get_cache(self, project_path: str) -> GranularCache:
        """Get cache for a project."""
        main_path = Path(project_path).resolve()
        if main_path not in self.caches:
            self.caches[main_path] = GranularCache()
        return self.caches[main_path]

    def search_all_projects(self, name: str) -> dict[str, list]:
        """Search for a symbol across all active projects.

        Args:
            name: Symbol name to search for

        Returns:
            Dictionary mapping project paths to results
        """
        results = {}

        for project_path, project in self.projects.items():
            try:
                search_results = project.search(name, all_scopes=True)
                if search_results:
                    results[project_path.as_posix()] = [
                        {
                            "name": r.name,
                            "file": Path(r.module_path).as_posix() if r.module_path else None,
                            "line": r.line,
                            "type": r.type,
                        }
                        for r in search_results
                    ]
            except Exception as e:
                logger.error(f"Error searching in {project_path.as_posix()}: {e}")

        return results

    def get_analyzer(self, project_path: str) -> JediAnalyzer:
        """Get a configured JediAnalyzer for the given project.

        Analyzers are cached by resolved project path.  Repeated calls with the
        same path return the **same** ``JediAnalyzer`` instance, preserving its
        ``scoped_cache`` and Jedi's internal inference state across lookups.

        Cache invalidation contract
        ---------------------------
        When configuration changes after an analyzer has been constructed (for
        example, a new package path is added via ``configure_packages`` or a new
        namespace is registered), the caller must call
        ``invalidate_analyzer(project_path)`` to evict the stale entry.  The
        next ``get_analyzer`` call will then rebuild a fresh, fully-configured
        analyzer.

        LRU eviction
        ------------
        Both the analyzer cache and the project cache are limited to
        ``max_projects`` entries combined.  When
        ``max(len(analyzers), len(projects)) > max_projects``, the
        least-recently-used entry is evicted via ``_cleanup_project``, which
        tears down watchers and project state in addition to dropping the
        analyzer.

        This method creates a JediAnalyzer and configures it with:
        - Additional package paths from dependencies
        - Namespace package mappings
        - Standalone script directories

        Args:
            project_path: Path to the project to analyze

        Returns:
            Configured JediAnalyzer instance (cached on repeated calls with
            the same resolved path until explicitly invalidated or evicted).
        """
        # Import here to avoid circular imports
        from .config import ProjectConfig

        path_key = Path(project_path).resolve()

        # --- Cache hit: return the existing analyzer ---
        if path_key in self.analyzers:
            # Update LRU order so this project stays "recently used"
            if path_key in self.access_order:
                self.access_order.remove(path_key)
            self.access_order.append(path_key)
            logger.debug(f"Analyzer cache hit for {path_key.as_posix()}")
            return self.analyzers[path_key]

        # --- Cache miss: construct and store ---
        # Build from the resolved path, not the caller's raw string: the cache is
        # keyed on ``path_key``, so whichever spelling arrives first would
        # otherwise fix the root (and every location.file) for the process (#603).
        resolved_project_path = path_key.as_posix()
        config = ProjectConfig(resolved_project_path)

        # Resolve namespace paths from config file AND namespace_resolver.
        # These must be computed BEFORE creating the analyzer so the Jedi
        # project is created with namespace repo roots in added_sys_path —
        # ensuring full_name values include the namespace prefix from the
        # very first query.
        namespace_config: dict[str, list[str]] = {}
        config_namespaces = config.get_namespaces()
        for ns, paths in config_namespaces.items():
            resolved_paths = []
            for p in paths:
                resolved = Path(p)
                if not resolved.is_absolute():
                    resolved = path_key / resolved
                resolved_paths.append(str(resolved))
            namespace_config[ns] = resolved_paths
            # Also register with namespace_resolver for scope-based file searching
            self.namespace_resolver.register_namespace(ns, resolved_paths)
            logger.info(f"Bridged namespace '{ns}' from config to namespace resolver")
        # Include namespaces from prior configure_packages calls
        for ns_key, ns_path_list in self.namespace_resolver.namespace_paths.items():
            if ns_key not in namespace_config:
                namespace_config[ns_key] = [str(p) for p in ns_path_list]

        analyzer = JediAnalyzer(
            resolved_project_path, config=config, namespace_config=namespace_config or None
        )

        # Bridge: apply package paths from config file to dependencies.
        # Only apply when packages were explicitly configured (not auto-discovered)
        # to avoid spuriously picking up unrelated sibling directories.
        if config.has_explicit_config:
            config_package_paths = config.get_package_paths()
            # get_package_paths() always prepends the project itself; skip the first entry
            extra_paths = [p for p in config_package_paths if Path(p).resolve() != path_key]
            if extra_paths:
                self.get_project(path_key.as_posix(), extra_paths)
                logger.info(
                    f"Bridged {len(extra_paths)} extra package paths from config to dependencies"
                )

        # Set additional paths if this project has dependencies configured
        if path_key in self.dependencies:
            analyzer.set_additional_paths(list(self.dependencies[path_key]))
            logger.info(
                f"Configured analyzer with {len(self.dependencies[path_key])} additional paths"
            )

        # Namespace paths were already applied via namespace_config at init time.
        # No need to call set_namespace_paths — the Jedi project was created
        # with namespace repo roots in added_sys_path atomically.

        # Configure standalone directories from project config
        standalone_config = config.get_standalone_config()
        standalone_dirs = standalone_config.get("dirs", [])
        if standalone_dirs:
            # Resolve standalone directory paths
            standalone_paths = []
            for dir_path in standalone_dirs:
                resolved_path = Path(dir_path)
                if not resolved_path.is_absolute():
                    resolved_path = path_key / resolved_path
                if resolved_path.exists():
                    standalone_paths.append(resolved_path)
                else:
                    logger.warning(
                        f"Standalone directory does not exist: {resolved_path.as_posix()}"
                    )

            if standalone_paths:
                analyzer.set_standalone_paths(standalone_paths)
                self.standalone_dirs[path_key] = set(standalone_paths)
                logger.info(
                    f"Configured analyzer with {len(standalone_paths)} standalone directories"
                )

        # Every analyzer is watched, config or not (#617): its root plus every
        # package, namespace and standalone root its layout reads from.
        if path_key not in self.caches:
            self.caches[path_key] = GranularCache(ttl_seconds=settings.settings.cache_ttl)
        for root in self._layout_roots(analyzer):
            self._watch(root, path_key)

        # Store in cache and update LRU
        self.analyzers[path_key] = analyzer
        if path_key in self.access_order:
            self.access_order.remove(path_key)
        self.access_order.append(path_key)

        # Evict if over the project limit
        self._evict_if_needed()

        return analyzer

    def invalidate_analyzer(self, project_path: str) -> None:
        """Evict the cached JediAnalyzer for *project_path* without tearing down the project.

        Call this whenever analyzer-relevant configuration changes after an
        analyzer has already been constructed — for example after
        ``configure_packages`` adds new package paths or registers a new
        namespace.  The next call to ``get_analyzer`` will rebuild a fresh
        analyzer with the updated configuration.

        Unlike ``_cleanup_project``, this method only removes the analyzer
        entry; it does **not** stop watchers, clear the GranularCache, or
        remove the ``jedi.Project`` from ``self.projects``.

        Args:
            project_path: Path to the project whose analyzer should be evicted.
        """
        path_key = Path(project_path).resolve()
        if self.analyzers.pop(path_key, None) is not None:
            logger.info(f"Invalidated cached analyzer for {path_key.as_posix()}")
        # Keep access_order consistent so _evict_if_needed never tries to pop
        # a path that is no longer in self.analyzers.
        with contextlib.suppress(ValueError):
            self.access_order.remove(path_key)

    @staticmethod
    def _layout_roots(analyzer: JediAnalyzer) -> list[Path]:
        """Every directory *analyzer* reads code from, resolved and existing."""
        roots = [analyzer.project_path, *analyzer.additional_paths, *analyzer.standalone_paths]
        for ns_paths in analyzer.namespace_paths.values():
            roots.extend(ns_paths)
        seen: dict[Path, None] = {}
        for root in roots:
            resolved = Path(root).resolve()
            if resolved.is_dir():
                seen.setdefault(resolved, None)
        return list(seen)

    def _watch(self, root: Path, project: Path) -> None:
        """Watch *root* on behalf of *project*, starting at most one watcher per root."""
        root = Path(root).resolve()
        with self._watch_lock:
            self._watch_users.setdefault(root, set()).add(project)
            if root in self.watchers:
                return

            def on_change(paths: list[str], root: Path = root) -> None:
                self._on_files_changed(root, paths)

            watcher = CodebaseWatcher(root.as_posix(), on_change)
            try:
                watcher.start()
            except OSError as e:
                # e.g. the OS inotify limit. Analysis still works; only freshness
                # degrades, so warn and carry on. The next get_analyzer retries.
                logger.warning(
                    f"Could not watch {root.as_posix()} for changes ({e}); edits under "
                    "it won't refresh pyeye's caches until the analyzer is rebuilt"
                )
                return
            self.watchers[root] = watcher
        logger.info(f"Started watching {root.as_posix()}")

    def _unwatch_project(self, project: Path) -> None:
        """Drop *project* as a user of every root, stopping watchers nobody else uses."""
        stopped = []
        with self._watch_lock:
            for root in [r for r, users in self._watch_users.items() if project in users]:
                users = self._watch_users[root]
                users.discard(project)
                if not users:
                    del self._watch_users[root]
                    watcher = self.watchers.pop(root, None)
                    if watcher is not None:
                        stopped.append(watcher)
        # Outside the lock: stop() joins the observer thread, which may be inside
        # _on_files_changed waiting for this lock.
        for watcher in stopped:
            watcher.stop()

    def _setup_watcher(self, path: Path) -> None:
        """Watch *path* as its own project (kept for callers that predate ``_watch``)."""
        resolved = Path(path).resolve()
        self._watch(resolved, resolved)

    def _on_files_changed(self, root: Path, paths: list[str]) -> None:
        """Invalidate every cache of every project that reads from *root* (#617).

        For each such project: its ``GranularCache`` entries for each path, its
        name index (``project_graph.invalidate`` keyed on that project only),
        its TypeRef cache (``typeref.invalidate_project``), and its analyzer's
        ``scoped_cache`` (file lists and lookup results).
        Each path's ``file_artifact_cache`` entries are dropped once. Projects
        that don't read from *root* keep their caches.

        Args:
            root: The watched root the change happened under
            paths: Every path changed in the debounced batch
        """
        from pyeye import file_artifact_cache
        from pyeye.analyzers import project_graph
        from pyeye.mcp.operations import typeref

        with self._watch_lock:
            projects = sorted(self._watch_users.get(Path(root).resolve(), set()))
        logger.info(
            f"{len(paths)} change(s) under {Path(root).as_posix()}; "
            f"invalidating {len(projects)} project(s)"
        )
        for path in paths:
            file_artifact_cache.invalidate(path)
        for project in projects:
            cache = self.caches.get(project)
            if cache is not None:
                for path in paths:
                    cache.invalidate_file(Path(path))
            project_graph.invalidate(project.as_posix())
            # A referenced type can move to another file, which the TypeRef key
            # (keyed on the annotation's own file) can't see (#620).
            typeref.invalidate_project(project)
            analyzer = self.analyzers.get(project)
            if analyzer is not None:
                analyzer.scoped_cache.invalidate_all()

    def get_pool_stats(self) -> dict | None:
        """Get connection pool statistics.

        Returns:
            Pool statistics if pooling is enabled, None otherwise
        """
        if self.connection_pool:
            return self.connection_pool.get_stats()
        return None

    def cleanup_all(self) -> None:
        """Clean up all projects and evict the analyzer cache."""
        known = set(self.projects) | set(self.analyzers)
        for users in self._watch_users.values():
            known |= users
        for project_path in sorted(known):
            self._cleanup_project(project_path)
        # Anything still watched has no user left.
        with self._watch_lock:
            leftovers = list(self.watchers.values())
            self.watchers.clear()
            self._watch_users.clear()
        for watcher in leftovers:
            watcher.stop()

        # Clear any analyzer entries that had no corresponding jedi.Project
        # (e.g. get_analyzer was called without a prior get_project call).
        self.analyzers.clear()

        self.access_order.clear()

        # Clear connection pool if it exists
        if self.connection_pool:
            self.connection_pool.clear()


# Global project manager instance
_project_manager: ProjectManager | None = None


def get_project_manager() -> ProjectManager:
    """Get or create the global project manager."""
    global _project_manager
    if _project_manager is None:
        _project_manager = ProjectManager()
    return _project_manager
