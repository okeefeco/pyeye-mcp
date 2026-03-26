"""Backward compatibility tests for list_modules with fields parameter.

These tests ensure that:
1. When fields parameter is omitted, all fields are returned (existing behavior)
2. The response structure remains consistent with historical behavior
3. No breaking changes are introduced by the fields parameter optimization

Note: These tests are designed to PASS before the fields parameter is added,
and continue to PASS after the fields parameter is added (backward compatibility).
"""

import pytest

from pyeye.mcp.server import list_modules


class TestListModulesBackwardCompatibility:
    """Test backward compatibility of list_modules response structure."""

    @pytest.mark.asyncio
    async def test_list_modules_returns_all_fields_by_default(self, tmp_path):
        """Test that list_modules returns all expected fields when no fields parameter is specified.

        This is the critical backward compatibility test - existing callers expect
        all fields to be present in the response.
        """
        # Create a simple module with various elements
        module_file = tmp_path / "sample.py"
        module_file.write_text('''
"""Sample module for testing."""

import os
import json
from pathlib import Path

class SampleClass:
    """A sample class."""
    pass

class AnotherClass:
    """Another class."""
    pass

def public_function():
    """A public function."""
    pass

def another_public_function():
    """Another public function."""
    pass

def _private_function():
    """This should not be in exports."""
    pass
''')

        # Call list_modules WITHOUT any fields parameter (existing behavior)
        result = await list_modules(str(tmp_path))

        # Verify we got exactly one module
        assert len(result) == 1, "Expected exactly one module"

        module = result[0]

        # CRITICAL: All these fields MUST be present for backward compatibility
        # Any caller relying on these fields should not break
        expected_fields = {
            "name",
            "import_path",
            "file",
            "exports",
            "classes",
            "functions",
            "imports_from",
            "size_lines",
            "has_tests",
        }

        actual_fields = set(module.keys())

        assert actual_fields == expected_fields, (
            f"Response structure changed! "
            f"Missing fields: {expected_fields - actual_fields}, "
            f"Extra fields: {actual_fields - expected_fields}"
        )

        # Verify field types and content
        assert isinstance(module["name"], str)
        assert module["name"] == "sample"

        assert isinstance(module["import_path"], str)
        assert module["import_path"] == "sample"

        assert isinstance(module["file"], str)
        assert module["file"].endswith("sample.py")

        assert isinstance(module["exports"], list)
        assert "SampleClass" in module["exports"]
        assert "AnotherClass" in module["exports"]
        assert "public_function" in module["exports"]
        assert "another_public_function" in module["exports"]
        assert "_private_function" not in module["exports"]

        assert isinstance(module["classes"], list)
        assert "SampleClass" in module["classes"]
        assert "AnotherClass" in module["classes"]

        assert isinstance(module["functions"], list)
        assert "public_function" in module["functions"]
        assert "another_public_function" in module["functions"]
        assert "_private_function" not in module["functions"]

        assert isinstance(module["imports_from"], list)
        assert "os" in module["imports_from"]
        assert "json" in module["imports_from"]
        assert "pathlib" in module["imports_from"]

        assert isinstance(module["size_lines"], int)
        assert module["size_lines"] > 0

        assert isinstance(module["has_tests"], bool)

    @pytest.mark.asyncio
    async def test_list_modules_multiple_modules_all_fields(self, tmp_path):
        """Test that all modules in a project get all fields by default.

        Ensures the backward compatibility extends to multi-module projects.
        """
        # Create a package with multiple modules
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()

        (package_dir / "__init__.py").write_text('"""Package init."""')

        (package_dir / "module1.py").write_text('''
"""Module 1."""

class ClassOne:
    pass

def func_one():
    pass
''')

        (package_dir / "module2.py").write_text('''
"""Module 2."""

import sys

class ClassTwo:
    pass

def func_two():
    pass
''')

        # Call list_modules WITHOUT fields parameter
        result = await list_modules(str(tmp_path))

        # Should have 3 modules: __init__, module1, module2
        assert len(result) == 3, "Expected 3 modules"

        # Verify ALL modules have ALL fields
        expected_fields = {
            "name",
            "import_path",
            "file",
            "exports",
            "classes",
            "functions",
            "imports_from",
            "size_lines",
            "has_tests",
        }

        for i, module in enumerate(result):
            actual_fields = set(module.keys())
            assert actual_fields == expected_fields, (
                f"Module {i} ({module.get('name', 'unknown')}) has inconsistent fields! "
                f"Missing: {expected_fields - actual_fields}, "
                f"Extra: {actual_fields - expected_fields}"
            )

    @pytest.mark.asyncio
    async def test_list_modules_empty_project_returns_empty_list(self, tmp_path):
        """Test that empty projects still work with backward compatible behavior."""
        result = await list_modules(str(tmp_path))
        assert result == [], "Empty project should return empty list"
        assert isinstance(result, list), "Result should be a list"

    @pytest.mark.asyncio
    async def test_list_modules_preserves_sorting(self, tmp_path):
        """Test that modules are sorted by import_path (existing behavior)."""
        # Create modules that would have different sort orders
        (tmp_path / "zebra.py").write_text("# Zebra module")
        (tmp_path / "apple.py").write_text("# Apple module")
        (tmp_path / "middle.py").write_text("# Middle module")

        result = await list_modules(str(tmp_path))

        # Should be sorted by import_path
        import_paths = [m["import_path"] for m in result]
        assert import_paths == sorted(import_paths), "Modules should be sorted by import_path"
        assert import_paths == ["apple", "middle", "zebra"], "Expected alphabetical order"

    @pytest.mark.asyncio
    async def test_list_modules_field_content_completeness(self, tmp_path):
        """Test that list content in fields is complete (not truncated or summarized).

        This ensures that even with many classes/functions, all are returned.
        """
        # Create a module with many classes and functions
        code = '"""Module with many exports."""\n\n'

        # Add 20 classes
        for i in range(20):
            code += f"class Class{i:02d}:\n    pass\n\n"

        # Add 20 functions
        for i in range(20):
            code += f"def function_{i:02d}():\n    pass\n\n"

        module_file = tmp_path / "large_module.py"
        module_file.write_text(code)

        result = await list_modules(str(tmp_path))
        assert len(result) == 1

        module = result[0]

        # All 20 classes should be present
        assert len(module["classes"]) == 20, "All classes should be included"
        for i in range(20):
            assert f"Class{i:02d}" in module["classes"]

        # All 20 functions should be present
        assert len(module["functions"]) == 20, "All functions should be included"
        for i in range(20):
            assert f"function_{i:02d}" in module["functions"]

        # Exports should have all 40 items (20 classes + 20 functions)
        assert len(module["exports"]) == 40, "All exports should be included"

    @pytest.mark.asyncio
    async def test_list_modules_preserves_sorted_lists(self, tmp_path):
        """Test that lists within module data are sorted (existing behavior)."""
        module_file = tmp_path / "module.py"
        module_file.write_text('''
"""Test module."""

import zebra_lib
import apple_lib
import middle_lib

class ZebraClass:
    pass

class AppleClass:
    pass

def zebra_func():
    pass

def apple_func():
    pass
''')

        result = await list_modules(str(tmp_path))
        module = result[0]

        # Classes should be sorted
        assert module["classes"] == sorted(module["classes"]), "Classes should be sorted"
        assert module["classes"] == ["AppleClass", "ZebraClass"]

        # Functions should be sorted
        assert module["functions"] == sorted(module["functions"]), "Functions should be sorted"
        assert module["functions"] == ["apple_func", "zebra_func"]

        # Exports should be sorted
        assert module["exports"] == sorted(module["exports"]), "Exports should be sorted"

        # Imports should be sorted
        assert module["imports_from"] == sorted(module["imports_from"]), "Imports should be sorted"
        assert module["imports_from"] == ["apple_lib", "middle_lib", "zebra_lib"]


class TestListModulesFieldFiltering:
    """TDD tests for the fields parameter in list_modules.

    These tests will FAIL with TypeError until we implement the fields parameter.
    They define the expected behavior for field filtering functionality.

    Tests follow the exact pattern from test_get_type_info_backward_compatibility.py
    to ensure consistency across the Phase 2 implementation.
    """

    @pytest.mark.asyncio
    async def test_fields_single_field_name(self, tmp_path):
        """Test filtering to a single field: name."""
        module_file = tmp_path / "sample.py"
        module_file.write_text('''
"""Sample module."""

class SampleClass:
    pass

def sample_function():
    pass
''')

        # Request only the 'name' field
        result = await list_modules(str(tmp_path), fields=["name"])

        assert len(result) == 1
        module = result[0]

        # Should only have 'name' field
        assert "name" in module
        assert "import_path" not in module
        assert "file" not in module
        assert "exports" not in module
        assert "classes" not in module
        assert "functions" not in module
        assert "imports_from" not in module
        assert "size_lines" not in module
        assert "has_tests" not in module
        assert len(module) == 1

        # Verify value
        assert module["name"] == "sample"

    @pytest.mark.asyncio
    async def test_fields_single_field_file(self, tmp_path):
        """Test filtering to a single field: file."""
        module_file = tmp_path / "example.py"
        module_file.write_text('"""Example module."""')

        result = await list_modules(str(tmp_path), fields=["file"])

        assert len(result) == 1
        module = result[0]

        # Should only have 'file' field
        assert "file" in module
        assert "name" not in module
        assert "import_path" not in module
        assert len(module) == 1

        # Verify value
        assert module["file"].endswith("example.py")

    @pytest.mark.asyncio
    async def test_fields_single_field_exports(self, tmp_path):
        """Test filtering to a single field: exports."""
        module_file = tmp_path / "exports_test.py"
        module_file.write_text('''
"""Module for testing exports."""

class ClassA:
    pass

def func_a():
    pass
''')

        result = await list_modules(str(tmp_path), fields=["exports"])

        assert len(result) == 1
        module = result[0]

        # Should only have 'exports' field
        assert "exports" in module
        assert "name" not in module
        assert "classes" not in module
        assert "functions" not in module
        assert len(module) == 1

        # Verify exports content
        assert isinstance(module["exports"], list)
        assert "ClassA" in module["exports"]
        assert "func_a" in module["exports"]

    @pytest.mark.asyncio
    async def test_fields_multiple_fields_name_and_file(self, tmp_path):
        """Test filtering to multiple fields: name and file."""
        module_file = tmp_path / "multi.py"
        module_file.write_text('"""Multi-field test."""')

        result = await list_modules(str(tmp_path), fields=["name", "file"])

        assert len(result) == 1
        module = result[0]

        # Should have name and file only
        assert "name" in module
        assert "file" in module
        assert "import_path" not in module
        assert "exports" not in module
        assert "classes" not in module
        assert "functions" not in module
        assert "imports_from" not in module
        assert "size_lines" not in module
        assert "has_tests" not in module
        assert len(module) == 2

    @pytest.mark.asyncio
    async def test_fields_multiple_fields_classes_and_functions(self, tmp_path):
        """Test filtering to content-focused fields: classes and functions."""
        module_file = tmp_path / "content.py"
        module_file.write_text('''
"""Content module."""

class MyClass:
    pass

class AnotherClass:
    pass

def my_function():
    pass
''')

        result = await list_modules(str(tmp_path), fields=["classes", "functions"])

        assert len(result) == 1
        module = result[0]

        # Should have classes and functions only
        assert "classes" in module
        assert "functions" in module
        assert "name" not in module
        assert "file" not in module
        assert "exports" not in module
        assert len(module) == 2

        # Verify content
        assert "MyClass" in module["classes"]
        assert "AnotherClass" in module["classes"]
        assert "my_function" in module["functions"]

    @pytest.mark.asyncio
    async def test_fields_all_fields_explicitly(self, tmp_path):
        """Test explicitly requesting all fields."""
        module_file = tmp_path / "all_fields.py"
        module_file.write_text('''
"""All fields test."""

import os

class TestClass:
    pass

def test_func():
    pass
''')

        result = await list_modules(
            str(tmp_path),
            fields=[
                "name",
                "import_path",
                "file",
                "exports",
                "classes",
                "functions",
                "imports_from",
                "size_lines",
                "has_tests",
            ],
        )

        assert len(result) == 1
        module = result[0]

        # Should have all 9 fields
        expected_fields = {
            "name",
            "import_path",
            "file",
            "exports",
            "classes",
            "functions",
            "imports_from",
            "size_lines",
            "has_tests",
        }
        assert set(module.keys()) == expected_fields

    @pytest.mark.asyncio
    async def test_fields_array_behavior_all_modules_filtered_consistently(self, tmp_path):
        """Test that field filtering applies consistently to all modules in result array.

        This is critical: when fields parameter is provided, ALL modules in the array
        must have the same filtered field set.
        """
        # Create multiple modules
        (tmp_path / "module_a.py").write_text('''
"""Module A."""

class ClassA:
    pass
''')
        (tmp_path / "module_b.py").write_text('''
"""Module B."""

def func_b():
    pass
''')
        (tmp_path / "module_c.py").write_text('''
"""Module C."""

import sys
''')

        # Request only name and exports fields
        result = await list_modules(str(tmp_path), fields=["name", "exports"])

        # Should have 3 modules
        assert len(result) == 3

        # ALL modules should have exactly the same field set
        for module in result:
            assert set(module.keys()) == {"name", "exports"}
            assert "file" not in module
            assert "classes" not in module
            assert "functions" not in module

        # Verify each module has correct data
        names = [m["name"] for m in result]
        assert "module_a" in names
        assert "module_b" in names
        assert "module_c" in names

    @pytest.mark.asyncio
    async def test_fields_empty_list_raises_error(self, tmp_path):
        """Test that empty fields list raises ValueError."""
        module_file = tmp_path / "test.py"
        module_file.write_text('"""Test module."""')

        with pytest.raises(ValueError) as exc_info:
            await list_modules(str(tmp_path), fields=[])

        assert "cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fields_invalid_field_name_raises_error(self, tmp_path):
        """Test that invalid field name raises ValueError with helpful message."""
        module_file = tmp_path / "test.py"
        module_file.write_text('"""Test module."""')

        with pytest.raises(ValueError) as exc_info:
            await list_modules(str(tmp_path), fields=["invalid_field"])

        error_msg = str(exc_info.value)
        assert "Invalid field" in error_msg
        assert "invalid_field" in error_msg
        # Should show valid fields in sorted order
        assert "classes" in error_msg
        assert "exports" in error_msg
        assert "file" in error_msg
        assert "functions" in error_msg
        assert "has_tests" in error_msg
        assert "import_path" in error_msg
        assert "imports_from" in error_msg
        assert "name" in error_msg
        assert "size_lines" in error_msg

    @pytest.mark.asyncio
    async def test_fields_multiple_invalid_fields_all_shown(self, tmp_path):
        """Test that multiple invalid fields are all shown in error message."""
        module_file = tmp_path / "test.py"
        module_file.write_text('"""Test module."""')

        with pytest.raises(ValueError) as exc_info:
            await list_modules(str(tmp_path), fields=["bad_field1", "bad_field2", "name"])

        error_msg = str(exc_info.value)
        # Both invalid fields should be mentioned
        assert "bad_field1" in error_msg
        assert "bad_field2" in error_msg
        # Should show valid fields
        assert "Valid fields are:" in error_msg

    @pytest.mark.asyncio
    async def test_fields_typo_in_field_name_shows_valid_fields(self, tmp_path):
        """Test that typo in field name shows sorted valid fields."""
        module_file = tmp_path / "test.py"
        module_file.write_text('"""Test module."""')

        with pytest.raises(ValueError) as exc_info:
            await list_modules(str(tmp_path), fields=["clases"])  # Typo: missing 's'

        error_msg = str(exc_info.value)
        # Should show the typo
        assert "clases" in error_msg
        # Should show valid fields in sorted order (making 'classes' easy to spot)
        assert "classes" in error_msg
        assert "Valid fields are:" in error_msg

    @pytest.mark.asyncio
    async def test_fields_subset_with_list_fields(self, tmp_path):
        """Test that list fields (exports, classes, functions) are properly filtered."""
        module_file = tmp_path / "lists.py"
        module_file.write_text('''
"""List fields test."""

class Class1:
    pass

class Class2:
    pass

def func1():
    pass

def func2():
    pass
''')

        # Request only classes and functions
        result = await list_modules(str(tmp_path), fields=["classes", "functions"])

        assert len(result) == 1
        module = result[0]

        # Should have classes and functions with full content
        assert len(module["classes"]) == 2
        assert "Class1" in module["classes"]
        assert "Class2" in module["classes"]

        assert len(module["functions"]) == 2
        assert "func1" in module["functions"]
        assert "func2" in module["functions"]

        # Should NOT have other fields
        assert "exports" not in module
        assert "imports_from" not in module

    @pytest.mark.asyncio
    async def test_fields_metadata_only(self, tmp_path):
        """Test requesting only metadata fields (size_lines, has_tests)."""
        module_file = tmp_path / "metadata.py"
        module_file.write_text('''
"""Metadata test."""

class SomeClass:
    pass
''')

        result = await list_modules(str(tmp_path), fields=["size_lines", "has_tests"])

        assert len(result) == 1
        module = result[0]

        # Should only have metadata fields
        assert "size_lines" in module
        assert "has_tests" in module
        assert "name" not in module
        assert "classes" not in module
        assert len(module) == 2

        # Verify types
        assert isinstance(module["size_lines"], int)
        assert isinstance(module["has_tests"], bool)

    @pytest.mark.asyncio
    async def test_fields_empty_project_with_fields_parameter(self, tmp_path):
        """Test that empty projects return empty list even with fields parameter."""
        result = await list_modules(str(tmp_path), fields=["name", "file"])

        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_fields_order_independence(self, tmp_path):
        """Test that field order in request doesn't matter, response has consistent order."""
        module_file = tmp_path / "order.py"
        module_file.write_text('"""Order test."""')

        # Request in one order
        result1 = await list_modules(str(tmp_path), fields=["file", "name", "exports"])

        # Request in different order
        result2 = await list_modules(str(tmp_path), fields=["exports", "name", "file"])

        # Both should return same fields (order in dict keys may vary but fields should match)
        assert set(result1[0].keys()) == set(result2[0].keys())
        assert set(result1[0].keys()) == {"name", "file", "exports"}

    @pytest.mark.asyncio
    async def test_fields_with_package_structure(self, tmp_path):
        """Test field filtering works correctly with package structures."""
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()

        (package_dir / "__init__.py").write_text('"""Package init."""')
        (package_dir / "module1.py").write_text('''
"""Module 1."""

class Module1Class:
    pass
''')

        # Request only name and classes
        result = await list_modules(str(tmp_path), fields=["name", "classes"])

        # Should have 2 modules (init and module1)
        assert len(result) == 2

        # All modules should have only name and classes
        for module in result:
            assert set(module.keys()) == {"name", "classes"}

        # Verify data
        module_names = [m["name"] for m in result]
        assert "__init__" in module_names
        assert "module1" in module_names
