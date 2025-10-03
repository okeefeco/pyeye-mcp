"""Tests for module analysis functionality."""

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.exceptions import FileAccessError
from pyeye.mcp.server import (
    analyze_dependencies,
    get_module_info,
    list_modules,
    list_packages,
)


class TestListPackages:
    """Test the list_packages functionality."""

    @pytest.mark.asyncio
    async def test_list_packages_empty_project(self, tmp_path):
        """Test listing packages in an empty project."""
        result = await list_packages(str(tmp_path))
        assert result == []

    @pytest.mark.asyncio
    async def test_list_packages_single_package(self, tmp_path):
        """Test listing a single package."""
        # Create a package structure
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("")
        (package_dir / "module1.py").write_text("def foo(): pass")
        (package_dir / "module2.py").write_text("class Bar: pass")

        result = await list_packages(str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "mypackage"
        assert result[0]["path"] == package_dir.as_posix()
        assert result[0]["is_namespace"] is False
        assert "module1" in result[0]["modules"]
        assert "module2" in result[0]["modules"]
        assert result[0]["subpackages"] == []

    @pytest.mark.asyncio
    async def test_list_packages_nested(self, tmp_path):
        """Test listing nested packages."""
        # Create nested package structure
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "__init__.py").write_text("")

        child_dir = parent_dir / "child"
        child_dir.mkdir()
        (child_dir / "__init__.py").write_text("")
        (child_dir / "module.py").write_text("def func(): pass")

        result = await list_packages(str(tmp_path))
        assert len(result) == 2

        # Find parent package
        parent_pkg = next(p for p in result if p["name"] == "parent")
        assert "child" in parent_pkg["subpackages"]

        # Find child package
        child_pkg = next(p for p in result if p["name"] == "parent.child")
        assert "module" in child_pkg["modules"]

    @pytest.mark.asyncio
    async def test_list_packages_ignores_hidden(self, tmp_path):
        """Test that hidden directories are ignored."""
        # Create visible package
        visible_dir = tmp_path / "visible"
        visible_dir.mkdir()
        (visible_dir / "__init__.py").write_text("")

        # Create hidden package
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "__init__.py").write_text("")

        result = await list_packages(str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "visible"

    @pytest.mark.asyncio
    async def test_list_packages_project_not_found(self):
        """Test error handling for non-existent project."""
        with pytest.raises(FileAccessError) as exc_info:
            await list_packages("/non/existent/path")
        assert "Project path not found" in str(exc_info.value)


class TestListModules:
    """Test the list_modules functionality."""

    @pytest.mark.asyncio
    async def test_list_modules_empty_project(self, tmp_path):
        """Test listing modules in an empty project."""
        result = await list_modules(str(tmp_path))
        assert result == []

    @pytest.mark.asyncio
    async def test_list_modules_single_file(self, tmp_path):
        """Test listing a single module."""
        module_file = tmp_path / "module.py"
        module_file.write_text(
            '''
"""Module docstring."""

def public_func():
    """Public function."""
    pass

def _private_func():
    """Private function."""
    pass

class MyClass:
    """A class."""
    pass
'''
        )

        result = await list_modules(str(tmp_path))
        assert len(result) == 1
        module = result[0]
        assert module["name"] == "module"
        assert module["import_path"] == "module"
        assert module["file"] == module_file.as_posix()
        assert "public_func" in module["functions"]
        assert "_private_func" not in module["functions"]  # Private functions not in exports
        assert "MyClass" in module["classes"]
        assert module["size_lines"] > 0

    @pytest.mark.asyncio
    async def test_list_modules_with_imports(self, tmp_path):
        """Test module with imports."""
        module_file = tmp_path / "module.py"
        module_file.write_text(
            """
import os
import json
from pathlib import Path
from typing import List

def process_file(path: Path) -> List[str]:
    return []
"""
        )

        result = await list_modules(str(tmp_path))
        assert len(result) == 1
        module = result[0]
        assert "os" in module["imports_from"]
        assert "json" in module["imports_from"]
        assert "pathlib" in module["imports_from"]
        assert "typing" in module["imports_from"]

    @pytest.mark.asyncio
    async def test_list_modules_in_package(self, tmp_path):
        """Test listing modules in a package."""
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("# Package init")
        (package_dir / "module1.py").write_text("def func1(): pass")
        (package_dir / "module2.py").write_text("def func2(): pass")

        result = await list_modules(str(tmp_path))
        assert len(result) == 3  # __init__ + 2 modules

        # Check import paths
        import_paths = [m["import_path"] for m in result]
        assert "mypackage" in import_paths  # __init__.py
        assert "mypackage.module1" in import_paths
        assert "mypackage.module2" in import_paths

    @pytest.mark.asyncio
    async def test_list_modules_skips_tests(self, tmp_path):
        """Test that test directories are skipped."""
        # Create main module
        (tmp_path / "module.py").write_text("def func(): pass")

        # Create test directory
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_module.py").write_text("def test_func(): pass")

        result = await list_modules(str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "module"


class TestAnalyzeDependencies:
    """Test the analyze_dependencies functionality."""

    @pytest.mark.asyncio
    async def test_analyze_dependencies_simple(self, tmp_path):
        """Test analyzing dependencies of a simple module."""
        # Create module with imports
        module_file = tmp_path / "module.py"
        module_file.write_text(
            """
import os
import json
from pathlib import Path
"""
        )

        result = await analyze_dependencies("module", str(tmp_path))
        assert result["module"] == "module"
        assert "os" in result["imports"]["stdlib"]
        assert "json" in result["imports"]["stdlib"]
        assert "pathlib" in result["imports"]["stdlib"]
        assert result["imports"]["internal"] == []
        assert result["imports"]["external"] == []

    @pytest.mark.asyncio
    async def test_analyze_dependencies_internal(self, tmp_path):
        """Test analyzing internal dependencies."""
        # Create two modules where one imports the other
        (tmp_path / "module_a.py").write_text("def func_a(): pass")
        (tmp_path / "module_b.py").write_text(
            """
import module_a

def func_b():
    module_a.func_a()
"""
        )

        result = await analyze_dependencies("module_b", str(tmp_path))
        assert "module_a" in result["imports"]["internal"]
        assert result["imported_by"] == []  # module_b is not imported by anything

        # Check reverse dependency
        result_a = await analyze_dependencies("module_a", str(tmp_path))
        assert "module_b" in result_a["imported_by"]

    @pytest.mark.asyncio
    async def test_analyze_dependencies_circular(self, tmp_path):
        """Test detecting circular dependencies."""
        # Create circular dependency
        (tmp_path / "module_a.py").write_text("import module_b")
        (tmp_path / "module_b.py").write_text("import module_a")

        result = await analyze_dependencies("module_a", str(tmp_path))
        assert "module_b" in result["imports"]["internal"]
        assert "module_b" in result["circular_dependencies"]

    @pytest.mark.asyncio
    async def test_analyze_dependencies_module_not_found(self, tmp_path):
        """Test error when module doesn't exist."""
        with pytest.raises(FileAccessError) as exc_info:
            await analyze_dependencies("nonexistent", str(tmp_path))
        assert "Module not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_analyze_dependencies_package(self, tmp_path):
        """Test analyzing dependencies of a package module."""
        # Create package structure
        pkg_dir = tmp_path / "mypackage"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "module.py").write_text(
            """
import os
from . import __init__
"""
        )

        result = await analyze_dependencies("mypackage.module", str(tmp_path))
        assert result["module"] == "mypackage.module"
        assert "os" in result["imports"]["stdlib"]


class TestGetModuleInfo:
    """Test the get_module_info functionality."""

    @pytest.mark.asyncio
    async def test_get_module_info_simple(self, tmp_path):
        """Test getting info for a simple module."""
        module_file = tmp_path / "module.py"
        module_file.write_text(
            '''
"""Module documentation."""

MODULE_CONSTANT = 42

def public_function(arg1, arg2):
    """Function documentation."""
    return arg1 + arg2

def _private_function():
    pass

class MyClass:
    """Class documentation."""

    def method(self):
        """Method documentation."""
        pass

    def _private_method(self):
        pass
'''
        )

        result = await get_module_info("module", str(tmp_path))
        assert result["module"] == "module"
        assert result["file"] == module_file.as_posix()
        assert result["docstring"] == "Module documentation."

        # Check exports
        assert "public_function" in result["exports"]
        assert "MyClass" in result["exports"]
        assert "MODULE_CONSTANT" in result["exports"]
        assert "_private_function" not in result["exports"]

        # Check classes
        assert len(result["classes"]) == 1
        class_info = result["classes"][0]
        assert class_info["name"] == "MyClass"
        assert class_info["docstring"] == "Class documentation."
        assert len(class_info["methods"]) == 2

        # Check functions
        public_funcs = [f for f in result["functions"] if not f["is_private"]]
        assert len(public_funcs) == 1
        assert public_funcs[0]["name"] == "public_function"
        assert public_funcs[0]["args"] == ["arg1", "arg2"]

        # Check variables
        assert len(result["variables"]) == 1
        assert result["variables"][0]["name"] == "MODULE_CONSTANT"

        # Check metrics
        assert result["metrics"]["classes"] == 1
        assert result["metrics"]["functions"] == 2  # Including private
        assert result["metrics"]["lines"] > 0
        assert result["metrics"]["complexity"] >= 1

    @pytest.mark.asyncio
    async def test_get_module_info_with_imports(self, tmp_path):
        """Test module info with imports."""
        module_file = tmp_path / "module.py"
        module_file.write_text(
            """
import os
from pathlib import Path
import json as j
from typing import List, Dict
"""
        )

        result = await get_module_info("module", str(tmp_path))

        # Check imports
        imports = result["imports"]
        assert len(imports) > 0

        # Find specific imports
        os_import = next((i for i in imports if i["module"] == "os"), None)
        assert os_import is not None
        assert os_import["alias"] is None

        json_import = next((i for i in imports if i["module"] == "json"), None)
        assert json_import is not None
        assert json_import["alias"] == "j"

    @pytest.mark.asyncio
    async def test_get_module_info_complexity(self, tmp_path):
        """Test cyclomatic complexity calculation."""
        module_file = tmp_path / "module.py"
        module_file.write_text(
            """
def complex_function(x):
    if x > 0:
        if x > 10:
            return "big"
        else:
            return "small"
    elif x < 0:
        return "negative"
    else:
        return "zero"

    for i in range(10):
        if i % 2 == 0:
            print(i)
"""
        )

        result = await get_module_info("module", str(tmp_path))
        # Base complexity + if/elif/else + for + nested ifs
        assert result["metrics"]["complexity"] > 1

    @pytest.mark.asyncio
    async def test_get_module_info_module_not_found(self, tmp_path):
        """Test error when module doesn't exist."""
        with pytest.raises(FileAccessError) as exc_info:
            await get_module_info("nonexistent", str(tmp_path))
        assert "Module not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_module_info_includes_dependencies(self, tmp_path):
        """Test that module info includes dependency analysis."""
        (tmp_path / "module.py").write_text("import os")

        result = await get_module_info("module", str(tmp_path))
        assert result["dependencies"] is not None
        assert result["dependencies"]["module"] == "module"
        assert "os" in result["dependencies"]["imports"]["stdlib"]


class TestJediAnalyzerMethods:
    """Test the JediAnalyzer methods directly."""

    def test_analyzer_initialization(self, tmp_path):
        """Test JediAnalyzer initialization."""
        analyzer = JediAnalyzer(str(tmp_path))
        assert analyzer.project_path == tmp_path

    def test_analyzer_project_not_found(self):
        """Test analyzer with non-existent project."""
        from pyeye.exceptions import ProjectNotFoundError

        with pytest.raises(ProjectNotFoundError):
            JediAnalyzer("/non/existent/path")

    @pytest.mark.asyncio
    async def test_list_packages_method(self, tmp_path):
        """Test list_packages method directly."""
        # Create a package
        pkg_dir = tmp_path / "package"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        analyzer = JediAnalyzer(str(tmp_path))
        result = await analyzer.list_packages()
        assert len(result) == 1
        assert result[0]["name"] == "package"

    @pytest.mark.asyncio
    async def test_list_modules_method(self, tmp_path):
        """Test list_modules method directly."""
        (tmp_path / "module.py").write_text("def func(): pass")

        analyzer = JediAnalyzer(str(tmp_path))
        result = await analyzer.list_modules()
        assert len(result) == 1
        assert result[0]["name"] == "module"

    @pytest.mark.asyncio
    async def test_analyze_dependencies_method(self, tmp_path):
        """Test analyze_dependencies method directly."""
        (tmp_path / "module.py").write_text("import os")

        analyzer = JediAnalyzer(str(tmp_path))
        result = await analyzer.analyze_dependencies("module")
        assert "os" in result["imports"]["stdlib"]

    @pytest.mark.asyncio
    async def test_get_module_info_method(self, tmp_path):
        """Test get_module_info method directly."""
        (tmp_path / "module.py").write_text('"""Doc."""\ndef func(): pass')

        analyzer = JediAnalyzer(str(tmp_path))
        result = await analyzer.get_module_info("module")
        assert result["docstring"] == "Doc."
        assert len(result["functions"]) == 1
