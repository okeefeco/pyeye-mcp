"""Tests for Jedi analyzer integration."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.exceptions import AnalysisError, FileAccessError


class TestJediAnalyzer:
    """Test the JediAnalyzer class."""

    def test_initialization(self, temp_project_dir):
        """Test analyzer initialization."""
        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project") as mock_project:
            analyzer = JediAnalyzer(str(temp_project_dir))

            assert analyzer.project_path == temp_project_dir
            # JediAnalyzer calls .resolve() before passing to jedi.Project, which
            # collapses symlinks (macOS /var -> /private/var) and expands Windows
            # short paths (RUNNER~1 -> runneradmin). Apply the same canonicalization
            # to the expected value so the assertion is platform-independent.
            mock_project.assert_called_once_with(path=temp_project_dir.resolve().as_posix())

    @pytest.mark.asyncio
    async def test_find_symbol(self, temp_project_dir):
        """find_symbol returns the project definition of a name (AST name-index)."""
        (temp_project_dir / "test_module.py").write_text("def test_function():\n    pass\n")
        project_graph.invalidate()
        analyzer = JediAnalyzer(str(temp_project_dir))
        results = await analyzer.find_symbol("test_function")

        assert len(results) == 1
        assert results[0]["name"] == "test_function"
        assert results[0]["type"] == "function"
        assert results[0]["line"] == 1

    @pytest.mark.asyncio
    async def test_find_symbol_fuzzy(self, temp_project_dir):
        """fuzzy=False returns the exact match; fuzzy=True returns substring matches."""
        (temp_project_dir / "module.py").write_text(
            "def test_func():\n    pass\n\n\n"
            "def test_function():\n    pass\n\n\n"
            "def testing_function():\n    pass\n"
        )
        project_graph.invalidate()
        analyzer = JediAnalyzer(str(temp_project_dir))

        # Non-fuzzy returns only the exact match.
        results = await analyzer.find_symbol("test_function", fuzzy=False)
        assert len(results) == 1
        assert results[0]["name"] == "test_function"

        # Fuzzy returns every indexed name containing the query.
        results = await analyzer.find_symbol("test", fuzzy=True)
        assert len(results) == 3

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_goto_definition(self, mock_project_class, mock_script_class, temp_project_dir):
        """Test going to symbol definition."""
        mock_project = Mock()
        mock_project_class.return_value = mock_project

        # Create test file
        test_file = temp_project_dir / "test.py"
        test_file.write_text("""
def test_function():
    pass

test_function()
""")

        # Mock definition
        mock_definition = Mock()
        mock_definition.name = "test_function"
        mock_definition.module_name = "test"
        mock_definition.line = 2
        mock_definition.column = 4
        mock_definition.module_path = test_file
        mock_definition.type = "function"
        mock_definition.docstring = Mock(return_value="Function docstring")

        mock_script = Mock()
        mock_script.goto.return_value = [mock_definition]
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))
        result = await analyzer.goto_definition(str(test_file), 5, 0)

        assert result is not None
        assert result["name"] == "test_function"
        assert result["line"] == 2
        assert "docstring" in result

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_goto_definition_no_result(
        self, mock_project_class, mock_script_class, temp_project_dir
    ):
        """Test goto definition with no results."""
        mock_project = Mock()
        mock_project_class.return_value = mock_project

        test_file = temp_project_dir / "test.py"
        test_file.write_text("# Empty file")

        mock_script = Mock()
        mock_script.goto.return_value = []
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))
        result = await analyzer.goto_definition(str(test_file), 1, 0)

        assert result is None

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_find_references(self, mock_project_class, mock_script_class, temp_project_dir):
        """Test finding symbol references."""
        mock_project = Mock()
        mock_project_class.return_value = mock_project

        test_file = temp_project_dir / "test.py"
        test_file.write_text("""
def func():
    pass

func()
func()
""")

        # Mock references
        references = []
        for line in [2, 5, 6]:  # Definition and two calls
            mock_ref = Mock()
            mock_ref.line = line
            mock_ref.column = 0
            mock_ref.module_path = test_file
            mock_ref.module_name = "test"
            mock_ref.is_definition = Mock(return_value=(line == 2))
            mock_ref.name = "func"
            mock_ref.type = "function"
            mock_ref.description = "def func"
            mock_ref.full_name = "test.func"
            mock_ref.docstring = Mock(return_value="")
            references.append(mock_ref)

        mock_script = Mock()
        mock_script.get_references.return_value = references
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))
        results = await analyzer.find_references(str(test_file), 2, 0)

        assert len(results) == 3
        assert results[0]["is_definition"]
        assert not results[1]["is_definition"]
        assert not results[2]["is_definition"]

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_get_type_info(self, mock_project_class, mock_script_class, temp_project_dir):
        """Test getting type information."""
        mock_project = Mock()
        mock_project_class.return_value = mock_project

        test_file = temp_project_dir / "test.py"
        test_file.write_text("""
def func() -> str:
    return "hello"

result = func()
""")

        # Mock type inference
        mock_type = Mock()
        mock_type.name = "str"
        mock_type.type = "class"
        mock_type.module_name = "builtins"
        mock_type.description = "str() -> str"
        mock_type.full_name = "builtins.str"
        mock_type.docstring = Mock(return_value="String type")

        # Mock help info
        mock_help = Mock()
        mock_help.docstring = Mock(return_value="String type")

        mock_script = Mock()
        mock_script.infer.return_value = [mock_type]
        mock_script.help.return_value = [mock_help]
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))
        result = await analyzer.get_type_info(str(test_file), 5, 0)

        assert result is not None
        assert "inferred_types" in result
        assert len(result["inferred_types"]) == 1
        assert result["inferred_types"][0]["name"] == "str"
        assert "docstring" in result

    @pytest.mark.asyncio
    async def test_find_reexports(self):
        """Test finding re-export paths for symbols."""
        # Create test fixture
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reexport_test"
        analyzer = JediAnalyzer(str(fixture_path))

        # Test finding re-exports for User class
        user_file = fixture_path / "models" / "user.py"
        import_paths = await analyzer.find_reexports("User", "models.user", str(user_file))

        assert len(import_paths) >= 1
        assert "from models.user import User" in import_paths
        # Should also find the re-export from models/__init__.py
        assert "from models import User" in import_paths

    @pytest.mark.asyncio
    async def test_find_symbol_with_import_paths(self):
        """Test find_symbol includes import_paths for re-exported symbols."""
        # Use the test fixture
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reexport_test"
        analyzer = JediAnalyzer(str(fixture_path))

        # Find the User symbol
        results = await analyzer.find_symbol("User", include_import_paths=True)

        # Should find at least one result
        assert len(results) > 0

        # Check that import_paths is included for symbols that are re-exported
        for result in results:
            if result.get("name") == "User":
                # Should have import_paths field if re-exported
                if "reexport_test.models.user" in result.get("full_name", ""):
                    assert "import_paths" in result
                    assert len(result["import_paths"]) >= 1

    @pytest.mark.asyncio
    async def test_multi_level_reexports(self):
        """Test multi-level re-exports (core -> auth -> authenticator)."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reexport_test"
        analyzer = JediAnalyzer(str(fixture_path))

        # Test finding re-exports for Authenticator class (multi-level)
        auth_file = fixture_path / "core" / "auth" / "authenticator.py"
        import_paths = await analyzer.find_reexports(
            "Authenticator", "core.auth.authenticator", str(auth_file)
        )

        assert len(import_paths) >= 1
        # Direct import
        assert "from core.auth.authenticator import Authenticator" in import_paths
        # Re-export from auth/__init__.py
        assert "from core.auth import Authenticator" in import_paths
        # Re-export from core/__init__.py
        assert "from core import Authenticator" in import_paths

    @pytest.mark.asyncio
    async def test_find_reexports_with_longer_file_path(self):
        """Test that file path is used when it provides more complete module info."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reexport_test"
        analyzer = JediAnalyzer(str(fixture_path))

        # Test with a short module name but complete file path
        # This should use the file path to determine the full module
        file_path = str(fixture_path / "models" / "user.py")
        # Pass just "user" as module, file path should expand it to "models.user"
        import_paths = await analyzer.find_reexports("User", "user", file_path)

        # The function should use the file path to get full module
        assert len(import_paths) >= 1
        # Even with short module input, we get the re-export
        assert "from models import User" in import_paths

    def test_find_init_file_with_matching_base_name(self):
        """Test _find_init_file when base directory name matches module prefix."""
        # Create a temporary test structure where base name matches
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create mypackage/mypackage/__init__.py structure
            base = Path(tmpdir) / "mypackage"
            base.mkdir()
            sub = base / "mypackage"
            sub.mkdir()
            init_file = sub / "__init__.py"
            init_file.write_text("# Test init")

            analyzer = JediAnalyzer(str(base))
            # Looking for mypackage.submodule, but we're already in mypackage base
            found = analyzer._find_init_file("mypackage")
            assert found == init_file

    @pytest.mark.asyncio
    async def test_check_symbol_in_init_with_all(self):
        """Test _check_symbol_in_init with __all__ declaration."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            init_file = Path(tmpdir) / "__init__.py"
            init_file.write_text("""
from .models import User, Admin

__all__ = [
    "User",
    "Admin",
]
""")

            fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reexport_test"
            analyzer = JediAnalyzer(str(fixture_path))

            # Check symbol that's in __all__ and imported
            assert await analyzer._check_symbol_in_init(init_file, "User", "models")
            assert await analyzer._check_symbol_in_init(init_file, "Admin", "models")
            # Check symbol not in __all__
            assert not await analyzer._check_symbol_in_init(init_file, "NotThere", "models")

    @pytest.mark.asyncio
    async def test_check_symbol_in_init_error_handling(self):
        """Test _check_symbol_in_init handles file read errors gracefully."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reexport_test"
        analyzer = JediAnalyzer(str(fixture_path))

        # Test with non-existent file
        non_existent = Path("/does/not/exist/__init__.py")
        result = await analyzer._check_symbol_in_init(non_existent, "Symbol", "module")
        assert result is False  # Should return False on error

    def test_find_init_file_not_found(self):
        """Test _find_init_file returns None when init file doesn't exist."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reexport_test"
        analyzer = JediAnalyzer(str(fixture_path))

        # Test with module that doesn't exist
        result = analyzer._find_init_file("nonexistent.module.path")
        assert result is None  # Should return None when not found

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_find_imports(self, mock_project_class, mock_script_class, temp_project_dir):
        """Test finding module imports."""
        mock_project = Mock()
        mock_project_class.return_value = mock_project

        # Create test files with imports
        file1 = temp_project_dir / "file1.py"
        file1.write_text("""
import os
from pathlib import Path
import sys
""")

        file2 = temp_project_dir / "file2.py"
        file2.write_text("""
import os
import json
""")

        # Mock the get_names results for each file
        mock_name1 = Mock()
        mock_name1.type = "module"
        mock_name1.full_name = "os"
        mock_name1.line = 2
        mock_name1.column = 0
        mock_name1.description = "import os"

        mock_name2 = Mock()
        mock_name2.type = "module"
        mock_name2.full_name = "os"
        mock_name2.line = 2
        mock_name2.column = 0
        mock_name2.description = "import os"

        # Mock Script for each file
        mock_script1 = Mock()
        mock_script1.get_names.return_value = [mock_name1]

        mock_script2 = Mock()
        mock_script2.get_names.return_value = [mock_name2]

        # Make Script return different mocks for different files
        mock_script_class.side_effect = [mock_script1, mock_script2]

        analyzer = JediAnalyzer(str(temp_project_dir))
        results = await analyzer.find_imports("os")

        assert len(results) == 2
        assert all(r["import_statement"] == "import os" for r in results)

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_get_call_hierarchy(
        self, mock_project_class, mock_script_class, temp_project_dir
    ):
        """Test getting call hierarchy for functions."""
        mock_project = Mock()
        mock_project_class.return_value = mock_project

        test_file = temp_project_dir / "test.py"
        test_file.write_text("""
def caller():
    callee()

def callee():
    pass

def main():
    caller()
""")

        # Mock function definition search
        mock_func_def = Mock()
        mock_func_def.name = "callee"
        mock_func_def.type = "function"
        mock_func_def.module_path = test_file
        mock_func_def.line = 5
        mock_func_def.column = 4

        mock_project.search.return_value = [mock_func_def]

        # Mock references (callers)
        mock_ref = Mock()
        mock_ref.is_definition = Mock(return_value=False)
        mock_ref.module_path = test_file
        mock_ref.line = 3
        mock_ref.column = 4

        mock_script = Mock()
        mock_script.get_references.return_value = [mock_func_def, mock_ref]
        mock_script.get_names.return_value = []
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))
        result = await analyzer.get_call_hierarchy("callee", str(test_file))

        assert result["function"] == "callee"
        assert len(result["callers"]) == 1
        assert result["callers"][0]["line"] == 3

    @pytest.mark.asyncio
    async def test_error_handling(self, temp_project_dir, caplog):
        """find_symbol wraps an internal search failure in AnalysisError."""
        analyzer = JediAnalyzer(str(temp_project_dir))

        # Make the name-index build fail; find_symbol must wrap it.
        with (
            patch(
                "pyeye.analyzers.project_graph.get_name_index",
                side_effect=Exception("Jedi error"),
            ),
            pytest.raises(AnalysisError) as exc_info,
        ):
            await analyzer.find_symbol("test")

        assert "Failed to search for symbol 'test'" in str(exc_info.value)
        assert "Error in find_symbol" in caplog.text

    @pytest.mark.asyncio
    async def test_serialize_name(self, temp_project_dir):
        """Test serializing Jedi name objects."""
        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project"):
            analyzer = JediAnalyzer(str(temp_project_dir))

            # Create mock name object matching the fields _serialize_name reads
            mock_name = Mock()
            mock_name.name = "TestClass"
            mock_name.line = 42
            mock_name.column = 8
            mock_name.module_path = Path("/test/module.py")
            mock_name.type = "class"
            mock_name.description = "class TestClass"
            mock_name.full_name = "test_module.TestClass"
            mock_name.docstring = Mock(return_value="Test class docstring")

            result = await analyzer._serialize_name(mock_name, include_docstring=True)

            assert result["name"] == "TestClass"
            assert result["line"] == 42
            assert result["column"] == 8
            assert result["type"] == "class"
            assert result["file"] == "/test/module.py"
            assert result["docstring"] == "Test class docstring"

    @pytest.mark.asyncio
    async def test_nonexistent_file_handling(self, temp_project_dir):
        """Test handling of non-existent files."""
        with patch("pyeye.analyzers.jedi_analyzer.jedi.Project"):
            analyzer = JediAnalyzer(str(temp_project_dir))

            # Try to analyze non-existent file - should raise FileAccessError
            with pytest.raises(FileAccessError) as exc_info:
                await analyzer.goto_definition("/nonexistent/file.py", 1, 0)
            assert "File not found" in str(exc_info.value)

            # find_references should also raise FileAccessError for non-existent files
            with pytest.raises(FileAccessError):
                await analyzer.find_references("/nonexistent/file.py", 1, 0)

    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    def test_multiple_projects(self, mock_project_class, tmp_path):
        """Test that analyzer can work with different projects."""
        # Create actual directories for the test
        project1 = tmp_path / "project1"
        project2 = tmp_path / "project2"
        project1.mkdir()
        project2.mkdir()

        # Create two analyzers for different projects
        _ = JediAnalyzer(str(project1))
        _ = JediAnalyzer(str(project2))

        # Should create two different project instances
        assert mock_project_class.call_count == 2

        # Check paths - we now pass POSIX strings to Jedi
        calls = mock_project_class.call_args_list
        assert calls[0][1]["path"] == project1.as_posix()
        assert calls[1][1]["path"] == project2.as_posix()

    @pytest.mark.asyncio
    async def test_get_type_info_error_handling(self, temp_project_dir):
        """Test error handling in get_type_info."""
        analyzer = JediAnalyzer(str(temp_project_dir))

        # Test with non-existent file
        with pytest.raises(FileAccessError) as exc_info:
            await analyzer.get_type_info("nonexistent.py", 1, 0)
        assert "nonexistent.py" in str(exc_info.value)

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @pytest.mark.asyncio
    async def test_get_type_info_jedi_error(self, mock_script_class, temp_project_dir):
        """Test get_type_info when Jedi raises an error."""
        # Create a test file
        test_file = temp_project_dir / "test.py"
        test_file.write_text("x = 1")

        # Make Script.infer raise an exception
        mock_script = Mock()
        mock_script.infer.side_effect = Exception("Jedi inference error")
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))

        with pytest.raises(AnalysisError) as exc_info:
            await analyzer.get_type_info(str(test_file), 1, 0)
        assert "Failed to get type info" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_find_references_error_handling(self, temp_project_dir):
        """Test error handling in find_references."""
        analyzer = JediAnalyzer(str(temp_project_dir))

        # Test with non-existent file
        with pytest.raises(FileAccessError) as exc_info:
            await analyzer.find_references("nonexistent.py", 1, 0)
        assert "nonexistent.py" in str(exc_info.value)

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @pytest.mark.asyncio
    async def test_find_references_jedi_error(self, mock_script_class, temp_project_dir, caplog):
        """Test find_references when Jedi raises an error."""
        # Create a test file
        test_file = temp_project_dir / "test.py"
        test_file.write_text("x = 1")

        # Make Script.get_references raise an exception
        mock_script = Mock()
        mock_script.get_references.side_effect = Exception("Jedi references error")
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))

        # Should return empty results and log error
        results = await analyzer.find_references(str(test_file), 1, 0)
        assert results == []
        assert "Error in find_references" in caplog.text

    @patch("pyeye.analyzers.jedi_analyzer.rglob_async")
    @pytest.mark.asyncio
    async def test_find_imports_file_read_error(self, mock_rglob, temp_project_dir):
        """Test find_imports when file reading fails."""
        # Mock rglob to return a file that will fail to read
        mock_rglob.return_value = [Path("/unreadable/file.py")]

        analyzer = JediAnalyzer(str(temp_project_dir))
        results = await analyzer.find_imports("os")

        # Should return empty results when files can't be read
        assert results == []

    @pytest.mark.asyncio
    async def test_get_call_hierarchy_search_error(self, temp_project_dir):
        """get_call_hierarchy wraps an internal search failure in AnalysisError."""
        analyzer = JediAnalyzer(str(temp_project_dir))

        with (
            patch(
                "pyeye.analyzers.project_graph.get_name_index",
                side_effect=Exception("Search failed"),
            ),
            pytest.raises(AnalysisError) as exc_info,
        ):
            await analyzer.get_call_hierarchy("test_func")
        assert "Failed to get call hierarchy" in str(exc_info.value)

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_get_call_hierarchy_with_file_path(
        self, mock_project_class, mock_script_class, temp_project_dir
    ):
        """Test get_call_hierarchy with specific file path."""
        # Create a test file
        test_file = temp_project_dir / "test.py"
        test_file.write_text("def test_func():\n    pass")

        mock_project = Mock()
        mock_project_class.return_value = mock_project

        # Mock search result
        mock_def = Mock()
        mock_def.name = "test_func"
        mock_def.type = "function"
        mock_def.module_path = test_file
        mock_def.line = 1
        mock_def.column = 4
        mock_def.get_line_code.return_value = "def test_func():"
        mock_project.search.return_value = [mock_def]

        # Mock script for references
        mock_script = Mock()
        mock_script.get_references.return_value = []
        mock_script.get_names.return_value = []
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))
        result = await analyzer.get_call_hierarchy("test_func", str(test_file))

        assert result["function"] == "test_func"
        assert "callers" in result
        assert "callees" in result

    @patch("pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_script")
    @patch("pyeye.analyzers.jedi_analyzer.jedi.Project")
    @pytest.mark.asyncio
    async def test_get_call_hierarchy_with_class(
        self, mock_project_class, mock_script_class, temp_project_dir
    ):
        """Test get_call_hierarchy supports class names."""
        mock_project = Mock()
        mock_project_class.return_value = mock_project

        test_file = temp_project_dir / "test.py"
        test_file.write_text("""
class MyClass:
    def __init__(self):
        self.value = 0

def create():
    obj = MyClass()
    return obj
""")

        # Mock class definition search
        mock_class_def = Mock()
        mock_class_def.name = "MyClass"
        mock_class_def.type = "class"
        mock_class_def.module_path = test_file
        mock_class_def.line = 2
        mock_class_def.column = 6

        mock_project.search.return_value = [mock_class_def]

        # Mock references (instantiation sites)
        mock_ref = Mock()
        mock_ref.is_definition = Mock(return_value=False)
        mock_ref.module_path = test_file
        mock_ref.line = 7
        mock_ref.column = 10

        mock_script = Mock()
        mock_script.get_references.return_value = [mock_class_def, mock_ref]
        mock_script.get_names.return_value = []
        mock_script_class.return_value = mock_script

        analyzer = JediAnalyzer(str(temp_project_dir))
        result = await analyzer.get_call_hierarchy("MyClass", str(test_file))

        assert result["function"] == "MyClass"
        assert len(result["callers"]) == 1
        assert result["callers"][0]["line"] == 7

    @pytest.mark.asyncio
    async def test_find_subclasses_direct(self, temp_project_dir):
        """Test finding direct subclasses only."""
        # Create test files with class hierarchy
        base_file = temp_project_dir / "base.py"
        base_file.write_text("""
class Animal:
    def speak(self):
        pass

class Dog(Animal):
    def speak(self):
        return "Woof!"

class Cat(Animal):
    def speak(self):
        return "Meow!"
""")

        child_file = temp_project_dir / "child.py"
        child_file.write_text("""
from base import Dog

class Puppy(Dog):
    def speak(self):
        return "Yip!"

class Kitten(Cat):  # This won't be found since Cat is not imported
    def speak(self):
        return "Mew!"
""")

        analyzer = JediAnalyzer(str(temp_project_dir))

        # Find direct subclasses of Animal only
        raw = await analyzer.find_subclasses("Animal", include_indirect=False)
        assert not raw.get("ambiguous"), "Animal is unambiguous in this project"
        results = raw["subclasses"]

        # Should find Dog and Cat (direct subclasses)
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert "Dog" in names
        assert "Cat" in names

        # All should be marked as direct
        for result in results:
            assert result["is_direct"] is True
            assert result["direct_parent"] == "Animal"

    @pytest.mark.asyncio
    async def test_find_subclasses_indirect(self, temp_project_dir):
        """Test finding both direct and indirect subclasses."""
        # Create test files with deeper hierarchy
        base_file = temp_project_dir / "hierarchy.py"
        base_file.write_text("""
class Animal:
    pass

class Mammal(Animal):
    pass

class Dog(Mammal):
    pass

class GoldenRetriever(Dog):
    pass

class Bird(Animal):
    pass

class Eagle(Bird):
    pass
""")

        analyzer = JediAnalyzer(str(temp_project_dir))

        # Find all subclasses of Animal (direct and indirect)
        raw = await analyzer.find_subclasses("Animal", include_indirect=True)
        assert not raw.get("ambiguous"), "Animal is unambiguous in this project"
        results = raw["subclasses"]

        # Should find all subclasses
        assert len(results) == 5
        names = {r["name"] for r in results}
        assert names == {"Mammal", "Dog", "GoldenRetriever", "Bird", "Eagle"}

        # Check direct vs indirect
        for result in results:
            if result["name"] in ["Mammal", "Bird"]:
                assert result["is_direct"] is True
                assert result["direct_parent"] == "Animal"
            else:
                assert result["is_direct"] is False
                assert result["direct_parent"] != "Animal"

    @pytest.mark.asyncio
    async def test_find_subclasses_with_hierarchy(self, temp_project_dir):
        """Test finding subclasses with full hierarchy chain."""
        # Create test file
        test_file = temp_project_dir / "classes.py"
        test_file.write_text("""
class A:
    pass

class B(A):
    pass

class C(B):
    pass

class D(C):
    pass
""")

        analyzer = JediAnalyzer(str(temp_project_dir))

        # Find subclasses with hierarchy
        raw = await analyzer.find_subclasses("A", show_hierarchy=True)
        assert not raw.get("ambiguous"), "A is unambiguous in this project"
        results = raw["subclasses"]

        # Check that hierarchy chains are included
        for result in results:
            assert "inheritance_chain" in result
            chain = result["inheritance_chain"]
            assert isinstance(chain, list)
            assert result["name"] in chain
            assert "object" in chain  # Should end with object

            # Check specific chains
            if result["name"] == "D":
                assert "C" in chain
                assert "B" in chain
                assert "A" in chain

    @pytest.mark.asyncio
    async def test_find_subclasses_multiple_inheritance(self, temp_project_dir):
        """Test finding subclasses with multiple inheritance."""
        test_file = temp_project_dir / "multiple.py"
        test_file.write_text("""
class Flyable:
    def fly(self):
        pass

class Swimmable:
    def swim(self):
        pass

class Duck(Flyable, Swimmable):
    pass

class Airplane(Flyable):
    pass
""")

        analyzer = JediAnalyzer(str(temp_project_dir))

        # Find subclasses of Flyable
        raw = await analyzer.find_subclasses("Flyable")
        assert not raw.get("ambiguous"), "Flyable is unambiguous in this project"
        results = raw["subclasses"]

        assert len(results) == 2
        names = {r["name"] for r in results}
        assert "Duck" in names
        assert "Airplane" in names

    @pytest.mark.asyncio
    async def test_find_subclasses_base_not_found(self, temp_project_dir):
        """Test find_subclasses when base class doesn't exist."""
        analyzer = JediAnalyzer(str(temp_project_dir))

        # Try to find subclasses of non-existent class
        raw = await analyzer.find_subclasses("NonExistentClass")
        # Should return unambiguous empty list (no classes exist with that name)
        assert not raw.get("ambiguous")
        results = raw["subclasses"]
        assert results == []

    @pytest.mark.asyncio
    async def test_find_subclasses_builtin_class(self, temp_project_dir):
        """Test finding subclasses of builtin classes."""
        test_file = temp_project_dir / "exceptions.py"
        test_file.write_text("""
class CustomError(Exception):
    pass

class ValidationError(CustomError):
    pass

class NetworkError(Exception):
    pass
""")

        analyzer = JediAnalyzer(str(temp_project_dir))

        # Find subclasses of Exception
        raw = await analyzer.find_subclasses("Exception")
        # Exception is a unique name in this temp project
        assert not raw.get("ambiguous"), "Exception is unambiguous in this project"
        results = raw["subclasses"]

        # Should find CustomError and NetworkError (direct)
        # and ValidationError (indirect)
        assert len(results) >= 2
        names = {r["name"] for r in results}
        assert "CustomError" in names
        assert "NetworkError" in names

    @pytest.mark.asyncio
    async def test_find_subclasses_identical_names_different_modules(self, temp_project_dir):
        """Test finding subclasses when multiple classes have the same name in different modules.

        Regression test for issue #234 - find_subclasses was using simple class name
        for deduplication instead of FQN, causing it to skip identically-named classes.
        """
        # Create base class
        base_file = temp_project_dir / "base.py"
        base_file.write_text("""
class BaseService:
    pass
""")

        # Create module A with a class named "Service"
        module_a = temp_project_dir / "module_a"
        module_a.mkdir()
        (module_a / "__init__.py").write_text("")
        (module_a / "components.py").write_text("""
from base import BaseService

class Service(BaseService):
    '''Service implementation for module A'''
    pass
""")

        # Create module B with a DIFFERENT class also named "Service"
        module_b = temp_project_dir / "module_b"
        module_b.mkdir()
        (module_b / "__init__.py").write_text("")
        (module_b / "components.py").write_text("""
from base import BaseService

class Service(BaseService):
    '''Service implementation for module B'''
    pass
""")

        # Create module C with ANOTHER class also named "Service"
        module_c = temp_project_dir / "module_c"
        module_c.mkdir()
        (module_c / "__init__.py").write_text("")
        (module_c / "components.py").write_text("""
from base import BaseService

class Service(BaseService):
    '''Service implementation for module C'''
    pass
""")

        analyzer = JediAnalyzer(str(temp_project_dir))
        raw = await analyzer.find_subclasses("BaseService", include_indirect=False)
        assert not raw.get("ambiguous"), "BaseService is unambiguous in this project"
        results = raw["subclasses"]

        # Should find ALL THREE classes named "Service"
        assert (
            len(results) == 3
        ), f"Expected 3 subclasses, found {len(results)}: {[r['name'] for r in results]}"

        # Verify all three modules are represented
        files = {r["file"] for r in results}
        assert any("module_a" in f for f in files), "module_a.components.Service not found"
        assert any("module_b" in f for f in files), "module_b.components.Service not found"
        assert any("module_c" in f for f in files), "module_c.components.Service not found"

        # Verify full_name field exists for disambiguation
        for result in results:
            assert "full_name" in result, "Missing full_name field for disambiguation"
            assert result["name"] == "Service"

        # Verify FQNs are different
        fqns = {r["full_name"] for r in results}
        assert len(fqns) == 3, f"FQNs should be unique, got: {fqns}"

    @pytest.mark.asyncio
    async def test_find_subclasses_indirect_across_files(self, temp_project_dir):
        """Test finding indirect subclasses when inheritance crosses file boundaries.

        Regression test for issue #234 - indirect inheritance only worked within
        a single file because _check_inheritance only searched the current file's AST.
        """
        # Create base class
        base_file = temp_project_dir / "base.py"
        base_file.write_text("""
class BaseService:
    pass
""")

        # Create intermediate class in module_a
        module_a = temp_project_dir / "module_a"
        module_a.mkdir()
        (module_a / "__init__.py").write_text("")
        (module_a / "components.py").write_text("""
from base import BaseService

class Service(BaseService):
    '''Direct subclass'''
    pass
""")

        # Create indirect subclass in different module that imports from module_a
        module_b = temp_project_dir / "module_b"
        module_b.mkdir()
        (module_b / "__init__.py").write_text("")
        (module_b / "prod.py").write_text("""
from module_a.components import Service

class ProdService(Service):
    '''Indirect subclass - inherits from Service which inherits from BaseService'''
    pass
""")

        analyzer = JediAnalyzer(str(temp_project_dir))
        raw = await analyzer.find_subclasses("BaseService", include_indirect=True)
        assert not raw.get("ambiguous"), "BaseService is unambiguous in this project"
        results = raw["subclasses"]

        # Should find both Service (direct) and ProdService (indirect)
        assert (
            len(results) >= 2
        ), f"Expected at least 2 subclasses, found {len(results)}: {[r['name'] for r in results]}"

        names = {r["name"] for r in results}
        assert "Service" in names, "Direct subclass 'Service' not found"
        assert "ProdService" in names, "Indirect subclass 'ProdService' not found"

        # Check is_direct flag
        for result in results:
            if result["name"] == "Service":
                assert result["is_direct"] is True, "Service should be marked as direct"
            elif result["name"] == "ProdService":
                assert result["is_direct"] is False, "ProdService should be marked as indirect"


class TestFindSubclassesLazyIndexBuild:
    """#421 item 1: the resolved index is built only when it is consulted.

    The simple-name + ``include_indirect=False`` path resolves direct subclasses
    from ``parent_to_children`` (plus aliased-base goto) alone — it never reads
    the resolved index, so it must not pay for (nor run the non-deterministic
    Jedi ``goto`` fallbacks of) ``_build_ast_resolution_tables``. The FQN-input
    and indirect-traversal paths DO consult the index and must still build it.
    """

    @staticmethod
    def _make_project(temp_project_dir: Path) -> JediAnalyzer:
        (temp_project_dir / "animals.py").write_text(
            "class Animal:\n"
            "    pass\n"
            "\n"
            "class Dog(Animal):\n"
            "    pass\n"
            "\n"
            "class Cat(Animal):\n"
            "    pass\n"
            "\n"
            "class Puppy(Dog):\n"  # grandchild — only the indirect path reaches it
            "    pass\n"
        )
        return JediAnalyzer(str(temp_project_dir))

    @pytest.mark.asyncio
    async def test_simple_name_non_indirect_skips_index_build(self, temp_project_dir):
        """Simple name + non-indirect: index build is skipped, result still correct."""
        analyzer = self._make_project(temp_project_dir)
        with patch.object(
            analyzer,
            "_build_ast_resolution_tables",
            wraps=analyzer._build_ast_resolution_tables,
        ) as spy:
            raw = await analyzer.find_subclasses("Animal", include_indirect=False)

        assert spy.call_count == 0, "simple-name + non-indirect path must not build the index"
        assert not raw.get("ambiguous")
        assert {r["name"] for r in raw["subclasses"]} == {"Dog", "Cat"}

    @pytest.mark.asyncio
    async def test_indirect_path_builds_index(self, temp_project_dir):
        """Indirect traversal consults the index, so it must be built."""
        analyzer = self._make_project(temp_project_dir)
        with patch.object(
            analyzer,
            "_build_ast_resolution_tables",
            wraps=analyzer._build_ast_resolution_tables,
        ) as spy:
            raw = await analyzer.find_subclasses("Animal", include_indirect=True)

        assert spy.call_count == 1, "indirect path must build the resolved index"
        assert "Puppy" in {r["name"] for r in raw["subclasses"]}

    @pytest.mark.asyncio
    async def test_fqn_non_indirect_builds_index(self, temp_project_dir):
        """FQN input consults the index even when non-indirect, so it must be built."""
        analyzer = self._make_project(temp_project_dir)
        with patch.object(
            analyzer,
            "_build_ast_resolution_tables",
            wraps=analyzer._build_ast_resolution_tables,
        ) as spy:
            raw = await analyzer.find_subclasses("animals.Animal", include_indirect=False)

        assert spy.call_count == 1, "FQN-input path must build the resolved index"
        assert not raw.get("ambiguous")
        assert {r["name"] for r in raw["subclasses"]} == {"Dog", "Cat"}


_RESOLVE_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"


class TestFindSubclassesAmbiguity:
    """Regression tests for the simple-name conflation bug.

    Previously, find_subclasses("Widget") returned the UNION of subclasses across
    ALL classes named Widget in the project.  The fix adds ambiguity detection:
    bare simple names that match >1 class return {"ambiguous": True, "candidates": [...]}.
    FQN inputs return the FQN-strict subclass list.
    """

    @pytest.mark.asyncio
    async def test_bare_widget_returns_ambiguous(self) -> None:
        """find_subclasses("Widget") returns the ambiguous variant.

        The resolve_project fixture has at least two classes named Widget
        (mypackage._core.widgets.Widget and mypackage.helpers.Widget — plus
        mypackage.collision_demo.Widget), so the bare name is ambiguous.
        """
        analyzer = JediAnalyzer(str(_RESOLVE_FIXTURE))
        raw = await analyzer.find_subclasses("Widget")

        assert (
            raw.get("ambiguous") is True
        ), f"Expected ambiguous=True for bare 'Widget'; got: {raw}"
        assert "candidates" in raw, "Ambiguous result must include 'candidates'"
        handles = {c["handle"] for c in raw["candidates"]}
        assert (
            "mypackage._core.widgets.Widget" in handles
        ), f"mypackage._core.widgets.Widget missing from candidates: {handles}"
        assert (
            "mypackage.collision_demo.Widget" in handles
        ), f"mypackage.collision_demo.Widget missing from candidates: {handles}"
        # Each candidate must have handle, kind, location
        for c in raw["candidates"]:
            assert "handle" in c
            assert c["kind"] == "class"
            assert "location" in c
            assert "file" in c["location"]

    @pytest.mark.asyncio
    async def test_fqn_real_widget_returns_exactly_three_subclasses(self) -> None:
        """find_subclasses("mypackage._core.widgets.Widget") returns exactly 3.

        Confirmed subclasses of the real Widget:
        - Premium   (direct, in widgets.py)
        - Deluxe    (direct, in widgets.py)
        - ViaAttr   (direct via attribute access, in inheritance_via_attr.py)

        UnrelatedSub (from collision_demo.Widget) must NOT appear.
        """
        analyzer = JediAnalyzer(str(_RESOLVE_FIXTURE))
        raw = await analyzer.find_subclasses("mypackage._core.widgets.Widget")

        assert raw.get("ambiguous") is False, f"FQN input must not be ambiguous; got: {raw}"
        subclasses = raw["subclasses"]
        names = {s["name"] for s in subclasses}

        assert "Premium" in names, f"Premium missing; got {names}"
        assert "Deluxe" in names, f"Deluxe missing; got {names}"
        assert "ViaAttr" in names, f"ViaAttr missing; got {names}"
        assert (
            "UnrelatedSub" not in names
        ), f"UnrelatedSub belongs to collision_demo.Widget, NOT the real Widget; got {names}"
        assert (
            len(subclasses) == 3
        ), f"Expected exactly 3 subclasses of mypackage._core.widgets.Widget; got {len(subclasses)}: {names}"

    @pytest.mark.asyncio
    async def test_fqn_collision_widget_returns_exactly_one_subclass(self) -> None:
        """find_subclasses("mypackage.collision_demo.Widget") returns exactly 1.

        UnrelatedSub is the only subclass of the collision_demo Widget.
        Premium/Deluxe/ViaAttr must NOT appear.
        """
        analyzer = JediAnalyzer(str(_RESOLVE_FIXTURE))
        raw = await analyzer.find_subclasses("mypackage.collision_demo.Widget")

        assert raw.get("ambiguous") is False, f"FQN input must not be ambiguous; got: {raw}"
        subclasses = raw["subclasses"]
        names = {s["name"] for s in subclasses}

        assert "UnrelatedSub" in names, f"UnrelatedSub missing; got {names}"
        assert (
            "Premium" not in names
        ), f"Premium belongs to widgets.Widget, not collision_demo.Widget; got {names}"
        assert (
            "Deluxe" not in names
        ), f"Deluxe belongs to widgets.Widget, not collision_demo.Widget; got {names}"
        assert (
            "ViaAttr" not in names
        ), f"ViaAttr belongs to widgets.Widget, not collision_demo.Widget; got {names}"
        assert (
            len(subclasses) == 1
        ), f"Expected exactly 1 subclass of mypackage.collision_demo.Widget; got {len(subclasses)}: {names}"


_ISSUE_335_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "issue_335_subclasses"


class TestFindSubclassesReExport:
    """Issue #335 Bug A: FQN-strict exact-match must survive re-export boundaries.

    ``pkg.shapes.Shape`` (public re-export) and ``pkg.shapes._impl.Shape``
    (definition site) bind to the same class.  Circle and Square subclass it.
    Querying by EITHER path must return both subclasses; exact string equality
    against Jedi's resolved ``full_name`` silently drops them when the caller's
    path and Jedi's resolved path straddle the re-export boundary.
    """

    @pytest.mark.asyncio
    async def test_canonical_path_includes_reexport_subclasses(self) -> None:
        """Querying the definition-site FQN returns both subclasses."""
        analyzer = JediAnalyzer(str(_ISSUE_335_FIXTURE))
        raw = await analyzer.find_subclasses("pkg.shapes._impl.Shape")

        assert raw.get("ambiguous") is False, f"FQN input must not be ambiguous; got: {raw}"
        names = {s["name"] for s in raw["subclasses"]}
        assert names == {
            "Circle",
            "Square",
        }, f"Expected Circle and Square as subclasses of the canonical Shape; got {names}"

    @pytest.mark.asyncio
    async def test_reexport_path_includes_reexport_subclasses(self) -> None:
        """Querying the re-exported public FQN returns the same subclasses.

        This is the direction that fails before the fix: Jedi resolves each
        child's base to ``pkg.shapes._impl.Shape`` while the caller passed
        ``pkg.shapes.Shape``; exact equality drops Circle and Square.
        """
        analyzer = JediAnalyzer(str(_ISSUE_335_FIXTURE))
        raw = await analyzer.find_subclasses("pkg.shapes.Shape")

        assert raw.get("ambiguous") is False, f"FQN input must not be ambiguous; got: {raw}"
        names = {s["name"] for s in raw["subclasses"]}
        assert names == {
            "Circle",
            "Square",
        }, (
            "Re-exported base path must resolve to the same subclasses as the "
            f"canonical path; got {names}"
        )


class TestFindSubclassesIndirectIdentity:
    """Issue #335 Bug B: grandchild traversal must carry FQN identity.

    Two unrelated classes share the simple name ``Car``:
    - ``pkg.vehicles_a.Car`` is a real subclass of ``Vehicle`` (with grandchild RaceCar).
    - ``pkg.vehicles_b.Car`` is unrelated (with child SportsCar).

    The indirect-subclass walk previously expanded via the simple name ``Car``
    against ``parent_to_children``, pulling SportsCar (a child of the *unrelated*
    Car) into Vehicle's subclass list.
    """

    @pytest.mark.asyncio
    async def test_indirect_walk_excludes_same_named_unrelated_grandchild(self) -> None:
        """Vehicle's subclasses are exactly {Car, RaceCar}; SportsCar excluded."""
        analyzer = JediAnalyzer(str(_ISSUE_335_FIXTURE))
        raw = await analyzer.find_subclasses("pkg.vehicles_a.Vehicle")

        assert raw.get("ambiguous") is False, f"FQN input must not be ambiguous; got: {raw}"
        names = {s["name"] for s in raw["subclasses"]}
        assert "Car" in names, f"Real direct subclass Car missing; got {names}"
        assert "RaceCar" in names, f"Genuine grandchild RaceCar missing; got {names}"
        assert (
            "SportsCar" not in names
        ), f"SportsCar extends the unrelated vehicles_b.Car and must not appear; got {names}"
        assert (
            len(raw["subclasses"]) == 2
        ), f"Expected exactly 2 subclasses of Vehicle; got {len(raw['subclasses'])}: {names}"

    @pytest.mark.asyncio
    async def test_unrelated_car_keeps_only_its_own_child(self) -> None:
        """The unrelated Car's subclasses are exactly {SportsCar}; RaceCar excluded."""
        analyzer = JediAnalyzer(str(_ISSUE_335_FIXTURE))
        raw = await analyzer.find_subclasses("pkg.vehicles_b.Car")

        assert raw.get("ambiguous") is False, f"FQN input must not be ambiguous; got: {raw}"
        names = {s["name"] for s in raw["subclasses"]}
        assert names == {"SportsCar"}, f"Unrelated Car must own only SportsCar; got {names}"


class TestExpandSubclassesIssue335:
    """Issue #335 criterion 3: expand(handle, "subclasses") matches truth.

    subclasses is an expand-only edge (inspect no longer measures it — #392), and
    the expand resolver delegates to find_subclasses with the canonical FQN, so
    the Bug A / Bug B fixes must flow through to the expand surface.
    """

    @pytest.mark.asyncio
    async def test_shape_expand_includes_reexport_subclasses(self) -> None:
        """expand(Shape, "subclasses") counts both re-export subclasses."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.shapes._impl.Shape",
            edge="subclasses",
            project_path=str(_ISSUE_335_FIXTURE),
        )
        assert (
            len(result["stubs"]) == 2
        ), f"Expected 2 subclass stubs for Shape; got {result['stubs']!r}"

    @pytest.mark.asyncio
    async def test_vehicle_expand_direct_child_only(self) -> None:
        """expand(Vehicle, "subclasses") == 1 stub (Car only) — direct, #422.

        The genuine grandchild RaceCar is INDIRECT and excluded from the
        single-hop edge; the unrelated ``vehicles_b.Car``/``SportsCar`` hierarchy
        (simple-name collision, Bug B) must never appear either.
        """
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.vehicles_a.Vehicle",
            edge="subclasses",
            project_path=str(_ISSUE_335_FIXTURE),
        )
        handles = {stub["handle"] for stub in result["stubs"]}
        assert handles == {
            "pkg.vehicles_a.Car"
        }, f"Expected only the direct subclass Car for Vehicle; got {sorted(handles)!r}"

    @pytest.mark.asyncio
    async def test_vehicle_trace_closure_keeps_grandchild_identity(self) -> None:
        """trace(Vehicle, [subclasses]) reaches the real grandchild, not the collision (Bug B).

        The transitive closure now lives in ``trace``.  At depth 2 it must reach
        the genuine grandchild ``RaceCar`` (via the REAL Car) while the simple-name
        collision ``vehicles_b.Car``/``SportsCar`` stays out — the grandchild walk
        carries FQN identity rather than re-keying on the simple name ``Car``.
        """
        from pyeye.mcp.server import trace

        result = await trace(
            start="pkg.vehicles_a.Vehicle",
            follow=["subclasses"],
            project_path=str(_ISSUE_335_FIXTURE),
            max_depth=2,
            max_nodes=100,
        )
        nodes = set(result["nodes"])
        assert "pkg.vehicles_a.Car" in nodes, "direct subclass Car must be reached"
        assert "pkg.vehicles_a.RaceCar" in nodes, "genuine grandchild RaceCar must be reached"
        assert (
            "pkg.vehicles_b.SportsCar" not in nodes
        ), "unrelated SportsCar (simple-name collision) must NOT appear in the closure"
        assert "pkg.vehicles_b.Car" not in nodes, "unrelated Car must NOT appear in the closure"


class TestFindSubclassesJediIndependence:
    """Issue #335 macOS-regression guard: unique-name hierarchies resolve via AST.

    On symlinked temp dirs (macOS ``/var`` -> ``/private/var``) Jedi goto() and
    canonicalisation return degraded/empty results.  When a class's simple name
    is unique in the project the subclass relationship is unambiguous from the
    AST alone, so resolution MUST NOT depend on the Jedi layer.  This test
    simulates total Jedi-layer failure by patching ``get_script`` and asserts
    the full unique-name chain (Root -> Mid -> Leaf) is still discovered.
    """

    @pytest.mark.asyncio
    async def test_unique_name_chain_resolves_without_jedi(self) -> None:
        """Direct and indirect subclasses of a unique-name class survive Jedi failure."""
        failed_script = Mock()
        failed_script.goto.return_value = []
        failed_script.get_names.return_value = []

        analyzer = JediAnalyzer(str(_ISSUE_335_FIXTURE))
        with patch("pyeye.file_artifact_cache.get_script", return_value=failed_script):
            raw = await analyzer.find_subclasses("pkg.deep_chain.Root")

        assert raw.get("ambiguous") is False, f"FQN input must not be ambiguous; got: {raw}"
        names = {s["name"] for s in raw["subclasses"]}
        assert names == {
            "Mid",
            "Leaf",
        }, (
            "Unique-name subclass chain must resolve from the AST without Jedi "
            f"goto/canonicalisation; got {names}"
        )
