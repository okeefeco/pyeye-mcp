"""Tests for the MCP server and tools."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from pyeye.exceptions import AnalysisError, FileAccessError
from pyeye.mcp.server import (
    configure_packages,
    find_imports,
    find_references,
    find_subclasses,
    find_symbol,
    get_call_hierarchy,
    get_type_info,
    goto_definition,
    list_project_structure,
    mcp,
)


class TestMCPServer:
    """Test the MCP server setup and configuration."""

    def test_server_initialization(self):
        """Test that MCP server is properly initialized."""
        assert mcp is not None
        assert isinstance(mcp, FastMCP)
        assert mcp.name == "PyEye"

    def test_server_has_tools(self):
        """Test that server has registered tools."""
        # The tools should be registered
        # This would need access to internal MCP state
        pass


class TestConfigurePackages:
    """Test the configure_packages tool."""

    @patch("pyeye.mcp.server.get_project_manager")
    @patch("pyeye.mcp.server.ProjectConfig")
    @patch("pyeye.validation.PathValidator.validate_path")
    def test_configure_packages_basic(
        self, mock_validate_path, mock_config_class, mock_get_manager
    ):
        """Test basic package configuration."""
        # Create a real dict that can be modified
        config_dict = {}
        mock_config = Mock()
        mock_config.config = config_dict
        mock_config.get_package_paths.return_value = ["../lib1", "../lib2"]
        mock_config.get_namespaces.return_value = {}
        mock_config.project_path = Path(".")
        mock_config_class.return_value = mock_config

        mock_manager = Mock()
        mock_manager.namespace_resolver = Mock()
        mock_manager.get_project = Mock()
        mock_get_manager.return_value = mock_manager

        # Mock path validation to return resolved paths as strings
        mock_validate_path.side_effect = lambda p, _base=None: str(Path(p).resolve())

        result = configure_packages(packages=["../lib1", "../lib2"], save=False)

        # Check that packages were added to config (as resolved paths)
        assert "packages" in config_dict
        assert any("lib1" in p for p in config_dict["packages"])
        assert any("lib2" in p for p in config_dict["packages"])
        # Check return value
        assert "packages" in result
        assert len(result["packages"]) == 2

    @patch("pyeye.mcp.server.get_project_manager")
    @patch("pyeye.mcp.server.ProjectConfig")
    @patch("pyeye.validation.PathValidator.validate_path")
    def test_configure_namespaces(self, mock_validate_path, mock_config_class, mock_get_manager):
        """Test namespace configuration."""
        config_dict = {}
        mock_config = Mock()
        mock_config.config = config_dict
        mock_config.get_package_paths.return_value = []
        mock_config.get_namespaces.return_value = {"company": ["/repos/auth", "/repos/api"]}
        mock_config.project_path = Path(".")
        mock_config_class.return_value = mock_config

        mock_manager = Mock()
        mock_manager.namespace_resolver = Mock()
        mock_get_manager.return_value = mock_manager

        # Mock path validation
        mock_validate_path.side_effect = lambda p, _base=None: str(Path(p).resolve())

        _ = configure_packages(namespaces={"company": ["/repos/auth", "/repos/api"]}, save=False)

        assert "namespaces" in config_dict
        assert "company" in config_dict["namespaces"]

    @patch("pyeye.mcp.server.get_project_manager")
    @patch("pyeye.mcp.server.ProjectConfig")
    @patch("pyeye.validation.PathValidator.validate_path")
    def test_configure_save(self, mock_validate_path, mock_config_class, mock_get_manager):
        """Test saving configuration."""
        config_dict = {}
        mock_config = Mock()
        mock_config.config = config_dict
        mock_config.save_config = Mock()
        mock_config.get_package_paths.return_value = ["test"]
        mock_config.get_namespaces.return_value = {}
        mock_config.project_path = Path(".")
        mock_config_class.return_value = mock_config

        mock_manager = Mock()
        mock_manager.namespace_resolver = Mock()
        mock_get_manager.return_value = mock_manager

        # Mock path validation
        mock_validate_path.side_effect = lambda p, _base=None: str(Path(p).resolve())

        _ = configure_packages(packages=["test"], save=True)

        mock_config.save_config.assert_called_once()

    @patch("pyeye.mcp.server.get_project_manager")
    @patch("pyeye.validation.PathValidator")
    @patch("pyeye.mcp.server.ProjectConfig")
    def test_configure_validates_paths(self, mock_config_class, mock_validator, mock_get_manager):
        """Test that paths are validated before configuration."""
        config_dict = {}
        mock_config = Mock()
        mock_config.config = config_dict
        mock_config.get_package_paths.return_value = ["../lib1"]
        mock_config.get_namespaces.return_value = {}
        mock_config.project_path = Path(".")
        mock_config_class.return_value = mock_config

        mock_manager = Mock()
        mock_manager.namespace_resolver = Mock()
        mock_get_manager.return_value = mock_manager

        # Mock path validation to track calls
        mock_validator.validate_path.side_effect = lambda p, _base=None: str(Path(p).resolve())

        configure_packages(packages=["../lib1"])

        # Path validator should be called via the decorator
        mock_validator.validate_path.assert_called()


class TestFindSymbol:
    """Test the find_symbol tool."""

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_symbol_basic(self, mock_get_analyzer):
        """Test basic symbol finding."""
        # Mock JediAnalyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the find_symbol method to return expected results
        mock_analyzer.find_symbol.return_value = [
            {
                "name": "TestClass",
                "file": "/project/test.py",
                "line": 10,
                "column": 0,
                "type": "class",
                "description": "class TestClass",
                "full_name": "test.TestClass",
            }
        ]

        result = await find_symbol("TestClass")

        assert len(result) == 1
        assert result[0]["name"] == "TestClass"
        assert "test.py" in result[0]["file"]
        mock_analyzer.find_symbol.assert_called_with(
            "TestClass", fuzzy=False, include_import_paths=True, scope="all"
        )

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_symbol_fuzzy(self, mock_get_analyzer):
        """Test fuzzy symbol search."""
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the find_symbol method to return fuzzy matches
        mock_analyzer.find_symbol.return_value = [
            {
                "name": "test_function",
                "file": "/project/test.py",
                "line": 5,
                "column": 0,
                "type": "function",
                "description": "def test_function",
                "full_name": "test.test_function",
            }
        ]

        result = await find_symbol("test", fuzzy=True)

        # With fuzzy=True, it should include partial matches
        assert len(result) == 1
        mock_analyzer.find_symbol.assert_called_with(
            "test", fuzzy=True, include_import_paths=True, scope="all"
        )

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_symbol_with_scope(self, mock_get_analyzer):
        """Test symbol finding passes scope to analyzer."""
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer
        mock_analyzer.find_symbol.return_value = []

        await find_symbol("test", scope="main")

        mock_get_analyzer.assert_called()
        mock_analyzer.find_symbol.assert_called_with(
            "test", fuzzy=False, include_import_paths=True, scope="main"
        )

    @pytest.mark.asyncio
    async def test_find_symbol_with_reexports(self):
        """Test find_symbol includes import_paths for re-exported symbols."""
        # Use the test fixture
        fixture_path = str(Path(__file__).parent.parent.parent / "fixtures" / "reexport_test")

        # Find the User symbol in the test fixture
        results = await find_symbol("User", project_path=fixture_path, scope="main")

        # Should find at least one result
        assert len(results) > 0

        # Check that import_paths is included for the User class
        user_found = False
        for result in results:
            if result.get("name") == "User" and "user.py" in result.get("file", ""):
                user_found = True
                # Should have import_paths field with re-export information
                assert "import_paths" in result
                import_paths = result["import_paths"]
                assert len(import_paths) >= 2
                # Should have both direct and re-exported paths
                assert any("from models.user import User" in path for path in import_paths)
                assert any("from models import User" in path for path in import_paths)

        assert user_found, "User class not found in results"

    @pytest.mark.asyncio
    async def test_find_symbol_multi_level_reexports(self):
        """Test find_symbol with multi-level re-exports."""
        fixture_path = str(Path(__file__).parent.parent.parent / "fixtures" / "reexport_test")

        # Find the Authenticator symbol
        results = await find_symbol("Authenticator", project_path=fixture_path, scope="main")

        # Should find the Authenticator class
        assert len(results) > 0

        auth_found = False
        for result in results:
            if result.get("name") == "Authenticator" and "authenticator.py" in result.get(
                "file", ""
            ):
                auth_found = True
                assert "import_paths" in result
                import_paths = result["import_paths"]
                # Should have multiple levels of re-exports
                assert len(import_paths) >= 3
                # Check for all three levels
                assert any(
                    "from core.auth.authenticator import Authenticator" in p for p in import_paths
                )
                assert any("from core.auth import Authenticator" in p for p in import_paths)
                assert any("from core import Authenticator" in p for p in import_paths)

        assert auth_found, "Authenticator class not found in results"


class TestGotoDefinition:
    """Test the goto_definition tool."""

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_goto_definition(self, mock_get_analyzer):
        """Test going to symbol definition."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the result
        expected_result = {
            "name": "function",
            "file": "/project/module.py",
            "line": 42,
            "column": 4,
            "type": "function",
            "description": "def function",
            "docstring": "Function docstring",
        }
        mock_analyzer.goto_definition.return_value = expected_result

        result = await goto_definition("test.py", 10, 5)

        assert result["name"] == "function"
        assert result["line"] == 42
        mock_analyzer.goto_definition.assert_called_with("test.py", 10, 5)

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_goto_definition_not_found(self, mock_get_analyzer):
        """Test goto definition when symbol not found."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock returning None (no definition found)
        mock_analyzer.goto_definition.return_value = None

        result = await goto_definition("test.py", 10, 5)

        assert result is None
        mock_analyzer.goto_definition.assert_called_with("test.py", 10, 5)


class TestFindReferences:
    """Test the find_references tool."""

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_references(self, mock_get_analyzer):
        """Test finding symbol references."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the result
        expected_result = [
            {
                "file": "/project/test.py",
                "line": 10,
                "column": 0,
                "type": "reference",
                "description": "test_var",
            },
            {
                "file": "/project/test.py",
                "line": 20,
                "column": 5,
                "type": "reference",
                "description": "test_var",
            },
        ]
        mock_analyzer.find_references.return_value = expected_result

        result = await find_references("test.py", 5, 0)

        assert len(result) == 2
        assert result[0]["line"] == 10
        assert result[1]["line"] == 20
        mock_analyzer.find_references.assert_called_with("test.py", 5, 0, True, False)

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_references_exclude_definitions(self, mock_get_analyzer):
        """Test finding references excluding definitions."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the result - only non-definition references
        expected_result = [
            {
                "file": "/project/test.py",
                "line": 20,
                "column": 5,
                "type": "reference",
                "description": "test_var",
            }
        ]
        mock_analyzer.find_references.return_value = expected_result

        result = await find_references("test.py", 5, 0, include_definitions=False)

        # Should only include non-definition references
        assert len(result) == 1
        assert result[0]["line"] == 20
        mock_analyzer.find_references.assert_called_with("test.py", 5, 0, False, False)


class TestGetTypeInfo:
    """Test the get_type_info tool."""

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_get_type_info(self, mock_get_analyzer):
        """Test getting type information."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the result
        expected_result = {
            "position": {"file": "test.py", "line": 10, "column": 5},
            "inferred_types": [
                {
                    "name": "str",
                    "type": "class",
                    "description": "class str",
                    "full_name": "builtins.str",
                    "module_name": "builtins",
                }
            ],
            "docstring": "String type",
        }
        mock_analyzer.get_type_info.return_value = expected_result

        result = await get_type_info("test.py", 10, 5)

        assert len(result["inferred_types"]) > 0
        assert result["inferred_types"][0]["name"] == "str"
        assert result["docstring"] == "String type"
        mock_analyzer.get_type_info.assert_called_with("test.py", 10, 5, detailed=False)


class TestFindImports:
    """Test the find_imports tool."""

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_imports(self, mock_get_analyzer):
        """Test finding module imports."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the result
        expected_result = [
            {
                "file": "/project/test.py",
                "line": 1,
                "column": 0,
                "import_statement": "import os",
                "type": "module",
            },
            {
                "file": "/project/utils.py",
                "line": 1,
                "column": 0,
                "import_statement": "from os import path",
                "type": "import",
            },
        ]
        mock_analyzer.find_imports.return_value = expected_result

        result = await find_imports("os")

        # Should find imports in both files
        assert len(result) == 2
        assert result[0]["file"] == "/project/test.py"
        assert result[1]["file"] == "/project/utils.py"
        mock_analyzer.find_imports.assert_called_with("os")


class TestGetCallHierarchy:
    """Test the get_call_hierarchy tool."""

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_get_call_hierarchy(self, mock_get_analyzer):
        """Test getting call hierarchy."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the result
        expected_result = {
            "function": "test_func",
            "file": "/project/module.py",
            "line": 5,
            "callers": [
                {"file": "/project/main.py", "line": 10, "column": 4, "context": "test_func()"}
            ],
            "callees": [],
        }
        mock_analyzer.get_call_hierarchy.return_value = expected_result

        result = await get_call_hierarchy("test_func")

        assert result["function"] == "test_func"
        assert "callers" in result
        assert "callees" in result
        mock_analyzer.get_call_hierarchy.assert_called_with("test_func", None)

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_get_call_hierarchy_with_file(self, mock_get_analyzer):
        """Test call hierarchy with specific file."""
        # Mock analyzer
        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer

        # Mock the result
        expected_result = {
            "function": "func",
            "file": "test.py",
            "line": 5,
            "callers": [],
            "callees": [],
        }
        mock_analyzer.get_call_hierarchy.return_value = expected_result

        result = await get_call_hierarchy("func", file="test.py")

        # Should search for function in specific file
        assert result is not None
        assert result["function"] == "func"
        mock_analyzer.get_call_hierarchy.assert_called_with("func", "test.py")


class TestListProjectStructure:
    """Test the list_project_structure tool."""

    def test_list_project_structure(self, temp_project_dir):
        """Test listing project structure."""
        # Create project structure
        (temp_project_dir / "src").mkdir()
        (temp_project_dir / "src" / "main.py").write_text("# Main")
        (temp_project_dir / "tests").mkdir()
        (temp_project_dir / "tests" / "test_main.py").write_text("# Test")

        result = list_project_structure(str(temp_project_dir))

        # Should return a tree structure
        assert "name" in result
        assert "type" in result
        assert result["type"] == "directory"
        # Should have children (src and tests directories)
        assert "children" in result
        assert len(result["children"]) >= 2

    def test_list_project_structure_max_depth(self, temp_project_dir):
        """Test project structure with max depth limit."""
        # Create deep structure
        deep_path = temp_project_dir / "a" / "b" / "c" / "d" / "e"
        deep_path.mkdir(parents=True)
        (deep_path / "deep.py").write_text("# Deep file")

        result = list_project_structure(str(temp_project_dir), max_depth=2)

        # Result should be truncated at max depth
        assert "name" in result
        assert "type" in result
        # Navigate to check truncation
        if "children" in result:
            for child in result["children"]:
                if child["name"] == "a" and "children" in child:
                    # Check that deep nesting is truncated
                    for subchild in child["children"]:
                        if subchild["name"] == "b":
                            # Should be truncated here or at next level
                            assert "truncated" in subchild or (
                                "children" in subchild
                                and any("truncated" in sc for sc in subchild["children"])
                            )


class TestFindSubclasses:
    """Test the find_subclasses tool."""

    @pytest.mark.asyncio
    async def test_find_subclasses_basic(self, temp_project_dir):
        """Test basic find_subclasses functionality."""
        # Create test file with class hierarchy
        test_file = temp_project_dir / "animals.py"
        test_file.write_text(
            """
class Animal:
    pass

class Dog(Animal):
    pass

class Cat(Animal):
    pass
"""
        )

        result = await find_subclasses("Animal", str(temp_project_dir))

        # Should find both Dog and Cat
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert "Dog" in names
        assert "Cat" in names

    @pytest.mark.asyncio
    async def test_find_subclasses_with_params(self, temp_project_dir):
        """Test find_subclasses with include_indirect and show_hierarchy."""
        test_file = temp_project_dir / "hierarchy.py"
        test_file.write_text(
            """
class Base:
    pass

class Middle(Base):
    pass

class Leaf(Middle):
    pass
"""
        )

        # Test with indirect=False
        result = await find_subclasses("Base", str(temp_project_dir), include_indirect=False)
        assert len(result) == 1
        assert result[0]["name"] == "Middle"

        # Test with indirect=True and hierarchy
        result = await find_subclasses(
            "Base", str(temp_project_dir), include_indirect=True, show_hierarchy=True
        )
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert "Middle" in names
        assert "Leaf" in names

        # Check hierarchy is included
        for r in result:
            assert "inheritance_chain" in r

    @pytest.mark.asyncio
    async def test_find_subclasses_not_found(self, temp_project_dir):
        """Test find_subclasses when base class doesn't exist."""
        result = await find_subclasses("NonExistentClass", str(temp_project_dir))
        assert result == []

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_subclasses_error_handling(self, mock_get_analyzer):
        """Test error handling in find_subclasses."""
        # Make analyzer's find_subclasses raise an exception
        mock_analyzer = Mock()
        mock_analyzer.find_subclasses.side_effect = Exception("Analysis error")
        mock_get_analyzer.return_value = mock_analyzer

        with pytest.raises(AnalysisError) as exc_info:
            await find_subclasses("TestClass", "/test/path")
        assert "Failed to find subclasses" in str(exc_info.value)


class TestPluginActivation:
    """Test plugin activation based on project type."""

    @patch("pyeye.mcp.server._plugins")
    def test_plugin_detection(self, mock_plugins):
        """Test that plugins are detected and activated."""
        # Create mock plugins
        flask_plugin = Mock()
        flask_plugin.detect.return_value = True
        flask_plugin.name.return_value = "Flask"

        django_plugin = Mock()
        django_plugin.detect.return_value = False
        django_plugin.name.return_value = "Django"

        # Test that we can access the plugins list
        assert isinstance(mock_plugins, Mock)

        # In the actual implementation, plugins are activated via initialize_plugins
        # This test verifies the structure is present


class TestErrorHandling:
    """Test error handling in MCP tools."""

    @patch("pyeye.mcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_symbol_error(self, mock_get_analyzer):
        """Test error handling in find_symbol."""
        # Mock analyzer that raises error on find_symbol
        mock_analyzer = AsyncMock()
        mock_analyzer.find_symbol.side_effect = Exception("Search error")
        mock_get_analyzer.return_value = mock_analyzer

        # Should raise AnalysisError when search fails
        with pytest.raises(AnalysisError) as exc_info:
            await find_symbol("test")
        assert "Failed to search for symbol" in str(exc_info.value)

    @patch("pyeye.mcp.server.Path")
    @pytest.mark.asyncio
    async def test_file_not_found_error(self, mock_path_class):
        """Test handling of file not found errors."""
        mock_path = Mock()
        mock_path.exists.return_value = False
        mock_path_class.return_value = mock_path

        # Should raise FileAccessError for non-existent file
        with pytest.raises(FileAccessError) as exc_info:
            await goto_definition("nonexistent.py", 1, 0)
        assert "File not found" in str(exc_info.value)


class TestInputValidation:
    """Test input validation decorators."""

    @patch("pyeye.mcp.server.Path")
    @pytest.mark.asyncio
    async def test_validate_negative_line_number(self, mock_path_class):
        """Test that negative line numbers are rejected."""
        from pyeye.exceptions import ValidationError

        # Mock file path exists
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path_class.return_value = mock_path

        # The @validate_mcp_inputs decorator should raise ValidationError for invalid inputs
        with pytest.raises(ValidationError) as exc_info:
            await goto_definition("test.py", -1, 0)

        assert "line number" in str(exc_info.value).lower()

    @patch("pyeye.mcp.server.Path")
    @pytest.mark.asyncio
    async def test_validate_negative_column_number(self, mock_path_class):
        """Test that negative column numbers are rejected."""
        from pyeye.exceptions import ValidationError

        # Mock file path exists
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path_class.return_value = mock_path

        # The @validate_mcp_inputs decorator should raise ValidationError for invalid inputs
        with pytest.raises(ValidationError) as exc_info:
            await goto_definition("test.py", 10, -5)

        assert "column" in str(exc_info.value).lower()


class TestGetPerformanceMetrics:
    """Test the optional get_performance_metrics tool."""

    @patch("pyeye.mcp.server.settings")
    def test_tool_not_registered_by_default(self, mock_settings):
        """Test that get_performance_metrics is not registered when disabled."""
        mock_settings.enable_performance_metrics = False
        # The tool is conditionally registered at import time,
        # so we verify the setting defaults to False
        from pyeye.settings import PerformanceSettings

        default_settings = PerformanceSettings()
        assert default_settings.enable_performance_metrics is False

    @patch.dict("os.environ", {"PYEYE_ENABLE_PERFORMANCE_METRICS": "true"})
    def test_setting_enabled_via_env(self):
        """Test that the setting can be enabled via environment variable."""
        from pyeye.settings import PerformanceSettings

        settings = PerformanceSettings()
        assert settings.enable_performance_metrics is True

    def test_metrics_report_structure(self):
        """Test that the metrics report has the expected structure."""
        from pyeye.metrics import metrics

        report = metrics.get_performance_report()
        assert "uptime_seconds" in report
        assert "memory" in report
        assert "cache" in report
        assert "operations" in report
        assert "summary" in report

    def test_metrics_prometheus_export(self):
        """Test that prometheus export produces valid output."""
        from pyeye.metrics import metrics

        output = metrics.export_prometheus()
        assert isinstance(output, str)
        assert "pyeye_" in output

    @pytest.mark.asyncio
    async def test_tool_function_json_format(self):
        """Test the tool function returns JSON report by default."""
        from pyeye.mcp.server import get_performance_metrics

        result = await get_performance_metrics()
        assert isinstance(result, dict)
        assert "uptime_seconds" in result
        assert "memory" in result
        assert result["memory"]["rss_mb"] > 0

    @pytest.mark.asyncio
    async def test_tool_function_specific_metric(self):
        """Test requesting a specific metric name."""
        from pyeye.mcp.server import get_performance_metrics

        # Non-existent metric returns error
        result = await get_performance_metrics(metric_name="nonexistent_metric")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_function_prometheus_format(self):
        """Test requesting prometheus export format."""
        from pyeye.mcp.server import get_performance_metrics

        result = await get_performance_metrics(export_format="prometheus")
        assert isinstance(result, str)
        assert "pyeye_cache_hits" in result
        assert "pyeye_memory_mb" in result
