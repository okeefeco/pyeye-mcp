"""Tests for the MCP server and tools."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.exceptions import ValidationError
from pyeye.mcp.server import (
    configure_packages,
    find_references,
    get_call_hierarchy,
    mcp,
)


async def _find_subclasses_flat(
    base_class: str,
    project_path: str,
    include_indirect: bool = True,
    show_hierarchy: bool = False,
) -> list[dict[str, Any]]:
    """Flatten ``JediAnalyzer.find_subclasses`` to the legacy ``list[dict]`` contract.

    The analyzer returns an ambiguity discriminated union
    (``{"ambiguous": False, "subclasses": [...]}`` or
    ``{"ambiguous": True, "candidates": [...]}``).  The now-deleted
    ``find_subclasses`` MCP wrapper collapsed that to a flat list (issue #336);
    this helper reproduces that behaviour so the real-fixture coverage is
    preserved against the kept analyzer method.
    """
    analyzer = JediAnalyzer(project_path)
    result = await analyzer.find_subclasses(
        base_class=base_class,
        include_indirect=include_indirect,
        show_hierarchy=show_hierarchy,
    )

    if result.get("ambiguous", False):
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in result.get("candidates", []):
            candidate_handle = candidate.get("handle")
            if not candidate_handle:
                continue
            candidate_result = await analyzer.find_subclasses(
                base_class=candidate_handle,
                include_indirect=include_indirect,
                show_hierarchy=show_hierarchy,
            )
            for subclass in candidate_result.get("subclasses", []):
                key = subclass.get("full_name") or repr(subclass)
                if key not in seen:
                    seen.add(key)
                    merged.append(subclass)
        return merged

    subclasses: list[dict[str, Any]] = result.get("subclasses", [])
    return subclasses


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
    """Test the find_symbol analyzer method (re-export behavior)."""

    @pytest.mark.asyncio
    async def test_find_symbol_with_reexports(self):
        """Test find_symbol includes import_paths for re-exported symbols."""
        # Use the test fixture
        fixture_path = str(Path(__file__).parent.parent.parent / "fixtures" / "reexport_test")

        # Find the User symbol in the test fixture
        analyzer = JediAnalyzer(fixture_path)
        results = await analyzer.find_symbol("User", include_import_paths=True, scope="main")

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
        analyzer = JediAnalyzer(fixture_path)
        results = await analyzer.find_symbol(
            "Authenticator", include_import_paths=True, scope="main"
        )

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


class TestFindSubclasses:
    """Test the kept ``JediAnalyzer.find_subclasses`` method (flat-list contract)."""

    @pytest.mark.asyncio
    async def test_find_subclasses_basic(self, temp_project_dir):
        """Test basic find_subclasses functionality."""
        # Create test file with class hierarchy
        test_file = temp_project_dir / "animals.py"
        test_file.write_text("""
class Animal:
    pass

class Dog(Animal):
    pass

class Cat(Animal):
    pass
""")

        result = await _find_subclasses_flat("Animal", str(temp_project_dir))

        # Should find both Dog and Cat
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert "Dog" in names
        assert "Cat" in names

    @pytest.mark.asyncio
    async def test_find_subclasses_with_params(self, temp_project_dir):
        """Test find_subclasses with include_indirect and show_hierarchy."""
        test_file = temp_project_dir / "hierarchy.py"
        test_file.write_text("""
class Base:
    pass

class Middle(Base):
    pass

class Leaf(Middle):
    pass
""")

        # Test with indirect=False
        result = await _find_subclasses_flat("Base", str(temp_project_dir), include_indirect=False)
        assert len(result) == 1
        assert result[0]["name"] == "Middle"

        # Test with indirect=True and hierarchy
        result = await _find_subclasses_flat(
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
        result = await _find_subclasses_flat("NonExistentClass", str(temp_project_dir))
        assert result == []

    @pytest.mark.asyncio
    async def test_ambiguous_bare_name_returns_flat_list_not_dict(self):
        """Issue #336: a bare colliding name returns a flat list, never a dict.

        The analyzer now returns an ambiguity discriminated union, but the legacy
        ``list[dict]`` contract (flat union of every same-named class's
        subclasses) must be preserved by the flattening helper.  An existing
        consumer doing ``for sc in result: sc["name"]`` must not break (a dict
        would yield string keys and raise TypeError).

        Uses the committed resolve_project fixture (real dir, not a tmp dir):
        ``Widget`` is defined in three modules, so the bare name is ambiguous,
        and the per-candidate FQN resolution exercises Jedi on a non-symlinked
        path.
        """
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"
        result = await _find_subclasses_flat("Widget", fixture.as_posix())

        # Old contract: always a list (never the ambiguity dict).
        assert isinstance(result, list), f"expected a list, got {type(result).__name__}: {result!r}"

        # Iterable as the old shape: each entry is a subclass dict with a name.
        names = {sc["name"] for sc in result}

        # Flat union of every Widget's subclasses (matches main's behaviour):
        # mypackage._core.widgets.Widget -> Premium, Deluxe, ViaAttr
        # mypackage.collision_demo.Widget -> UnrelatedSub
        assert {"Premium", "Deluxe", "ViaAttr", "UnrelatedSub"} <= names, names


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


class TestInputValidation:
    """Test the @validate_mcp_inputs decorator via a kept position-based tool.

    The decorator is shared infrastructure; we exercise it through the kept
    ``find_references`` tool (same ``file``/``line``/``column`` signature and the
    same ``@validate_mcp_inputs`` decorator the deleted ``goto_definition`` used).
    """

    @patch("pyeye.mcp.server.Path")
    @pytest.mark.asyncio
    async def test_validate_negative_line_number(self, mock_path_class):
        """Test that negative line numbers are rejected."""
        # Mock file path exists
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path_class.return_value = mock_path

        # The @validate_mcp_inputs decorator should raise ValidationError for invalid inputs
        with pytest.raises(ValidationError) as exc_info:
            await find_references("test.py", -1, 0)

        assert "line number" in str(exc_info.value).lower()

    @patch("pyeye.mcp.server.Path")
    @pytest.mark.asyncio
    async def test_validate_negative_column_number(self, mock_path_class):
        """Test that negative column numbers are rejected."""
        # Mock file path exists
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path_class.return_value = mock_path

        # The @validate_mcp_inputs decorator should raise ValidationError for invalid inputs
        with pytest.raises(ValidationError) as exc_info:
            await find_references("test.py", 10, -5)

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
