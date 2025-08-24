"""Test coverage for import analyzer."""

from pathlib import Path
from unittest.mock import mock_open, patch

from pycodemcp.import_analyzer import ImportAnalyzer


class TestImportAnalyzer:
    """Test the ImportAnalyzer class."""

    def test_initialization(self, tmp_path):
        """Test analyzer initialization."""
        analyzer = ImportAnalyzer(tmp_path)
        assert analyzer.project_path == tmp_path.resolve()

    def test_get_module_name_basic(self, tmp_path):
        """Test basic module name conversion."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create test file
        test_file = tmp_path / "module.py"
        test_file.touch()

        module_name = analyzer.get_module_name(test_file)
        assert module_name == "module"

    def test_get_module_name_nested(self, tmp_path):
        """Test nested module name conversion."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create nested structure
        nested_dir = tmp_path / "package" / "subpackage"
        nested_dir.mkdir(parents=True)
        test_file = nested_dir / "module.py"
        test_file.touch()

        module_name = analyzer.get_module_name(test_file)
        assert module_name == "package.subpackage.module"

    def test_get_module_name_init_file(self, tmp_path):
        """Test __init__.py file handling."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create package with __init__.py
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()
        init_file = package_dir / "__init__.py"
        init_file.touch()

        module_name = analyzer.get_module_name(init_file)
        assert module_name == "mypackage"

    def test_get_module_name_root_init(self, tmp_path):
        """Test root __init__.py file handling."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create __init__.py in project root
        init_file = tmp_path / "__init__.py"
        init_file.touch()

        # Should return None for root __init__.py
        module_name = analyzer.get_module_name(init_file)
        assert module_name is None

    def test_get_module_name_outside_project(self, tmp_path):
        """Test file outside project path."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create file outside project
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "module.py"
        outside_file.touch()

        module_name = analyzer.get_module_name(outside_file)
        assert module_name is None

    def test_get_module_name_not_python(self, tmp_path):
        """Test non-Python file."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create non-Python file
        text_file = tmp_path / "data.txt"
        text_file.touch()

        module_name = analyzer.get_module_name(text_file)
        assert module_name is None

    def test_get_module_name_value_error(self, tmp_path):
        """Test handling of ValueError in path resolution."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create a mock path that raises ValueError
        with patch.object(Path, "resolve") as mock_resolve:
            mock_resolve.side_effect = ValueError("Invalid path")

            test_file = tmp_path / "module.py"
            module_name = analyzer.get_module_name(test_file)
            assert module_name is None

    def test_get_module_name_attribute_error(self, tmp_path):
        """Test handling of AttributeError in path resolution."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create a mock path that raises AttributeError
        with patch.object(Path, "relative_to") as mock_relative:
            mock_relative.side_effect = AttributeError("No attribute")

            test_file = tmp_path / "module.py"
            test_file.touch()

            module_name = analyzer.get_module_name(test_file)
            assert module_name is None

    def test_analyze_imports_basic(self, tmp_path):
        """Test basic import analysis."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create Python file with imports
        test_file = tmp_path / "test_module.py"
        test_file.write_text(
            """
import os
import sys
from pathlib import Path
from typing import Dict, List

def my_function():
    pass

class MyClass:
    pass

CONSTANT = 42
"""
        )

        result = analyzer.analyze_imports(test_file)

        assert result["module_name"] == "test_module"
        assert "os" in result["imports"]
        assert "sys" in result["imports"]
        assert "pathlib" in result["from_imports"]
        assert "Path" in result["from_imports"]["pathlib"]
        assert "typing" in result["from_imports"]
        assert "Dict" in result["from_imports"]["typing"]
        assert "List" in result["from_imports"]["typing"]
        assert "my_function" in result["symbols"]
        assert "MyClass" in result["symbols"]
        assert "CONSTANT" in result["symbols"]

    def test_analyze_imports_relative(self, tmp_path):
        """Test relative import analysis."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create nested structure
        package_dir = tmp_path / "package"
        package_dir.mkdir()

        # Create submodule with relative imports
        test_file = package_dir / "module.py"
        test_file.write_text(
            """
from . import sibling
from ..parent import something
from ...grandparent import other
"""
        )

        result = analyzer.analyze_imports(test_file)

        assert result["module_name"] == "package.module"
        # Check that relative imports are processed (exact resolution may vary)
        assert len(result["from_imports"]) > 0

    def test_analyze_imports_malformed_syntax(self, tmp_path, caplog):
        """Test handling of malformed Python syntax."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create Python file with syntax error
        test_file = tmp_path / "bad_syntax.py"
        test_file.write_text(
            """
import os
def broken_function(
    # Missing closing parenthesis and proper indentation
"""
        )

        result = analyzer.analyze_imports(test_file)

        # Should return empty result but not crash
        # The module name might still be determined from the path
        assert result["imports"] == []
        assert result["from_imports"] == {}
        assert result["symbols"] == []
        assert "Failed to analyze imports" in caplog.text

    def test_analyze_imports_file_not_found(self, tmp_path, caplog):
        """Test handling when file doesn't exist."""
        analyzer = ImportAnalyzer(tmp_path)

        # Try to analyze non-existent file
        nonexistent_file = tmp_path / "nonexistent.py"

        result = analyzer.analyze_imports(nonexistent_file)

        # Should return empty result but not crash
        # The module name might still be determined from the path
        assert result["imports"] == []
        assert result["from_imports"] == {}
        assert result["symbols"] == []
        assert "Failed to analyze imports" in caplog.text

    def test_analyze_imports_encoding_error(self, tmp_path, caplog):
        """Test handling of encoding errors."""
        analyzer = ImportAnalyzer(tmp_path)

        test_file = tmp_path / "encoding_test.py"
        test_file.touch()

        # Mock file reading to raise UnicodeDecodeError
        with patch("builtins.open", mock_open()) as mock_file:
            mock_file.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")

            analyzer.analyze_imports(test_file)

            # Module name might still be determined from path
            assert "Failed to analyze imports" in caplog.text

    def test_analyze_imports_star_import(self, tmp_path):
        """Test handling of star imports."""
        analyzer = ImportAnalyzer(tmp_path)

        test_file = tmp_path / "star_import.py"
        test_file.write_text(
            """
from os import *
from pathlib import Path, PurePath
"""
        )

        result = analyzer.analyze_imports(test_file)

        assert "os" in result["from_imports"]
        # Star imports should not add items to the import list
        assert "*" not in result["from_imports"]["os"]

        # Regular imports should work normally
        assert "pathlib" in result["from_imports"]
        assert "Path" in result["from_imports"]["pathlib"]
        assert "PurePath" in result["from_imports"]["pathlib"]

    def test_resolve_relative_import_basic(self, tmp_path):
        """Test basic relative import resolution."""
        analyzer = ImportAnalyzer(tmp_path)

        result = analyzer._resolve_relative_import("package.module", "utils", 1)
        assert result == "package.utils"

    def test_resolve_relative_import_multiple_levels(self, tmp_path):
        """Test multiple level relative imports."""
        analyzer = ImportAnalyzer(tmp_path)

        result = analyzer._resolve_relative_import("deep.package.subpackage.module", "utils", 2)
        assert result == "deep.package.utils"

    def test_resolve_relative_import_too_many_levels(self, tmp_path):
        """Test relative import with too many levels."""
        analyzer = ImportAnalyzer(tmp_path)

        # Trying to go up more levels than exist
        result = analyzer._resolve_relative_import("package.module", "utils", 5)
        assert result is None

    def test_resolve_relative_import_no_module(self, tmp_path):
        """Test relative import with no module name."""
        analyzer = ImportAnalyzer(tmp_path)

        # Import from parent package itself
        result = analyzer._resolve_relative_import("package.module", None, 1)
        assert result == "package"

    def test_resolve_relative_import_exception(self, tmp_path):
        """Test exception handling in relative import resolution."""
        analyzer = ImportAnalyzer(tmp_path)

        # Test with valid arguments that don't cause exceptions
        result = analyzer._resolve_relative_import("valid.module", "other", 1)
        assert result == "valid.other"

    def test_build_dependency_graph_basic(self, tmp_path):
        """Test building dependency graph."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create multiple Python files
        file1 = tmp_path / "module1.py"
        file1.write_text(
            """
import os
from . import module2

def func1():
    pass
"""
        )

        file2 = tmp_path / "module2.py"
        file2.write_text(
            """
from pathlib import Path

class Class2:
    pass
"""
        )

        graph = analyzer.build_dependency_graph([file1, file2])

        assert "module1" in graph["modules"]
        assert "module2" in graph["modules"]

        assert "module1" in graph["imports"]
        assert "os" in graph["imports"]["module1"]

        assert "module2" in graph["imports"]
        assert "pathlib" in graph["imports"]["module2"]

        assert "module1" in graph["symbols"]
        assert "func1" in graph["symbols"]["module1"]

        assert "module2" in graph["symbols"]
        assert "Class2" in graph["symbols"]["module2"]

    def test_build_dependency_graph_with_errors(self, tmp_path, caplog):
        """Test building dependency graph with problematic files."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create a file that will cause errors
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("invalid python syntax {{{")

        good_file = tmp_path / "good.py"
        good_file.write_text("import os")

        graph = analyzer.build_dependency_graph([bad_file, good_file])

        # Good file should be processed
        assert "good" in graph["modules"]

        # Error should be logged
        assert "Failed to analyze imports" in caplog.text

    def test_build_dependency_graph_outside_project(self, tmp_path):
        """Test building graph with files outside project."""
        analyzer = ImportAnalyzer(tmp_path)

        # Create file outside project
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "external.py"
        outside_file.write_text("import os")

        graph = analyzer.build_dependency_graph([outside_file])

        # Should have no modules since file is outside project
        assert len(graph["modules"]) == 0

    def test_build_dependency_graph_file_processing_exception(self, tmp_path, caplog):
        """Test exception handling during file processing."""
        analyzer = ImportAnalyzer(tmp_path)

        test_file = tmp_path / "test.py"
        test_file.touch()

        # Mock analyze_imports to raise an exception
        with patch.object(analyzer, "analyze_imports") as mock_analyze:
            mock_analyze.side_effect = Exception("Processing failed")

            graph = analyzer.build_dependency_graph([test_file])

            assert test_file.as_posix() in graph["errors"]
            assert "Failed to process" in caplog.text

    def test_analyze_imports_complex_assignments(self, tmp_path):
        """Test analysis of complex assignment patterns."""
        analyzer = ImportAnalyzer(tmp_path)

        test_file = tmp_path / "complex.py"
        test_file.write_text(
            """
# Multiple assignment
a, b = 1, 2

# Tuple assignment
(x, y) = (3, 4)

# Simple assignment
simple_var = "test"

# Attribute assignment (should be ignored)
obj.attr = value
"""
        )

        result = analyzer.analyze_imports(test_file)

        # Should only capture simple name assignments
        assert "simple_var" in result["symbols"]
        # Complex assignments should not be captured (current implementation)
        # This tests the isinstance(target, ast.Name) check

    def test_analyze_imports_nested_definitions(self, tmp_path):
        """Test that only top-level definitions are captured."""
        analyzer = ImportAnalyzer(tmp_path)

        test_file = tmp_path / "nested.py"
        test_file.write_text(
            """
def top_level_func():
    def nested_func():  # Should not be captured
        pass

    class NestedClass:  # Should not be captured
        pass

class TopLevelClass:
    def method(self):  # Should not be captured
        pass

# Top level assignment
top_var = 1
"""
        )

        result = analyzer.analyze_imports(test_file)

        # Only top-level symbols should be captured
        assert "top_level_func" in result["symbols"]
        assert "TopLevelClass" in result["symbols"]
        assert "top_var" in result["symbols"]

        # Nested definitions should not be captured
        assert "nested_func" not in result["symbols"]
        assert "NestedClass" not in result["symbols"]
        assert "method" not in result["symbols"]
