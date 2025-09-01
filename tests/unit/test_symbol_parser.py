"""Unit tests for the symbol parser module.

These tests follow the testing strategy defined in docs/testing/STRATEGY.md
and conventions from docs/testing/CONVENTIONS.md.
"""

import pytest

from pycodemcp.symbol_parser import (
    classify_symbol_type,
    get_parent_and_member,
    is_compound_symbol,
    parse_compound_symbol,
    validate_symbol_component,
)


class TestSymbolParser:
    """Test suite for symbol parser functions following unit test best practices."""

    def test_is_compound_symbol(self) -> None:
        """Test detection of compound symbols."""
        # Compound symbols
        assert is_compound_symbol("Model.__init__") is True
        assert is_compound_symbol("module.Class.method") is True
        assert is_compound_symbol("a.b") is True

        # Simple symbols
        assert is_compound_symbol("Model") is False
        assert is_compound_symbol("__init__") is False
        assert is_compound_symbol("simple_function") is False
        assert is_compound_symbol("") is False

    def test_parse_compound_symbol_valid(self) -> None:
        """Test parsing valid compound symbols."""
        # Two components
        components, valid = parse_compound_symbol("Model.__init__")
        assert valid is True
        assert components == ["Model", "__init__"]

        # Three components
        components, valid = parse_compound_symbol("module.Class.method")
        assert valid is True
        assert components == ["module", "Class", "method"]

        # Many components
        components, valid = parse_compound_symbol("a.b.c.d.e")
        assert valid is True
        assert components == ["a", "b", "c", "d", "e"]

        # With underscores
        components, valid = parse_compound_symbol("My_Class._private_method")
        assert valid is True
        assert components == ["My_Class", "_private_method"]

    def test_parse_compound_symbol_invalid(self) -> None:
        """Test parsing invalid compound symbols."""
        # Double dots
        components, valid = parse_compound_symbol("Model..method")
        assert valid is False
        assert components == []

        # Leading dot
        components, valid = parse_compound_symbol(".Model.method")
        assert valid is False
        assert components == []

        # Trailing dot
        components, valid = parse_compound_symbol("Model.method.")
        assert valid is False
        assert components == []

        # Empty string
        components, valid = parse_compound_symbol("")
        assert valid is False
        assert components == []

        # Just dots
        components, valid = parse_compound_symbol("...")
        assert valid is False
        assert components == []

        # Invalid component (starts with number)
        components, valid = parse_compound_symbol("Model.123invalid")
        assert valid is False
        assert components == []

    def test_validate_symbol_component(self) -> None:
        """Test validation of individual symbol components."""
        # Valid components
        assert validate_symbol_component("Model") is True
        assert validate_symbol_component("__init__") is True
        assert validate_symbol_component("_private") is True
        assert validate_symbol_component("method123") is True
        assert validate_symbol_component("CONSTANT") is True
        assert validate_symbol_component("a") is True
        assert validate_symbol_component("_") is True

        # Invalid components
        assert validate_symbol_component("123start") is False
        assert validate_symbol_component("with-dash") is False
        assert validate_symbol_component("with space") is False
        assert validate_symbol_component("") is False
        assert validate_symbol_component("with.dot") is False
        assert validate_symbol_component("with@symbol") is False

    def test_get_parent_and_member(self) -> None:
        """Test splitting components into parent and member."""
        # Two components
        parent, member = get_parent_and_member(["Model", "__init__"])
        assert parent == "Model"
        assert member == "__init__"

        # Three components
        parent, member = get_parent_and_member(["module", "Class", "method"])
        assert parent == "module.Class"
        assert member == "method"

        # Many components
        parent, member = get_parent_and_member(["a", "b", "c", "d"])
        assert parent == "a.b.c"
        assert member == "d"

        # Error case: too few components
        with pytest.raises(ValueError, match="Need at least 2 components"):
            get_parent_and_member(["single"])

        with pytest.raises(ValueError, match="Need at least 2 components"):
            get_parent_and_member([])

    def test_classify_symbol_type(self) -> None:
        """Test classification of symbol types."""
        # Class constructor
        assert classify_symbol_type(["Model", "__init__"]) == "class_constructor"

        # Magic method
        assert classify_symbol_type(["Model", "__str__"]) == "magic_method"
        assert classify_symbol_type(["Model", "__eq__"]) == "magic_method"

        # Private member
        assert classify_symbol_type(["Model", "_private"]) == "private_member"

        # Class member (uppercase first component)
        assert classify_symbol_type(["Model", "save"]) == "class_member"
        assert classify_symbol_type(["UserFactory", "create"]) == "class_member"

        # Module function (lowercase first component)
        assert classify_symbol_type(["utils", "format"]) == "module_function"
        assert classify_symbol_type(["os", "listdir"]) == "module_function"

        # Qualified member (3+ components)
        assert classify_symbol_type(["module", "Class", "method"]) == "qualified_member"
        assert classify_symbol_type(["a", "b", "c", "d"]) == "qualified_member"

        # Edge cases
        assert classify_symbol_type([]) == "unknown"
        assert classify_symbol_type(["single"]) == "simple_member"

    def test_parse_compound_symbol_edge_cases(self) -> None:
        """Test edge cases for compound symbol parsing."""
        # Single dot
        components, valid = parse_compound_symbol(".")
        assert valid is False
        assert components == []

        # Multiple consecutive dots
        components, valid = parse_compound_symbol("a...b")
        assert valid is False
        assert components == []

        # Valid symbol with numbers
        components, valid = parse_compound_symbol("Class1.method2")
        assert valid is True
        assert components == ["Class1", "method2"]

        # Unicode characters (should fail)
        components, valid = parse_compound_symbol("Class.方法")
        assert valid is False
        assert components == []

        # Special characters in component
        components, valid = parse_compound_symbol("Class.method$")
        assert valid is False
        assert components == []

    def test_validate_symbol_component_edge_cases(self) -> None:
        """Test edge cases for symbol component validation."""
        # Single underscore is valid
        assert validate_symbol_component("_") is True

        # Double underscore is valid
        assert validate_symbol_component("__") is True

        # Mix of letters, numbers, underscores
        assert validate_symbol_component("_test_123_ABC") is True

        # Very long but valid identifier
        long_name = "a" * 100 + "_" * 50 + "1" * 50
        assert validate_symbol_component(long_name) is True

        # Tab character (invalid)
        assert validate_symbol_component("test\ttab") is False

        # Newline character (invalid)
        assert validate_symbol_component("test\nnewline") is False

    def test_classify_symbol_type_all_branches(self) -> None:
        """Test all branches of classify_symbol_type for full coverage."""
        # Magic methods - various forms
        assert classify_symbol_type(["Cls", "__len__"]) == "magic_method"
        assert classify_symbol_type(["Cls", "__call__"]) == "magic_method"
        assert classify_symbol_type(["Cls", "__getitem__"]) == "magic_method"

        # Private members - various forms
        assert classify_symbol_type(["Cls", "_single_underscore"]) == "private_member"
        assert classify_symbol_type(["Cls", "_123"]) == "private_member"

        # Class members with different first letters
        assert classify_symbol_type(["ABC", "method"]) == "class_member"
        assert classify_symbol_type(["Z", "method"]) == "class_member"

        # Module functions with different first letters
        assert classify_symbol_type(["abc", "func"]) == "module_function"
        assert classify_symbol_type(["z", "func"]) == "module_function"
        assert classify_symbol_type(["_private_module", "func"]) == "module_function"

        # Qualified members with various depths
        assert classify_symbol_type(["a", "b", "c"]) == "qualified_member"
        assert classify_symbol_type(["pkg", "mod", "cls", "meth"]) == "qualified_member"
        assert classify_symbol_type(["x", "y", "z", "w", "v"]) == "qualified_member"

        # Single component edge cases
        assert classify_symbol_type(["A"]) == "simple_member"
        assert classify_symbol_type(["_"]) == "private_member"  # Single underscore is private
        assert classify_symbol_type(["abc123"]) == "simple_member"

    def test_get_parent_and_member_various_depths(self) -> None:
        """Test parent/member splitting with various component depths."""
        # Maximum practical depth
        deep_components = ["a", "b", "c", "d", "e", "f", "g", "h"]
        parent, member = get_parent_and_member(deep_components)
        assert parent == "a.b.c.d.e.f.g"
        assert member == "h"

        # With underscores and numbers
        components = ["module_1", "Class2", "method_3"]
        parent, member = get_parent_and_member(components)
        assert parent == "module_1.Class2"
        assert member == "method_3"
