"""Tests for connection pooling functionality."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import jedi

from pycodemcp.connection_pool import PooledConnection, ProjectConnectionPool


class TestPooledConnection:
    """Test PooledConnection data class."""

    def test_creation(self, tmp_path):
        """Test creating a pooled connection."""
        project = MagicMock(spec=jedi.Project)
        connection = PooledConnection(
            project=project, project_path=tmp_path, added_paths={Path("/path1"), Path("/path2")}
        )

        assert connection.project == project
        assert connection.project_path == tmp_path
        assert connection.added_paths == {Path("/path1"), Path("/path2")}
        assert connection.access_count == 0
        assert connection.created_at > 0
        assert connection.last_accessed > 0

    def test_touch(self, tmp_path):
        """Test updating access time and count."""
        project = MagicMock(spec=jedi.Project)
        connection = PooledConnection(project=project, project_path=tmp_path)

        initial_time = connection.last_accessed
        initial_count = connection.access_count

        time.sleep(0.01)  # Small delay to ensure time difference
        connection.touch()

        assert connection.last_accessed > initial_time
        assert connection.access_count == initial_count + 1


class TestProjectConnectionPool:
    """Test ProjectConnectionPool functionality."""

    def test_initialization(self):
        """Test pool initialization with custom settings."""
        pool = ProjectConnectionPool(max_connections=5, ttl_seconds=600)

        assert pool.max_connections == 5
        assert pool.ttl_seconds == 600
        assert len(pool._pool) == 0
        assert pool._stats["hits"] == 0
        assert pool._stats["misses"] == 0

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_get_connection_cache_miss(self, mock_project_class, tmp_path):
        """Test getting a connection when not in cache."""
        mock_project = MagicMock()
        mock_project_class.return_value = mock_project

        pool = ProjectConnectionPool(max_connections=2)

        # First request - cache miss
        project = pool.get_connection(tmp_path)

        assert project == mock_project
        assert pool._stats["misses"] == 1
        assert pool._stats["hits"] == 0
        assert pool._stats["creates"] == 1
        assert len(pool._pool) == 1

        # Verify Jedi project was created with correct params
        mock_project_class.assert_called_once_with(
            path=tmp_path.as_posix(), added_sys_path=[tmp_path.as_posix()]
        )

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_get_connection_cache_hit(self, mock_project_class, tmp_path):
        """Test getting a connection when it exists in cache."""
        mock_project = MagicMock()
        mock_project_class.return_value = mock_project

        pool = ProjectConnectionPool(max_connections=2)

        # First request - cache miss
        project1 = pool.get_connection(tmp_path)

        # Second request with same path - cache hit
        project2 = pool.get_connection(tmp_path)

        assert project1 == project2
        assert pool._stats["misses"] == 1
        assert pool._stats["hits"] == 1
        assert pool._stats["reuses"] == 1
        assert pool._stats["creates"] == 1
        assert len(pool._pool) == 1

        # Jedi project should only be created once
        assert mock_project_class.call_count == 1

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_get_connection_with_additional_paths(self, mock_project_class, tmp_path):
        """Test connections with different additional paths are cached separately."""
        mock_project1 = MagicMock()
        mock_project2 = MagicMock()
        mock_project_class.side_effect = [mock_project1, mock_project2]

        pool = ProjectConnectionPool(max_connections=3)

        path1 = tmp_path / "dep1"
        path2 = tmp_path / "dep2"
        path1.mkdir()
        path2.mkdir()

        # Request with no additional paths
        project1 = pool.get_connection(tmp_path)

        # Request with additional paths - should create new connection
        project2 = pool.get_connection(tmp_path, [path1, path2])

        assert project1 == mock_project1
        assert project2 == mock_project2
        assert pool._stats["misses"] == 2
        assert pool._stats["creates"] == 2
        assert len(pool._pool) == 2

        # Verify second call included additional paths
        assert mock_project_class.call_count == 2
        second_call = mock_project_class.call_args_list[1]
        assert set(second_call[1]["added_sys_path"]) == {
            tmp_path.as_posix(),
            path1.as_posix(),
            path2.as_posix(),
        }

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_lru_eviction(self, mock_project_class, tmp_path):
        """Test LRU eviction when pool is full."""
        mock_projects = [MagicMock() for _ in range(3)]
        mock_project_class.side_effect = mock_projects

        pool = ProjectConnectionPool(max_connections=2)

        path1 = tmp_path / "project1"
        path2 = tmp_path / "project2"
        path3 = tmp_path / "project3"

        for path in [path1, path2, path3]:
            path.mkdir()

        # Add first two projects
        pool.get_connection(path1)
        pool.get_connection(path2)

        assert len(pool._pool) == 2
        assert pool._stats["evictions"] == 0

        # Add third project - should evict path1 (LRU)
        pool.get_connection(path3)

        assert len(pool._pool) == 2
        assert pool._stats["evictions"] == 1
        assert pool._stats["creates"] == 3

        # path1 should have been evicted
        cache_keys = [key[0] for key in pool._pool]
        assert path1 not in cache_keys
        assert path2 in cache_keys
        assert path3 in cache_keys

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_lru_ordering(self, mock_project_class, tmp_path):
        """Test that accessing a connection moves it to MRU position."""
        mock_projects = [MagicMock() for _ in range(3)]
        mock_project_class.side_effect = mock_projects + mock_projects  # Allow reuse

        pool = ProjectConnectionPool(max_connections=2)

        path1 = tmp_path / "project1"
        path2 = tmp_path / "project2"
        path3 = tmp_path / "project3"

        for path in [path1, path2, path3]:
            path.mkdir()

        # Add two projects
        pool.get_connection(path1)  # path1 is LRU
        pool.get_connection(path2)  # path2 is MRU

        # Access path1 again - should move to MRU
        pool.get_connection(path1)

        # Add path3 - should evict path2 (now LRU)
        pool.get_connection(path3)

        cache_keys = [key[0] for key in pool._pool]
        assert path1 in cache_keys  # Still in pool (was accessed)
        assert path2 not in cache_keys  # Evicted (was LRU)
        assert path3 in cache_keys  # Just added

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_clear_stale(self, mock_project_class, tmp_path):
        """Test removing stale connections."""
        mock_project = MagicMock()
        mock_project_class.return_value = mock_project

        pool = ProjectConnectionPool(max_connections=5, ttl_seconds=1)

        path1 = tmp_path / "project1"
        path2 = tmp_path / "project2"
        path1.mkdir()
        path2.mkdir()

        # Add two connections
        pool.get_connection(path1)
        pool.get_connection(path2)

        # Access path2 to update its last_accessed time
        time.sleep(0.5)
        pool.get_connection(path2)

        # Wait for path1 to become stale
        time.sleep(0.6)

        # Clear stale connections
        removed = pool.clear_stale()

        assert removed == 1
        assert len(pool._pool) == 1

        # Only path2 should remain
        cache_keys = [key[0] for key in pool._pool]
        assert path1 not in cache_keys
        assert path2 in cache_keys

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_get_stats(self, mock_project_class, tmp_path):
        """Test getting pool statistics."""
        mock_project = MagicMock()
        mock_project_class.return_value = mock_project

        pool = ProjectConnectionPool(max_connections=3)

        path1 = tmp_path / "project1"
        path2 = tmp_path / "project2"
        path1.mkdir()
        path2.mkdir()

        # Generate some activity
        pool.get_connection(path1)  # Miss
        pool.get_connection(path1)  # Hit
        pool.get_connection(path2)  # Miss
        pool.get_connection(path1)  # Hit

        stats = pool.get_stats()

        assert stats["pool_size"] == 2
        assert stats["max_connections"] == 3
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5
        assert stats["evictions"] == 0
        assert stats["creates"] == 2
        assert stats["reuses"] == 2
        assert len(stats["connections"]) == 2

        # Check connection details
        conn_paths = {conn["project_path"] for conn in stats["connections"]}
        assert conn_paths == {path1.as_posix(), path2.as_posix()}

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_clear(self, mock_project_class, tmp_path):
        """Test clearing all connections from pool."""
        mock_project = MagicMock()
        mock_project_class.return_value = mock_project

        pool = ProjectConnectionPool(max_connections=3)

        paths = [tmp_path / f"project{i}" for i in range(3)]
        for path in paths:
            path.mkdir()
            pool.get_connection(path)

        assert len(pool._pool) == 3

        pool.clear()

        assert len(pool._pool) == 0

    @patch("pycodemcp.connection_pool.jedi.Project")
    def test_thread_safety(self, mock_project_class, tmp_path):
        """Test thread-safe access to pool."""
        import threading

        mock_project = MagicMock()
        mock_project_class.return_value = mock_project

        pool = ProjectConnectionPool(max_connections=10)

        paths = [tmp_path / f"project{i}" for i in range(5)]
        for path in paths:
            path.mkdir()

        results = []
        errors = []

        def worker(path):
            try:
                for _ in range(10):
                    project = pool.get_connection(path)
                    results.append(project)
                    time.sleep(0.001)  # Small delay to increase contention
            except Exception as e:
                errors.append(e)

        # Create threads that will access the pool concurrently
        threads = []
        for path in paths:
            thread = threading.Thread(target=worker, args=(path,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Check results
        assert len(errors) == 0
        assert len(results) == 50  # 5 paths * 10 accesses each
        assert all(r == mock_project for r in results)

    def test_pool_performance(self, tmp_path):
        """Test that pooling provides cache hits and reuse."""

        paths = [tmp_path / f"project{i}" for i in range(5)]
        for path in paths:
            path.mkdir()

        # Test with pooling - focus on reuse metrics
        pool = ProjectConnectionPool(max_connections=10)

        # First round - all misses
        for path in paths:
            pool.get_connection(path)

        initial_stats = pool.get_stats()
        assert initial_stats["misses"] == 5
        assert initial_stats["hits"] == 0

        # Second round - all hits (reuse)
        for _ in range(10):
            for path in paths:
                pool.get_connection(path)

        final_stats = pool.get_stats()

        # Verify significant reuse
        assert final_stats["hits"] == 50  # 10 rounds * 5 paths
        assert final_stats["reuses"] == 50
        assert final_stats["creates"] == 5  # Only initial creates

        # Hit rate should be high
        hit_rate = final_stats["hits"] / (final_stats["hits"] + final_stats["misses"])
        assert hit_rate > 0.9  # 50 hits / 55 total = 0.909
