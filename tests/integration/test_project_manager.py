"""Tests for ProjectManager component."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyeye.project_manager import ProjectManager  # noqa: E402


class TestProjectManager:
    """Test the ProjectManager class."""

    @pytest.fixture(autouse=True)
    def disable_pooling(self, monkeypatch):
        """Disable connection pooling for tests that depend on direct project management.

        These tests verify the internal LRU behavior of ProjectManager which works
        differently when pooling is enabled (pool handles its own eviction).
        """
        monkeypatch.setenv("PYEYE_ENABLE_CONNECTION_POOLING", "false")

        # Re-initialize settings with pooling disabled
        from pycodemcp import settings as settings_module

        settings_module.settings = settings_module.PerformanceSettings()

        yield

        # Restore settings after test
        settings_module.settings = settings_module.PerformanceSettings()

    def test_initialization(self):
        """Test ProjectManager initialization."""
        manager = ProjectManager(max_projects=5)

        assert manager.max_projects == 5
        assert len(manager.projects) == 0
        assert len(manager.watchers) == 0
        assert len(manager.caches) == 0
        assert len(manager.access_order) == 0
        assert len(manager.dependencies) == 0

    @patch("pycodemcp.project_manager.jedi.Project")
    def test_get_project_creates_new(self, mock_jedi_project, temp_project_dir):
        """Test creating a new project."""
        manager = ProjectManager()
        mock_project = Mock()
        mock_jedi_project.return_value = mock_project

        project = manager.get_project(str(temp_project_dir))

        assert project == mock_project
        assert Path(temp_project_dir).resolve() in manager.projects
        assert Path(temp_project_dir).resolve() in manager.access_order
        mock_jedi_project.assert_called_once()

    @patch("pycodemcp.project_manager.jedi.Project")
    def test_get_project_with_dependencies(self, mock_jedi_project, temp_project_dir):
        """Test creating project with additional dependencies."""
        manager = ProjectManager()
        mock_project = Mock()
        mock_jedi_project.return_value = mock_project

        dep1 = temp_project_dir / "dep1"
        dep2 = temp_project_dir / "dep2"
        dep1.mkdir()
        dep2.mkdir()

        project = manager.get_project(str(temp_project_dir), include_paths=[str(dep1), str(dep2)])

        assert project == mock_project
        main_path = Path(temp_project_dir).resolve()
        assert main_path in manager.dependencies
        assert len(manager.dependencies[main_path]) == 2

    @patch("pycodemcp.project_manager.jedi.Project")
    def test_lru_cache_eviction(self, mock_jedi_project, temp_project_dir):
        """Test that old projects are evicted when max_projects is reached."""
        manager = ProjectManager(max_projects=3)
        mock_jedi_project.return_value = Mock()

        # Create 4 project directories
        projects = []
        for i in range(4):
            proj_dir = temp_project_dir / f"project{i}"
            proj_dir.mkdir()
            projects.append(proj_dir)

        # Access first 3 projects
        for i in range(3):
            manager.get_project(str(projects[i]))

        assert len(manager.projects) == 3
        assert len(manager.access_order) == 3

        # Access 4th project - should evict the first
        manager.get_project(str(projects[3]))

        assert len(manager.projects) == 3
        assert len(manager.access_order) == 3
        assert Path(projects[0]).resolve() not in manager.projects
        assert Path(projects[3]).resolve() in manager.projects

    @patch("pycodemcp.project_manager.jedi.Project")
    def test_lru_access_order_update(self, mock_jedi_project, temp_project_dir):
        """Test that accessing a project updates its position in LRU."""
        manager = ProjectManager(max_projects=3)
        mock_jedi_project.return_value = Mock()

        # Create 3 projects
        projects = []
        for i in range(3):
            proj_dir = temp_project_dir / f"project{i}"
            proj_dir.mkdir()
            projects.append(proj_dir)
            manager.get_project(str(proj_dir))

        # Access order should be [0, 1, 2]
        assert manager.access_order[-1] == Path(projects[2]).resolve()

        # Access project 0 again
        manager.get_project(str(projects[0]))

        # Access order should now be [1, 2, 0]
        assert manager.access_order[-1] == Path(projects[0]).resolve()
        assert manager.access_order[0] == Path(projects[1]).resolve()

    @patch("pycodemcp.project_manager.jedi.Project")
    def test_needs_update_detects_changes(self, mock_jedi_project, temp_project_dir):
        """Test that dependency changes are detected."""
        manager = ProjectManager()
        mock_jedi_project.return_value = Mock()

        dep1 = temp_project_dir / "dep1"
        dep1.mkdir()

        # Create project with one dependency
        manager.get_project(str(temp_project_dir), include_paths=[str(dep1)])

        main_path = Path(temp_project_dir).resolve()
        assert not manager._needs_update(main_path, [str(dep1)])

        # Check with different dependencies
        dep2 = temp_project_dir / "dep2"
        dep2.mkdir()
        assert manager._needs_update(main_path, [str(dep1), str(dep2)])

    @patch("pycodemcp.project_manager.CodebaseWatcher")
    @patch("pycodemcp.project_manager.GranularCache")
    @patch("pycodemcp.project_manager.jedi.Project")
    def test_watcher_and_cache_creation(
        self, mock_jedi_project, mock_cache_class, mock_watcher_class, temp_project_dir
    ):
        """Test that watchers and caches are created for projects."""
        manager = ProjectManager()
        mock_jedi_project.return_value = Mock()
        mock_watcher = Mock()
        mock_cache = Mock()
        mock_watcher_class.return_value = mock_watcher
        mock_cache_class.return_value = mock_cache

        manager.get_project(str(temp_project_dir))

        main_path = Path(temp_project_dir).resolve()
        assert main_path in manager.watchers
        assert main_path in manager.caches
        mock_watcher.start.assert_called_once()

    @patch("pycodemcp.project_manager.jedi.Project")
    def test_cleanup_old_project(self, mock_jedi_project, temp_project_dir):
        """Test that old projects are properly cleaned up."""
        manager = ProjectManager()
        mock_jedi_project.return_value = Mock()

        # Create project
        manager.get_project(str(temp_project_dir))
        main_path = Path(temp_project_dir).resolve()

        # Mock watcher for cleanup test
        mock_watcher = Mock()
        manager.watchers[main_path] = mock_watcher

        # Update project (should cleanup old one)
        dep1 = temp_project_dir / "dep1"
        dep1.mkdir()
        manager.get_project(str(temp_project_dir), include_paths=[str(dep1)])

        # Watcher should be stopped
        mock_watcher.stop.assert_called_once()

    @patch("pycodemcp.project_manager.jedi.Project")
    def test_nonexistent_dependency_ignored(self, mock_jedi_project, temp_project_dir):
        """Test that non-existent dependencies are ignored."""
        manager = ProjectManager()
        mock_jedi_project.return_value = Mock()

        # Try to add non-existent dependencies
        manager.get_project(
            str(temp_project_dir), include_paths=["/nonexistent/path1", "/nonexistent/path2"]
        )

        main_path = Path(temp_project_dir).resolve()
        # No dependencies should be added
        assert len(manager.dependencies[main_path]) == 0

    def test_get_cache_for_project(self, temp_project_dir):
        """Test retrieving cache for a project."""
        manager = ProjectManager()

        with patch("pycodemcp.project_manager.jedi.Project"):
            manager.get_project(str(temp_project_dir))

            main_path = Path(temp_project_dir).resolve()
            cache = manager.get_cache(main_path)

            assert cache is not None
            assert main_path in manager.caches

    @pytest.mark.skip(reason="ProjectManager doesn't have invalidate_cache method yet")
    def test_invalidate_cache(self, temp_project_dir):
        """Test cache invalidation."""
        manager = ProjectManager()

        with patch("pycodemcp.project_manager.jedi.Project"):
            manager.get_project(str(temp_project_dir))

            main_path = Path(temp_project_dir).resolve()
            mock_cache = Mock()
            manager.caches[main_path] = mock_cache

            manager.invalidate_cache(main_path)
            mock_cache.invalidate.assert_called_once()

    def test_namespace_resolver_integration(self, temp_project_dir):
        """Test namespace resolver is available."""
        manager = ProjectManager()

        assert manager.namespace_resolver is not None

        # Test namespace registration through manager
        manager.namespace_resolver.register_namespace("test.namespace", [str(temp_project_dir)])

        assert "test.namespace" in manager.namespace_resolver.namespace_paths
