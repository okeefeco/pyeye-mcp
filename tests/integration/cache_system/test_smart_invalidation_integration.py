"""Integration tests for smart cache invalidation system."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pyeye.cache import GranularCache
from pyeye.project_manager import ProjectManager


class TestSmartInvalidationIntegration:
    """Integration tests for the complete smart invalidation system."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            # Create project structure
            (project_path / "core").mkdir()
            (project_path / "utils").mkdir()
            (project_path / "app").mkdir()

            # Create core module
            (project_path / "core" / "__init__.py").write_text("")
            (project_path / "core" / "models.py").write_text("""
class BaseModel:
    pass

class User(BaseModel):
    pass
""")

            # Create utils module that imports from core
            (project_path / "utils" / "__init__.py").write_text("")
            (project_path / "utils" / "helpers.py").write_text("""
from core.models import BaseModel

def process_model(model: BaseModel):
    return model
""")

            # Create app module that imports from both
            (project_path / "app" / "__init__.py").write_text("")
            (project_path / "app" / "main.py").write_text("""
from core.models import User
from utils.helpers import process_model

def main():
    user = User()
    return process_model(user)
""")

            yield project_path

    @patch("pyeye.project_manager.CodebaseWatcher")
    def test_project_manager_smart_invalidation(self, mock_watcher_class, temp_project):
        """Test ProjectManager with smart invalidation."""
        manager = ProjectManager()

        # Mock the watcher to avoid actual file watching
        mock_watcher = Mock()
        mock_watcher_class.return_value = mock_watcher

        # Get project (creates cache)
        manager.get_project(str(temp_project))
        cache = manager.get_cache(str(temp_project))

        # Populate cache with some data
        core_path = temp_project / "core" / "models.py"
        cache.set("test_key", "test_value", file_path=core_path, module_name="core.models")

        # Set up dependencies
        cache.dependency_tracker.add_file_mapping(core_path, "core.models")
        utils_path = temp_project / "utils" / "helpers.py"
        cache.dependency_tracker.add_file_mapping(utils_path, "utils.helpers")
        cache.dependency_tracker.add_import("utils.helpers", "core.models")

        cache.set("utils_key", "utils_value", file_path=utils_path, module_name="utils.helpers")

        # Simulate file change callback
        # Get the callback from when the watcher was created
        # The callback is passed as the second positional argument
        on_change_callback = mock_watcher_class.call_args[0][1]

        # Trigger smart invalidation
        # The callback receives the whole debounced batch (#617).
        on_change_callback([str(core_path)])

        # Both keys should be invalidated due to dependency
        assert cache.get("test_key") is None
        assert cache.get("utils_key") is None

    def test_circular_dependency_handling(self):
        """Test handling of circular dependencies."""
        cache = GranularCache()

        # Create circular dependency: A -> B -> C -> A
        file_a = Path("/project/a.py")
        file_b = Path("/project/b.py")
        file_c = Path("/project/c.py")

        cache.dependency_tracker.add_file_mapping(file_a, "module_a")
        cache.dependency_tracker.add_file_mapping(file_b, "module_b")
        cache.dependency_tracker.add_file_mapping(file_c, "module_c")

        cache.dependency_tracker.add_import("module_a", "module_b")
        cache.dependency_tracker.add_import("module_b", "module_c")
        cache.dependency_tracker.add_import("module_c", "module_a")

        # Set cache entries
        cache.set("a_data", "data_a", file_path=file_a, module_name="module_a")
        cache.set("b_data", "data_b", file_path=file_b, module_name="module_b")
        cache.set("c_data", "data_c", file_path=file_c, module_name="module_c")

        # Invalidate one file in the cycle
        cache.invalidate_file(file_a)

        # Should invalidate the changed file and its dependents
        assert cache.get("a_data") is None
        assert cache.get("c_data") is None  # C imports A

        # B might or might not be invalidated depending on implementation
        # The current implementation only does direct dependents

    def test_cache_hit_rate_improvement(self):
        """Test that smart invalidation improves cache hit rate."""
        # Traditional cache (invalidate all)
        traditional_cache = GranularCache()

        # Smart cache with dependencies
        smart_cache = GranularCache()

        # Set up file structure
        files = [Path(f"/project/module{i}.py") for i in range(10)]

        # Populate both caches
        for i, file in enumerate(files):
            module = f"module{i}"
            for j in range(5):
                key = f"{module}:item{j}"
                traditional_cache.set(key, f"value_{i}_{j}", file_path=file)
                smart_cache.set(key, f"value_{i}_{j}", file_path=file, module_name=module)

            # Add some dependencies for smart cache
            if i > 0:
                smart_cache.dependency_tracker.add_file_mapping(file, module)
                if i < 5:  # Only first 5 modules have dependencies
                    smart_cache.dependency_tracker.add_import(module, "module0")

        smart_cache.dependency_tracker.add_file_mapping(files[0], "module0")

        # Simulate file change - change module0
        traditional_cache.invalidate()  # Traditional: invalidate all
        smart_cache.invalidate_file(files[0])  # Smart: only affected

        # Traditional cache: everything invalidated
        assert len(traditional_cache.cache) == 0

        # Smart cache: only affected modules invalidated
        # Should have invalidated module0 and modules 1-4 that depend on it
        # Modules 5-9 should still be cached
        remaining = len(smart_cache.cache)
        assert remaining > 0  # Some entries should remain
        assert remaining < 50  # But not all

        # Verify unaffected modules still cached
        for i in range(6, 10):
            key = f"module{i}:item0"
            assert smart_cache.get(key) is not None  # Should still be cached
