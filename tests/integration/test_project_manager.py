"""Tests for ProjectManager component."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pyeye.project_manager import ProjectManager


@pytest.fixture(autouse=True)
def fake_watchers():
    """Replace CodebaseWatcher so no test starts a real observer thread."""
    with patch("pyeye.project_manager.CodebaseWatcher") as watcher_class:
        watcher_class.side_effect = lambda *_a, **_k: Mock()
        yield watcher_class


def _dirs(base: Path, *names: str) -> list[Path]:
    out = []
    for name in names:
        d = base / name
        d.mkdir()
        out.append(d)
    return out


class TestProjectManager:
    """Test the ProjectManager class."""

    def test_initialization(self):
        """Test ProjectManager initialization."""
        manager = ProjectManager(max_projects=5)

        assert manager.max_projects == 5
        assert len(manager.watchers) == 0
        assert len(manager.access_order) == 0
        assert len(manager.dependencies) == 0
        assert len(manager.analyzers) == 0

    def test_dead_pool_and_cache_api_is_gone(self):
        """#628: the never-read caches, the pool and the pooled jedi.Project are gone."""
        manager = ProjectManager()
        for name in (
            "projects",
            "caches",
            "connection_pool",
            "get_project",
            "get_cache",
            "search_all_projects",
            "get_pool_stats",
        ):
            assert not hasattr(manager, name), name

    def test_register_project_records_it(self, temp_project_dir):
        manager = ProjectManager()

        assert manager.register_project(str(temp_project_dir)) is None

        main_path = Path(temp_project_dir).resolve()
        assert manager.dependencies[main_path] == set()
        assert main_path in manager.access_order

    def test_register_project_with_dependencies(self, temp_project_dir):
        manager = ProjectManager()
        dep1, dep2 = _dirs(temp_project_dir, "dep1", "dep2")

        manager.register_project(str(temp_project_dir), include_paths=[str(dep1), str(dep2)])

        main_path = Path(temp_project_dir).resolve()
        assert manager.dependencies[main_path] == {dep1.resolve(), dep2.resolve()}

    def test_register_project_watches_root_and_dependencies(self, temp_project_dir):
        manager = ProjectManager()
        (dep1,) = _dirs(temp_project_dir, "dep1")

        manager.register_project(str(temp_project_dir), include_paths=[str(dep1)])

        main_path = Path(temp_project_dir).resolve()
        assert set(manager.watchers) == {main_path, dep1.resolve()}
        for watcher in manager.watchers.values():
            watcher.start.assert_called_once()
        assert manager._watch_users[dep1.resolve()] == {main_path}

    def test_registered_dependencies_reach_the_analyzer(self, temp_project_dir):
        """The live side effect: get_analyzer passes registered paths to the analyzer."""
        manager = ProjectManager()
        (dep1,) = _dirs(temp_project_dir, "dep1")
        manager.register_project(str(temp_project_dir), include_paths=[str(dep1)])

        analyzer = manager.get_analyzer(str(temp_project_dir))

        assert [Path(p).resolve() for p in analyzer.additional_paths] == [dep1.resolve()]

    def test_lru_eviction(self, temp_project_dir):
        """Old projects are evicted when max_projects is reached."""
        manager = ProjectManager(max_projects=3)
        projects = _dirs(temp_project_dir, "p0", "p1", "p2", "p3")

        for proj in projects[:3]:
            manager.register_project(str(proj))
        assert len(manager.dependencies) == 3

        manager.register_project(str(projects[3]))

        assert len(manager.dependencies) == 3
        assert len(manager.access_order) == 3
        assert projects[0].resolve() not in manager.dependencies
        assert projects[3].resolve() in manager.dependencies

    def test_eviction_counts_registered_projects_and_analyzers_together(self, temp_project_dir):
        manager = ProjectManager(max_projects=2)
        a, b, c = _dirs(temp_project_dir, "a", "b", "c")

        manager.register_project(str(a))
        manager.get_analyzer(str(b))
        manager.register_project(str(c))

        known = set(manager.dependencies) | set(manager.analyzers)
        assert known == {b.resolve(), c.resolve()}

    def test_lru_access_order_update(self, temp_project_dir):
        """Re-registering a project moves it to the most-recent end."""
        manager = ProjectManager(max_projects=3)
        projects = _dirs(temp_project_dir, "p0", "p1", "p2")
        for proj in projects:
            manager.register_project(str(proj))

        manager.register_project(str(projects[0]))

        assert manager.access_order[-1] == projects[0].resolve()
        assert manager.access_order[0] == projects[1].resolve()

    def test_needs_update_detects_changes(self, temp_project_dir):
        manager = ProjectManager()
        dep1, dep2 = _dirs(temp_project_dir, "dep1", "dep2")

        manager.register_project(str(temp_project_dir), include_paths=[str(dep1)])

        main_path = Path(temp_project_dir).resolve()
        assert not manager._needs_update(main_path, [str(dep1)])
        assert manager._needs_update(main_path, [str(dep1), str(dep2)])

    def test_changed_paths_tear_down_the_old_registration(self, temp_project_dir):
        manager = ProjectManager()
        (dep1,) = _dirs(temp_project_dir, "dep1")
        manager.register_project(str(temp_project_dir))
        main_path = Path(temp_project_dir).resolve()
        old_watcher = manager.watchers[main_path]
        analyzer = manager.get_analyzer(str(temp_project_dir))

        manager.register_project(str(temp_project_dir), include_paths=[str(dep1)])

        old_watcher.stop.assert_called_once()
        assert manager.dependencies[main_path] == {dep1.resolve()}
        assert main_path in manager.watchers
        assert manager.watchers[main_path] is not old_watcher
        # The stale analyzer was dropped, so the next one sees the new path.
        assert manager.get_analyzer(str(temp_project_dir)) is not analyzer

    def test_unchanged_paths_keep_the_registration(self, temp_project_dir):
        manager = ProjectManager()
        manager.register_project(str(temp_project_dir))
        main_path = Path(temp_project_dir).resolve()
        watcher = manager.watchers[main_path]

        manager.register_project(str(temp_project_dir))

        watcher.stop.assert_not_called()
        assert manager.watchers[main_path] is watcher

    def test_nonexistent_dependency_ignored(self, temp_project_dir):
        manager = ProjectManager()

        manager.register_project(
            str(temp_project_dir), include_paths=["/nonexistent/path1", "/nonexistent/path2"]
        )

        assert manager.dependencies[Path(temp_project_dir).resolve()] == set()

    def test_cleanup_all(self, temp_project_dir):
        manager = ProjectManager()
        (dep1,) = _dirs(temp_project_dir, "dep1")
        manager.register_project(str(temp_project_dir), include_paths=[str(dep1)])
        watchers = list(manager.watchers.values())

        manager.cleanup_all()

        assert not manager.dependencies
        assert not manager.watchers
        assert not manager.access_order
        for watcher in watchers:
            watcher.stop.assert_called_once()

    def test_namespace_resolver_integration(self, temp_project_dir):
        """Test namespace resolver is available."""
        manager = ProjectManager()

        assert manager.namespace_resolver is not None

        manager.namespace_resolver.register_namespace("test.namespace", [str(temp_project_dir)])

        assert "test.namespace" in manager.namespace_resolver.namespace_paths
