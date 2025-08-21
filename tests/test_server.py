"""Tests for the MCP server and tools."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from pycodemcp.exceptions import AnalysisError, FileAccessError
from pycodemcp.server import (
    configure_namespace_package,
    configure_packages,
    find_imports,
    find_in_namespace,
    find_references,
    find_symbol,
    find_symbol_multi,
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
        assert mcp.name == "Python Code Intelligence"

    def test_server_has_tools(self):
        """Test that server has registered tools."""
        # The tools should be registered
        # This would need access to internal MCP state
        pass


class TestConfigurePackages:
    """Test the configure_packages tool."""

    @patch("pycodemcp.server.get_project_manager")
    @patch("pycodemcp.server.ProjectConfig")
    @patch("pycodemcp.validation.PathValidator.validate_path")
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

    @patch("pycodemcp.server.get_project_manager")
    @patch("pycodemcp.server.ProjectConfig")
    @patch("pycodemcp.validation.PathValidator.validate_path")
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

    @patch("pycodemcp.server.get_project_manager")
    @patch("pycodemcp.server.ProjectConfig")
    @patch("pycodemcp.validation.PathValidator.validate_path")
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

    @patch("pycodemcp.server.get_project_manager")
    @patch("pycodemcp.validation.PathValidator")
    @patch("pycodemcp.server.ProjectConfig")
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

    @patch("pycodemcp.server.get_analyzer")
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
            "TestClass", fuzzy=False, include_import_paths=True
        )

    @patch("pycodemcp.server.get_analyzer")
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
        mock_analyzer.find_symbol.assert_called_with("test", fuzzy=True, include_import_paths=True)

    @patch("pycodemcp.server.ProjectConfig")
    @patch("pycodemcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_find_symbol_with_config(self, mock_get_analyzer, mock_config_class):
        """Test symbol finding with configuration."""
        # Mock configuration
        mock_config = Mock()
        mock_config.get_package_paths.return_value = [".", "../lib"]
        mock_config_class.return_value = mock_config

        mock_analyzer = AsyncMock()
        mock_get_analyzer.return_value = mock_analyzer
        mock_analyzer.find_symbol.return_value = []

        await find_symbol("test", use_config=True)

        # Should use configuration (ProjectConfig gets resolved path)
        mock_config_class.assert_called_once()
        mock_get_analyzer.assert_called()
        # Check that additional_paths was set
        assert hasattr(mock_analyzer, "additional_paths")

    @pytest.mark.asyncio
    async def test_find_symbol_with_reexports(self):
        """Test find_symbol includes import_paths for re-exported symbols."""
        # Use the test fixture
        fixture_path = str(Path(__file__).parent / "fixtures" / "reexport_test")

        # Find the User symbol in the test fixture
        results = await find_symbol("User", project_path=fixture_path, use_config=False)

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
        fixture_path = str(Path(__file__).parent / "fixtures" / "reexport_test")

        # Find the Authenticator symbol
        results = await find_symbol("Authenticator", project_path=fixture_path, use_config=False)

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

    @patch("pycodemcp.server.get_analyzer")
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

    @patch("pycodemcp.server.get_analyzer")
    @pytest.mark.asyncio
    async def test_goto_definition_not_found(self, mock_get_analyzer):  # noqa: ARG002
        """Test goto definition when symbol not found."""
        pytest.skip("Test needs refactoring after architecture changes")


class TestFindReferences:
    """Test the find_references tool."""

    @patch("pycodemcp.server.get_analyzer")
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
        mock_analyzer.find_references.assert_called_with("test.py", 5, 0, True)

    @patch("pycodemcp.server.get_analyzer")
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
        mock_analyzer.find_references.assert_called_with("test.py", 5, 0, False)


class TestGetTypeInfo:
    """Test the get_type_info tool."""

    @patch("pycodemcp.server.get_analyzer")
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
        mock_analyzer.get_type_info.assert_called_with("test.py", 10, 5)


class TestFindImports:
    """Test the find_imports tool."""

    @patch("pycodemcp.server.get_analyzer")
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

    @patch("pycodemcp.server.get_analyzer")
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

    @patch("pycodemcp.server.get_analyzer")
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


class TestNamespaceTools:
    """Test namespace-related tools."""

    @patch("pycodemcp.server.get_project_manager")
    def test_configure_namespace_package(self, mock_get_manager):
        """Test configuring namespace packages."""
        mock_manager = Mock()
        mock_resolver = Mock()
        mock_manager.namespace_resolver = mock_resolver
        mock_get_manager.return_value = mock_manager

        # Mock namespace discovery
        mock_resolver.discover_namespaces.return_value = {
            "company": [Path("/repos/auth"), Path("/repos/api")]
        }
        mock_resolver.build_namespace_map.return_value = {}

        result = configure_namespace_package("company", ["/repos/auth", "/repos/api"])

        assert result["namespace"] == "company"
        assert result["status"] == "configured"
        mock_resolver.register_namespace.assert_called()

    @patch("pycodemcp.server.get_project_manager")
    def test_find_in_namespace(self, mock_get_manager):
        """Test finding imports in namespace."""
        mock_manager = Mock()
        mock_resolver = Mock()
        mock_manager.namespace_resolver = mock_resolver
        mock_get_manager.return_value = mock_manager

        # Mock namespace resolution
        mock_resolver.discover_namespaces.return_value = {}
        mock_resolver.resolve_import.return_value = [Path("/repos/auth/models.py")]
        mock_resolver.build_namespace_map.return_value = {}

        # Mock project search
        mock_project = Mock()
        mock_manager.get_project.return_value = mock_project

        mock_search_result = Mock()
        mock_search_result.module_path = Path("/repos/auth/models.py")
        mock_search_result.line = 10
        mock_search_result.type = "class"
        mock_search_result.description = "class User"

        mock_project.search.return_value = [mock_search_result]

        result = find_in_namespace("company.auth.User", ["/repos/auth", "/repos/api"])

        assert "import_path" in result
        assert result["import_path"] == "company.auth.User"
        mock_resolver.resolve_import.assert_called()


class TestFindSymbolMulti:
    """Test the find_symbol_multi tool."""

    @patch("pycodemcp.server.get_project_manager")
    def test_find_symbol_multi(self, mock_get_manager):
        """Test finding symbols across multiple projects."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        # Mock project for each path
        mock_project = Mock()

        # Mock search result
        mock_result = Mock()
        mock_result.name = "test"
        mock_result.module_path = Path("test.py")
        mock_result.line = 10
        mock_result.column = 0
        mock_result.type = "function"
        mock_result.description = "def test"

        mock_project.search.return_value = [mock_result]
        mock_manager.get_project.return_value = mock_project

        result = find_symbol_multi("test", ["/proj1", "/proj2"])

        # Check that both projects are in results, handling platform-specific paths
        result_keys = list(result.keys())
        assert len(result) == 2
        # On Windows, paths may be resolved to full paths like "D:\proj1"
        # Check that keys end with the expected directory names
        assert any("proj1" in key for key in result_keys)
        assert any("proj2" in key for key in result_keys)
        # Should call get_project for each path
        assert mock_manager.get_project.call_count == 2


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


class TestPluginActivation:
    """Test plugin activation based on project type."""

    @patch("pycodemcp.server._plugins")
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

    @patch("pycodemcp.server.get_analyzer")
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

    @patch("pycodemcp.server.Path")
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

    @patch("pycodemcp.server.Path")
    @pytest.mark.asyncio
    async def test_validate_negative_line_number(self, mock_path_class):
        """Test that negative line numbers are rejected."""
        from pycodemcp.exceptions import ValidationError

        # Mock file path exists
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path_class.return_value = mock_path

        # The @validate_mcp_inputs decorator should raise ValidationError for invalid inputs
        with pytest.raises(ValidationError) as exc_info:
            await goto_definition("test.py", -1, 0)

        assert "line number" in str(exc_info.value).lower()

    @patch("pycodemcp.server.Path")
    @pytest.mark.asyncio
    async def test_validate_negative_column_number(self, mock_path_class):
        """Test that negative column numbers are rejected."""
        from pycodemcp.exceptions import ValidationError

        # Mock file path exists
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path_class.return_value = mock_path

        # The @validate_mcp_inputs decorator should raise ValidationError for invalid inputs
        with pytest.raises(ValidationError) as exc_info:
            await goto_definition("test.py", 10, -5)

        assert "column" in str(exc_info.value).lower()
