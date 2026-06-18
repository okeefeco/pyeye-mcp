"""Backward compatibility tests for find_references with fields parameter.

These tests ensure that:
1. When fields parameter is omitted, all fields are returned (existing behavior)
2. The response structure remains consistent with historical behavior
3. No breaking changes are introduced by the fields parameter optimization

Note: Backward compatibility tests are designed to PASS before the fields parameter
is added, and continue to PASS after the fields parameter is added.
"""

import pytest

from pyeye.mcp.server import find_references


class TestFindReferencesBackwardCompatibility:
    """Test backward compatibility of find_references response structure."""

    @pytest.mark.asyncio
    async def test_find_references_returns_all_fields_by_default(self, tmp_path):
        """Test that find_references returns all expected fields when no fields parameter is specified.

        This is the critical backward compatibility test - existing callers expect
        all fields to be present in each reference in the response array.
        """
        # Create a module with a class that will have multiple references
        main_file = tmp_path / "main.py"
        main_file.write_text('''
"""Main module with a class definition."""

class ServiceManager:
    """Manages services."""

    def __init__(self):
        self.services = []

    def add_service(self, service):
        """Add a service to the manager."""
        self.services.append(service)

    def get_services(self):
        """Get all services."""
        return self.services
''')

        # Create a usage file with multiple references
        usage_file = tmp_path / "usage.py"
        usage_file.write_text('''
"""Usage of ServiceManager."""

from main import ServiceManager

# Reference 1: Import/definition
manager = ServiceManager()

# Reference 2: Assignment
another_manager = ServiceManager()

# Reference 3: In expression
def get_manager():
    return ServiceManager()

# Reference 4: Type annotation
def process(mgr: ServiceManager):
    pass
''')

        # Call find_references on ServiceManager WITHOUT any fields parameter (existing behavior)
        # Position: line 4, column 6 is the "ServiceManager" class definition
        result = await find_references(str(main_file), 4, 6, project_path=str(tmp_path))

        # Verify we got multiple references (at least definition + usages)
        assert len(result) > 1, "Expected multiple references to ServiceManager"

        # CRITICAL: All these fields MUST be present in EACH reference for backward compatibility
        # Any caller relying on these fields should not break
        expected_fields = {
            "name",
            "type",
            "line",
            "column",
            "description",
            "full_name",
            "file",
            "is_definition",
        }

        # Verify EVERY reference has ALL expected fields
        for i, ref in enumerate(result):
            actual_fields = set(ref.keys())

            # Note: "referenced_class" may be present for polymorphic searches
            # but is not part of the base expected fields
            base_fields = actual_fields - {"referenced_class"}

            assert base_fields == expected_fields, (
                f"Reference {i} has inconsistent fields! "
                f"Missing fields: {expected_fields - base_fields}, "
                f"Extra fields: {base_fields - expected_fields}"
            )

            # Verify field types
            assert isinstance(ref["name"], str), f"Reference {i}: name should be str"
            assert isinstance(ref["type"], str), f"Reference {i}: type should be str"
            assert isinstance(ref["line"], int), f"Reference {i}: line should be int"
            assert isinstance(ref["column"], int), f"Reference {i}: column should be int"
            assert isinstance(ref["description"], str), f"Reference {i}: description should be str"
            assert isinstance(ref["full_name"], str), f"Reference {i}: full_name should be str"
            assert isinstance(ref["file"], str), f"Reference {i}: file should be str"
            assert isinstance(
                ref["is_definition"], bool
            ), f"Reference {i}: is_definition should be bool"

            # Verify field content
            assert ref["name"] == "ServiceManager", f"Reference {i}: wrong name"
            assert ref["file"].endswith(".py"), f"Reference {i}: file should be .py"

        # Verify we have both definition and non-definition references
        has_definition = any(ref["is_definition"] for ref in result)
        has_reference = any(not ref["is_definition"] for ref in result)
        assert has_definition, "Should include definition"
        assert has_reference, "Should include at least one usage reference"

    @pytest.mark.asyncio
    async def test_find_references_function_all_fields(self, tmp_path):
        """Test that function references also include all fields by default."""
        # Create a module with a function
        func_file = tmp_path / "functions.py"
        func_file.write_text('''
"""Module with functions."""

def calculate_total(items):
    """Calculate total of items."""
    return sum(items)

def process_items(items):
    """Process items using calculate_total."""
    total = calculate_total(items)
    return total * 2
''')

        # Find references to calculate_total
        # Position: line 4, column 4 is the function definition
        result = await find_references(str(func_file), 4, 4, project_path=str(tmp_path))

        # Should have at least 2 references: definition + call in process_items
        assert len(result) >= 2, "Expected at least definition and one call"

        # Verify all references have all expected fields
        expected_fields = {
            "name",
            "type",
            "line",
            "column",
            "description",
            "full_name",
            "file",
            "is_definition",
        }

        for ref in result:
            base_fields = set(ref.keys()) - {"referenced_class"}
            assert (
                base_fields == expected_fields
            ), f"Function reference missing fields: {expected_fields - base_fields}"
            assert ref["name"] == "calculate_total"
            # Note: Jedi may return "function" or "statement" depending on context
            assert ref["type"] in ["function", "statement"]

    @pytest.mark.asyncio
    async def test_find_references_with_include_definitions_false(self, tmp_path):
        """Test that include_definitions=False still returns all fields for each reference."""
        main_file = tmp_path / "main.py"
        main_file.write_text('''
"""Main module."""

class DataProcessor:
    """Processes data."""
    pass

# Usage
processor = DataProcessor()
another = DataProcessor()
''')

        # Find references excluding definitions
        result = await find_references(
            str(main_file), 4, 6, project_path=str(tmp_path), include_definitions=False
        )

        # Should have at least the two instantiations (no definition)
        assert len(result) >= 2, "Expected at least two usage references"

        # None should be definitions
        assert not any(ref["is_definition"] for ref in result), "Should not include definitions"

        # All references should still have all fields
        expected_fields = {
            "name",
            "type",
            "line",
            "column",
            "description",
            "full_name",
            "file",
            "is_definition",
        }

        for ref in result:
            base_fields = set(ref.keys()) - {"referenced_class"}
            assert base_fields == expected_fields

    @pytest.mark.asyncio
    async def test_find_references_cross_file_all_fields(self, tmp_path):
        """Test that cross-file references all have complete field sets."""
        # Create definition file
        (tmp_path / "models.py").write_text('''
"""Models module."""

class User:
    """User model."""

    def __init__(self, name):
        self.name = name
''')

        # Create multiple usage files
        (tmp_path / "service.py").write_text('''
"""Service module."""

from models import User

def create_user(name):
    return User(name)
''')

        (tmp_path / "controller.py").write_text('''
"""Controller module."""

from models import User

def handle_request(name):
    user = User(name)
    return user
''')

        # Find references to User across all files
        result = await find_references(
            str(tmp_path / "models.py"), 4, 6, project_path=str(tmp_path)
        )

        # Should have references from multiple files
        files_with_refs = {ref["file"] for ref in result}
        assert len(files_with_refs) >= 2, "Expected references from multiple files"

        # Every reference from every file should have all fields
        expected_fields = {
            "name",
            "type",
            "line",
            "column",
            "description",
            "full_name",
            "file",
            "is_definition",
        }

        for ref in result:
            base_fields = set(ref.keys()) - {"referenced_class"}
            assert (
                base_fields == expected_fields
            ), f"Cross-file reference in {ref['file']} missing fields"

    @pytest.mark.asyncio
    async def test_find_references_polymorphic_includes_referenced_class(self, tmp_path):
        """Test that polymorphic search adds referenced_class field but keeps all other fields."""
        # Create base class
        (tmp_path / "base.py").write_text('''
"""Base module."""

class BaseHandler:
    """Base handler class."""
    pass
''')

        # Create subclass
        (tmp_path / "handlers.py").write_text('''
"""Handlers module."""

from base import BaseHandler

class FileHandler(BaseHandler):
    """File handler implementation."""
    pass

# Usage
handler = FileHandler()
''')

        # Find references with polymorphic search
        result = await find_references(
            str(tmp_path / "base.py"),
            4,
            6,
            project_path=str(tmp_path),
            include_subclasses=True,
        )

        # Should have references to both base and subclass
        assert len(result) > 0, "Expected references"

        # Check that references have either base fields or base fields + referenced_class
        base_expected_fields = {
            "name",
            "type",
            "line",
            "column",
            "description",
            "full_name",
            "file",
            "is_definition",
        }

        for ref in result:
            actual_fields = set(ref.keys())

            # Remove referenced_class if present
            base_fields = actual_fields - {"referenced_class"}

            # Base fields should match expected
            assert (
                base_fields == base_expected_fields
            ), f"Polymorphic reference missing base fields: {base_expected_fields - base_fields}"

            # If referenced_class is present, verify it's a string
            if "referenced_class" in actual_fields:
                assert isinstance(ref["referenced_class"], str)

    @pytest.mark.asyncio
    async def test_find_references_empty_result_returns_empty_list(self, tmp_path):
        """Test that finding references to unused symbol returns empty list."""
        test_file = tmp_path / "unused.py"
        test_file.write_text('''
"""Module with unused class."""

class UnusedClass:
    """This class is never used."""
    pass
''')

        # Find references to UnusedClass (only definition, no usages)
        result = await find_references(
            str(test_file), 4, 6, project_path=str(tmp_path), include_definitions=False
        )

        # Should return empty list (no usages found)
        assert isinstance(result, list), "Should return a list"
        assert len(result) == 0, "Should be empty list for unused symbol"


class TestFindReferencesFieldFiltering:
    """TDD tests for the fields parameter in find_references.

    These tests will FAIL with TypeError until we implement the fields parameter.
    They define the expected behavior for field filtering functionality.

    Tests follow the exact pattern from test_list_modules_backward_compat.py
    to ensure consistency across the implementation.
    """

    @pytest.mark.asyncio
    async def test_fields_single_field_name(self, tmp_path):
        """Test filtering to a single field: name."""
        test_file = tmp_path / "single.py"
        test_file.write_text('''
"""Test module."""

class TestClass:
    """A test class."""
    pass

# Usage
obj = TestClass()
''')

        # Request only the 'name' field
        result = await find_references(
            str(test_file), 4, 6, project_path=str(tmp_path), fields=["name"]
        )

        # Should have at least 2 references (definition + usage)
        assert len(result) >= 2

        # Each reference should only have 'name' field
        for ref in result:
            assert "name" in ref
            assert "type" not in ref
            assert "line" not in ref
            assert "column" not in ref
            assert "description" not in ref
            assert "full_name" not in ref
            assert "file" not in ref
            assert "is_definition" not in ref
            assert len(ref) == 1
            assert ref["name"] == "TestClass"

    @pytest.mark.asyncio
    async def test_fields_single_field_file(self, tmp_path):
        """Test filtering to a single field: file."""
        test_file = tmp_path / "file_test.py"
        test_file.write_text('''
"""File test module."""

def my_function():
    """A function."""
    pass

result = my_function()
''')

        result = await find_references(
            str(test_file), 4, 4, project_path=str(tmp_path), fields=["file"]
        )

        # Should have references
        assert len(result) >= 2

        # Each reference should only have 'file' field
        for ref in result:
            assert "file" in ref
            assert "name" not in ref
            assert "line" not in ref
            assert len(ref) == 1
            assert ref["file"].endswith("file_test.py")

    @pytest.mark.asyncio
    async def test_fields_location_fields_only(self, tmp_path):
        """Test filtering to location fields: file, line, column."""
        test_file = tmp_path / "location.py"
        test_file.write_text('''
"""Location test."""

class LocationClass:
    """Test class for location."""
    pass

obj1 = LocationClass()
obj2 = LocationClass()
''')

        result = await find_references(
            str(test_file),
            4,
            6,
            project_path=str(tmp_path),
            fields=["file", "line", "column"],
        )

        assert len(result) >= 3  # Definition + 2 usages

        # Each reference should only have location fields
        for ref in result:
            assert "file" in ref
            assert "line" in ref
            assert "column" in ref
            assert "name" not in ref
            assert "type" not in ref
            assert "description" not in ref
            assert "full_name" not in ref
            assert "is_definition" not in ref
            assert len(ref) == 3

            # Verify types
            assert isinstance(ref["file"], str)
            assert isinstance(ref["line"], int)
            assert isinstance(ref["column"], int)

    @pytest.mark.asyncio
    async def test_fields_metadata_only(self, tmp_path):
        """Test filtering to metadata fields: name, type, is_definition."""
        test_file = tmp_path / "metadata.py"
        test_file.write_text('''
"""Metadata test."""

def test_function():
    """A test function."""
    return 42

value = test_function()
''')

        result = await find_references(
            str(test_file),
            4,
            4,
            project_path=str(tmp_path),
            fields=["name", "type", "is_definition"],
        )

        assert len(result) >= 2

        for ref in result:
            assert "name" in ref
            assert "type" in ref
            assert "is_definition" in ref
            assert "file" not in ref
            assert "line" not in ref
            assert "column" not in ref
            assert "description" not in ref
            assert "full_name" not in ref
            assert len(ref) == 3

            # Verify values
            assert ref["name"] == "test_function"
            # Note: Jedi may return "function" or "statement" depending on context
            assert ref["type"] in ["function", "statement"]
            assert isinstance(ref["is_definition"], bool)

    @pytest.mark.asyncio
    async def test_fields_all_fields_explicitly(self, tmp_path):
        """Test explicitly requesting all fields."""
        test_file = tmp_path / "all_fields.py"
        test_file.write_text('''
"""All fields test."""

class AllFieldsClass:
    """Test class."""
    pass

obj = AllFieldsClass()
''')

        result = await find_references(
            str(test_file),
            4,
            6,
            project_path=str(tmp_path),
            fields=[
                "name",
                "type",
                "line",
                "column",
                "description",
                "full_name",
                "file",
                "is_definition",
            ],
        )

        assert len(result) >= 2

        expected_fields = {
            "name",
            "type",
            "line",
            "column",
            "description",
            "full_name",
            "file",
            "is_definition",
        }

        for ref in result:
            assert set(ref.keys()) == expected_fields

    @pytest.mark.asyncio
    async def test_fields_array_behavior_all_references_filtered_consistently(self, tmp_path):
        """Test that field filtering applies consistently to all references in result array.

        This is critical: when fields parameter is provided, ALL references in the array
        must have the same filtered field set.
        """
        test_file = tmp_path / "consistent.py"
        test_file.write_text('''
"""Consistency test."""

class MyClass:
    """Test class with multiple usages."""
    pass

# Multiple usages
obj1 = MyClass()
obj2 = MyClass()
obj3 = MyClass()
obj4 = MyClass()
''')

        # Request only name and line fields
        result = await find_references(
            str(test_file), 4, 6, project_path=str(tmp_path), fields=["name", "line"]
        )

        # Should have definition + 4 usages = 5 references
        assert len(result) >= 5

        # ALL references should have exactly the same field set
        for ref in result:
            assert set(ref.keys()) == {"name", "line"}
            assert "file" not in ref
            assert "column" not in ref
            assert "type" not in ref
            assert ref["name"] == "MyClass"
            assert isinstance(ref["line"], int)

    @pytest.mark.asyncio
    async def test_fields_empty_list_raises_error(self, tmp_path):
        """Test that empty fields list raises ValueError."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""
class TestClass:
    pass

obj = TestClass()
""")

        with pytest.raises(ValueError) as exc_info:
            await find_references(str(test_file), 1, 6, project_path=str(tmp_path), fields=[])

        assert "cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fields_invalid_field_name_raises_error(self, tmp_path):
        """Test that invalid field name raises ValueError with helpful message."""
        test_file = tmp_path / "test.py"
        test_file.write_text('''
"""Test module."""

class TestClass:
    """A test class."""
    pass

obj = TestClass()
''')

        with pytest.raises(ValueError) as exc_info:
            await find_references(
                str(test_file), 4, 6, project_path=str(tmp_path), fields=["invalid_field"]
            )

        error_msg = str(exc_info.value)
        assert "Invalid field" in error_msg
        assert "invalid_field" in error_msg
        # Should show valid fields
        assert "name" in error_msg
        assert "type" in error_msg
        assert "file" in error_msg
        assert "line" in error_msg
        assert "column" in error_msg
        assert "description" in error_msg
        assert "full_name" in error_msg
        assert "is_definition" in error_msg

    @pytest.mark.asyncio
    async def test_fields_multiple_invalid_fields_all_shown(self, tmp_path):
        """Test that multiple invalid fields are all shown in error message."""
        test_file = tmp_path / "test.py"
        test_file.write_text('''
"""Test module."""

class TestClass:
    """A test class."""
    pass

obj = TestClass()
''')

        with pytest.raises(ValueError) as exc_info:
            await find_references(
                str(test_file),
                4,
                6,
                project_path=str(tmp_path),
                fields=["bad_field1", "bad_field2", "name"],
            )

        error_msg = str(exc_info.value)
        # Both invalid fields should be mentioned
        assert "bad_field1" in error_msg
        assert "bad_field2" in error_msg
        # Should show valid fields
        assert "Valid fields are:" in error_msg

    @pytest.mark.asyncio
    async def test_fields_works_with_include_definitions_false(self, tmp_path):
        """Test that fields parameter works correctly with include_definitions=False."""
        test_file = tmp_path / "no_defs.py"
        test_file.write_text('''
"""No definitions test."""

class FilterClass:
    """Test class."""
    pass

obj1 = FilterClass()
obj2 = FilterClass()
''')

        result = await find_references(
            str(test_file),
            4,
            6,
            project_path=str(tmp_path),
            include_definitions=False,
            fields=["name", "is_definition"],
        )

        # Should have only usages (no definition)
        assert len(result) >= 2

        for ref in result:
            # Should only have requested fields
            assert set(ref.keys()) == {"name", "is_definition"}
            assert ref["name"] == "FilterClass"
            assert ref["is_definition"] is False

    @pytest.mark.asyncio
    async def test_fields_works_with_polymorphic_search(self, tmp_path):
        """Test that fields parameter works with include_subclasses=True."""
        # Create base class
        (tmp_path / "base.py").write_text('''
"""Base module."""

class BaseService:
    """Base service."""
    pass
''')

        # Create subclass
        (tmp_path / "impl.py").write_text('''
"""Implementation module."""

from base import BaseService

class ImplService(BaseService):
    """Implementation."""
    pass

service = ImplService()
''')

        # Polymorphic search with field filtering
        result = await find_references(
            str(tmp_path / "base.py"),
            4,
            6,
            project_path=str(tmp_path),
            include_subclasses=True,
            fields=["name", "line", "referenced_class"],
        )

        assert len(result) > 0

        # All references should have only requested fields
        # Note: referenced_class may not be present in all references
        for ref in result:
            # Should have at least name and line
            assert "name" in ref
            assert "line" in ref
            assert "file" not in ref
            assert "type" not in ref
            assert "column" not in ref

            # referenced_class is optional depending on the reference
            allowed_fields = {"name", "line", "referenced_class"}
            assert set(ref.keys()).issubset(allowed_fields)

    @pytest.mark.asyncio
    async def test_fields_order_independence(self, tmp_path):
        """Test that field order in request doesn't matter."""
        test_file = tmp_path / "order.py"
        test_file.write_text('''
"""Order test."""

class OrderClass:
    pass

obj = OrderClass()
''')

        # Request in one order
        result1 = await find_references(
            str(test_file), 4, 6, project_path=str(tmp_path), fields=["line", "name", "file"]
        )

        # Request in different order
        result2 = await find_references(
            str(test_file), 4, 6, project_path=str(tmp_path), fields=["file", "name", "line"]
        )

        # Both should return same fields
        assert len(result1) == len(result2)
        for ref1, ref2 in zip(result1, result2, strict=False):
            assert set(ref1.keys()) == set(ref2.keys())
            assert set(ref1.keys()) == {"name", "file", "line"}
