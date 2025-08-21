"""Caching and file watching for the MCP server."""

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from .dependency_tracker import DependencyTracker
from .settings import settings

logger = logging.getLogger(__name__)


class CodebaseWatcher(FileSystemEventHandler):
    """Watches for file changes and invalidates cache."""

    def __init__(self, project_path: str, on_change_callback: Any = None) -> None:
        """Initialize the watcher.

        Args:
            project_path: Root path to watch
            on_change_callback: Function to call when files change
        """
        self.project_path = Path(project_path)
        self.on_change_callback = on_change_callback
        self.last_change = time.time()
        self._observer: BaseObserver | None = None

        # Debouncing support
        self.debounce_timer: threading.Timer | None = None
        self.debounce_delay = settings.watcher_debounce
        self.pending_changes: set[str] = set()
        self.debounce_lock = threading.Lock()

    def on_modified(self, event: Any) -> None:
        """Handle file modification events with debouncing."""
        if event.is_directory:
            return

        # Only care about Python files
        if isinstance(event, FileModifiedEvent):
            src_path = event.src_path
            if isinstance(src_path, str) and src_path.endswith(".py"):
                logger.debug(f"Python file modified: {src_path}")
                self.last_change = time.time()

                # Add to pending changes and reset debounce timer
                with self.debounce_lock:
                    self.pending_changes.add(src_path)

                    # Cancel existing timer if any
                    if self.debounce_timer:
                        self.debounce_timer.cancel()

                    # Start new timer
                    self.debounce_timer = threading.Timer(
                        self.debounce_delay, self._process_changes
                    )
                    self.debounce_timer.start()

    def _process_changes(self) -> None:
        """Process accumulated changes after debounce delay."""
        with self.debounce_lock:
            if not self.pending_changes:
                return

            changes = list(self.pending_changes)
            self.pending_changes.clear()
            self.debounce_timer = None

        # Log all changes at once
        logger.info(f"Processing {len(changes)} file change(s) after debounce")
        for path in changes:
            logger.debug(f"  - {path}")

        # Call callback once for all changes
        if self.on_change_callback:
            # Pass the first changed file (for compatibility)
            # Could be enhanced to pass all files if needed
            self.on_change_callback(changes[0])

    def start(self) -> None:
        """Start watching the project."""
        if self._observer is None:
            self._observer = Observer()
            self._observer.schedule(self, str(self.project_path), recursive=True)
            self._observer.start()
            logger.info(f"Started watching {self.project_path}")

    def stop(self) -> None:
        """Stop watching."""
        # Cancel any pending debounce timer
        with self.debounce_lock:
            if self.debounce_timer:
                self.debounce_timer.cancel()
                self.debounce_timer = None
            self.pending_changes.clear()

        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped watching")

    def is_stale(self, cache_time: float) -> bool:
        """Check if cache is stale based on last change."""
        return self.last_change > cache_time


class ProjectCache:
    """Simple cache for project analysis results."""

    def __init__(self, ttl_seconds: int | None = None):
        """Initialize cache.

        Args:
            ttl_seconds: Time to live for cache entries.
                        If None, uses value from settings.
        """
        self.cache: dict[str, Any] = {}
        self.timestamps: dict[str, float] = {}
        self.ttl = ttl_seconds if ttl_seconds is not None else settings.cache_ttl

    def get(self, key: str) -> Any | None:
        """Get value from cache if not expired."""
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                return self.cache[key]
            else:
                # Expired
                del self.cache[key]
                del self.timestamps[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Store value in cache."""
        self.cache[key] = value
        self.timestamps[key] = time.time()

    def invalidate(self, pattern: str | None = None) -> None:
        """Invalidate cache entries."""
        if pattern is None:
            # Clear all
            self.cache.clear()
            self.timestamps.clear()
        else:
            # Clear matching keys
            keys_to_delete = [k for k in self.cache if pattern in k]
            for key in keys_to_delete:
                del self.cache[key]
                del self.timestamps[key]

        logger.info(f"Cache invalidated: {pattern or 'all'}")


@dataclass
class CacheMetrics:
    """Metrics for cache performance tracking."""

    hits: int = 0
    misses: int = 0
    invalidations: int = 0
    total_entries: int = 0

    # Detailed tracking
    file_invalidations: int = 0
    module_invalidations: int = 0
    cascade_invalidations: int = 0

    # Time tracking
    last_hit: float | None = None
    last_miss: float | None = None
    last_invalidation: float | None = None

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def record_hit(self) -> None:
        """Record a cache hit."""
        self.hits += 1
        self.last_hit = time.time()

    def record_miss(self) -> None:
        """Record a cache miss."""
        self.misses += 1
        self.last_miss = time.time()

    def record_invalidation(self, count: int = 1) -> None:
        """Record cache invalidation(s)."""
        self.invalidations += count
        self.last_invalidation = time.time()


class GranularCache(ProjectCache):
    """Enhanced cache with granular invalidation and dependency tracking."""

    def __init__(self, ttl_seconds: int | None = None):
        """Initialize granular cache.

        Args:
            ttl_seconds: Time to live for cache entries.
                        If None, uses value from settings.
        """
        super().__init__(ttl_seconds)

        # Dependency tracker for smart invalidation
        self.dependency_tracker = DependencyTracker()

        # File-level cache mapping
        self.file_cache: dict[Path, set[str]] = {}  # file -> cache keys

        # Module-level cache mapping
        self.module_cache: dict[str, set[str]] = {}  # module -> cache keys

        # Metrics tracking
        self.metrics = CacheMetrics()

        # Lock for thread-safe operations
        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        """Get value from cache if not expired, with metrics tracking."""
        with self._lock:
            result = super().get(key)
            if result is not None:
                self.metrics.record_hit()
                logger.debug(f"Cache hit: {key}")
            else:
                self.metrics.record_miss()
                logger.debug(f"Cache miss: {key}")
            return result

    def set(
        self, key: str, value: Any, file_path: Path | None = None, module_name: str | None = None
    ) -> None:
        """Store value in cache with optional file/module association.

        Args:
            key: Cache key
            value: Value to cache
            file_path: Optional file this cache entry is associated with
            module_name: Optional module this cache entry is associated with
        """
        with self._lock:
            super().set(key, value)

            # Track file association
            if file_path:
                file_path = file_path.resolve()
                if file_path not in self.file_cache:
                    self.file_cache[file_path] = set()
                self.file_cache[file_path].add(key)

            # Track module association
            if module_name:
                if module_name not in self.module_cache:
                    self.module_cache[module_name] = set()
                self.module_cache[module_name].add(key)

            self.metrics.total_entries = len(self.cache)
            logger.debug(f"Cache set: {key} (file={file_path}, module={module_name})")

    def invalidate_file(self, file_path: Path) -> int:
        """Invalidate cache entries associated with a specific file.

        Args:
            file_path: Path to the file

        Returns:
            Number of cache entries invalidated
        """
        with self._lock:
            file_path = file_path.resolve()
            invalidated_count = 0

            # Always count file invalidation attempt even if no cached entries
            self.metrics.file_invalidations += 1

            # Get cache keys associated with this file
            if file_path in self.file_cache:
                keys_to_invalidate = self.file_cache[file_path].copy()

                for key in keys_to_invalidate:
                    if key in self.cache:
                        del self.cache[key]
                        del self.timestamps[key]
                        invalidated_count += 1

                # Clear file cache mapping
                del self.file_cache[file_path]

                self.metrics.record_invalidation(invalidated_count)

                logger.info(f"Invalidated {invalidated_count} cache entries for {file_path}")

            # Also invalidate affected modules
            affected_modules = self.dependency_tracker.get_affected_modules(file_path)
            for module_name in affected_modules:
                count = self.invalidate_module(module_name)
                invalidated_count += count

            self.metrics.total_entries = len(self.cache)
            return invalidated_count

    def invalidate_module(self, module_name: str) -> int:
        """Invalidate cache entries associated with a specific module.

        Args:
            module_name: Dotted module name

        Returns:
            Number of cache entries invalidated
        """
        with self._lock:
            invalidated_count = 0

            # Get cache keys associated with this module
            if module_name in self.module_cache:
                keys_to_invalidate = self.module_cache[module_name].copy()

                for key in keys_to_invalidate:
                    if key in self.cache:
                        del self.cache[key]
                        del self.timestamps[key]
                        invalidated_count += 1

                # Clear module cache mapping
                del self.module_cache[module_name]

                self.metrics.record_invalidation(invalidated_count)
                self.metrics.module_invalidations += 1

                logger.info(
                    f"Invalidated {invalidated_count} cache entries for module {module_name}"
                )

            self.metrics.total_entries = len(self.cache)
            return invalidated_count

    def invalidate_dependents(self, module_name: str) -> int:
        """Invalidate cache entries for modules that depend on the given module.

        Args:
            module_name: Module whose dependents should be invalidated

        Returns:
            Number of cache entries invalidated
        """
        with self._lock:
            invalidated_count = 0
            dependents = self.dependency_tracker.get_dependents(module_name)

            for dependent_module in dependents:
                count = self.invalidate_module(dependent_module)
                invalidated_count += count

            if invalidated_count > 0:
                self.metrics.cascade_invalidations += 1
                logger.info(
                    f"Cascade invalidated {invalidated_count} entries for {len(dependents)} dependent modules"
                )

            return invalidated_count

    def invalidate(self, pattern: str | None = None) -> None:
        """Invalidate cache entries with metrics tracking."""
        with self._lock:
            count_before = len(self.cache)
            super().invalidate(pattern)
            count_after = len(self.cache)

            invalidated = count_before - count_after
            if invalidated > 0:
                self.metrics.record_invalidation(invalidated)

            # Clear all mappings if full invalidation
            if pattern is None:
                self.file_cache.clear()
                self.module_cache.clear()
                self.dependency_tracker.clear()

            self.metrics.total_entries = len(self.cache)

    def get_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dict with cache metrics and statistics
        """
        with self._lock:
            dep_stats = self.dependency_tracker.get_stats()

            return {
                "cache": {
                    "hits": self.metrics.hits,
                    "misses": self.metrics.misses,
                    "hit_rate": f"{self.metrics.hit_rate:.1f}%",
                    "total_entries": self.metrics.total_entries,
                    "invalidations": {
                        "total": self.metrics.invalidations,
                        "file": self.metrics.file_invalidations,
                        "module": self.metrics.module_invalidations,
                        "cascade": self.metrics.cascade_invalidations,
                    },
                    "last_activity": {
                        "hit": self.metrics.last_hit,
                        "miss": self.metrics.last_miss,
                        "invalidation": self.metrics.last_invalidation,
                    },
                },
                "dependencies": dep_stats,
                "mappings": {
                    "files_tracked": len(self.file_cache),
                    "modules_tracked": len(self.module_cache),
                },
            }

    def clear_metrics(self) -> None:
        """Reset cache metrics."""
        with self._lock:
            self.metrics = CacheMetrics()
            self.metrics.total_entries = len(self.cache)
