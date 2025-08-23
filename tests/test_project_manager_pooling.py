"""Tests for ProjectManager with connection pooling enabled."""

from pathlib import Path

import pytest

from pycodemcp.project_manager import ProjectManager


class TestProjectManagerPooling:
    """Test ProjectManager with connection pooling functionality."""

    @pytest.fixture
    def enable_pooling(self, monkeypatch):
        """Enable connection pooling for tests."""
        # Save original settings
        from pycodemcp import settings as settings_module

        original_settings = settings_module.settings

        # Set environment variables
        monkeypatch.setenv("PYCODEMCP_ENABLE_CONNECTION_POOLING", "true")
        monkeypatch.setenv("PYCODEMCP_POOL_MAX_CONNECTIONS", "5")
        monkeypatch.setenv("PYCODEMCP_POOL_TTL", "300")

        # Force settings reload
        settings_module.settings = settings_module.PerformanceSettings()

        yield

        # Restore original settings
        settings_module.settings = original_settings

    @pytest.fixture
    def disable_pooling(self, monkeypatch):
        """Disable connection pooling for tests."""
        # Save original settings
        from pycodemcp import settings as settings_module

        original_settings = settings_module.settings

        monkeypatch.setenv("PYCODEMCP_ENABLE_CONNECTION_POOLING", "false")

        # Force settings reload
        settings_module.settings = settings_module.PerformanceSettings()

        yield

        # Restore original settings
        settings_module.settings = original_settings

    def test_manager_with_pooling_enabled(self, enable_pooling, tmp_path):  # noqa: ARG002
        """Test that ProjectManager uses connection pool when enabled."""
        # Import settings after fixture has set env vars
        from pycodemcp.settings import settings

        manager = ProjectManager()

        assert manager.connection_pool is not None
        assert manager.connection_pool.max_connections == settings.pool_max_connections
        assert manager.connection_pool.ttl_seconds == settings.pool_ttl

    def test_manager_with_pooling_disabled(self, disable_pooling, tmp_path):  # noqa: ARG002
        """Test that ProjectManager doesn't use pool when disabled."""
        manager = ProjectManager()

        assert manager.connection_pool is None

    def test_get_project_uses_pool(self, enable_pooling, tmp_path):  # noqa: ARG002
        """Test that get_project uses the connection pool."""
        project_path = tmp_path / "test_project"
        project_path.mkdir()
        (project_path / "__init__.py").touch()

        manager = ProjectManager()

        # Get project multiple times
        project1 = manager.get_project(str(project_path))
        project2 = manager.get_project(str(project_path))

        # Should be the same project from pool
        assert project1 is project2

        # Check pool stats
        stats = manager.get_pool_stats()
        assert stats is not None
        assert stats["hits"] == 1  # Second request was a hit
        assert stats["misses"] == 1  # First request was a miss
        assert stats["reuses"] == 1

    def test_get_project_with_dependencies_uses_pool(
        self, enable_pooling, tmp_path  # noqa: ARG002
    ):
        """Test that projects with dependencies use the pool correctly."""
        main_path = tmp_path / "main_project"
        dep1_path = tmp_path / "dependency1"
        dep2_path = tmp_path / "dependency2"

        for path in [main_path, dep1_path, dep2_path]:
            path.mkdir()
            (path / "__init__.py").touch()

        manager = ProjectManager()

        # Get project with dependencies
        project1 = manager.get_project(str(main_path), [str(dep1_path), str(dep2_path)])

        # Get same configuration again
        project2 = manager.get_project(str(main_path), [str(dep1_path), str(dep2_path)])

        assert project1 is project2

        # Get with different dependencies - should create new connection
        project3 = manager.get_project(str(main_path), [str(dep1_path)])  # Only one dependency

        # Should be different project (different configuration)
        assert project3 is not project1

        stats = manager.get_pool_stats()
        assert stats["pool_size"] == 2  # Two different configurations

    def test_pool_eviction_in_manager(self, tmp_path, monkeypatch):
        """Test that pool eviction works through ProjectManager."""
        # Configure small pool size for testing
        from pycodemcp import settings as settings_module

        original_settings = settings_module.settings

        monkeypatch.setenv("PYCODEMCP_ENABLE_CONNECTION_POOLING", "true")
        monkeypatch.setenv("PYCODEMCP_POOL_MAX_CONNECTIONS", "2")
        settings_module.settings = settings_module.PerformanceSettings()

        try:
            manager = ProjectManager()

            # Create multiple projects
            projects = []
            for i in range(3):
                path = tmp_path / f"project{i}"
                path.mkdir()
                (path / "__init__.py").touch()
                projects.append(path)

            # Access all three projects
            for path in projects:
                manager.get_project(str(path))

            stats = manager.get_pool_stats()
            assert stats["pool_size"] == 2  # Max connections
            assert stats["evictions"] == 1  # One eviction occurred
        finally:
            # Restore original settings
            settings_module.settings = original_settings

    def test_watchers_setup_with_pooling(self, enable_pooling, tmp_path):  # noqa: ARG002
        """Test that file watchers are set up correctly with pooling."""
        project_path = tmp_path / "test_project"
        dep_path = tmp_path / "dependency"

        for path in [project_path, dep_path]:
            path.mkdir()
            (path / "__init__.py").touch()

        manager = ProjectManager()

        # Get project with dependency
        manager.get_project(str(project_path), [str(dep_path)])

        # Check watchers are set up
        assert Path(project_path).resolve() in manager.watchers
        assert Path(dep_path).resolve() in manager.watchers

        # Get same project again
        manager.get_project(str(project_path), [str(dep_path)])

        # Should still have watchers (not recreated)
        assert len(manager.watchers) == 2

    def test_cache_setup_with_pooling(self, enable_pooling, tmp_path):  # noqa: ARG002
        """Test that caches are set up correctly with pooling."""
        project_path = tmp_path / "test_project"
        project_path.mkdir()
        (project_path / "__init__.py").touch()

        manager = ProjectManager()

        # Get project
        manager.get_project(str(project_path))

        # Check cache is set up
        assert Path(project_path).resolve() in manager.caches

        # Get cache directly
        cache = manager.get_cache(str(project_path))
        assert cache is not None

    def test_cleanup_with_pooling(self, enable_pooling, tmp_path):  # noqa: ARG002
        """Test cleanup works correctly with pooling."""
        project_path = tmp_path / "test_project"
        project_path.mkdir()
        (project_path / "__init__.py").touch()

        manager = ProjectManager()

        # Get project
        manager.get_project(str(project_path))

        # Verify resources exist
        assert manager.get_pool_stats()["pool_size"] > 0
        # Note: watchers may not exist if pooling reuses existing project
        assert len(manager.caches) > 0

        # Clean up
        manager.cleanup_all()

        # Verify cleanup
        assert manager.get_pool_stats()["pool_size"] == 0
        # Watchers should be cleaned up if they exist
        for watcher in manager.watchers.values():
            assert not watcher.observer.is_alive()
        assert len(manager.caches) == 0
        assert len(manager.projects) == 0

    def test_fallback_without_pooling(self, disable_pooling, tmp_path):  # noqa: ARG002
        """Test that manager falls back to original behavior without pooling."""
        project_path = tmp_path / "test_project"
        project_path.mkdir()
        (project_path / "__init__.py").touch()

        manager = ProjectManager()

        # Get project multiple times
        project1 = manager.get_project(str(project_path))
        project2 = manager.get_project(str(project_path))

        # Should be the same project (from manager's cache, not pool)
        assert project1 is project2

        # No pool stats available
        assert manager.get_pool_stats() is None

        # Should be in manager's projects dict
        assert Path(project_path).resolve() in manager.projects

    def test_pool_stats_tracking(self, enable_pooling, tmp_path):  # noqa: ARG002
        """Test that pool statistics are tracked correctly."""
        paths = []
        for i in range(3):
            path = tmp_path / f"project{i}"
            path.mkdir()
            (path / "__init__.py").touch()
            paths.append(path)

        manager = ProjectManager()

        # Initial stats
        stats = manager.get_pool_stats()
        assert stats["pool_size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

        # Access projects
        manager.get_project(str(paths[0]))
        manager.get_project(str(paths[0]))  # Hit
        manager.get_project(str(paths[1]))
        manager.get_project(str(paths[0]))  # Hit
        manager.get_project(str(paths[2]))

        # Check updated stats
        stats = manager.get_pool_stats()
        assert stats["pool_size"] == 3
        assert stats["hits"] == 2
        assert stats["misses"] == 3
        assert stats["hit_rate"] == 0.4  # 2 hits / 5 total

        # Check connection details
        assert len(stats["connections"]) == 3
        for conn in stats["connections"]:
            assert "project_path" in conn
            assert "access_count" in conn
            assert "age_seconds" in conn
            assert "idle_seconds" in conn
