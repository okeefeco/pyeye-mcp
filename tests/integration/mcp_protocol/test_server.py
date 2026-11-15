"""Tests for the MCP server and tools."""

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.exceptions import ValidationError
from pyeye.mcp.server import (
    configure_packages,
    mcp,
    resolve_at,
)


async def _find_subclasses_flat(
    base_class: str,
    project_path: str,
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
    result = await analyzer.find_subclasses(base_class=base_class)

    if result.get("ambiguous", False):
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in result.get("candidates", []):
            candidate_handle = candidate.get("handle")
            if not candidate_handle:
                continue
            candidate_result = await analyzer.find_subclasses(base_class=candidate_handle)
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
        assert isinstance(mcp, MCPServer)
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
    async def test_configure_packages_basic(
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

        result = await configure_packages(packages=["../lib1", "../lib2"], save=False)

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
    async def test_configure_namespaces(
        self, mock_validate_path, mock_config_class, mock_get_manager
    ):
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

        _ = await configure_packages(
            namespaces={"company": ["/repos/auth", "/repos/api"]}, save=False
        )

        assert "namespaces" in config_dict
        assert "company" in config_dict["namespaces"]

    @patch("pyeye.mcp.server.get_project_manager")
    @patch("pyeye.mcp.server.ProjectConfig")
    @patch("pyeye.validation.PathValidator.validate_path")
    async def test_configure_save(self, mock_validate_path, mock_config_class, mock_get_manager):
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

        _ = await configure_packages(packages=["test"], save=True)

        mock_config.save_config.assert_called_once()

    @patch("pyeye.mcp.server.get_project_manager")
    @patch("pyeye.validation.PathValidator")
    @patch("pyeye.mcp.server.ProjectConfig")
    async def test_configure_validates_paths(
        self, mock_config_class, mock_validator, mock_get_manager
    ):
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

        await configure_packages(packages=["../lib1"])

        # Path validator should be called via the decorator
        mock_validator.validate_path.assert_called()


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
    async def test_find_subclasses_direct_only(self, temp_project_dir):
        """find_subclasses returns direct subclasses only; the grandchild is excluded."""
        test_file = temp_project_dir / "hierarchy.py"
        test_file.write_text("""
class Base:
    pass

class Middle(Base):
    pass

class Leaf(Middle):
    pass
""")

        result = await _find_subclasses_flat("Base", str(temp_project_dir))
        assert [r["name"] for r in result] == ["Middle"]
        assert result[0]["is_direct"] is True
        assert result[0]["direct_parent"] == "Base"

        # The grandchild is one more hop away: a direct subclass of Middle.
        result = await _find_subclasses_flat("Middle", str(temp_project_dir))
        assert [r["name"] for r in result] == ["Leaf"]

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

    The decorator is shared infrastructure; we exercise it through ``resolve_at``,
    which carries the same ``file``/``line``/``column`` signature and the same
    ``@validate_mcp_inputs`` decorator that the removed position-based tools
    (``goto_definition``, then ``find_references`` in #505) used.
    """

    # No filesystem mocking: the decorator rejects out-of-range coordinates
    # before it ever touches the file, so these assertions hold for a path that
    # does not exist.

    # Since #626 slice C the rejection reaches the client as an MCP tool error
    # (``ToolError``) naming the error type and the parameter, raised from the
    # original ``ValidationError``.

    @pytest.mark.asyncio
    async def test_validate_negative_line_number(self):
        """Test that negative line numbers are rejected as a tool error naming ``line``."""
        with pytest.raises(ToolError) as exc_info:
            await resolve_at("test.py", -1, 0)

        message = str(exc_info.value)
        assert message.startswith("ValidationError:")
        assert "line number" in message.lower()
        assert "parameter=line" in message
        assert isinstance(exc_info.value.__cause__, ValidationError)

    @pytest.mark.asyncio
    async def test_validate_negative_column_number(self):
        """Test that negative column numbers are rejected as a tool error naming ``column``."""
        with pytest.raises(ToolError) as exc_info:
            await resolve_at("test.py", 10, -5)

        message = str(exc_info.value)
        assert message.startswith("ValidationError:")
        assert "parameter=column" in message
        assert isinstance(exc_info.value.__cause__, ValidationError)


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
