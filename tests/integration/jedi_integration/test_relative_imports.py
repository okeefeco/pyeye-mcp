"""Tests for relative import detection in find_imports.

This tests the fix for issue #283 where find_imports only detected
absolute imports, missing relative imports like:
- from . import module
- from .. import module
- from .subpkg import module
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig


class TestRelativeImportDetection:
    """Test that find_imports detects relative imports."""

    @pytest.fixture
    def package_with_relative_imports(self, temp_project_dir: Path) -> Path:
        """Create a package structure with relative imports.

        Structure:
            temp_project_dir/
            ├── pyproject.toml
            └── mypackage/
                ├── __init__.py       # from . import platform, from .component import X
                ├── component.py
                ├── platform.py
                ├── nodejs.py
                └── subpkg/
                    ├── __init__.py
                    └── helper.py     # from .. import nodejs
        """
        # Create package directory
        pkg_dir = temp_project_dir / "mypackage"
        pkg_dir.mkdir()

        # Create subpackage
        subpkg_dir = pkg_dir / "subpkg"
        subpkg_dir.mkdir()

        # __init__.py with relative imports
        (pkg_dir / "__init__.py").write_text("""\"\"\"Package init with relative imports.\"\"\"

from . import platform
from . import nodejs
from .component import Component
""")

        # component.py
        (pkg_dir / "component.py").write_text("""\"\"\"Component module.\"\"\"


class Component:
    \"\"\"A component class.\"\"\"

    def run(self):
        return "running"
""")

        # platform.py
        (pkg_dir / "platform.py").write_text("""\"\"\"Platform module.\"\"\"


def get_platform():
    return "test"
""")

        # nodejs.py
        (pkg_dir / "nodejs.py").write_text("""\"\"\"Nodejs module.\"\"\"


def get_nodejs():
    return "v18"
""")

        # subpkg/__init__.py
        (subpkg_dir / "__init__.py").write_text('"""Subpackage init."""')

        # subpkg/helper.py with relative import from parent
        (subpkg_dir / "helper.py").write_text("""\"\"\"Helper module with relative imports.\"\"\"

from .. import nodejs
from ..platform import get_platform


def help_me():
    return nodejs.get_nodejs(), get_platform()
""")

        # pyproject.toml
        (temp_project_dir / "pyproject.toml").write_text("""[project]
name = "mypackage"
version = "1.0.0"
""")

        return temp_project_dir

    @pytest.mark.asyncio
    async def test_find_imports_detects_relative_import_from_dot(
        self, package_with_relative_imports: Path
    ):
        """Test that 'from . import platform' is detected.

        This is the main regression test for issue #283.
        """
        config = ProjectConfig(str(package_with_relative_imports))
        analyzer = JediAnalyzer(str(package_with_relative_imports), config=config)

        # Find files that import mypackage.platform
        results = await analyzer.find_imports("mypackage.platform")

        assert len(results) > 0, (
            "find_imports should find __init__.py which imports mypackage.platform "
            "via 'from . import platform'. This was broken for relative imports (issue #283)."
        )

        # Verify the found file is __init__.py
        found_files = [r["file"] for r in results]
        assert any(
            "__init__.py" in f for f in found_files
        ), f"Expected to find __init__.py importing mypackage.platform, got: {found_files}"

    @pytest.mark.asyncio
    async def test_find_imports_detects_relative_import_from_double_dot(
        self, package_with_relative_imports: Path
    ):
        """Test that 'from .. import nodejs' is detected."""
        config = ProjectConfig(str(package_with_relative_imports))
        analyzer = JediAnalyzer(str(package_with_relative_imports), config=config)

        # Find files that import mypackage.nodejs
        results = await analyzer.find_imports("mypackage.nodejs")

        assert len(results) > 0, (
            "find_imports should find imports of mypackage.nodejs. "
            "This should include both __init__.py and subpkg/helper.py"
        )

        # Should find both __init__.py (from . import nodejs) and helper.py (from .. import nodejs)
        found_files = [r["file"] for r in results]
        assert any(
            "__init__.py" in f for f in found_files
        ), f"Expected __init__.py to import nodejs, got: {found_files}"
        assert any(
            "helper.py" in f for f in found_files
        ), f"Expected helper.py to import nodejs via 'from .. import nodejs', got: {found_files}"

    @pytest.mark.asyncio
    async def test_find_imports_detects_relative_import_with_name(
        self, package_with_relative_imports: Path
    ):
        """Test that 'from .component import Component' is detected."""
        config = ProjectConfig(str(package_with_relative_imports))
        analyzer = JediAnalyzer(str(package_with_relative_imports), config=config)

        # Find files that import mypackage.component
        results = await analyzer.find_imports("mypackage.component")

        assert len(results) > 0, (
            "find_imports should find __init__.py which imports from mypackage.component "
            "via 'from .component import Component'."
        )

        found_files = [r["file"] for r in results]
        assert any(
            "__init__.py" in f for f in found_files
        ), f"Expected __init__.py, got: {found_files}"

    @pytest.mark.asyncio
    async def test_find_imports_reports_is_relative_flag(self, package_with_relative_imports: Path):
        """Test that results include is_relative flag."""
        config = ProjectConfig(str(package_with_relative_imports))
        analyzer = JediAnalyzer(str(package_with_relative_imports), config=config)

        results = await analyzer.find_imports("mypackage.nodejs")

        # Find the result from helper.py which has a relative import
        helper_results = [r for r in results if "helper.py" in r["file"]]
        assert len(helper_results) > 0, "Should find helper.py"

        # Check that is_relative flag is set
        assert helper_results[0].get("is_relative") is True, (
            "Result from helper.py should have is_relative=True since it uses "
            "'from .. import nodejs'"
        )

    @pytest.mark.asyncio
    async def test_find_imports_reports_resolved_module(self, package_with_relative_imports: Path):
        """Test that results include resolved_module."""
        config = ProjectConfig(str(package_with_relative_imports))
        analyzer = JediAnalyzer(str(package_with_relative_imports), config=config)

        results = await analyzer.find_imports("mypackage.nodejs")

        # All results should have resolved_module
        for result in results:
            assert "resolved_module" in result, "Result should include resolved_module"
            assert (
                "nodejs" in result["resolved_module"]
            ), f"resolved_module should contain 'nodejs', got: {result['resolved_module']}"

    @pytest.mark.asyncio
    async def test_find_imports_relative_from_parent_with_attribute(
        self, package_with_relative_imports: Path
    ):
        """Test that 'from ..platform import get_platform' is detected."""
        config = ProjectConfig(str(package_with_relative_imports))
        analyzer = JediAnalyzer(str(package_with_relative_imports), config=config)

        # Find files that import mypackage.platform
        results = await analyzer.find_imports("mypackage.platform")

        # Should find both __init__.py and helper.py
        found_files = [r["file"] for r in results]
        assert any(
            "helper.py" in f for f in found_files
        ), f"Expected helper.py to import platform via 'from ..platform import ...', got: {found_files}"

    @pytest.mark.asyncio
    async def test_find_imports_shows_actual_import_statement(
        self, package_with_relative_imports: Path
    ):
        """Test that import_statement shows the actual relative import syntax."""
        config = ProjectConfig(str(package_with_relative_imports))
        analyzer = JediAnalyzer(str(package_with_relative_imports), config=config)

        results = await analyzer.find_imports("mypackage.nodejs")

        # Find the result from helper.py
        helper_results = [r for r in results if "helper.py" in r["file"]]
        assert len(helper_results) > 0

        # The import statement should show the relative syntax, not the resolved absolute
        import_stmt = helper_results[0].get("import_statement", "")
        assert (
            "from .. import nodejs" in import_stmt or "from .." in import_stmt
        ), f"import_statement should show relative syntax, got: '{import_stmt}'"


class TestRelativeImportEdgeCases:
    """Test edge cases for relative import detection."""

    @pytest.fixture
    def deep_nested_package(self, temp_project_dir: Path) -> Path:
        """Create a deeply nested package structure.

        Structure:
            temp_project_dir/
            └── pkg/
                ├── __init__.py
                ├── core.py
                └── sub1/
                    ├── __init__.py
                    └── sub2/
                        ├── __init__.py
                        └── deep.py  # from ... import core
        """
        pkg_dir = temp_project_dir / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "core.py").write_text("def core_func(): pass")

        sub1 = pkg_dir / "sub1"
        sub1.mkdir()
        (sub1 / "__init__.py").write_text("")

        sub2 = sub1 / "sub2"
        sub2.mkdir()
        (sub2 / "__init__.py").write_text("")
        (sub2 / "deep.py").write_text("""\"\"\"Deeply nested with triple-dot relative import.\"\"\"

from ... import core

def use_core():
    return core.core_func()
""")

        (temp_project_dir / "pyproject.toml").write_text("""[project]
name = "pkg"
version = "1.0.0"
""")

        return temp_project_dir

    @pytest.mark.asyncio
    async def test_find_imports_triple_dot_relative(self, deep_nested_package: Path):
        """Test that 'from ... import core' (triple dot) is detected."""
        config = ProjectConfig(str(deep_nested_package))
        analyzer = JediAnalyzer(str(deep_nested_package), config=config)

        results = await analyzer.find_imports("pkg.core")

        assert len(results) > 0, (
            "find_imports should find deep.py which imports pkg.core " "via 'from ... import core'"
        )

        found_files = [r["file"] for r in results]
        assert any("deep.py" in f for f in found_files), f"Expected deep.py, got: {found_files}"


class TestImportAnalyzerRelativeImports:
    """Test ImportAnalyzer directly for relative import tracking."""

    @pytest.fixture
    def simple_relative_import_file(self, temp_project_dir: Path) -> Path:
        """Create a simple file with relative imports."""
        pkg_dir = temp_project_dir / "mypkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        test_file = pkg_dir / "consumer.py"
        test_file.write_text("""\"\"\"Consumer with various relative imports.\"\"\"

from . import sibling
from .. import parent_module
from .sub import helper

def consume():
    pass
""")

        return temp_project_dir

    def test_import_details_tracks_relative_imports(self, simple_relative_import_file: Path):
        """Test that import_details includes relative import info."""
        from pyeye.import_analyzer import ImportAnalyzer

        pkg_dir = simple_relative_import_file / "mypkg"
        analyzer = ImportAnalyzer(simple_relative_import_file)
        result = analyzer.analyze_imports(pkg_dir / "consumer.py")

        # Check import_details is populated
        assert "import_details" in result
        assert len(result["import_details"]) > 0, "Should have import details"

        # Check that relative imports are marked
        relative_imports = [d for d in result["import_details"] if d.get("is_relative")]
        assert len(relative_imports) > 0, "Should have relative imports marked"

        # Verify line numbers are captured
        for detail in result["import_details"]:
            assert "line" in detail, "Should have line number"
            assert detail["line"] > 0, "Line number should be positive"

    def test_import_details_includes_level(self, simple_relative_import_file: Path):
        """Test that import_details includes the relative level (number of dots)."""
        from pyeye.import_analyzer import ImportAnalyzer

        pkg_dir = simple_relative_import_file / "mypkg"
        analyzer = ImportAnalyzer(simple_relative_import_file)
        result = analyzer.analyze_imports(pkg_dir / "consumer.py")

        # Find the 'from .. import' (double dot)
        double_dot_imports = [d for d in result["import_details"] if d.get("level", 0) == 2]
        assert len(double_dot_imports) > 0, "Should find double-dot relative import"
