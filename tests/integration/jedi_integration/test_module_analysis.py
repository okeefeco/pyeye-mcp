"""Tests for module analysis functionality."""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.exceptions import FileAccessError
from pyeye.mcp.server import analyze_dependencies


class TestListPackages:
    """Test the list_packages functionality."""

    @pytest.mark.asyncio
    async def test_list_packages_empty_project(self, tmp_path):
        """Test listing packages in an empty project."""
        result = await JediAnalyzer(str(tmp_path)).list_packages()
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

        result = await JediAnalyzer(str(tmp_path)).list_packages()
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

        result = await JediAnalyzer(str(tmp_path)).list_packages()
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

        result = await JediAnalyzer(str(tmp_path)).list_packages()
        assert len(result) == 1
        assert result[0]["name"] == "visible"

    def test_list_packages_project_not_found(self):
        """Test error handling for non-existent project.

        The deleted ``list_packages`` tool wrapper used to validate the path
        and raise ``FileAccessError``; that path validation now lives in the
        kept ``JediAnalyzer`` constructor, which raises ``ProjectNotFoundError``
        for a non-existent project. The behavior (error on bad project path) is
        preserved at the construction site.
        """
        from pyeye.exceptions import ProjectNotFoundError

        with pytest.raises(ProjectNotFoundError) as exc_info:
            JediAnalyzer("/non/existent/path")
        assert "Project not found" in str(exc_info.value)


class TestListModules:
    """Test the list_modules functionality."""

    @pytest.mark.asyncio
    async def test_list_modules_empty_project(self, tmp_path):
        """Test listing modules in an empty project."""
        result = await JediAnalyzer(str(tmp_path)).list_modules()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_modules_single_file(self, tmp_path):
        """Test listing a single module."""
        module_file = tmp_path / "module.py"
        module_file.write_text('''
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
''')

        result = await JediAnalyzer(str(tmp_path)).list_modules()
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
        module_file.write_text("""
import os
import json
from pathlib import Path
from typing import List

def process_file(path: Path) -> List[str]:
    return []
""")

        result = await JediAnalyzer(str(tmp_path)).list_modules()
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

        result = await JediAnalyzer(str(tmp_path)).list_modules()
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

        result = await JediAnalyzer(str(tmp_path)).list_modules()
        assert len(result) == 1
        assert result[0]["name"] == "module"


class TestAnalyzeDependencies:
    """Test the analyze_dependencies functionality."""

    @pytest.mark.asyncio
    async def test_analyze_dependencies_simple(self, tmp_path):
        """Test analyzing dependencies of a simple module."""
        # Create module with imports
        module_file = tmp_path / "module.py"
        module_file.write_text("""
import os
import json
from pathlib import Path
""")

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
        (tmp_path / "module_b.py").write_text("""
import module_a

def func_b():
    module_a.func_a()
""")

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
        (pkg_dir / "module.py").write_text("""
import os
from . import __init__
""")

        result = await analyze_dependencies("mypackage.module", str(tmp_path))
        assert result["module"] == "mypackage.module"
        assert "os" in result["imports"]["stdlib"]

    @pytest.mark.asyncio
    async def test_relative_import_records_reverse_dependency(self, tmp_path):
        """A sibling importing via `from .a import f` appears in imported_by (#343)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("def f(): pass")
        (pkg / "b.py").write_text("from .a import f\n\n\ndef g():\n    f()\n")

        result = await analyze_dependencies("pkg.a", str(tmp_path))
        assert "pkg.b" in result["imported_by"]

    @pytest.mark.asyncio
    async def test_relative_import_classified_internal_not_bare_external(self, tmp_path):
        """`from .a import f` resolves to pkg.a in internal, never bare 'a' in external (#343)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("def f(): pass")
        (pkg / "b.py").write_text("from .a import f\n")

        result = await analyze_dependencies("pkg.b", str(tmp_path))
        assert "pkg.a" in result["imports"]["internal"]
        assert "a" not in result["imports"]["external"]

    @pytest.mark.asyncio
    async def test_multi_level_relative_import_reverse_dependency(self, tmp_path):
        """A `from ..a import f` two levels up is attributed to the importer (#343)."""
        pkg = tmp_path / "pkg"
        sub = pkg / "sub"
        sub.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("def f(): pass")
        (sub / "__init__.py").write_text("")
        (sub / "c.py").write_text("from ..a import f\n")

        result = await analyze_dependencies("pkg.a", str(tmp_path))
        assert "pkg.sub.c" in result["imported_by"]


class TestGetModuleInfo:
    """Test the get_module_info functionality."""

    @pytest.mark.asyncio
    async def test_get_module_info_simple(self, tmp_path):
        """Test getting info for a simple module."""
        module_file = tmp_path / "module.py"
        module_file.write_text('''
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
''')

        result = await JediAnalyzer(str(tmp_path)).get_module_info("module")
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
        module_file.write_text("""
import os
from pathlib import Path
import json as j
from typing import List, Dict
""")

        result = await JediAnalyzer(str(tmp_path)).get_module_info("module")

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
        module_file.write_text("""
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
""")

        result = await JediAnalyzer(str(tmp_path)).get_module_info("module")
        # Base complexity + if/elif/else + for + nested ifs
        assert result["metrics"]["complexity"] > 1

    @pytest.mark.asyncio
    async def test_get_module_info_module_not_found(self, tmp_path):
        """Test error when module doesn't exist."""
        with pytest.raises(FileAccessError) as exc_info:
            await JediAnalyzer(str(tmp_path)).get_module_info("nonexistent")
        assert "Module not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_module_info_includes_dependencies(self, tmp_path):
        """Test that module info includes dependency analysis."""
        (tmp_path / "module.py").write_text("import os")

        result = await JediAnalyzer(str(tmp_path)).get_module_info("module")
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


_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"
_TARGET = "mypackage._core.widgets"
_TARGET_FILE = _FIXTURE / "mypackage" / "_core" / "widgets.py"


class TestFindImporters:
    """Tests for the extracted ``find_importers`` reverse-scan method.

    Uses the committed ``resolve_project`` fixture (a real directory, not a
    tmp dir) so the file-based reverse scan exercises the same code paths the
    legacy ``analyze_dependencies`` does.
    """

    @pytest.mark.asyncio
    async def test_find_importers_reports_direct_and_relative_importers(self):
        """Both a direct ``import`` and a relative ``from`` importer are found.

        ``direct_importer`` reaches the target via ``import
        mypackage._core.widgets`` (``ast.Import``); ``rel_importer`` reaches it
        via ``from .widgets import make_widget`` (``ast.ImportFrom`` resolved
        through ``_resolve_relative_import``). Subset assertions keep this
        robust against fixture growth.
        """
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")

        modules = {m for m, _ in pairs}
        # Direct ast.Import importer.
        assert "mypackage._core.direct_importer" in modules
        # Relative ast.ImportFrom importer.
        assert "mypackage._core.rel_importer" in modules
        # Existing absolute from-importers are still present.
        assert "mypackage.usage" in modules

    @pytest.mark.asyncio
    async def test_find_importers_excludes_target_and_is_deduped(self):
        """The target's own file is excluded and modules are deduped."""
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")

        modules = [m for m, _ in pairs]
        # Target's own module never reports itself as an importer.
        assert _TARGET not in modules
        # Deduped by importer module (one entry per module).
        assert len(modules) == len(set(modules))
        # Every pair carries the importer's file path.
        for _module, file_path in pairs:
            assert isinstance(file_path, Path)

    @pytest.mark.asyncio
    async def test_find_importers_reports_non_package_script(self):
        """A standalone script outside the package is still reported.

        ``script_importer.py`` lives at the fixture root, outside
        ``mypackage/``, so its handle is the path-derived ``script_importer``
        (not a package module). The file-based scan must still attribute it,
        proving coverage breadth (tests + standalone scripts).
        """
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")

        modules = {m for m, _ in pairs}
        assert "script_importer" in modules

    @pytest.mark.asyncio
    async def test_analyze_dependencies_imported_by_parity(self):
        """``analyze_dependencies['imported_by']`` matches ``find_importers``.

        Extraction parity: the legacy method's ``imported_by`` field must equal
        the sorted, deduped module projection of ``find_importers`` output for
        the same target. Exact equality (both sides compute the same set).
        """
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")
        expected = sorted({m for m, _ in pairs})

        result = await analyzer.analyze_dependencies(_TARGET, scope="all")
        assert result["imported_by"] == expected
