"""Tests for field filtering validation logic.

This module tests the filter_fields helper function that will be used
across PyEye tools to reduce token consumption by filtering response data.
"""

import pytest

from pyeye.mcp.server import filter_fields


class TestFilterFieldsSingleDict:
    """Test field filtering on single dict input (e.g., get_type_info)."""

    def test_filter_fields_with_none_returns_all_fields(self):
        """Test that fields=None returns the entire dict unchanged."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py"}
        result = filter_fields(data, fields=None)

        assert result == data
        assert result is not data  # Should be a copy, not the same object

    def test_filter_fields_with_valid_subset(self):
        """Test filtering to a valid subset of fields."""
        data = {
            "name": "MyClass",
            "type": "class",
            "file": "/path/to/file.py",
            "docstring": "A test class",
            "line": 42,
        }

        result = filter_fields(data, fields=["name", "file"])

        assert result == {"name": "MyClass", "file": "/path/to/file.py"}
        assert "type" not in result
        assert "docstring" not in result
        assert "line" not in result

    def test_filter_fields_with_single_field(self):
        """Test filtering to a single field."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py"}

        result = filter_fields(data, fields=["name"])

        assert result == {"name": "MyClass"}
        assert len(result) == 1

    def test_filter_fields_with_all_fields(self):
        """Test requesting all available fields explicitly."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py"}

        result = filter_fields(data, fields=["name", "type", "file"])

        assert result == data

    def test_filter_fields_with_empty_list_raises_error(self):
        """Test that fields=[] raises ValueError with clear message."""
        data = {"name": "MyClass", "type": "class"}

        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=[])

        error_msg = str(exc_info.value)
        assert "cannot be empty" in error_msg.lower()

    def test_filter_fields_with_invalid_field_raises_error(self):
        """Test that invalid field name raises ValueError with helpful message."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py"}

        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=["invalid_field"])

        error_msg = str(exc_info.value)
        assert "Invalid field(s): 'invalid_field'" in error_msg
        # Should list valid fields alphabetically
        assert "file, name, type" in error_msg or "file" in error_msg

    def test_filter_fields_with_multiple_invalid_fields_raises_error(self):
        """Test that multiple invalid fields are all listed in error message."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py"}

        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=["invalid1", "invalid2", "name"])

        error_msg = str(exc_info.value)
        assert "Invalid field(s):" in error_msg
        assert "invalid1" in error_msg
        assert "invalid2" in error_msg
        # Should still show valid fields
        assert "Valid fields are:" in error_msg

    def test_filter_fields_with_mixed_valid_invalid_raises_error(self):
        """Test that mixing valid and invalid fields raises error listing only invalid ones."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py"}

        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=["name", "invalid_field", "file"])

        error_msg = str(exc_info.value)
        assert "Invalid field(s): 'invalid_field'" in error_msg
        # Should not list 'name' or 'file' as invalid
        assert "'name'" not in error_msg or "Invalid field(s): 'name'" not in error_msg
        assert "'file'" not in error_msg or "Invalid field(s): 'file'" not in error_msg

    def test_filter_fields_preserves_field_order(self):
        """Test that filtered dict preserves the order of requested fields."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py", "line": 42}

        # Request fields in different order than they appear in data
        result = filter_fields(data, fields=["file", "name", "line"])

        # Result should have fields in the requested order
        assert list(result.keys()) == ["file", "name", "line"]

    def test_filter_fields_on_empty_dict_with_none(self):
        """Test that empty dict with fields=None returns empty dict."""
        data = {}
        result = filter_fields(data, fields=None)

        assert result == {}

    def test_filter_fields_on_empty_dict_with_fields_raises_error(self):
        """Test that empty dict with requested fields raises error."""
        data = {}

        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=["name"])

        error_msg = str(exc_info.value)
        assert "Invalid field(s): 'name'" in error_msg


class TestFilterFieldsArrayOfDicts:
    """Test field filtering on list of dicts (e.g., list_modules, find_references)."""

    def test_filter_fields_array_with_none_returns_all_fields(self):
        """Test that fields=None returns entire array unchanged."""
        data = [
            {"name": "module1", "type": "module", "file": "/path/1.py"},
            {"name": "module2", "type": "module", "file": "/path/2.py"},
        ]

        result = filter_fields(data, fields=None)

        assert result == data
        assert result is not data  # Should be a copy

    def test_filter_fields_array_with_valid_subset(self):
        """Test filtering array to valid subset of fields."""
        data = [
            {"name": "module1", "type": "module", "file": "/path/1.py"},
            {"name": "module2", "type": "module", "file": "/path/2.py"},
            {"name": "module3", "type": "module", "file": "/path/3.py"},
        ]

        result = filter_fields(data, fields=["name", "file"])

        assert len(result) == 3
        assert result == [
            {"name": "module1", "file": "/path/1.py"},
            {"name": "module2", "file": "/path/2.py"},
            {"name": "module3", "file": "/path/3.py"},
        ]
        # Ensure 'type' was filtered out from all items
        for item in result:
            assert "type" not in item

    def test_filter_fields_array_with_single_field(self):
        """Test filtering array to single field."""
        data = [
            {"name": "module1", "type": "module"},
            {"name": "module2", "type": "module"},
        ]

        result = filter_fields(data, fields=["name"])

        assert result == [
            {"name": "module1"},
            {"name": "module2"},
        ]

    def test_filter_fields_array_validates_against_first_item(self):
        """Test that field validation uses first item in array."""
        data = [
            {"name": "module1", "type": "module", "file": "/path/1.py"},
            {"name": "module2", "type": "module", "file": "/path/2.py"},
        ]

        # Valid fields from first item
        result = filter_fields(data, fields=["name", "type"])
        assert len(result) == 2

        # Invalid field based on first item
        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=["invalid_field"])

        error_msg = str(exc_info.value)
        assert "Invalid field(s): 'invalid_field'" in error_msg
        assert "file, name, type" in error_msg or "file" in error_msg

    def test_filter_fields_empty_array_with_none_returns_empty(self):
        """Test that empty array with fields=None returns empty array."""
        data = []
        result = filter_fields(data, fields=None)

        assert result == []

    def test_filter_fields_empty_array_with_valid_fields_returns_empty(self):
        """Test that empty array with fields list returns empty array (no validation)."""
        data = []
        # When array is empty, there's nothing to validate against
        # Should return empty array without error
        result = filter_fields(data, fields=["name", "type"])

        assert result == []

    def test_filter_fields_array_with_empty_list_raises_error(self):
        """Test that fields=[] raises ValueError even for arrays."""
        data = [
            {"name": "module1", "type": "module"},
            {"name": "module2", "type": "module"},
        ]

        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=[])

        error_msg = str(exc_info.value)
        assert "cannot be empty" in error_msg.lower()

    def test_filter_fields_array_preserves_order(self):
        """Test that filtered array items preserve requested field order."""
        data = [
            {"name": "module1", "type": "module", "file": "/path/1.py", "line": 1},
            {"name": "module2", "type": "module", "file": "/path/2.py", "line": 10},
        ]

        result = filter_fields(data, fields=["file", "name"])

        # Each item should have fields in requested order
        for item in result:
            assert list(item.keys()) == ["file", "name"]

    def test_filter_fields_array_with_inconsistent_keys(self):
        """Test behavior when array items have different keys (edge case)."""
        # First item defines the valid fields
        data = [
            {"name": "module1", "type": "module"},
            {"name": "module2", "type": "module", "extra": "value"},  # Has extra key
        ]

        # Should validate against first item
        result = filter_fields(data, fields=["name"])

        # Both items should be filtered to just 'name'
        assert result == [
            {"name": "module1"},
            {"name": "module2"},
        ]

    def test_filter_fields_array_handles_missing_fields_in_later_items(self):
        """Test that filtering handles items missing some fields (edge case)."""
        data = [
            {"name": "module1", "type": "module", "file": "/path/1.py"},
            {"name": "module2", "type": "module"},  # Missing 'file'
        ]

        # Request fields that exist in first item
        result = filter_fields(data, fields=["name", "file"])

        # First item should have both fields
        assert "name" in result[0] and "file" in result[0]
        # Second item should have 'name' but 'file' might be missing
        # Implementation should handle gracefully (either include with None or skip)
        assert "name" in result[1]


class TestFilterFieldsEdgeCases:
    """Test edge cases and error conditions."""

    def test_filter_fields_with_duplicate_field_names(self):
        """Test that duplicate field names in request are handled."""
        data = {"name": "MyClass", "type": "class", "file": "/path/to/file.py"}

        # Duplicate 'name' in fields list
        result = filter_fields(data, fields=["name", "type", "name"])

        # Should still work, possibly deduplicating
        assert "name" in result
        assert "type" in result
        # Result should only have each field once
        assert len(result) == 2

    def test_filter_fields_preserves_none_values(self):
        """Test that None values in data are preserved during filtering."""
        data = {"name": "MyClass", "type": None, "file": "/path/to/file.py"}

        result = filter_fields(data, fields=["type", "file"])

        assert result == {"type": None, "file": "/path/to/file.py"}
        assert "type" in result  # None values should be preserved

    def test_filter_fields_case_sensitivity(self):
        """Test that field names are case-sensitive."""
        data = {"name": "MyClass", "Name": "OtherName", "type": "class"}

        # Request lowercase 'name'
        result = filter_fields(data, fields=["name"])

        assert result == {"name": "MyClass"}
        assert "Name" not in result

    def test_filter_fields_with_special_characters_in_keys(self):
        """Test filtering works with keys containing special characters."""
        data = {
            "name": "test",
            "type": "class",
            "meta:info": "value",
            "field-with-dash": "data",
        }

        result = filter_fields(data, fields=["name", "meta:info"])

        assert result == {"name": "test", "meta:info": "value"}

    def test_filter_fields_validates_fields_is_list(self):
        """Test that fields parameter must be a list or None."""
        data = {"name": "MyClass", "type": "class"}

        # String instead of list should raise error
        with pytest.raises((TypeError, ValueError)):
            filter_fields(data, fields="name")

        # Set instead of list should raise error
        with pytest.raises((TypeError, ValueError)):
            filter_fields(data, fields={"name", "type"})

    def test_filter_fields_error_message_shows_sorted_valid_fields(self):
        """Test that error message shows valid fields in alphabetical order."""
        data = {"zebra": "z", "alpha": "a", "beta": "b"}

        with pytest.raises(ValueError) as exc_info:
            filter_fields(data, fields=["invalid"])

        error_msg = str(exc_info.value)
        # Valid fields should be sorted alphabetically
        assert "alpha, beta, zebra" in error_msg
