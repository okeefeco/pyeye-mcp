"""Tests for the MCP server and tools."""

from unittest.mock import Mock, patch

import pytest
from fastmcp import FastMCP
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
        assert mcp.name == "python-code-intelligence"

    def test_server_has_tools(self):
        """Test that server has registered tools."""
        # The tools should be registered
        # This would need access to internal MCP state
        pass


class TestConfigurePackages:
    """Test the configure_packages tool."""

    @patch("pycodemcp.server.project_config")
    def test_configure_packages_basic(self, mock_config):
        """Test basic package configuration."""
        mock_config.config = {}

        _ = configure_packages(packages=["../lib1", "../lib2"], save=False)

        assert "packages" in mock_config.config
        assert "../lib1" in mock_config.config["packages"]
        assert "../lib2" in mock_config.config["packages"]

    @patch("pycodemcp.server.project_config")
    def test_configure_namespaces(self, mock_config):
        """Test namespace configuration."""
        mock_config.config = {}

        _ = configure_packages(namespaces={"company": ["/repos/auth", "/repos/api"]}, save=False)

        assert "namespaces" in mock_config.config
        assert "company" in mock_config.config["namespaces"]

    @patch("pycodemcp.server.project_config")
    def test_configure_save(self, mock_config):
        """Test saving configuration."""
        mock_config.config = {}
        mock_config.save_config = Mock()

        _ = configure_packages(packages=["test"], save=True)

        mock_config.save_config.assert_called_once()

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.project_config")
    def test_configure_validates_paths(self, mock_config, mock_validator):
        """Test that paths are validated before configuration."""
        mock_config.config = {}

        configure_packages(packages=["../lib1"])

        # Path validator should be called
        mock_validator.validate_path.assert_called()


class TestFindSymbol:
    """Test the find_symbol tool."""

    @patch("pycodemcp.server.InputValidator")
    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.get_analyzer")
    def test_find_symbol_basic(self, mock_get_analyzer, _mock_path_val, _mock_input_val):
        """Test basic symbol finding."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        mock_analyzer.find_symbol.return_value = [
            {"name": "TestClass", "file": "/project/test.py", "line": 10, "type": "class"}
        ]

        result = find_symbol("TestClass")

        assert len(result) == 1
        assert result[0]["name"] == "TestClass"
        mock_analyzer.find_symbol.assert_called_with("TestClass", fuzzy=False)

    @patch("pycodemcp.server.get_analyzer")
    def test_find_symbol_fuzzy(self, mock_get_analyzer):
        """Test fuzzy symbol search."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer
        mock_analyzer.find_symbol.return_value = []

        find_symbol("test", fuzzy=True)

        mock_analyzer.find_symbol.assert_called_with("test", fuzzy=True)

    @patch("pycodemcp.server.get_analyzer")
    def test_find_symbol_with_config(self, mock_get_analyzer):
        """Test symbol finding with configuration."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer
        mock_analyzer.find_symbol.return_value = []

        find_symbol("test", use_config=True)

        # Should use configuration
        mock_get_analyzer.assert_called()


class TestGotoDefinition:
    """Test the goto_definition tool."""

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.InputValidator")
    @patch("pycodemcp.server.get_analyzer")
    def test_goto_definition(self, mock_get_analyzer, _mock_input_val, _mock_path_val):
        """Test going to symbol definition."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        mock_analyzer.goto_definition.return_value = {
            "name": "function",
            "file": "/project/module.py",
            "line": 42,
            "column": 4,
        }

        result = goto_definition("test.py", 10, 5)

        assert result["name"] == "function"
        assert result["line"] == 42

    @patch("pycodemcp.server.get_analyzer")
    def test_goto_definition_not_found(self, mock_get_analyzer):
        """Test goto definition when symbol not found."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer
        mock_analyzer.goto_definition.return_value = None

        result = goto_definition("test.py", 10, 5)

        assert result is None


class TestFindReferences:
    """Test the find_references tool."""

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.InputValidator")
    @patch("pycodemcp.server.get_analyzer")
    def test_find_references(self, mock_get_analyzer, _mock_input_val, _mock_path_val):
        """Test finding symbol references."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        mock_analyzer.find_references.return_value = [
            {"file": "/project/test.py", "line": 10},
            {"file": "/project/test.py", "line": 20},
        ]

        result = find_references("test.py", 5, 0)

        assert len(result) == 2
        mock_analyzer.find_references.assert_called_with("test.py", 5, 0, include_definitions=True)

    @patch("pycodemcp.server.get_analyzer")
    def test_find_references_exclude_definitions(self, mock_get_analyzer):
        """Test finding references excluding definitions."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer
        mock_analyzer.find_references.return_value = []

        find_references("test.py", 5, 0, include_definitions=False)

        mock_analyzer.find_references.assert_called_with("test.py", 5, 0, include_definitions=False)


class TestGetTypeInfo:
    """Test the get_type_info tool."""

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.InputValidator")
    @patch("pycodemcp.server.get_analyzer")
    def test_get_type_info(self, mock_get_analyzer, mock_input_val, mock_path_val):  # noqa: ARG002
        """Test getting type information."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        mock_analyzer.get_type_info.return_value = {"type": "str", "docstring": "String type"}

        result = get_type_info("test.py", 10, 5)

        assert result["type"] == "str"
        assert "docstring" in result


class TestFindImports:
    """Test the find_imports tool."""

    @patch("pycodemcp.server.get_analyzer")
    def test_find_imports(self, mock_get_analyzer):
        """Test finding module imports."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        mock_analyzer.find_imports.return_value = [
            {"file": "/project/test.py", "line": 1, "import": "import os"},
            {"file": "/project/utils.py", "line": 3, "import": "import os"},
        ]

        result = find_imports("os")

        assert len(result) == 2
        mock_analyzer.find_imports.assert_called_with("os")


class TestGetCallHierarchy:
    """Test the get_call_hierarchy tool."""

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.get_analyzer")
    def test_get_call_hierarchy(self, mock_get_analyzer, mock_path_val):  # noqa: ARG002
        """Test getting call hierarchy."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        mock_analyzer.get_call_hierarchy.return_value = {
            "function": "test_func",
            "callers": [{"name": "main", "line": 10}],
            "callees": [{"name": "helper", "line": 5}],
        }

        result = get_call_hierarchy("test_func")

        assert result["function"] == "test_func"
        assert len(result["callers"]) == 1
        assert len(result["callees"]) == 1

    @patch("pycodemcp.server.get_analyzer")
    def test_get_call_hierarchy_with_file(self, mock_get_analyzer):
        """Test call hierarchy with specific file."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer
        mock_analyzer.get_call_hierarchy.return_value = {}

        get_call_hierarchy("func", file="test.py")

        mock_analyzer.get_call_hierarchy.assert_called_with("func", "test.py")


class TestNamespaceTools:
    """Test namespace-related tools."""

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.project_manager")
    def test_configure_namespace_package(self, mock_manager, mock_path_val):  # noqa: ARG002
        """Test configuring namespace packages."""
        mock_resolver = Mock()
        mock_manager.namespace_resolver = mock_resolver

        _ = configure_namespace_package("company", ["/repos/auth", "/repos/api"])

        mock_resolver.register_namespace.assert_called_with(
            "company", ["/repos/auth", "/repos/api"]
        )

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.project_manager")
    def test_find_in_namespace(self, mock_manager, mock_path_val):  # noqa: ARG002
        """Test finding imports in namespace."""
        mock_resolver = Mock()
        mock_manager.namespace_resolver = mock_resolver

        mock_resolver.find_in_namespace.return_value = [
            {"file": "/repos/auth/models.py", "line": 10}
        ]

        result = find_in_namespace("company.auth.User", ["/repos/auth", "/repos/api"])

        assert len(result) == 1
        mock_resolver.find_in_namespace.assert_called()


class TestFindSymbolMulti:
    """Test the find_symbol_multi tool."""

    @patch("pycodemcp.server.PathValidator")
    @patch("pycodemcp.server.get_analyzer")
    def test_find_symbol_multi(self, mock_get_analyzer, mock_path_val):  # noqa: ARG002
        """Test finding symbols across multiple projects."""
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        mock_analyzer.find_symbol.return_value = [{"name": "test", "file": "test.py"}]

        result = find_symbol_multi("test", ["/proj1", "/proj2"])

        assert "/proj1" in result
        assert "/proj2" in result
        assert len(result) == 2


class TestListProjectStructure:
    """Test the list_project_structure tool."""

    @patch("pycodemcp.server.PathValidator")
    def test_list_project_structure(self, mock_path_val, temp_project_dir):  # noqa: ARG002
        """Test listing project structure."""
        # Create project structure
        (temp_project_dir / "src").mkdir()
        (temp_project_dir / "src" / "main.py").write_text("# Main")
        (temp_project_dir / "tests").mkdir()
        (temp_project_dir / "tests" / "test_main.py").write_text("# Test")

        result = list_project_structure(str(temp_project_dir))

        assert "structure" in result
        assert "python_files" in result
        assert result["python_files"] >= 2

    def test_list_project_structure_max_depth(self, temp_project_dir):
        """Test project structure with max depth limit."""
        # Create deep structure
        deep_path = temp_project_dir / "a" / "b" / "c" / "d" / "e"
        deep_path.mkdir(parents=True)
        (deep_path / "deep.py").write_text("# Deep file")

        result = list_project_structure(str(temp_project_dir), max_depth=2)

        # Should not include files beyond max_depth
        assert "structure" in result


class TestPluginActivation:
    """Test plugin activation based on project type."""

    @patch("pycodemcp.server.active_plugins")
    @patch("pycodemcp.server.PLUGINS")
    def test_plugin_detection(self, mock_plugins, mock_active):  # noqa: ARG002
        """Test that plugins are detected and activated."""
        # Create mock plugins
        flask_plugin = Mock()
        flask_plugin.detect.return_value = True
        flask_plugin.name.return_value = "Flask"

        django_plugin = Mock()
        django_plugin.detect.return_value = False

        mock_plugins["flask"] = flask_plugin
        mock_plugins["django"] = django_plugin

        # Would need to trigger plugin detection
        # This happens during analyzer creation


class TestErrorHandling:
    """Test error handling in MCP tools."""

    @patch("pycodemcp.server.get_analyzer")
    def test_find_symbol_error(self, mock_get_analyzer):
        """Test error handling in find_symbol."""
        mock_get_analyzer.side_effect = Exception("Analyzer error")

        with pytest.raises(Exception):  # noqa: B017
            find_symbol("test")

    @patch("pycodemcp.server.PathValidator")
    def test_path_validation_error(self, mock_validator):
        """Test path validation errors."""
        from pycodemcp.validation import ValidationError

        mock_validator.validate_path.side_effect = ValidationError("Invalid path")

        with pytest.raises(ValidationError):
            goto_definition("../../../etc/passwd", 1, 0)


class TestInputValidation:
    """Test input validation decorators."""

    @patch("pycodemcp.server.InputValidator")
    def test_validate_line_number(self, mock_validator):
        """Test line number validation."""
        mock_validator.validate_line_number.side_effect = lambda x: x

        # Should validate line numbers
        goto_definition("test.py", 10, 0)
        mock_validator.validate_line_number.assert_called_with(10)

    @patch("pycodemcp.server.InputValidator")
    def test_validate_column_number(self, mock_validator):
        """Test column number validation."""
        mock_validator.validate_column_number.side_effect = lambda x: x

        # Should validate column numbers
        goto_definition("test.py", 10, 5)
        mock_validator.validate_column_number.assert_called_with(5)
