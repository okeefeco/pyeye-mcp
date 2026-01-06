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


class TestSrcLayoutEndToEnd:
    """End-to-end tests that verify Jedi actually resolves modules correctly.

    These tests don't mock Jedi - they verify the full resolution chain.
    """

    @pytest.fixture
    def real_src_project(self, temp_project_dir: Path) -> Path:
        """Create a real src-layout project for end-to-end testing.

        Structure:
            temp_project_dir/
            ├── pyproject.toml
            └── src/
                └── mypackage/
                    ├── __init__.py
                    └── core.py  (with MyClass)
        """
        src_dir = temp_project_dir / "src"
        src_dir.mkdir()

        pkg_dir = src_dir / "mypackage"
        pkg_dir.mkdir()

        (pkg_dir / "__init__.py").write_text('"""My Package."""\n\n__version__ = "1.0.0"\n')
        (pkg_dir / "core.py").write_text(
            '''"""Core module."""


class MyClass:
    """A class that should be findable via mypackage.core.MyClass."""

    def my_method(self):
        """A method."""
        return 42


def my_function():
    """A function that should be findable via mypackage.core.my_function."""
    return "hello"
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

    @pytest.mark.asyncio
    async def test_find_symbol_uses_package_path_not_src(self, real_src_project: Path):
        """Test that find_symbol returns 'mypackage.core.MyClass' not 'src.mypackage.core.MyClass'."""
        config = ProjectConfig(str(real_src_project))
        analyzer = JediAnalyzer(str(real_src_project), config=config)

        # Find the class
        results = await analyzer.find_symbol("MyClass")

        assert len(results) >= 1, "Should find MyClass"

        # Check the import path - it should be 'mypackage.core.MyClass', not 'src.mypackage.core.MyClass'
        result = results[0]
        import_paths = result.get("import_paths", [])

        # At least one import path should NOT start with 'src.'
        has_correct_path = any(
            "mypackage.core" in path and not path.startswith("src.") for path in import_paths
        )
        assert has_correct_path, (
            f"Expected import path like 'mypackage.core.MyClass', "
            f"got: {import_paths}. The 'src.' prefix should not appear."
        )

    @pytest.mark.asyncio
    async def test_find_symbol_function_uses_package_path(self, real_src_project: Path):
        """Test that find_symbol for function returns correct import path."""
        config = ProjectConfig(str(real_src_project))
        analyzer = JediAnalyzer(str(real_src_project), config=config)

        results = await analyzer.find_symbol("my_function")

        assert len(results) >= 1, "Should find my_function"

        result = results[0]
        import_paths = result.get("import_paths", [])

        has_correct_path = any(
            "mypackage.core" in path and not path.startswith("src.") for path in import_paths
        )
        assert has_correct_path, (
            f"Expected import path like 'mypackage.core.my_function', "
            f"got: {import_paths}. The 'src.' prefix should not appear."
        )

    @pytest.mark.asyncio
    async def test_get_module_info_uses_package_path(self, real_src_project: Path):
        """Test that modules can be accessed via 'mypackage.core' not 'src.mypackage.core'."""
        config = ProjectConfig(str(real_src_project))
        analyzer = JediAnalyzer(str(real_src_project), config=config)

        # Try to get info using 'mypackage.core' - this should work
        # without needing 'src.mypackage.core'
        module_info = await analyzer.get_module_info("mypackage.core")

        assert module_info is not None, (
            "Should be able to get module info using 'mypackage.core' " "(not 'src.mypackage.core')"
        )
        assert (
            "classes" in module_info or "functions" in module_info
        ), "Module info should have content"

    @pytest.mark.asyncio
    async def test_list_packages_uses_package_path_not_src(self, real_src_project: Path):
        """Test that list_packages returns 'mypackage' not 'src.mypackage'.

        This is a regression test for issue #281.
        """
        config = ProjectConfig(str(real_src_project))
        analyzer = JediAnalyzer(str(real_src_project), config=config)

        packages = await analyzer.list_packages()

        # Find the mypackage entry
        package_names = [p["name"] for p in packages]

        # Should have 'mypackage', not 'src.mypackage' or 'src'
        assert "mypackage" in package_names, (
            f"Expected 'mypackage' in package names, got: {package_names}. "
            "The 'src.' prefix should not appear."
        )
        assert "src.mypackage" not in package_names, (
            f"Found 'src.mypackage' which is wrong - should be just 'mypackage'. "
            f"Got: {package_names}"
        )

    @pytest.mark.asyncio
    async def test_list_modules_uses_package_path_not_src(self, real_src_project: Path):
        """Test that list_modules returns 'mypackage.core' not 'src.mypackage.core'.

        This is a regression test for issue #281.
        """
        config = ProjectConfig(str(real_src_project))
        analyzer = JediAnalyzer(str(real_src_project), config=config)

        modules = await analyzer.list_modules()

        # Get all module import paths (the key is 'import_path', not 'module')
        module_names = [m["import_path"] for m in modules]

        # Should have modules like 'mypackage.core', not 'src.mypackage.core'
        has_correct_module = any(
            name == "mypackage.core" or name == "mypackage" for name in module_names
        )
        has_src_prefix = any(name.startswith("src.mypackage") for name in module_names)

        assert (
            has_correct_module
        ), f"Expected 'mypackage' or 'mypackage.core' in module names, got: {module_names}"
        assert (
            not has_src_prefix
        ), f"Found modules with 'src.mypackage' prefix which is wrong. Got: {module_names}"


class TestSrcLayoutFindImports:
    """Tests for find_imports with src-layout projects.

    This is a regression test for issue #281 where find_imports returned empty
    results for src-layout projects.
    """

    @pytest.fixture
    def src_project_with_imports(self, temp_project_dir: Path) -> Path:
        """Create a src-layout project with internal imports.

        Structure:
            temp_project_dir/
            ├── pyproject.toml
            └── src/
                └── mypackage/
                    ├── __init__.py
                    ├── core.py  (imports mypackage.utils)
                    └── utils.py
        """
        src_dir = temp_project_dir / "src"
        src_dir.mkdir()

        pkg_dir = src_dir / "mypackage"
        pkg_dir.mkdir()

        (pkg_dir / "__init__.py").write_text('"""My Package."""\n')
        (pkg_dir / "utils.py").write_text(
            '''"""Utility module."""


def helper_function():
    """A helper function."""
    return "helping"


class UtilityClass:
    """A utility class."""
    pass
'''
        )
        (pkg_dir / "core.py").write_text(
            '''"""Core module that imports utils."""

from mypackage.utils import helper_function, UtilityClass
from mypackage import utils


def main():
    """Main function using utilities."""
    result = helper_function()
    obj = UtilityClass()
    return result, obj
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

    @pytest.mark.asyncio
    async def test_find_imports_works_for_src_layout(self, src_project_with_imports: Path):
        """Test that find_imports finds imports in src-layout projects.

        This is the main regression test for issue #281.
        """
        config = ProjectConfig(str(src_project_with_imports))
        analyzer = JediAnalyzer(str(src_project_with_imports), config=config)

        # Find files that import mypackage.utils
        results = await analyzer.find_imports("mypackage.utils")

        assert len(results) > 0, (
            "find_imports should find core.py which imports mypackage.utils. "
            "This was broken for src-layout projects (issue #281)."
        )

        # Verify the found file is core.py
        found_files = [r["file"] for r in results]
        assert any(
            "core.py" in f for f in found_files
        ), f"Expected to find core.py importing mypackage.utils, got: {found_files}"

    @pytest.mark.asyncio
    async def test_find_imports_with_from_import(self, src_project_with_imports: Path):
        """Test that find_imports finds 'from module import' style imports."""
        config = ProjectConfig(str(src_project_with_imports))
        analyzer = JediAnalyzer(str(src_project_with_imports), config=config)

        # Find files that import from mypackage.utils
        results = await analyzer.find_imports("mypackage.utils")

        # Should find the 'from mypackage.utils import helper_function' in core.py
        import_statements = [r.get("import_statement", "") for r in results]

        has_from_import = any("from mypackage.utils" in stmt for stmt in import_statements)
        assert has_from_import, (
            f"Expected to find 'from mypackage.utils import ...' statement. "
            f"Got: {import_statements}"
        )

    @pytest.mark.asyncio
    async def test_find_imports_returns_correct_file_paths(self, src_project_with_imports: Path):
        """Test that find_imports returns correct file paths (not src-prefixed)."""
        config = ProjectConfig(str(src_project_with_imports))
        analyzer = JediAnalyzer(str(src_project_with_imports), config=config)

        results = await analyzer.find_imports("mypackage.utils")

        # All file paths should be valid and point to real files
        for result in results:
            file_path = Path(result["file"])
            assert file_path.exists(), f"File should exist: {file_path}"
            assert file_path.suffix == ".py", f"Should be Python file: {file_path}"
