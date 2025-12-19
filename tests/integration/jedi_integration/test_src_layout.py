"""Tests for src-layout project support in JediAnalyzer.

This tests the fix for issue #277 where auto-detected src/ layout paths
were not being passed to Jedi's added_sys_path, requiring users to use
'src.package.*' instead of just 'package.*' for module paths.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig


class TestSrcLayoutSupport:
    """Test that src-layout projects work correctly with JediAnalyzer."""

    @pytest.fixture
    def src_layout_project(self, temp_project_dir: Path) -> Path:
        """Create a src-layout project structure.

        Structure:
            temp_project_dir/
            ├── pyproject.toml
            └── src/
                └── mypackage/
                    ├── __init__.py
                    └── module.py
        """
        # Create src directory with a package
        src_dir = temp_project_dir / "src"
        src_dir.mkdir()

        pkg_dir = src_dir / "mypackage"
        pkg_dir.mkdir()

        (pkg_dir / "__init__.py").write_text('__version__ = "1.0.0"')
        (pkg_dir / "module.py").write_text(
            '''"""Module in src-layout package."""


def my_function():
    """A function in the package."""
    return "hello"


class MyClass:
    """A class in the package."""

    def method(self):
        """A method."""
        return 42
'''
        )

        # Create pyproject.toml with setuptools src layout
        pyproject = temp_project_dir / "pyproject.toml"
        pyproject.write_text(
            """
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "mypackage"
version = "1.0.0"

[tool.setuptools.packages.find]
where = ["src"]
"""
        )

        return temp_project_dir

    def test_config_detects_src_layout(self, src_layout_project: Path):
        """Test that ProjectConfig detects src/ layout from pyproject.toml."""
        config = ProjectConfig(str(src_layout_project))

        packages = config.config.get("packages", [])
        assert "src" in packages, "Config should auto-detect src layout"

    def test_config_get_package_paths_includes_src(self, src_layout_project: Path):
        """Test that get_package_paths returns the src directory."""
        config = ProjectConfig(str(src_layout_project))

        package_paths = config.get_package_paths()

        # Should include both project path and src path
        src_path = (src_layout_project / "src").resolve().as_posix()
        assert any(
            src_path in p for p in package_paths
        ), f"Package paths should include src directory. Got: {package_paths}"

    def test_analyzer_passes_src_to_jedi(self, src_layout_project: Path):
        """Test that JediAnalyzer passes src/ to Jedi's added_sys_path."""
        config = ProjectConfig(str(src_layout_project))

        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            mock_project.return_value = Mock()

            JediAnalyzer(str(src_layout_project), config=config)

            # Verify jedi.Project was called with added_sys_path
            call_kwargs = mock_project.call_args.kwargs
            assert "added_sys_path" in call_kwargs, "Should pass added_sys_path to Jedi"

            added_paths = call_kwargs["added_sys_path"]
            assert added_paths is not None, "added_sys_path should not be None"

            # Check that src directory is in added paths
            src_path = (src_layout_project / "src").resolve().as_posix()
            assert any(
                src_path in p for p in added_paths
            ), f"added_sys_path should include src directory. Got: {added_paths}"

    def test_analyzer_without_config_no_added_paths(self, temp_project_dir: Path):
        """Test that analyzer without config doesn't add paths."""
        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            mock_project.return_value = Mock()

            JediAnalyzer(str(temp_project_dir), config=None)

            # Verify jedi.Project was called without added_sys_path kwarg
            # (Jedi doesn't accept None, so we don't pass it at all)
            call_kwargs = mock_project.call_args.kwargs
            assert (
                "added_sys_path" not in call_kwargs
            ), "Without config, added_sys_path should not be passed"

    def test_analyzer_excludes_external_paths(self, src_layout_project: Path):
        """Test that external package paths are not added to Jedi's added_sys_path."""
        # Create config with external path
        config_file = src_layout_project / ".pyeye.json"
        config_file.write_text(
            """
{
    "packages": ["src", "/external/path"]
}
"""
        )

        config = ProjectConfig(str(src_layout_project))

        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            mock_project.return_value = Mock()

            JediAnalyzer(str(src_layout_project), config=config)

            call_kwargs = mock_project.call_args.kwargs
            added_paths = call_kwargs.get("added_sys_path", []) or []

            # src should be included (it's a subpath)
            src_path = (src_layout_project / "src").resolve().as_posix()
            has_src = any(src_path in p for p in added_paths)
            assert has_src, "src should be in added_sys_path"

            # External path should NOT be included (it's not a subpath)
            has_external = any("/external/path" in p for p in added_paths)
            assert not has_external, "External paths should not be in added_sys_path"

    def test_is_subpath_helper(self, temp_project_dir: Path):
        """Test the _is_subpath helper method."""
        # Create analyzer (we just need an instance to test the method)
        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project"):
            analyzer = JediAnalyzer(str(temp_project_dir))

        # Test subpath detection
        parent = Path("/project")
        child = Path("/project/src/package")
        external = Path("/other/project")

        assert analyzer._is_subpath(child, parent) is True
        assert analyzer._is_subpath(external, parent) is False
        # Same path returns True (relative_to works), but we handle this
        # separately in __init__ by checking pkg != self.project_path first
        assert analyzer._is_subpath(parent, parent) is True


class TestSrcLayoutAutoDiscovery:
    """Test auto-discovery of src layout without explicit configuration."""

    @pytest.fixture
    def auto_discover_src_project(self, temp_project_dir: Path) -> Path:
        """Create a src-layout project without explicit pyproject.toml config.

        This tests the fallback auto-discovery when no build backend is specified.
        """
        # Create src directory with a package
        src_dir = temp_project_dir / "src"
        src_dir.mkdir()

        pkg_dir = src_dir / "mypackage"
        pkg_dir.mkdir()

        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "core.py").write_text("def core_function(): pass")

        return temp_project_dir

    def test_auto_discovers_src_layout(self, auto_discover_src_project: Path):
        """Test that src/ layout is auto-discovered even without pyproject.toml."""
        config = ProjectConfig(str(auto_discover_src_project))

        packages = config.config.get("packages", [])
        assert "src" in packages, "Should auto-discover src layout"

    def test_auto_discovered_src_passed_to_jedi(self, auto_discover_src_project: Path):
        """Test that auto-discovered src/ is passed to Jedi."""
        config = ProjectConfig(str(auto_discover_src_project))

        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            mock_project.return_value = Mock()

            JediAnalyzer(str(auto_discover_src_project), config=config)

            call_kwargs = mock_project.call_args.kwargs
            added_paths = call_kwargs.get("added_sys_path")

            assert added_paths is not None, "added_sys_path should not be None"

            src_path = (auto_discover_src_project / "src").resolve().as_posix()
            assert any(
                src_path in p for p in added_paths
            ), f"added_sys_path should include auto-discovered src. Got: {added_paths}"


class TestMultipleBuildBackends:
    """Test src-layout detection for different build backends."""

    @pytest.fixture
    def poetry_src_project(self, temp_project_dir: Path) -> Path:
        """Create a Poetry project with src layout."""
        src_dir = temp_project_dir / "src"
        src_dir.mkdir()
        pkg_dir = src_dir / "mypackage"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        pyproject = temp_project_dir / "pyproject.toml"
        pyproject.write_text(
            """
[tool.poetry]
name = "mypackage"
version = "1.0.0"

[[tool.poetry.packages]]
include = "mypackage"
from = "src"
"""
        )
        return temp_project_dir

    @pytest.fixture
    def hatch_src_project(self, temp_project_dir: Path) -> Path:
        """Create a Hatch project with src layout."""
        src_dir = temp_project_dir / "src"
        src_dir.mkdir()
        pkg_dir = src_dir / "mypackage"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        pyproject = temp_project_dir / "pyproject.toml"
        pyproject.write_text(
            """
[tool.hatch.build.targets.wheel]
sources = ["src"]
"""
        )
        return temp_project_dir

    def test_poetry_src_layout_passed_to_jedi(self, poetry_src_project: Path):
        """Test Poetry src layout is detected and passed to Jedi."""
        config = ProjectConfig(str(poetry_src_project))

        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            mock_project.return_value = Mock()

            JediAnalyzer(str(poetry_src_project), config=config)

            call_kwargs = mock_project.call_args.kwargs
            added_paths = call_kwargs.get("added_sys_path")

            assert added_paths is not None
            src_path = (poetry_src_project / "src").resolve().as_posix()
            assert any(src_path in p for p in added_paths)

    def test_hatch_src_layout_passed_to_jedi(self, hatch_src_project: Path):
        """Test Hatch src layout is detected and passed to Jedi."""
        config = ProjectConfig(str(hatch_src_project))

        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            mock_project.return_value = Mock()

            JediAnalyzer(str(hatch_src_project), config=config)

            call_kwargs = mock_project.call_args.kwargs
            added_paths = call_kwargs.get("added_sys_path")

            assert added_paths is not None
            src_path = (hatch_src_project / "src").resolve().as_posix()
            assert any(src_path in p for p in added_paths)
