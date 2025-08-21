"""Integration tests for smart cache invalidation system."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pycodemcp.cache import GranularCache
from pycodemcp.dependency_tracker import DependencyTracker
from pycodemcp.import_analyzer import ImportAnalyzer
from pycodemcp.project_manager import ProjectManager


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
            (project_path / "core" / "models.py").write_text(
                """
class BaseModel:
    pass

class User(BaseModel):
    pass
"""
            )

            # Create utils module that imports from core
            (project_path / "utils" / "__init__.py").write_text("")
            (project_path / "utils" / "helpers.py").write_text(
                """
from core.models import BaseModel

def process_model(model: BaseModel):
    return model
"""
            )

            # Create app module that imports from both
            (project_path / "app" / "__init__.py").write_text("")
            (project_path / "app" / "main.py").write_text(
                """
from core.models import User
from utils.helpers import process_model

def main():
    user = User()
    return process_model(user)
"""
            )

            yield project_path

    def test_import_analyzer_integration(self, temp_project):
        """Test import analyzer on real project structure."""
        analyzer = ImportAnalyzer(temp_project)

        # Analyze core.models
        core_models = temp_project / "core" / "models.py"
        result = analyzer.analyze_imports(core_models)

        assert result["module_name"] == "core.models"
        assert "BaseModel" in result["symbols"]
        assert "User" in result["symbols"]
        assert result["imports"] == []  # No imports

        # Analyze utils.helpers
        utils_helpers = temp_project / "utils" / "helpers.py"
        result = analyzer.analyze_imports(utils_helpers)

        assert result["module_name"] == "utils.helpers"
        assert "process_model" in result["symbols"]
        assert "core.models" in result["from_imports"]
        assert "BaseModel" in result["from_imports"]["core.models"]

        # Analyze app.main
        app_main = temp_project / "app" / "main.py"
        result = analyzer.analyze_imports(app_main)

        assert result["module_name"] == "app.main"
        assert "main" in result["symbols"]
        assert "core.models" in result["from_imports"]
        assert "utils.helpers" in result["from_imports"]

    def test_dependency_graph_building(self, temp_project):
        """Test building complete dependency graph."""
        analyzer = ImportAnalyzer(temp_project)

        # Find all Python files
        python_files = list(temp_project.rglob("*.py"))

        # Build dependency graph
        graph = analyzer.build_dependency_graph(python_files)

        assert "core.models" in graph["modules"]
        assert "utils.helpers" in graph["modules"]
        assert "app.main" in graph["modules"]

        assert "core.models" in graph["imports"]["utils.helpers"]
        assert "core.models" in graph["imports"]["app.main"]
        assert "utils.helpers" in graph["imports"]["app.main"]

        assert "BaseModel" in graph["symbols"]["core.models"]
        assert "User" in graph["symbols"]["core.models"]
        assert "process_model" in graph["symbols"]["utils.helpers"]
        assert "main" in graph["symbols"]["app.main"]

    def test_dependency_tracker_population(self, temp_project):
        """Test populating dependency tracker from real project."""
        tracker = DependencyTracker()
        analyzer = ImportAnalyzer(temp_project)

        # Build and populate
        python_files = list(temp_project.rglob("*.py"))
        graph = analyzer.build_dependency_graph(python_files)

        for module_name, file_path in graph["modules"].items():
            tracker.add_file_mapping(Path(file_path), module_name)

            if module_name in graph["imports"]:
                for imported in graph["imports"][module_name]:
                    if imported in graph["modules"]:  # Only internal imports
                        tracker.add_import(module_name, imported)

            if module_name in graph["symbols"]:
                for symbol in graph["symbols"][module_name]:
                    tracker.add_symbol_definition(module_name, symbol)

        # Verify relationships
        assert tracker.get_dependents("core.models") == {"utils.helpers", "app.main"}
        assert tracker.get_dependents("utils.helpers") == {"app.main"}
        assert tracker.get_dependencies("app.main") == {"core.models", "utils.helpers"}

        # Test affected modules
        core_models_path = temp_project / "core" / "models.py"
        affected = tracker.get_affected_modules(core_models_path)
        assert "core.models" in affected
        assert "utils.helpers" in affected
        assert "app.main" in affected

    def test_granular_cache_with_dependencies(self, temp_project):
        """Test granular cache with real dependency structure."""
        cache = GranularCache()
        analyzer = ImportAnalyzer(temp_project)

        # Build dependencies
        python_files = list(temp_project.rglob("*.py"))
        graph = analyzer.build_dependency_graph(python_files)

        # Populate cache's dependency tracker
        for module_name, file_path in graph["modules"].items():
            cache.dependency_tracker.add_file_mapping(Path(file_path), module_name)

            if module_name in graph["imports"]:
                for imported in graph["imports"][module_name]:
                    if imported in graph["modules"]:
                        cache.dependency_tracker.add_import(module_name, imported)

        # Simulate caching analysis results
        core_path = temp_project / "core" / "models.py"
        utils_path = temp_project / "utils" / "helpers.py"
        app_path = temp_project / "app" / "main.py"

        cache.set(
            "core:BaseModel", {"type": "class"}, file_path=core_path, module_name="core.models"
        )
        cache.set("core:User", {"type": "class"}, file_path=core_path, module_name="core.models")
        cache.set(
            "utils:process_model",
            {"type": "function"},
            file_path=utils_path,
            module_name="utils.helpers",
        )
        cache.set("app:main", {"type": "function"}, file_path=app_path, module_name="app.main")

        assert len(cache.cache) == 4

        # Invalidate core.models file
        invalidated = cache.invalidate_file(core_path)

        # Should invalidate core.models and its dependents
        assert invalidated >= 3  # At least core entries + dependents
        assert cache.get("core:BaseModel") is None
        assert cache.get("core:User") is None
        assert cache.get("utils:process_model") is None  # Depends on core
        assert cache.get("app:main") is None  # Depends on core

    @patch("pycodemcp.project_manager.CodebaseWatcher")
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
        on_change_callback(str(core_path))

        # Both keys should be invalidated due to dependency
        assert cache.get("test_key") is None
        assert cache.get("utils_key") is None

    def test_performance_metrics(self, temp_project):
        """Test that performance metrics are tracked correctly."""
        cache = GranularCache()
        analyzer = ImportAnalyzer(temp_project)

        # Build dependencies
        python_files = list(temp_project.rglob("*.py"))
        graph = analyzer.build_dependency_graph(python_files)

        for module_name, file_path in graph["modules"].items():
            cache.dependency_tracker.add_file_mapping(Path(file_path), module_name)
            if module_name in graph["imports"]:
                for imported in graph["imports"][module_name]:
                    if imported in graph["modules"]:
                        cache.dependency_tracker.add_import(module_name, imported)

        # Simulate cache usage
        cache.get("miss1")  # Miss
        cache.set("hit1", "value1", module_name="core.models")
        cache.get("hit1")  # Hit
        cache.get("hit1")  # Hit
        cache.set("hit2", "value2", module_name="utils.helpers")
        cache.get("hit2")  # Hit

        # Check hit rate before invalidation
        metrics = cache.get_metrics()
        assert metrics["cache"]["hits"] == 3
        assert metrics["cache"]["misses"] == 1
        assert metrics["cache"]["hit_rate"] == "75.0%"

        # Invalidate and check metrics
        core_path = temp_project / "core" / "models.py"
        invalidated = cache.invalidate_file(core_path)

        metrics = cache.get_metrics()
        assert metrics["cache"]["invalidations"]["file"] == 1
        assert metrics["cache"]["invalidations"]["total"] > 0

        # Verify cascade invalidation happened if we had dependencies
        if invalidated > 1:
            # Either module or cascade invalidations should have happened
            assert (
                metrics["cache"]["invalidations"]["module"] > 0
                or metrics["cache"]["invalidations"]["cascade"] > 0
            )

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
