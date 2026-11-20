"""Caching and file watching for the MCP server."""

import logging
import threading
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from .path_utils import relative_within
from .settings import settings

logger = logging.getLogger(__name__)


#: The file suffixes whose changes can change the project's modules: sources,
#: and stubs, from which a stub-only module is analysed (#933).
WATCHED_SUFFIXES: tuple[str, ...] = (".py", ".pyi")


class CodebaseWatcher(FileSystemEventHandler):
    """Watches for file changes and invalidates cache."""

    def __init__(self, project_path: str, on_change_callback: Any = None) -> None:
        """Initialize the watcher.

        Args:
            project_path: Root path to watch
            on_change_callback: Called once per debounced batch with the sorted
                list of every changed path (``list[str]``)
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

    # Directories that should never trigger cache invalidation.
    # Watchdog's Observer still receives events from these but we skip them
    # immediately to avoid unnecessary processing.
    _IGNORE_DIRS = frozenset(
        {
            ".git",
            ".hg",
            ".svn",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "node_modules",
            ".venv",
            "venv",
            ".env",
            "env",
            ".tox",
            ".nox",
            ".eggs",
            "dist",
            "build",
            ".idea",
            ".vscode",
        }
    )

    def _is_ignored(self, path: str) -> bool:
        """Whether *path* lies in an ignored directory **below** the watched root.

        Only components under the root are tested, so a project that itself lives
        under e.g. ``~/build/`` is still watched (the scan rule from #515).
        """
        candidate = Path(path)
        rel = relative_within(candidate, self.project_path)
        parts = rel.parts if rel is not None else candidate.parts
        return any(part in self._IGNORE_DIRS for part in parts)

    def _record(self, path: Any, is_directory: bool) -> bool:
        """Queue *path* if it can change the project's modules; return whether it did.

        A ``.py`` or ``.pyi`` file counts: a stub-only module is analysed from its
        stub (#933). A directory counts too, because creating, deleting or
        moving one adds or removes whole modules. Paths under ignored
        directories never count.
        """
        if not isinstance(path, str) or not path:
            return False
        if not is_directory and not path.endswith(WATCHED_SUFFIXES):
            return False
        if self._is_ignored(path):
            return False
        with self.debounce_lock:
            self.pending_changes.add(path)
        return True

    def _schedule(self) -> None:
        """Restart the debounce timer, so a burst of events is delivered as one batch."""
        self.last_change = time.time()
        with self.debounce_lock:
            if self.debounce_timer:
                self.debounce_timer.cancel()
            self.debounce_timer = threading.Timer(self.debounce_delay, self._process_changes)
            self.debounce_timer.daemon = True
            self.debounce_timer.start()

    def on_modified(self, event: Any) -> None:
        """A file's content changed. Directory "modified" events only echo a child change."""
        if event.is_directory:
            return
        if self._record(event.src_path, False):
            logger.debug(f"Python file modified: {Path(event.src_path).as_posix()}")
            self._schedule()

    def on_created(self, event: Any) -> None:
        """A file or directory appeared (#617: previously ignored)."""
        if self._record(event.src_path, event.is_directory):
            self._schedule()

    def on_deleted(self, event: Any) -> None:
        """A file or directory disappeared (#617: previously ignored)."""
        if self._record(event.src_path, event.is_directory):
            self._schedule()

    def on_moved(self, event: Any) -> None:
        """A file or directory moved: both the old and the new path changed (#617)."""
        recorded = self._record(event.src_path, event.is_directory)
        recorded = self._record(getattr(event, "dest_path", None), event.is_directory) or recorded
        if recorded:
            self._schedule()

    def _process_changes(self) -> None:
        """Deliver the accumulated batch after the debounce delay.

        The callback receives **every** changed path, sorted, in one call. Before
        #617 only the first one was passed on.
        """
        with self.debounce_lock:
            if not self.pending_changes:
                return

            changes = sorted(self.pending_changes)
            self.pending_changes.clear()
            self.debounce_timer = None

        logger.info(f"Processing {len(changes)} file change(s) after debounce")
        for path in changes:
            logger.debug(f"  - {Path(path).as_posix()}")

        if self.on_change_callback:
            self.on_change_callback(changes)

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
