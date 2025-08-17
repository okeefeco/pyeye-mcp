"""Caching and file watching for the MCP server."""

import time
from pathlib import Path
from typing import Optional, Dict, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
import logging

logger = logging.getLogger(__name__)


class CodebaseWatcher(FileSystemEventHandler):
    """Watches for file changes and invalidates cache."""
    
    def __init__(self, project_path: str, on_change_callback=None):
        """Initialize the watcher.
        
        Args:
            project_path: Root path to watch
            on_change_callback: Function to call when files change
        """
        self.project_path = Path(project_path)
        self.on_change_callback = on_change_callback
        self.last_change = time.time()
        self._observer = None
        
    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
            
        # Only care about Python files
        if isinstance(event, FileModifiedEvent) and event.src_path.endswith('.py'):
            logger.info(f"Python file modified: {event.src_path}")
            self.last_change = time.time()
            
            if self.on_change_callback:
                self.on_change_callback(event.src_path)
                
    def start(self):
        """Start watching the project."""
        if self._observer is None:
            self._observer = Observer()
            self._observer.schedule(self, str(self.project_path), recursive=True)
            self._observer.start()
            logger.info(f"Started watching {self.project_path}")
            
    def stop(self):
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
        self.cache: Dict[str, Any] = {}
        self.timestamps: Dict[str, float] = {}
        self.ttl = ttl_seconds
        
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                return self.cache[key]
            else:
                # Expired
                del self.cache[key]
                del self.timestamps[key]
        return None
        
    def set(self, key: str, value: Any):
        """Store value in cache."""
        self.cache[key] = value
        self.timestamps[key] = time.time()
        
    def invalidate(self, pattern: str = None):
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