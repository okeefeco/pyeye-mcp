"""Caching and file watching for the MCP server."""

import logging
import threading
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

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
