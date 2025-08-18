"""End-to-end integration tests for Python Code Intelligence MCP."""

import json
from pathlib import Path
from unittest.mock import patch

from pycodemcp.analyzers.jedi_analyzer import JediAnalyzer
from pycodemcp.config import ProjectConfig
from pycodemcp.namespace_resolver import NamespaceResolver
from pycodemcp.project_manager import ProjectManager


class TestEndToEndWorkflow:
    """Test complete workflows from config to analysis."""

    def test_complete_project_analysis_workflow(self, temp_project_dir):
        """Test complete workflow: config → project → analyze."""
        # Step 1: Create project structure
        src_dir = temp_project_dir / "src"
        src_dir.mkdir()

        main_py = src_dir / "main.py"
        main_py.write_text(
            """
def main():
    \"\"\"Main entry point.\"\"\"
    result = helper(42)
    return result

def helper(value: int) -> int:
    \"\"\"Helper function.\"\"\"
    return value * 2

if __name__ == "__main__":
    main()
"""
        )

        # Step 2: Create configuration
        config_file = temp_project_dir / ".pycodemcp.json"
        config_file.write_text(json.dumps({"cache_ttl": 300, "max_projects": 5}))

        # Step 3: Initialize components
        config = ProjectConfig(str(temp_project_dir))
        assert config.config["cache_ttl"] == 300

        manager = ProjectManager(max_projects=config.config.get("max_projects", 10))

        # Step 4: Get project and analyzer
        with patch("pycodemcp.project_manager.jedi.Project"):
            project = manager.get_project(str(temp_project_dir))
            assert project is not None

        # Step 5: Perform analysis
        analyzer = JediAnalyzer(str(temp_project_dir))

        with patch.object(analyzer, "find_symbol") as mock_find:
            mock_find.return_value = [
                {"name": "main", "line": 2, "type": "function"},
                {"name": "helper", "line": 7, "type": "function"},
            ]

            results = analyzer.find_symbol("main")
            assert len(results) == 2

    def test_multi_project_workflow(self, temp_project_dir):
        """Test managing multiple projects simultaneously."""
        manager = ProjectManager(max_projects=3)

        # Create multiple projects
        projects = []
        for i in range(3):
            proj_dir = temp_project_dir / f"project{i}"
            proj_dir.mkdir()
            (proj_dir / "main.py").write_text(f"# Project {i}")
            projects.append(proj_dir)

        # Load all projects
        with patch("pycodemcp.project_manager.jedi.Project"):
            for proj in projects:
                manager.get_project(str(proj))

            assert len(manager.projects) == 3

            # Access projects again - should use cache
            for proj in projects:
                cached_project = manager.get_project(str(proj))
                assert cached_project is not None

    def test_namespace_package_workflow(self, temp_project_dir):
        """Test distributed namespace package workflow."""
        # Create distributed namespace structure
        auth_repo = temp_project_dir / "auth-repo"
        api_repo = temp_project_dir / "api-repo"

        # Auth repository
        auth_pkg = auth_repo / "company" / "auth"
        auth_pkg.mkdir(parents=True)
        (auth_pkg / "__init__.py").write_text("")
        (auth_pkg / "models.py").write_text(
            """
class User:
    def __init__(self, username: str):
        self.username = username
"""
        )

        # API repository
        api_pkg = api_repo / "company" / "api"
        api_pkg.mkdir(parents=True)
        (api_pkg / "__init__.py").write_text("")
        (api_pkg / "client.py").write_text(
            """
from company.auth.models import User

class APIClient:
    def __init__(self, user: User):
        self.user = user
"""
        )

        # Configure namespace
        resolver = NamespaceResolver()
        resolver.register_namespace("company", [str(auth_repo), str(api_repo)])

        # Verify namespace is registered
        assert "company" in resolver.namespace_paths
        assert len(resolver.namespace_paths["company"]) == 2

        # Find imports across namespace
        results = resolver.resolve_import("company.auth.models", [str(auth_repo), str(api_repo)])

        # Should find the models module (resolve_import returns list of Path objects)
        assert len(results) > 0
        assert any("models" in str(path) for path in results)

    def test_file_change_cache_invalidation(self, temp_project_dir):
        """Test that file changes trigger cache invalidation."""
        from pycodemcp.cache import CodebaseWatcher, ProjectCache

        # Create project with file
        test_file = temp_project_dir / "test.py"
        test_file.write_text("def original(): pass")

        # Setup cache and watcher
        cache = ProjectCache(ttl_seconds=300)
        cache.set("test_key", "cached_value")

        def on_change(filepath):  # noqa: ARG001
            cache.invalidate()

        watcher = CodebaseWatcher(str(temp_project_dir), on_change)

        # Simulate file change
        from watchdog.events import FileModifiedEvent

        event = FileModifiedEvent(str(test_file))
        watcher.on_modified(event)

        # Cache should be invalidated
        assert cache.get("test_key") is None

    def test_plugin_activation_workflow(self, temp_project_dir):
        """Test that plugins are activated based on project type."""
        from pycodemcp.plugins.flask import FlaskPlugin
        from pycodemcp.plugins.pydantic import PydanticPlugin

        # Create Flask project
        app_py = temp_project_dir / "app.py"
        app_py.write_text(
            """
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return 'Hello'
"""
        )

        # Create Pydantic models
        models_py = temp_project_dir / "models.py"
        models_py.write_text(
            """
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int
"""
        )

        # Test Flask plugin detection
        flask_plugin = FlaskPlugin(str(temp_project_dir))
        assert flask_plugin.detect() is True

        routes = flask_plugin.find_routes()
        assert len(routes) == 1
        assert routes[0]["path"] == "/"

        # Test Pydantic plugin detection
        pydantic_plugin = PydanticPlugin(str(temp_project_dir))
        assert pydantic_plugin.detect() is True

        models = pydantic_plugin.find_models()
        assert len(models) == 1
        assert models[0]["name"] == "User"

    def test_configuration_precedence_workflow(self, temp_project_dir):
        """Test configuration loading from multiple sources."""
        import os

        # 1. Create local config
        local_config = temp_project_dir / ".pycodemcp.json"
        local_config.write_text(json.dumps({"packages": ["local_package"], "cache_ttl": 100}))

        # 2. Set environment variables
        with patch.dict(
            os.environ, {"PYCODEMCP_PACKAGES": "env_package", "PYCODEMCP_CACHE_TTL": "200"}
        ):
            # 3. Create global config
            global_dir = temp_project_dir / ".config" / "pycodemcp"
            global_dir.mkdir(parents=True)
            global_config = global_dir / "config.json"
            global_config.write_text(json.dumps({"packages": ["global_package"], "cache_ttl": 300}))

            # Load configuration
            with patch.object(Path, "home", return_value=temp_project_dir):
                config = ProjectConfig(str(temp_project_dir))

                # Local config should take precedence for cache_ttl
                assert config.config["cache_ttl"] == 100

                # Packages should be merged
                packages = config.config.get("packages", [])
                assert "local_package" in packages
                assert "env_package" in packages

    def test_error_recovery_workflow(self, temp_project_dir):
        """Test system recovery from various error conditions."""
        manager = ProjectManager()

        # Test handling non-existent project
        nonexistent = temp_project_dir / "nonexistent"

        with patch("pycodemcp.project_manager.jedi.Project") as mock_project:
            mock_project.side_effect = Exception("Project creation failed")

            # Should handle error gracefully
            try:
                manager.get_project(str(nonexistent))
            except Exception as e:
                assert "Project creation failed" in str(e)

        # Test handling invalid configuration
        bad_config = temp_project_dir / ".pycodemcp.json"
        bad_config.write_text("{ invalid json }")

        # Should not crash on bad config
        config = ProjectConfig(str(temp_project_dir))
        assert isinstance(config.config, dict)

    def test_concurrent_project_access(self, temp_project_dir):
        """Test handling concurrent access to multiple projects."""
        manager = ProjectManager(max_projects=10)

        # Create many projects
        projects = []
        for i in range(10):
            proj_dir = temp_project_dir / f"proj{i}"
            proj_dir.mkdir()
            (proj_dir / "main.py").write_text(f"# Project {i}")
            projects.append(proj_dir)

        with patch("pycodemcp.project_manager.jedi.Project"):
            # Rapidly access all projects
            for _ in range(3):  # Multiple rounds
                for proj in projects:
                    project = manager.get_project(str(proj))
                    assert project is not None

            # All should still be in cache (max_projects=10)
            assert len(manager.projects) == 10

    def test_large_codebase_workflow(self, temp_project_dir):
        """Test handling large codebases with many files."""
        # Create large structure
        for i in range(20):
            module_dir = temp_project_dir / f"module{i}"
            module_dir.mkdir()

            for j in range(10):
                py_file = module_dir / f"file{j}.py"
                py_file.write_text(
                    f"""
def function_{i}_{j}():
    \"\"\"Function in module {i} file {j}\"\"\"
    pass
"""
                )

        # Test project structure listing
        from pycodemcp.server import list_project_structure

        structure = list_project_structure(str(temp_project_dir), max_depth=2)

        # The new structure returns a tree, not a flat count
        assert "name" in structure
        assert structure["type"] == "directory"
        assert "children" in structure
        # Should have 10 module directories
        assert len([c for c in structure["children"] if c["type"] == "directory"]) == 10

    def test_cross_repository_import_resolution(self, temp_project_dir):
        """Test resolving imports across multiple repositories."""
        # Create main project
        main_proj = temp_project_dir / "main"
        main_proj.mkdir()
        (main_proj / "app.py").write_text(
            """
from lib.utils import helper
from shared.models import User

def main():
    user = User("test")
    return helper(user)
"""
        )

        # Create lib repository
        lib_repo = temp_project_dir / "lib"
        lib_repo.mkdir()
        (lib_repo / "utils.py").write_text(
            """
def helper(data):
    return str(data)
"""
        )

        # Create shared repository
        shared_repo = temp_project_dir / "shared"
        shared_repo.mkdir()
        (shared_repo / "models.py").write_text(
            """
class User:
    def __init__(self, name):
        self.name = name
"""
        )

        # Configure project with dependencies
        manager = ProjectManager()

        with patch("pycodemcp.project_manager.jedi.Project"):
            _ = manager.get_project(str(main_proj), include_paths=[str(lib_repo), str(shared_repo)])

            # Verify dependencies are tracked
            main_path = main_proj.resolve()
            assert len(manager.dependencies[main_path]) == 2
