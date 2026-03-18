"""Integration tests for standalone script support."""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig


@pytest.fixture
def standalone_project_path():
    """Get path to the standalone test fixture."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "standalone_project"
    return fixtures_dir


@pytest.fixture
def standalone_analyzer(standalone_project_path):
    """Create analyzer with standalone configuration."""
    config = ProjectConfig(str(standalone_project_path))
    analyzer = JediAnalyzer(str(standalone_project_path), config=config)

    # Set standalone paths from config
    standalone_config = config.get_standalone_config()
    standalone_dirs = standalone_config.get("dirs", [])
    if standalone_dirs:
        standalone_paths = []
        for dir_path in standalone_dirs:
            resolved_path = standalone_project_path / dir_path
            if resolved_path.exists():
                standalone_paths.append(resolved_path)
        analyzer.set_standalone_paths(standalone_paths)

    return analyzer


class TestStandaloneConfiguration:
    """Test standalone configuration loading."""

    def test_standalone_config_loaded(self, standalone_project_path):
        """Test that standalone config is correctly loaded."""
        config = ProjectConfig(str(standalone_project_path))
        standalone_config = config.get_standalone_config()

        assert "dirs" in standalone_config
        assert "notebooks" in standalone_config["dirs"]
        assert "scripts" in standalone_config["dirs"]
        assert standalone_config["recursive"] is True
        assert standalone_config["file_pattern"] == "*.py"

    def test_standalone_paths_set(self, standalone_analyzer):
        """Test that standalone paths are properly set."""
        assert len(standalone_analyzer.standalone_paths) == 2
        path_names = {p.name for p in standalone_analyzer.standalone_paths}
        assert "notebooks" in path_names
        assert "scripts" in path_names


class TestStandaloneFileDiscovery:
    """Test standalone file discovery."""

    @pytest.mark.asyncio
    async def test_discover_standalone_files(self, standalone_analyzer):
        """Test that standalone files are discovered."""
        files = await standalone_analyzer._discover_standalone_files()

        # Should find 3 standalone files
        assert len(files) == 3

        file_names = {f.name for f in files}
        assert "analysis1.py" in file_names
        assert "analysis2.py" in file_names
        assert "migrate.py" in file_names

    @pytest.mark.asyncio
    async def test_standalone_files_in_project_files(self, standalone_analyzer):
        """Test that standalone files are included in project files with 'all' scope."""
        files = await standalone_analyzer.get_project_files(scope="all")

        # Should include both package files and standalone files
        file_names = {f.name for f in files}
        assert "analysis1.py" in file_names
        assert "analysis2.py" in file_names
        assert "migrate.py" in file_names

    @pytest.mark.asyncio
    async def test_standalone_only_scope(self, standalone_analyzer):
        """Test 'standalone' scope returns only standalone files."""
        files = await standalone_analyzer.get_project_files(scope="standalone")

        file_names = {f.name for f in files}
        # Should only have standalone files
        assert "analysis1.py" in file_names
        assert "analysis2.py" in file_names
        assert "migrate.py" in file_names

        # Should NOT have package files
        assert "__init__.py" not in file_names
        assert "models.py" not in file_names


class TestStandaloneReferences:
    """Test finding references in standalone files."""

    @pytest.mark.asyncio
    async def test_find_symbol_in_package(self, standalone_analyzer):
        """Test finding MyClass symbol in the package."""
        results = await standalone_analyzer.find_symbol("MyClass")

        assert len(results) > 0
        assert any(r["name"] == "MyClass" for r in results)
        assert any("models.py" in r["file"] for r in results)

    @pytest.mark.asyncio
    async def test_find_references_includes_standalone(self, standalone_analyzer):
        """Test that find_references includes usages in standalone scripts."""
        # First find MyClass definition
        symbols = await standalone_analyzer.find_symbol("MyClass")
        assert len(symbols) > 0

        myclass_def = symbols[0]
        file_path = myclass_def["file"]
        line = myclass_def["line"]
        column = myclass_def["column"]

        # Now find all references to MyClass
        references = await standalone_analyzer.find_references(
            file_path, line, column, include_definitions=True
        )

        # Should find references in standalone scripts
        ref_files = {ref["file"] for ref in references}

        # Should include usage in notebooks/analysis1.py
        assert any("analysis1.py" in str(f) for f in ref_files)
        # Should include usage in scripts/migrate.py
        assert any("migrate.py" in str(f) for f in ref_files)

    @pytest.mark.asyncio
    async def test_find_references_external_standalone_dirs(self, tmp_path):
        """Test that find_references includes standalone scripts OUTSIDE project path.

        Regression test for issue #258 - find_references was not searching standalone
        directories when they were outside the main project path, because Jedi's
        get_references() only searches within the Jedi project's sys_path.
        """
        # Create main project in one directory
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        # Create package with a class
        (project_dir / "__init__.py").write_text("")
        (project_dir / "models.py").write_text("""
class MyClass:
    '''A test class'''
    pass
""")

        # Create standalone directory OUTSIDE the project
        notebooks_dir = tmp_path / "external_notebooks"
        notebooks_dir.mkdir()

        # Standalone script that uses MyClass
        (notebooks_dir / "analysis.py").write_text("""
'''Analysis notebook that uses MyClass from project'''
from myproject.models import MyClass

# Use MyClass
obj = MyClass()
""")

        # Create analyzer and configure standalone paths
        analyzer = JediAnalyzer(str(project_dir))
        analyzer.set_standalone_paths([notebooks_dir])

        # Find MyClass definition
        symbols = await analyzer.find_symbol("MyClass")
        assert len(symbols) > 0, "Should find MyClass definition"

        myclass_def = symbols[0]
        file_path = myclass_def["file"]
        line = myclass_def["line"]
        column = myclass_def["column"]

        # Find all references to MyClass
        references = await analyzer.find_references(
            file_path, line, column, include_definitions=True
        )

        # Should find reference in external standalone script
        ref_files = {ref["file"] for ref in references}

        # This is the bug: Jedi won't find the reference because notebooks_dir
        # is not in the Jedi project's sys_path
        assert any(
            "analysis.py" in str(f) for f in ref_files
        ), f"Should find reference in external standalone directory. Found refs in: {ref_files}"


class TestStandaloneImports:
    """Test import tracking in standalone files."""

    @pytest.mark.asyncio
    async def test_find_imports_in_standalone(self, standalone_analyzer):
        """Test that imports from standalone files are tracked."""
        # Find files that import mypackage
        imports = await standalone_analyzer.find_imports("mypackage")

        # Should find imports in both package and standalone files
        assert len(imports) > 0

        import_files = {imp["file"] for imp in imports}

        # Should include standalone script that imports mypackage
        assert any("analysis2.py" in imp_file for imp_file in import_files)


class TestExcludePatterns:
    """Test exclude pattern functionality."""

    @pytest.mark.asyncio
    async def test_exclude_patterns_respected(self, standalone_analyzer, standalone_project_path):
        """Test that exclude patterns are respected in standalone file discovery."""
        # Get standalone config with exclude patterns
        config = ProjectConfig(str(standalone_project_path))
        standalone_config = config.get_standalone_config()

        # Discover files with exclude patterns
        exclude_patterns = standalone_config.get("exclude_patterns", [])
        files = await standalone_analyzer._discover_standalone_files(
            exclude_patterns=exclude_patterns
        )

        file_names = {f.name for f in files}

        # test_ files should be excluded (per config)
        assert not any(f.startswith("test_") for f in file_names)


class TestCrossPlatformPaths:
    """Test cross-platform path handling."""

    @pytest.mark.asyncio
    async def test_paths_use_posix(self, standalone_analyzer):
        """Test that standalone file paths use .as_posix() format."""
        files = await standalone_analyzer._discover_standalone_files()

        for file_path in files:
            # File paths should be Path objects
            assert isinstance(file_path, Path)

            # When converted to string for comparison/display, should use forward slashes
            path_str = file_path.as_posix()
            assert "\\" not in path_str  # No backslashes


@pytest.mark.asyncio
async def test_standalone_files_not_in_packages(standalone_analyzer):
    """Test that standalone files in packages are excluded."""
    # Standalone files should NOT be discovered if they're in a package
    # (i.e., directory with __init__.py)
    files = await standalone_analyzer._discover_standalone_files()

    # None of the files should be from mypackage (which has __init__.py)
    for file_path in files:
        assert "mypackage" not in file_path.parts
