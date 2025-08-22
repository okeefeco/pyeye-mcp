"""Comprehensive tests for namespace-aware file operations."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pycodemcp.analyzers.jedi_analyzer import JediAnalyzer
from pycodemcp.project_manager import ProjectManager


@pytest.fixture
def temp_project():
    """Create a temporary project structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create main project structure
        main_project = root / "main_project"
        main_project.mkdir()
        (main_project / "__init__.py").touch()
        (main_project / "main.py").write_text("# Main module")
        (main_project / "utils.py").write_text("# Utils module")

        # Create test directory in main project
        test_dir = main_project / "tests"
        test_dir.mkdir()
        (test_dir / "test_main.py").write_text("# Test main")
        (test_dir / "test_utils.py").write_text("# Test utils")

        # Create additional package
        lib_package = root / "my_lib"
        lib_package.mkdir()
        (lib_package / "__init__.py").touch()
        (lib_package / "helpers.py").write_text("# Helpers")

        # Create namespace package structure (e.g., company-auth repo)
        auth_repo = root / "company-auth"
        auth_repo.mkdir()
        auth_ns = auth_repo / "company" / "auth"
        auth_ns.mkdir(parents=True)
        (auth_ns / "__init__.py").touch()
        (auth_ns / "models.py").write_text("# Auth models")
        (auth_ns / "views.py").write_text("# Auth views")

        # Create another namespace package part (e.g., company-api repo)
        api_repo = root / "company-api"
        api_repo.mkdir()
        api_ns = api_repo / "company" / "api"
        api_ns.mkdir(parents=True)
        (api_ns / "__init__.py").touch()
        (api_ns / "endpoints.py").write_text("# API endpoints")

        # Create sub-namespace
        tools_ns = api_repo / "company" / "api" / "tools"
        tools_ns.mkdir()
        (tools_ns / "__init__.py").touch()
        (tools_ns / "validators.py").write_text("# Validators")

        yield {
            "root": root,
            "main_project": main_project,
            "lib_package": lib_package,
            "auth_repo": auth_repo,
            "api_repo": api_repo,
            "auth_ns": auth_ns,
            "api_ns": api_ns,
            "tools_ns": tools_ns,
        }


class TestJediAnalyzerNamespaceSupport:
    """Test JediAnalyzer namespace-aware file operations."""

    async def test_get_project_files_main_scope(self, temp_project):
        """Test getting files from main project only."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        files = await analyzer.get_project_files(scope="main")

        # Should only include files from main project
        file_names = {f.name for f in files}
        assert "main.py" in file_names
        assert "utils.py" in file_names
        assert "test_main.py" in file_names
        assert "test_utils.py" in file_names
        # Should not include files from other packages
        assert "helpers.py" not in file_names
        assert "models.py" not in file_names

    async def test_get_project_files_all_scope(self, temp_project):
        """Test getting files from all configured sources."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        # Configure additional paths
        analyzer.set_additional_paths([temp_project["lib_package"]])
        analyzer.set_namespace_paths(
            {"company": [str(temp_project["auth_repo"]), str(temp_project["api_repo"])]}
        )

        files = await analyzer.get_project_files(scope="all")

        file_names = {f.name for f in files}
        # Should include main project files
        assert "main.py" in file_names
        assert "utils.py" in file_names
        # Should include additional package files
        assert "helpers.py" in file_names
        # Should include namespace package files
        assert "models.py" in file_names
        assert "endpoints.py" in file_names
        assert "validators.py" in file_names

    async def test_get_project_files_packages_scope(self, temp_project):
        """Test getting files from packages only (excluding main)."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))
        analyzer.set_additional_paths([temp_project["lib_package"]])

        files = await analyzer.get_project_files(scope="packages")

        file_names = {f.name for f in files}
        # Should include package files
        assert "helpers.py" in file_names
        # Should NOT include main project files
        assert "main.py" not in file_names
        assert "utils.py" not in file_names

    async def test_get_project_files_namespace_scope(self, temp_project):
        """Test getting files from a specific namespace."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))
        analyzer.set_namespace_paths(
            {"company": [str(temp_project["auth_repo"]), str(temp_project["api_repo"])]}
        )

        files = await analyzer.get_project_files(scope="namespace:company")

        file_names = {f.name for f in files}
        # Should include all company namespace files
        assert "models.py" in file_names
        assert "views.py" in file_names
        assert "endpoints.py" in file_names
        assert "validators.py" in file_names
        # Should NOT include main project files
        assert "main.py" not in file_names

    async def test_get_project_files_sub_namespace_scope(self, temp_project):
        """Test getting files from a sub-namespace."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))
        analyzer.set_namespace_paths(
            {"company": [str(temp_project["auth_repo"]), str(temp_project["api_repo"])]}
        )

        files = await analyzer.get_project_files(scope="namespace:company.api.tools")

        file_names = {f.name for f in files}
        # Should only include tools sub-namespace files
        assert "validators.py" in file_names
        # Should NOT include other namespace files
        assert "models.py" not in file_names
        assert "endpoints.py" not in file_names

    async def test_get_project_files_package_path_scope(self, temp_project):
        """Test getting files from a specific package path."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        files = await analyzer.get_project_files(scope=f"package:{temp_project['lib_package']}")

        file_names = {f.name for f in files}
        # Should only include files from specified package
        assert "helpers.py" in file_names
        # Should NOT include other files
        assert "main.py" not in file_names
        assert "models.py" not in file_names

    async def test_get_project_files_multiple_scopes(self, temp_project):
        """Test getting files from multiple scopes combined."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))
        analyzer.set_additional_paths([temp_project["lib_package"]])
        analyzer.set_namespace_paths(
            {"company": [str(temp_project["auth_repo"]), str(temp_project["api_repo"])]}
        )

        files = await analyzer.get_project_files(scope=["main", "namespace:company.auth"])

        file_names = {f.name for f in files}
        # Should include main project files
        assert "main.py" in file_names
        assert "utils.py" in file_names
        # Should include auth namespace files
        assert "models.py" in file_names
        assert "views.py" in file_names
        # Should NOT include other namespace files
        assert "endpoints.py" not in file_names
        assert "validators.py" not in file_names
        # Should NOT include package files
        assert "helpers.py" not in file_names

    async def test_get_project_files_with_pattern(self, temp_project):
        """Test getting files with a specific pattern."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        files = await analyzer.get_project_files(pattern="test_*.py", scope="main")

        file_names = {f.name for f in files}
        # Should only include test files
        assert "test_main.py" in file_names
        assert "test_utils.py" in file_names
        # Should NOT include non-test files
        assert "main.py" not in file_names
        assert "utils.py" not in file_names

    async def test_get_project_files_non_existent_namespace(self, temp_project):
        """Test handling of non-existent namespace."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        files = await analyzer.get_project_files(scope="namespace:nonexistent")

        # Should return empty list for non-existent namespace
        assert files == []

    async def test_get_project_files_non_existent_package(self, temp_project):
        """Test handling of non-existent package path."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        files = await analyzer.get_project_files(scope="package:/non/existent/path")

        # Should return empty list for non-existent package
        assert files == []

    async def test_namespace_directory_structure(self, temp_project):
        """Test proper namespace directory structure handling."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        # Test _get_namespace_directory_structure
        paths = analyzer._get_namespace_directory_structure(temp_project["auth_repo"])

        # The function should find the company directory within auth_repo
        # Since auth_repo doesn't have __init__.py at root, it should find the subdirectory
        assert len(paths) > 0
        # Check that it found the actual package directory
        path_names = {p.name for p in paths}
        # It should find either the repo itself or the company subdirectory
        assert "company" in path_names or "company-auth" in path_names

        # For namespace with actual package inside
        analyzer.set_namespace_paths({"company": [str(temp_project["auth_repo"])]})
        resolved = analyzer._resolve_namespace_scope("company")

        # Should find the company directory within the repo
        assert len(resolved) > 0

    async def test_resolve_scope_to_paths(self, temp_project):
        """Test scope resolution to filesystem paths."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))
        analyzer.set_additional_paths([temp_project["lib_package"]])
        analyzer.set_namespace_paths(
            {"company": [str(temp_project["auth_repo"]), str(temp_project["api_repo"])]}
        )

        # Test main scope
        paths = await analyzer._resolve_scope_to_paths("main")
        assert temp_project["main_project"] in paths
        assert len(paths) == 1

        # Test packages scope
        paths = await analyzer._resolve_scope_to_paths("packages")
        assert temp_project["lib_package"] in paths
        assert temp_project["main_project"] not in paths

        # Test all scope
        paths = await analyzer._resolve_scope_to_paths("all")
        assert temp_project["main_project"] in paths
        assert temp_project["lib_package"] in paths
        # Should include namespace paths (resolved to actual package dirs)
        assert len(paths) > 2

    def test_set_namespace_paths(self, temp_project):
        """Test setting namespace paths."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        namespaces = {
            "company": [str(temp_project["auth_repo"]), str(temp_project["api_repo"])],
            "utils": [str(temp_project["lib_package"])],
        }

        analyzer.set_namespace_paths(namespaces)

        assert "company" in analyzer.namespace_paths
        assert len(analyzer.namespace_paths["company"]) == 2
        assert "utils" in analyzer.namespace_paths
        assert len(analyzer.namespace_paths["utils"]) == 1

    def test_set_additional_paths(self, temp_project):
        """Test setting additional package paths."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        paths = [temp_project["lib_package"], temp_project["auth_repo"]]

        analyzer.set_additional_paths(paths)

        assert len(analyzer.additional_paths) == 2
        assert temp_project["lib_package"] in analyzer.additional_paths
        assert temp_project["auth_repo"] in analyzer.additional_paths


class TestProjectManagerIntegration:
    """Test ProjectManager integration with namespace support."""

    def test_get_analyzer_with_dependencies(self, temp_project):
        """Test get_analyzer configures dependencies correctly."""
        manager = ProjectManager()

        # Set up project with dependencies
        main_path = str(temp_project["main_project"])
        manager.get_project(main_path, [str(temp_project["lib_package"])])

        # Get configured analyzer
        analyzer = manager.get_analyzer(main_path)

        # Should have additional paths configured
        assert len(analyzer.additional_paths) == 1
        assert temp_project["lib_package"] in analyzer.additional_paths

    def test_get_analyzer_with_namespaces(self, temp_project):
        """Test get_analyzer configures namespaces correctly."""
        manager = ProjectManager()

        # Register namespaces
        manager.namespace_resolver.register_namespace(
            "company", [str(temp_project["auth_repo"]), str(temp_project["api_repo"])]
        )

        # Get configured analyzer
        analyzer = manager.get_analyzer(str(temp_project["main_project"]))

        # Should have namespace paths configured
        assert "company" in analyzer.namespace_paths
        assert len(analyzer.namespace_paths["company"]) == 2

    def test_get_analyzer_full_configuration(self, temp_project):
        """Test get_analyzer with both dependencies and namespaces."""
        manager = ProjectManager()

        # Set up project with dependencies
        main_path = str(temp_project["main_project"])
        manager.get_project(main_path, [str(temp_project["lib_package"])])

        # Register namespaces
        manager.namespace_resolver.register_namespace(
            "company", [str(temp_project["auth_repo"]), str(temp_project["api_repo"])]
        )

        # Get configured analyzer
        analyzer = manager.get_analyzer(main_path)

        # Should have both configured
        assert len(analyzer.additional_paths) == 1
        assert "company" in analyzer.namespace_paths


class TestScopeEdgeCases:
    """Test edge cases and error handling for scope resolution."""

    async def test_empty_scope_list(self, temp_project):
        """Test handling of empty scope list."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        files = await analyzer.get_project_files(scope=[])

        # Empty scope list should return no files
        assert files == []

    async def test_unknown_scope_type(self, temp_project):
        """Test handling of unknown scope specification."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        with patch("pycodemcp.analyzers.jedi_analyzer.logger") as mock_logger:
            files = await analyzer.get_project_files(scope="unknown:something")

            # Should log warning about unknown scope
            mock_logger.warning.assert_called()
            # Should return empty list
            assert files == []

    async def test_duplicate_files_removed(self, temp_project):
        """Test that duplicate files are removed when multiple scopes overlap."""
        analyzer = JediAnalyzer(str(temp_project["main_project"]))

        # Use scopes that would include the same files
        files = await analyzer.get_project_files(scope=["main", "main"])

        # Should not have duplicates
        file_paths = [str(f) for f in files]
        assert len(file_paths) == len(set(file_paths))

    async def test_namespace_without_subdirectory(self, temp_project):
        """Test namespace package without expected subdirectory structure."""
        # Create a flat namespace package
        flat_ns = temp_project["root"] / "flat_namespace"
        flat_ns.mkdir()
        (flat_ns / "__init__.py").touch()
        (flat_ns / "module.py").write_text("# Module")

        analyzer = JediAnalyzer(str(temp_project["main_project"]))
        analyzer.set_namespace_paths({"flat": [str(flat_ns)]})

        files = await analyzer.get_project_files(scope="namespace:flat")

        file_names = {f.name for f in files}
        # Should still find files in the flat structure
        assert "module.py" in file_names


class TestPerformance:
    """Test performance characteristics of namespace file operations."""

    async def test_large_project_performance(self, temp_project):
        """Test performance with many files."""
        import time

        # Create many files
        large_dir = temp_project["root"] / "large_project"
        large_dir.mkdir()

        for i in range(100):
            (large_dir / f"module_{i}.py").write_text(f"# Module {i}")

        analyzer = JediAnalyzer(str(large_dir))

        start_time = time.time()
        files = await analyzer.get_project_files(scope="main")
        elapsed = time.time() - start_time

        assert len(files) == 100
        # Should complete reasonably quickly (under 1 second for 100 files)
        assert elapsed < 1.0

    async def test_multiple_namespace_performance(self, temp_project):
        """Test performance with multiple namespaces."""
        import time

        # Create multiple namespace repos
        namespaces = {}
        for i in range(5):
            ns_repo = temp_project["root"] / f"ns_repo_{i}"
            ns_repo.mkdir()
            ns_dir = ns_repo / "namespace" / f"part_{i}"
            ns_dir.mkdir(parents=True)

            for j in range(20):
                (ns_dir / f"module_{j}.py").write_text(f"# Module {j}")

            namespaces[f"namespace.part_{i}"] = [str(ns_repo)]

        analyzer = JediAnalyzer(str(temp_project["main_project"]))
        analyzer.set_namespace_paths(namespaces)

        start_time = time.time()
        _ = await analyzer.get_project_files(scope="all")
        elapsed = time.time() - start_time

        # Should handle multiple namespaces efficiently
        assert elapsed < 2.0
