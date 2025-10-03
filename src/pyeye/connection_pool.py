"""Connection pooling for Jedi projects and analysis resources."""

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import jedi

logger = logging.getLogger(__name__)


@dataclass
class PooledConnection:
    """A pooled Jedi project connection with metadata."""

    project: jedi.Project
    project_path: Path
    added_paths: set[Path] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0

    def touch(self) -> None:
        """Update last access time and increment counter."""
        self.last_accessed = time.time()
        self.access_count += 1


class ProjectConnectionPool:
    """Connection pool for Jedi projects with LRU eviction and reuse.

    This pool manages Jedi project instances to reduce the overhead of
    creating new projects for each analysis request. It implements:

    - Connection reuse for identical configurations
    - LRU eviction when the pool is full
    - Thread-safe access to pooled connections
    - Automatic cleanup of stale connections

    The pool significantly improves performance when working with multiple
    projects or frequently switching between projects.
    """

    def __init__(self, max_connections: int = 10, ttl_seconds: int = 3600):
        """Initialize the connection pool.

        Args:
            max_connections: Maximum number of connections to keep in pool
            ttl_seconds: Time-to-live for idle connections (default 1 hour)
        """
        self.max_connections = max_connections
        self.ttl_seconds = ttl_seconds
        self._pool: OrderedDict[tuple[Path, frozenset[Path]], PooledConnection] = OrderedDict()
        self._lock = Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "creates": 0, "reuses": 0}

        logger.info(
            f"Initialized connection pool: max_connections={max_connections}, "
            f"ttl={ttl_seconds}s"
        )

    def get_connection(
        self, project_path: Path, additional_paths: list[Path] | None = None
    ) -> jedi.Project:
        """Get or create a pooled Jedi project connection.

        This method will:
        1. Check if a compatible connection exists in the pool
        2. Return it if found (cache hit)
        3. Create a new one if not (cache miss)
        4. Evict LRU connection if pool is full

        Args:
            project_path: Main project path
            additional_paths: Additional paths to include in sys_path

        Returns:
            Jedi project configured with the specified paths
        """
        with self._lock:
            # Create cache key from paths
            added_paths = frozenset(additional_paths or [])
            cache_key = (project_path, added_paths)

            # Check for existing connection
            if cache_key in self._pool:
                # Move to end (most recently used)
                connection = self._pool.pop(cache_key)
                self._pool[cache_key] = connection
                connection.touch()

                self._stats["hits"] += 1
                self._stats["reuses"] += 1

                logger.debug(
                    f"Connection pool hit for {project_path.as_posix()} "
                    f"(access #{connection.access_count})"
                )
                return connection.project

            # Cache miss - need to create new connection
            self._stats["misses"] += 1

            # Evict if at capacity
            if len(self._pool) >= self.max_connections:
                self._evict_lru()

            # Create new connection
            connection = self._create_connection(project_path, list(added_paths))
            self._pool[cache_key] = connection

            return connection.project

    def _create_connection(
        self, project_path: Path, additional_paths: list[Path]
    ) -> PooledConnection:
        """Create a new pooled connection.

        Args:
            project_path: Main project path
            additional_paths: Additional paths for sys_path

        Returns:
            New PooledConnection instance
        """
        start_time = time.time()

        # Prepare all paths for Jedi
        all_paths = [project_path] + additional_paths

        # Create Jedi project with all paths
        # Use as_posix() for cross-platform compatibility
        project = jedi.Project(
            path=project_path.as_posix(), added_sys_path=[p.as_posix() for p in all_paths]
        )

        connection = PooledConnection(
            project=project, project_path=project_path, added_paths=set(additional_paths)
        )

        elapsed_ms = (time.time() - start_time) * 1000
        self._stats["creates"] += 1

        logger.info(
            f"Created new connection for {project_path.as_posix()} "
            f"with {len(additional_paths)} additional paths in {elapsed_ms:.1f}ms"
        )

        return connection

    def _evict_lru(self) -> None:
        """Evict the least recently used connection from the pool."""
        if not self._pool:
            return

        # OrderedDict maintains insertion order, so first item is LRU
        lru_key, lru_connection = next(iter(self._pool.items()))
        del self._pool[lru_key]

        self._stats["evictions"] += 1

        logger.info(
            f"Evicted LRU connection: {lru_connection.project_path.as_posix()} "
            f"(accessed {lru_connection.access_count} times, "
            f"age={(time.time() - lru_connection.created_at):.1f}s)"
        )

    def clear_stale(self) -> int:
        """Remove connections that haven't been used recently.

        Returns:
            Number of connections removed
        """
        with self._lock:
            current_time = time.time()
            stale_keys = []

            for key, connection in self._pool.items():
                age = current_time - connection.last_accessed
                if age > self.ttl_seconds:
                    stale_keys.append(key)

            for key in stale_keys:
                connection = self._pool.pop(key)
                logger.info(
                    f"Removed stale connection: {connection.project_path.as_posix()} "
                    f"(idle for {(current_time - connection.last_accessed):.1f}s)"
                )

            return len(stale_keys)

    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics for monitoring.

        Returns:
            Dictionary with pool metrics
        """
        with self._lock:
            hit_rate = (
                self._stats["hits"] / (self._stats["hits"] + self._stats["misses"])
                if (self._stats["hits"] + self._stats["misses"]) > 0
                else 0.0
            )

            return {
                "pool_size": len(self._pool),
                "max_connections": self.max_connections,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": hit_rate,
                "evictions": self._stats["evictions"],
                "creates": self._stats["creates"],
                "reuses": self._stats["reuses"],
                "connections": [
                    {
                        "project_path": conn.project_path.as_posix(),
                        "additional_paths": len(conn.added_paths),
                        "access_count": conn.access_count,
                        "age_seconds": time.time() - conn.created_at,
                        "idle_seconds": time.time() - conn.last_accessed,
                    }
                    for conn in self._pool.values()
                ],
            }

    def clear(self) -> None:
        """Clear all connections from the pool."""
        with self._lock:
            self._pool.clear()
            logger.info("Cleared all connections from pool")

    def __del__(self) -> None:
        """Clean up when the pool is destroyed."""
        self.clear()
