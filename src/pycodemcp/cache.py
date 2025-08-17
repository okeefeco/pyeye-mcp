"""Caching and file watching for the MCP server."""

import logging
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

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

    def on_modified(self, event: Any) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return

        # Only care about Python files
        if isinstance(event, FileModifiedEvent):
            src_path = event.src_path
            if isinstance(src_path, str) and src_path.endswith(".py"):
                logger.info(f"Python file modified: {src_path}")
                self.last_change = time.time()

                if self.on_change_callback:
                    self.on_change_callback(src_path)

    def start(self) -> None:
        """Start watching the project."""
        if self._observer is None:
            self._observer = Observer()
            self._observer.schedule(self, str(self.project_path), recursive=True)
            self._observer.start()
            logger.info(f"Started watching {self.project_path}")

    def stop(self) -> None:
        """Stop watching."""
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

    def __init__(self, ttl_seconds: int = 300):
        """Initialize cache.

        Args:
            ttl_seconds: Time to live for cache entries
        """
        self.cache: dict[str, Any] = {}
        self.timestamps: dict[str, float] = {}
        self.ttl = ttl_seconds

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
