"""Backward compatibility tests for get_type_info with fields parameter.

This test suite ensures that when the fields parameter is added to get_type_info,
the default behavior (fields=None) continues to return ALL fields exactly as before.

These tests serve as regression protection - they will FAIL when we add the fields
parameter to the implementation, forcing us to verify backward compatibility.
"""

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


class TestGetTypeInfoBackwardCompatibility:
    """Test that get_type_info maintains backward compatibility when fields parameter is added."""

    @pytest.fixture
    async def analyzer(self, tmp_path):
        """Create a JediAnalyzer instance with a temp directory."""
        return JediAnalyzer(str(tmp_path))

    @pytest.mark.asyncio
    async def test_get_type_info_returns_all_fields_by_default(self, analyzer, tmp_path):
        """Test that get_type_info with no fields parameter returns ALL response fields.

        This is the backward compatibility test - existing code should continue
        to receive the full response without any changes.
        """
        # Create a class with methods, attributes, and inheritance
        test_file = tmp_path / "test_class.py"
        test_file.write_text("""
class BaseClass:
    '''Base class for testing.'''
    pass

class TestClass(BaseClass):
    '''A test class with methods and attributes.'''

    class_var = 42

    def __init__(self):
        '''Initialize the test class.'''
        self.instance_var = "test"

    def method_one(self, arg):
        '''First test method.'''
        return arg * 2

    def method_two(self):
        '''Second test method.'''
        pass
""")

        # Call get_type_info WITHOUT fields parameter (backward compatible call)
        result = await analyzer.get_type_info(str(test_file), 6, 6)

        # Verify top-level response structure
        assert "position" in result, "Missing 'position' field in response"
        assert "inferred_types" in result, "Missing 'inferred_types' field in response"
        assert "docstring" in result, "Missing 'docstring' field in response"

        # Verify position details
        assert result["position"]["file"] == str(test_file)
        assert result["position"]["line"] == 6
        assert result["position"]["column"] == 6

        # Verify inferred_types has data
        assert len(result["inferred_types"]) > 0, "Expected at least one inferred type"

        # Get the class info
        class_info = result["inferred_types"][0]

        # Verify ALL standard fields are present for a class
        assert "name" in class_info, "Missing 'name' field"
        assert "type" in class_info, "Missing 'type' field"
        assert "description" in class_info, "Missing 'description' field"
        assert "full_name" in class_info, "Missing 'full_name' field"
        assert "module_name" in class_info, "Missing 'module_name' field"

        # Verify class-specific fields
        assert "base_classes" in class_info, "Missing 'base_classes' field for class"
        assert "mro" in class_info, "Missing 'mro' field for class"

        # Verify values are correct
        assert class_info["name"] == "TestClass"
        assert class_info["type"] == "class"
        assert len(class_info["base_classes"]) == 1  # Has BaseClass as parent
        assert "BaseClass" in class_info["base_classes"][0]
        assert len(class_info["mro"]) >= 3  # TestClass, BaseClass, object

    @pytest.mark.asyncio
    async def test_get_type_info_detailed_returns_all_fields(self, analyzer, tmp_path):
        """Test that detailed=True continues to return ALL fields including methods/attributes.

        When we add the fields parameter, detailed=True should still work as before,
        returning everything including methods and attributes.
        """
        test_file = tmp_path / "detailed_class.py"
        test_file.write_text("""
class DetailedClass:
    '''A class for testing detailed mode.'''

    class_var = 100

    def __init__(self):
        '''Constructor.'''
        self.instance_var = 200

    def method_a(self, x):
        '''Method A.'''
        return x + 1

    def method_b(self):
        '''Method B.'''
        pass

    @property
    def computed_value(self):
        '''A computed property.'''
        return self.instance_var * 2
""")

        # Call with detailed=True (backward compatible call)
        result = await analyzer.get_type_info(str(test_file), 2, 6, detailed=True)

        # Verify top-level structure
        assert "position" in result
        assert "inferred_types" in result
        assert "docstring" in result

        class_info = result["inferred_types"][0]

        # Verify ALL standard fields
        assert "name" in class_info
        assert "type" in class_info
        assert "description" in class_info
        assert "full_name" in class_info
        assert "module_name" in class_info
        assert "base_classes" in class_info
        assert "mro" in class_info

        # Verify detailed=True adds methods and attributes
        assert "methods" in class_info, "Missing 'methods' field with detailed=True"
        assert "attributes" in class_info, "Missing 'attributes' field with detailed=True"

        # Verify methods are populated
        assert len(class_info["methods"]) >= 3  # __init__, method_a, method_b
        method_names = [m["name"] for m in class_info["methods"]]
        assert "__init__" in method_names
        assert "method_a" in method_names
        assert "method_b" in method_names

    @pytest.mark.asyncio
    async def test_get_type_info_function_returns_all_fields(self, analyzer, tmp_path):
        """Test that functions continue to return all their fields.

        Functions don't have base_classes/mro, but should still return all
        standard type info fields.
        """
        test_file = tmp_path / "test_function.py"
        test_file.write_text("""
def test_function(arg1, arg2):
    '''A test function with documentation.

    Args:
        arg1: First argument
        arg2: Second argument

    Returns:
        The sum of arguments
    '''
    return arg1 + arg2
""")

        result = await analyzer.get_type_info(str(test_file), 2, 4)

        # Verify top-level structure
        assert "position" in result
        assert "inferred_types" in result
        assert "docstring" in result

        # Verify docstring is populated for function
        assert result["docstring"] is not None
        assert "test function" in result["docstring"].lower()

        func_info = result["inferred_types"][0]

        # Verify ALL standard fields for function
        assert "name" in func_info
        assert "type" in func_info
        assert "description" in func_info
        assert "full_name" in func_info
        assert "module_name" in func_info

        # Functions should NOT have class-specific fields
        assert "base_classes" not in func_info, "Functions should not have base_classes"
        assert "mro" not in func_info, "Functions should not have mro"

        # Verify values
        assert func_info["name"] == "test_function"
        assert func_info["type"] == "function"

    @pytest.mark.asyncio
    async def test_get_type_info_simple_class_no_inheritance(self, analyzer, tmp_path):
        """Test backward compatibility for simple class with no explicit inheritance.

        Even simple classes should return base_classes (empty list) and mro.
        """
        test_file = tmp_path / "simple.py"
        test_file.write_text("""
class SimpleClass:
    '''A simple class.'''

    def simple_method(self):
        '''A simple method.'''
        pass
""")

        result = await analyzer.get_type_info(str(test_file), 2, 6)

        # Verify structure
        assert "position" in result
        assert "inferred_types" in result
        assert "docstring" in result

        class_info = result["inferred_types"][0]

        # Verify ALL fields present
        assert "name" in class_info
        assert "type" in class_info
        assert "description" in class_info
        assert "full_name" in class_info
        assert "module_name" in class_info
        assert "base_classes" in class_info
        assert "mro" in class_info

        # Simple class has no explicit bases but should have object in MRO
        assert class_info["base_classes"] == []
        assert "builtins.object" in class_info["mro"]
        assert "SimpleClass" in class_info["mro"][0]


class TestGetTypeInfoFieldFiltering:
    """TDD tests for the fields parameter in get_type_info.

    These tests will FAIL with TypeError until we implement the fields parameter.
    They define the expected behavior for field filtering functionality.
    """

    @pytest.fixture
    async def analyzer(self, tmp_path):
        """Create a JediAnalyzer instance with a temp directory."""
        return JediAnalyzer(str(tmp_path))

    @pytest.fixture
    def sample_class_file(self, tmp_path):
        """Create a sample class file for testing."""
        test_file = tmp_path / "sample_class.py"
        test_file.write_text("""
class BaseClass:
    '''Base class for testing.'''
    pass

class SampleClass(BaseClass):
    '''A sample class with various features.'''

    class_var = 42

    def __init__(self):
        '''Initialize the sample class.'''
        self.instance_var = "test"

    def sample_method(self, arg):
        '''A sample method.'''
        return arg * 2
""")
        return test_file

    @pytest.fixture
    def sample_function_file(self, tmp_path):
        """Create a sample function file for testing."""
        test_file = tmp_path / "sample_function.py"
        test_file.write_text("""
def sample_function(x, y):
    '''A sample function for testing.

    Args:
        x: First argument
        y: Second argument

    Returns:
        The sum of arguments
    '''
    return x + y
""")
        return test_file

    @pytest.fixture
    def sample_variable_file(self, tmp_path):
        """Create a sample variable file for testing."""
        test_file = tmp_path / "sample_variable.py"
        test_file.write_text("""
# A module-level variable
MODULE_CONSTANT = 100
""")
        return test_file

    # === SINGLE FIELD TESTS ===

    @pytest.mark.asyncio
    async def test_fields_position_only_class(self, analyzer, sample_class_file):
        """Test filtering to position field only for a class."""
        result = await analyzer.get_type_info(str(sample_class_file), 6, 6, fields=["position"])

        # Should only have position field
        assert "position" in result
        assert "inferred_types" not in result
        assert "docstring" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fields_inferred_types_only_class(self, analyzer, sample_class_file):
        """Test filtering to inferred_types field only for a class."""
        result = await analyzer.get_type_info(
            str(sample_class_file), 6, 6, fields=["inferred_types"]
        )

        # Should only have inferred_types field
        assert "inferred_types" in result
        assert "position" not in result
        assert "docstring" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fields_docstring_only_class(self, analyzer, sample_class_file):
        """Test filtering to docstring field only for a class."""
        result = await analyzer.get_type_info(str(sample_class_file), 6, 6, fields=["docstring"])

        # Should only have docstring field
        assert "docstring" in result
        assert "position" not in result
        assert "inferred_types" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fields_position_only_function(self, analyzer, sample_function_file):
        """Test filtering to position field only for a function."""
        result = await analyzer.get_type_info(str(sample_function_file), 2, 4, fields=["position"])

        assert "position" in result
        assert "inferred_types" not in result
        assert "docstring" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fields_inferred_types_only_function(self, analyzer, sample_function_file):
        """Test filtering to inferred_types field only for a function."""
        result = await analyzer.get_type_info(
            str(sample_function_file), 2, 4, fields=["inferred_types"]
        )

        assert "inferred_types" in result
        assert "position" not in result
        assert "docstring" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fields_docstring_only_function(self, analyzer, sample_function_file):
        """Test filtering to docstring field only for a function."""
        result = await analyzer.get_type_info(str(sample_function_file), 2, 4, fields=["docstring"])

        assert "docstring" in result
        assert "position" not in result
        assert "inferred_types" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fields_position_only_variable(self, analyzer, sample_variable_file):
        """Test filtering to position field only for a variable."""
        result = await analyzer.get_type_info(str(sample_variable_file), 2, 0, fields=["position"])

        assert "position" in result
        assert "inferred_types" not in result
        assert "docstring" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fields_inferred_types_only_variable(self, analyzer, sample_variable_file):
        """Test filtering to inferred_types field only for a variable."""
        result = await analyzer.get_type_info(
            str(sample_variable_file), 2, 0, fields=["inferred_types"]
        )

        assert "inferred_types" in result
        assert "position" not in result
        assert "docstring" not in result
        assert len(result) == 1

    # === COMBINATION FIELD TESTS ===

    @pytest.mark.asyncio
    async def test_fields_inferred_types_and_docstring_class(self, analyzer, sample_class_file):
        """Test filtering to inferred_types and docstring for a class."""
        result = await analyzer.get_type_info(
            str(sample_class_file), 6, 6, fields=["inferred_types", "docstring"]
        )

        assert "inferred_types" in result
        assert "docstring" in result
        assert "position" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fields_position_and_inferred_types_function(
        self, analyzer, sample_function_file
    ):
        """Test filtering to position and inferred_types for a function."""
        result = await analyzer.get_type_info(
            str(sample_function_file), 2, 4, fields=["position", "inferred_types"]
        )

        assert "position" in result
        assert "inferred_types" in result
        assert "docstring" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fields_position_and_docstring_class(self, analyzer, sample_class_file):
        """Test filtering to position and docstring for a class."""
        result = await analyzer.get_type_info(
            str(sample_class_file), 6, 6, fields=["position", "docstring"]
        )

        assert "position" in result
        assert "docstring" in result
        assert "inferred_types" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fields_all_three_fields_function(self, analyzer, sample_function_file):
        """Test explicitly requesting all three fields for a function."""
        result = await analyzer.get_type_info(
            str(sample_function_file), 2, 4, fields=["position", "inferred_types", "docstring"]
        )

        assert "position" in result
        assert "inferred_types" in result
        assert "docstring" in result
        assert len(result) == 3

    # === SERVER-LEVEL TESTS ===

    @pytest.mark.asyncio
    async def test_server_fields_position_only(self, tmp_path, sample_class_file):
        """Test that the MCP server's get_type_info accepts fields parameter."""
        from pyeye.mcp.server import get_type_info as server_get_type_info

        result = await server_get_type_info(
            str(sample_class_file), 6, 6, project_path=str(tmp_path), fields=["position"]
        )

        assert "position" in result
        assert "inferred_types" not in result
        assert "docstring" not in result
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_server_fields_combination(self, tmp_path, sample_function_file):
        """Test server with multiple fields."""
        from pyeye.mcp.server import get_type_info as server_get_type_info

        result = await server_get_type_info(
            str(sample_function_file),
            2,
            4,
            project_path=str(tmp_path),
            fields=["inferred_types", "docstring"],
        )

        assert "inferred_types" in result
        assert "docstring" in result
        assert "position" not in result
        assert len(result) == 2

    # === EDGE CASES ===

    @pytest.mark.asyncio
    async def test_fields_empty_list(self, analyzer, sample_class_file):
        """Test behavior with empty fields list."""
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(str(sample_class_file), 6, 6, fields=[])

        assert "cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fields_invalid_field_name(self, analyzer, sample_class_file):
        """Test behavior with invalid field name."""
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(str(sample_class_file), 6, 6, fields=["invalid_field"])

        assert "Invalid field" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fields_with_detailed_true(self, analyzer, sample_class_file):
        """Test fields parameter interaction with detailed=True."""
        result = await analyzer.get_type_info(
            str(sample_class_file), 6, 6, detailed=True, fields=["inferred_types"]
        )

        # Should only have inferred_types (which will include methods/attributes due to detailed=True)
        assert "inferred_types" in result
        assert "position" not in result
        assert "docstring" not in result
        assert len(result) == 1


class TestGetTypeInfoValidationErrors:
    """TDD tests for validation errors in get_type_info fields parameter.

    These tests ensure helpful error messages guide users when they make mistakes
    with the fields parameter, including symbol-type-specific field availability.

    These tests will FAIL until we implement proper validation in get_type_info.
    """

    @pytest.fixture
    async def analyzer(self, tmp_path):
        """Create a JediAnalyzer instance with a temp directory."""
        return JediAnalyzer(str(tmp_path))

    @pytest.fixture
    def sample_class_file(self, tmp_path):
        """Create a sample class file for testing."""
        test_file = tmp_path / "sample_class.py"
        test_file.write_text("""
class BaseClass:
    '''Base class for testing.'''
    pass

class SampleClass(BaseClass):
    '''A sample class with various features.'''

    class_var = 42

    def __init__(self):
        '''Initialize the sample class.'''
        self.instance_var = "test"

    def sample_method(self, arg):
        '''A sample method.'''
        return arg * 2
""")
        return test_file

    @pytest.fixture
    def sample_function_file(self, tmp_path):
        """Create a sample function file for testing."""
        test_file = tmp_path / "sample_function.py"
        test_file.write_text("""
def sample_function(x, y):
    '''A sample function for testing.

    Args:
        x: First argument
        y: Second argument

    Returns:
        The sum of arguments
    '''
    return x + y
""")
        return test_file

    @pytest.fixture
    def sample_variable_file(self, tmp_path):
        """Create a sample variable file for testing."""
        test_file = tmp_path / "sample_variable.py"
        test_file.write_text("""
# A module-level variable
MODULE_CONSTANT = 100
""")
        return test_file

    # === BASIC VALIDATION TESTS (filter_fields helper) ===

    @pytest.mark.asyncio
    async def test_empty_fields_list_raises_helpful_error(self, analyzer, sample_class_file):
        """Test that empty fields list raises ValueError with helpful message.

        This uses the filter_fields helper validation, so the error should mention
        that fields list cannot be empty.
        """
        # This will FAIL because fields parameter doesn't exist yet
        # Once implemented, it should raise ValueError (not TypeError)
        with pytest.raises((TypeError, ValueError)) as exc_info:
            await analyzer.get_type_info(str(sample_class_file), 6, 6, fields=[])

        # When implemented, verify helpful error message
        error_msg = str(exc_info.value).lower()
        if isinstance(exc_info.value, ValueError):
            assert "empty" in error_msg or "cannot be empty" in error_msg

    @pytest.mark.asyncio
    async def test_invalid_field_name_shows_valid_options(self, analyzer, sample_class_file):
        """Test that invalid field name raises ValueError showing valid options.

        This uses the filter_fields helper validation, which shows sorted list of
        valid fields when an invalid field is requested.
        """
        # This will FAIL because fields parameter doesn't exist yet
        with pytest.raises((TypeError, ValueError)) as exc_info:
            await analyzer.get_type_info(str(sample_class_file), 6, 6, fields=["invalid_field"])

        # When implemented, verify error shows valid fields
        error_msg = str(exc_info.value)
        if isinstance(exc_info.value, ValueError):
            # Should mention the invalid field
            assert "invalid_field" in error_msg
            # Should show valid top-level fields
            assert "position" in error_msg.lower()
            assert "inferred_types" in error_msg.lower()
            assert "docstring" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_typo_in_field_name_shows_suggestions(self, analyzer, sample_class_file):
        """Test that typo in field name provides helpful guidance.

        For example, 'docsting' instead of 'docstring' should show the valid fields
        in alphabetical order, making it easy to spot the correct spelling.
        """
        # This will FAIL because fields parameter doesn't exist yet
        with pytest.raises((TypeError, ValueError)) as exc_info:
            await analyzer.get_type_info(
                str(sample_class_file), 6, 6, fields=["docsting"]  # Typo: missing 'r'
            )

        # When implemented, verify error is helpful
        error_msg = str(exc_info.value)
        if isinstance(exc_info.value, ValueError):
            # Should show the typo
            assert "docsting" in error_msg
            # Should show sorted valid fields (making 'docstring' easy to spot)
            assert "docstring" in error_msg.lower()
            assert "inferred_types" in error_msg.lower()
            assert "position" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_multiple_invalid_fields_all_shown(self, analyzer, sample_class_file):
        """Test that all invalid fields are shown in error message."""
        # This will FAIL because fields parameter doesn't exist yet
        with pytest.raises((TypeError, ValueError)) as exc_info:
            await analyzer.get_type_info(
                str(sample_class_file),
                6,
                6,
                fields=["bad_field1", "bad_field2", "position"],  # 2 invalid, 1 valid
            )

        # When implemented, verify both invalid fields shown
        error_msg = str(exc_info.value)
        if isinstance(exc_info.value, ValueError):
            assert "bad_field1" in error_msg
            assert "bad_field2" in error_msg

    # === SYMBOL-TYPE-SPECIFIC VALIDATION TESTS ===
    # These tests are NEW - they check that get_type_info validates fields
    # based on the actual symbol type encountered (class vs function vs variable)

    @pytest.mark.asyncio
    async def test_class_specific_field_on_function_raises_helpful_error(
        self, analyzer, sample_function_file
    ):
        """Test requesting nested field syntax raises invalid field error.

        Phase 2 only supports top-level fields (position, inferred_types, docstring).
        Nested field syntax like 'inferred_types.base_classes' is not a valid top-level field.
        """
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(
                str(sample_function_file),
                2,
                4,
                fields=["inferred_types.base_classes"],  # Not a top-level field
            )

        # Should indicate this is not a valid top-level field
        error_msg = str(exc_info.value)
        assert "Invalid field" in error_msg
        assert "inferred_types.base_classes" in error_msg
        assert "Valid fields are:" in error_msg

    @pytest.mark.asyncio
    async def test_class_specific_field_mro_on_function(self, analyzer, sample_function_file):
        """Test requesting nested 'mro' field raises invalid field error.

        Phase 2 only supports top-level fields. 'inferred_types.mro' is not valid.
        """
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(
                str(sample_function_file), 2, 4, fields=["inferred_types.mro"]
            )

        error_msg = str(exc_info.value)
        assert "Invalid field" in error_msg
        assert "inferred_types.mro" in error_msg

    @pytest.mark.asyncio
    async def test_methods_field_on_function_raises_error(self, analyzer, sample_function_file):
        """Test requesting nested 'methods' field raises invalid field error.

        Phase 2 only supports top-level fields. 'inferred_types.methods' is not valid.
        """
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(
                str(sample_function_file), 2, 4, detailed=True, fields=["inferred_types.methods"]
            )

        error_msg = str(exc_info.value)
        assert "Invalid field" in error_msg
        assert "inferred_types.methods" in error_msg

    @pytest.mark.asyncio
    async def test_attributes_field_on_variable_raises_error(self, analyzer, sample_variable_file):
        """Test requesting nested 'attributes' field raises invalid field error.

        Phase 2 only supports top-level fields. 'inferred_types.attributes' is not valid.
        """
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(
                str(sample_variable_file), 2, 0, detailed=True, fields=["inferred_types.attributes"]
            )

        error_msg = str(exc_info.value)
        assert "Invalid field" in error_msg
        assert "inferred_types.attributes" in error_msg

    @pytest.mark.asyncio
    async def test_error_distinguishes_invalid_vs_unavailable_fields(
        self, analyzer, sample_function_file
    ):
        """Test that both invalid top-level fields are reported in error.

        Both 'completely_bogus' and 'inferred_types.base_classes' are invalid top-level fields.
        Phase 2 only supports: position, inferred_types, docstring
        """
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(
                str(sample_function_file),
                2,
                4,
                fields=["completely_bogus", "inferred_types.base_classes"],
            )

        error_msg = str(exc_info.value)
        assert "Invalid field" in error_msg
        # Both should be mentioned as invalid (sorted alphabetically)
        assert "completely_bogus" in error_msg
        assert "inferred_types.base_classes" in error_msg

    # === MIXED VALID AND INVALID FIELDS ===

    @pytest.mark.asyncio
    async def test_valid_and_invalid_fields_mixed_class(self, analyzer, sample_class_file):
        """Test mix of valid and invalid fields on class.

        Should only complain about invalid fields, allow valid ones.
        """
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(
                str(sample_class_file), 6, 6, fields=["position", "invalid_field", "docstring"]
            )

        error_msg = str(exc_info.value)
        # Should mention invalid field
        assert "Invalid field" in error_msg
        assert "invalid_field" in error_msg
        # Should show valid fields for reference
        assert "Valid fields are:" in error_msg

    @pytest.mark.asyncio
    async def test_nested_field_validation_top_level_only(self, analyzer, sample_class_file):
        """Test that field validation works at top level.

        Note: Phase 2 only implements top-level field filtering.
        Nested field filtering (e.g., 'inferred_types.name') is Phase 3.

        This test verifies we properly validate top-level fields: position, inferred_types, docstring.
        """
        # Valid: requesting only top-level fields
        result = await analyzer.get_type_info(
            str(sample_class_file), 6, 6, fields=["position", "docstring"]
        )
        assert "position" in result
        assert "docstring" in result
        assert "inferred_types" not in result

        # Invalid: requesting something that's not a top-level field
        with pytest.raises(ValueError) as exc_info:
            await analyzer.get_type_info(
                str(sample_class_file),
                6,
                6,
                fields=["name"],  # This is nested under inferred_types, not top-level
            )

        # Should indicate 'name' is not a valid top-level field
        if isinstance(exc_info.value, ValueError):
            error_msg = str(exc_info.value)
            assert "name" in error_msg
            # Should show valid top-level fields
            assert "position" in error_msg.lower() or "inferred_types" in error_msg.lower()
