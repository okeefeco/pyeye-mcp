"""Test coverage for plugin base class."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.plugins.base import AnalyzerPlugin


class ConcretePlugin(AnalyzerPlugin):
    """Concrete implementation for testing."""

    def name(self) -> str:
        """Return plugin name."""
        return "test-plugin"

    def detect(self) -> bool:
        """Detection logic."""
        return True


class FailingPlugin(AnalyzerPlugin):
    """Plugin that fails detection."""

    def name(self) -> str:
        """Return plugin name."""
        return "failing-plugin"

    def detect(self) -> bool:
        """Detection that always fails."""
        return False


class ErrorPlugin(AnalyzerPlugin):
    """Plugin that raises errors."""

    def name(self) -> str:
        """Return plugin name."""
        return "error-plugin"

    def detect(self) -> bool:
        """Detection that raises error."""
        raise RuntimeError("Detection failed")


class PluginWithTools(AnalyzerPlugin):
    """Plugin that registers tools."""

    def name(self) -> str:
        """Return plugin name."""
        return "tools-plugin"

    def detect(self) -> bool:
        """Detection logic."""
        return True

    def register_tools(self):
        """Register custom tools."""

        def custom_tool():
            return "tool_result"

        return {"custom_tool": custom_tool}


class PluginWithAugmentation(AnalyzerPlugin):
    """Plugin that augments results."""

    def name(self) -> str:
        """Return plugin name."""
        return "augment-plugin"

    def detect(self) -> bool:
        """Detection logic."""
        return True

    def augment_symbol_results(self, results):
        """Augment symbol results."""
        for result in results:
            result["augmented"] = True
        return results


class PluginWithPatterns(AnalyzerPlugin):
    """Plugin that finds patterns."""

    def name(self) -> str:
        """Return plugin name."""
        return "pattern-plugin"

    def detect(self) -> bool:
        """Detection logic."""
        return True

    def find_patterns(self, pattern_name):
        """Find specific patterns."""
        if pattern_name == "test_pattern":
            return [{"type": "pattern", "name": pattern_name}]
        return []


class PluginWithComponents(AnalyzerPlugin):
    """Plugin that provides framework components."""

    def name(self) -> str:
        """Return plugin name."""
        return "component-plugin"

    def detect(self) -> bool:
        """Detection logic."""
        return True

    def get_framework_components(self):
        """Get framework components."""
        return {"models": ["model1.py", "model2.py"], "views": ["view1.py", "view2.py"]}


@pytest.mark.asyncio
class TestAnalyzerPlugin:
    """Test the AnalyzerPlugin base class."""

    def test_abstract_methods_must_be_implemented(self):
        """Test that abstract methods must be implemented."""
        with pytest.raises(TypeError) as exc_info:
            # Can't instantiate abstract class without implementing abstract methods
            AnalyzerPlugin("/test/path")

        assert "Can't instantiate abstract class" in str(exc_info.value)

    def test_concrete_plugin_initialization(self, tmp_path):
        """Test concrete plugin initialization."""
        plugin = ConcretePlugin(str(tmp_path))

        assert plugin.project_path == tmp_path
        assert plugin.additional_paths == []
        assert plugin.namespace_paths == {}
        assert plugin.name() == "test-plugin"
        assert plugin.detect() is True

    def test_plugin_detection_variations(self, tmp_path):
        """Test different detection scenarios."""
        # Plugin that detects successfully
        plugin1 = ConcretePlugin(str(tmp_path))
        assert plugin1.detect() is True

        # Plugin that fails detection
        plugin2 = FailingPlugin(str(tmp_path))
        assert plugin2.detect() is False

        # Plugin that raises error during detection
        plugin3 = ErrorPlugin(str(tmp_path))
        with pytest.raises(RuntimeError, match="Detection failed"):
            plugin3.detect()

    def test_register_tools_default(self, tmp_path):
        """Test default register_tools returns empty dict."""
        plugin = ConcretePlugin(str(tmp_path))
        tools = plugin.register_tools()

        assert tools == {}
        assert isinstance(tools, dict)

    def test_register_tools_with_custom_tools(self, tmp_path):
        """Test plugin that registers custom tools."""
        plugin = PluginWithTools(str(tmp_path))
        tools = plugin.register_tools()

        assert "custom_tool" in tools
        assert callable(tools["custom_tool"])
        assert tools["custom_tool"]() == "tool_result"

    def test_augment_symbol_results_default(self, tmp_path):
        """Test default augment_symbol_results returns unchanged results."""
        plugin = ConcretePlugin(str(tmp_path))
        original_results = [{"name": "symbol1"}, {"name": "symbol2"}]
        results = plugin.augment_symbol_results(original_results.copy())

        assert results == original_results

    def test_augment_symbol_results_with_modification(self, tmp_path):
        """Test plugin that augments symbol results."""
        plugin = PluginWithAugmentation(str(tmp_path))
        original_results = [{"name": "symbol1"}, {"name": "symbol2"}]
        results = plugin.augment_symbol_results(original_results.copy())

        assert len(results) == 2
        assert all(r["augmented"] is True for r in results)
        assert results[0]["name"] == "symbol1"
        assert results[1]["name"] == "symbol2"

    def test_find_patterns_default(self, tmp_path):
        """Test default find_patterns returns empty list."""
        plugin = ConcretePlugin(str(tmp_path))
        patterns = plugin.find_patterns("any_pattern")

        assert patterns == []
        assert isinstance(patterns, list)

    def test_find_patterns_with_matches(self, tmp_path):
        """Test plugin that finds patterns."""
        plugin = PluginWithPatterns(str(tmp_path))

        # Pattern that matches
        patterns = plugin.find_patterns("test_pattern")
        assert len(patterns) == 1
        assert patterns[0]["type"] == "pattern"
        assert patterns[0]["name"] == "test_pattern"

        # Pattern that doesn't match
        patterns = plugin.find_patterns("unknown_pattern")
        assert patterns == []

    def test_get_framework_components_default(self, tmp_path):
        """Test default get_framework_components returns empty dict."""
        plugin = ConcretePlugin(str(tmp_path))
        components = plugin.get_framework_components()

        assert components == {}
        assert isinstance(components, dict)

    def test_get_framework_components_with_data(self, tmp_path):
        """Test plugin that provides framework components."""
        plugin = PluginWithComponents(str(tmp_path))
        components = plugin.get_framework_components()

        assert "models" in components
        assert "views" in components
        assert len(components["models"]) == 2
        assert len(components["views"]) == 2
        assert "model1.py" in components["models"]
        assert "view1.py" in components["views"]

    def test_set_additional_paths(self, tmp_path, caplog):
        """Test setting additional paths."""
        plugin = ConcretePlugin(str(tmp_path))

        path1 = tmp_path / "path1"
        path2 = tmp_path / "path2"
        path1.mkdir()
        path2.mkdir()

        with caplog.at_level(logging.INFO):
            plugin.set_additional_paths([path1, path2])

        assert len(plugin.additional_paths) == 2
        assert path1 in plugin.additional_paths
        assert path2 in plugin.additional_paths
        assert "Set 2 additional paths" in caplog.text

    def test_set_namespace_paths(self, tmp_path, caplog):
        """Test setting namespace paths."""
        plugin = ConcretePlugin(str(tmp_path))

        ns_path1 = tmp_path / "ns1"
        ns_path2 = tmp_path / "ns2"
        ns_path1.mkdir()
        ns_path2.mkdir()

        namespaces = {"namespace1": [str(ns_path1)], "namespace2": [str(ns_path2)]}

        with caplog.at_level(logging.INFO):
            plugin.set_namespace_paths(namespaces)

        assert len(plugin.namespace_paths) == 2
        assert "namespace1" in plugin.namespace_paths
        assert "namespace2" in plugin.namespace_paths
        assert plugin.namespace_paths["namespace1"] == [ns_path1]
        assert plugin.namespace_paths["namespace2"] == [ns_path2]
        assert "Set 2 namespace mappings" in caplog.text

    async def test_get_project_files_main_scope(self, tmp_path):
        """Test get_project_files with main scope."""
        plugin = ConcretePlugin(str(tmp_path))

        # Create test files
        (tmp_path / "file1.py").touch()
        (tmp_path / "file2.py").touch()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file3.py").touch()

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.return_value = [
                tmp_path / "file1.py",
                tmp_path / "file2.py",
                subdir / "file3.py",
            ]

            files = await plugin.get_project_files("*.py", scope="main")

            assert len(files) == 3
            assert tmp_path / "file1.py" in files
            assert tmp_path / "file2.py" in files
            assert subdir / "file3.py" in files
            mock_rglob.assert_called_once_with("*.py", tmp_path)

    async def test_get_project_files_all_scope(self, tmp_path):
        """Test get_project_files with all scope."""
        plugin = ConcretePlugin(str(tmp_path))

        # Set up additional paths and namespaces
        add_path = tmp_path / "additional"
        add_path.mkdir()
        plugin.additional_paths = [add_path]

        ns_path = tmp_path / "namespace"
        ns_path.mkdir()
        plugin.namespace_paths = {"ns": [ns_path]}

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.side_effect = [
                [tmp_path / "main.py"],
                [add_path / "additional.py"],
                [ns_path / "namespace.py"],
            ]

            files = await plugin.get_project_files("*.py", scope="all")

            assert len(files) == 3
            assert tmp_path / "main.py" in files
            assert add_path / "additional.py" in files
            assert ns_path / "namespace.py" in files
            assert mock_rglob.call_count == 3

    async def test_get_project_files_namespace_scope(self, tmp_path):
        """Test get_project_files with namespace scope."""
        plugin = ConcretePlugin(str(tmp_path))

        ns_path = tmp_path / "namespace"
        ns_path.mkdir()
        plugin.namespace_paths = {"test_ns": [ns_path]}

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.return_value = [ns_path / "file.py"]

            files = await plugin.get_project_files("*.py", scope="namespace:test_ns")

            assert len(files) == 1
            assert ns_path / "file.py" in files
            mock_rglob.assert_called_once_with("*.py", ns_path)

    async def test_get_project_files_unknown_namespace(self, tmp_path, caplog):
        """Test get_project_files with unknown namespace."""
        plugin = ConcretePlugin(str(tmp_path))

        with caplog.at_level(logging.WARNING):
            files = await plugin.get_project_files("*.py", scope="namespace:unknown")

            assert files == []
            assert "Namespace not found: unknown" in caplog.text

    async def test_get_project_files_package_scope(self, tmp_path):
        """Test get_project_files with package scope."""
        plugin = ConcretePlugin(str(tmp_path))

        pkg_path = tmp_path / "package"
        pkg_path.mkdir()
        (pkg_path / "module.py").touch()

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.return_value = [pkg_path / "module.py"]

            files = await plugin.get_project_files("*.py", scope=f"package:{pkg_path}")

            assert len(files) == 1
            assert pkg_path / "module.py" in files

    async def test_get_project_files_nonexistent_package(self, tmp_path, caplog):
        """Test get_project_files with non-existent package path."""
        plugin = ConcretePlugin(str(tmp_path))

        with caplog.at_level(logging.WARNING):
            files = await plugin.get_project_files("*.py", scope="package:/nonexistent/path")

            assert files == []
            assert "Package path does not exist" in caplog.text

    async def test_get_project_files_multiple_scopes(self, tmp_path):
        """Test get_project_files with multiple scopes."""
        plugin = ConcretePlugin(str(tmp_path))

        # Set up additional path
        add_path = tmp_path / "additional"
        add_path.mkdir()
        plugin.additional_paths = [add_path]

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.side_effect = [[tmp_path / "main.py"], [add_path / "additional.py"]]

            files = await plugin.get_project_files("*.py", scope=["main", "packages"])

            assert len(files) == 2
            assert tmp_path / "main.py" in files
            assert add_path / "additional.py" in files

    async def test_get_project_files_error_handling(self, tmp_path, caplog):
        """Test get_project_files handles errors gracefully."""
        plugin = ConcretePlugin(str(tmp_path))

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.side_effect = Exception("Search failed")

            with caplog.at_level(logging.WARNING):
                files = await plugin.get_project_files("*.py", scope="main")

                assert files == []
                assert "Error searching" in caplog.text
                assert "Search failed" in caplog.text

    async def test_get_project_files_removes_duplicates(self, tmp_path):
        """Test get_project_files removes duplicate files."""
        plugin = ConcretePlugin(str(tmp_path))

        file1 = tmp_path / "file1.py"
        file1.touch()

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            # Return same file multiple times
            mock_rglob.return_value = [file1, file1, file1]

            files = await plugin.get_project_files("*.py", scope="main")

            assert len(files) == 1
            assert files[0] == file1

    async def test_get_project_files_filters_namespace_subdirs(self, tmp_path):
        """Test get_project_files filters namespace subdirectories in main scope."""
        plugin = ConcretePlugin(str(tmp_path))

        # Create namespace as subdirectory of main project
        ns_subdir = tmp_path / "namespace_pkg"
        ns_subdir.mkdir()
        plugin.namespace_paths = {"ns": [ns_subdir]}

        main_file = tmp_path / "main.py"
        main_file.touch()
        ns_file = ns_subdir / "ns_module.py"
        ns_file.touch()

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.return_value = [main_file, ns_file]

            files = await plugin.get_project_files("*.py", scope="main")

            # Should exclude namespace subdirectory files
            assert len(files) == 1
            assert main_file in files
            assert ns_file not in files

    async def test_resolve_scope_to_paths_unknown_scope(self, tmp_path, caplog):
        """Test _resolve_scope_to_paths with unknown scope."""
        plugin = ConcretePlugin(str(tmp_path))

        with caplog.at_level(logging.WARNING):
            paths = await plugin._resolve_scope_to_paths("unknown_scope")

            assert len(paths) == 0
            assert "Unknown scope specification: unknown_scope" in caplog.text

    async def test_get_scope_roots(self, tmp_path):
        """Test _get_scope_roots helper method."""
        plugin = ConcretePlugin(str(tmp_path))

        add_path = tmp_path / "additional"
        add_path.mkdir()
        plugin.additional_paths = [add_path]

        roots = await plugin._get_scope_roots("all")

        assert tmp_path in roots
        assert add_path in roots
        assert len(roots) >= 2

    def test_plugin_with_path_string(self):
        """Test plugin initialization with string path."""
        plugin = ConcretePlugin("/test/path/as/string")

        assert plugin.project_path == Path("/test/path/as/string")
        assert isinstance(plugin.project_path, Path)

    def test_plugin_methods_return_types(self, tmp_path):
        """Test that all methods return expected types."""
        plugin = ConcretePlugin(str(tmp_path))

        # Test return types
        assert isinstance(plugin.name(), str)
        assert isinstance(plugin.detect(), bool)
        assert isinstance(plugin.register_tools(), dict)
        assert isinstance(plugin.augment_symbol_results([]), list)
        assert isinstance(plugin.find_patterns("test"), list)
        assert isinstance(plugin.get_framework_components(), dict)

    async def test_get_project_files_with_empty_namespace_paths(self, tmp_path):
        """Test get_project_files when namespace has empty path list."""
        plugin = ConcretePlugin(str(tmp_path))
        plugin.namespace_paths = {"empty_ns": []}

        with patch("pycodemcp.async_utils.rglob_async") as mock_rglob:
            mock_rglob.return_value = []

            files = await plugin.get_project_files("*.py", scope="namespace:empty_ns")

            assert files == []
            # Should not call rglob since no paths
            mock_rglob.assert_not_called()

    def test_set_additional_paths_empty(self, tmp_path):
        """Test setting empty additional paths."""
        plugin = ConcretePlugin(str(tmp_path))
        plugin.set_additional_paths([])

        assert plugin.additional_paths == []

    def test_set_namespace_paths_empty(self, tmp_path):
        """Test setting empty namespace paths."""
        plugin = ConcretePlugin(str(tmp_path))
        plugin.set_namespace_paths({})

        assert plugin.namespace_paths == {}
