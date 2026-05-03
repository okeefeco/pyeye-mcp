"""Tests for the Handle type — canonical Python dotted-name identity for symbols."""

import pytest

from pyeye.handle import Handle

# ---------------------------------------------------------------------------
# (a) Creation from valid dotted names
# ---------------------------------------------------------------------------


class TestHandleCreation:
    """Handle accepts any well-formed Python dotted name."""

    def test_simple_module(self) -> None:
        h = Handle("mymodule")
        assert str(h) == "mymodule"

    def test_dotted_module(self) -> None:
        h = Handle("a.b.c")
        assert str(h) == "a.b.c"

    def test_class_in_module(self) -> None:
        h = Handle("a.b.c.MyClass")
        assert str(h) == "a.b.c.MyClass"

    def test_method_handle(self) -> None:
        h = Handle("a.b.c.MyClass.method")
        assert str(h) == "a.b.c.MyClass.method"

    def test_dunder_method_valid(self) -> None:
        """Dunder names like __init__ are valid Python identifiers."""
        h = Handle("pkg.module.MyClass.__init__")
        assert str(h) == "pkg.module.MyClass.__init__"

    def test_dunder_component_in_middle(self) -> None:
        h = Handle("a.__b__.c")
        assert str(h) == "a.__b__.c"

    def test_private_member(self) -> None:
        h = Handle("mymod._private_func")
        assert str(h) == "mymod._private_func"

    def test_single_identifier(self) -> None:
        h = Handle("toplevel")
        assert str(h) == "toplevel"


# ---------------------------------------------------------------------------
# (b) Rejection of invalid forms
# ---------------------------------------------------------------------------


class TestHandleRejection:
    """Handle rejects malformed inputs with ValueError."""

    def test_empty_string(self) -> None:
        with pytest.raises(ValueError):
            Handle("")

    def test_leading_dot(self) -> None:
        with pytest.raises(ValueError):
            Handle(".a.b")

    def test_trailing_dot(self) -> None:
        with pytest.raises(ValueError):
            Handle("a.b.")

    def test_double_dot(self) -> None:
        with pytest.raises(ValueError):
            Handle("a..b")

    def test_spaces(self) -> None:
        with pytest.raises(ValueError):
            Handle("a.b c.d")

    def test_space_only(self) -> None:
        with pytest.raises(ValueError):
            Handle("   ")

    def test_numeric_start(self) -> None:
        """Component starting with a digit is not a valid Python identifier."""
        with pytest.raises(ValueError):
            Handle("1invalid.module")

    def test_hyphen_in_component(self) -> None:
        with pytest.raises(ValueError):
            Handle("a.bad-name.c")


# ---------------------------------------------------------------------------
# (c) Equality is string equality
# ---------------------------------------------------------------------------


class TestHandleEquality:
    """Two handles with the same dotted name are equal; equality works like str."""

    def test_equal_handles(self) -> None:
        assert Handle("a.b.c") == Handle("a.b.c")

    def test_unequal_handles(self) -> None:
        assert Handle("a.b.c") != Handle("a.b.d")

    def test_equal_to_plain_string(self) -> None:
        """Handle equality with its underlying string value."""
        h = Handle("a.b.c")
        assert h == "a.b.c"

    def test_not_equal_to_different_string(self) -> None:
        h = Handle("a.b.c")
        assert h != "x.y.z"

    def test_hashable_same_as_str(self) -> None:
        """Handle should be usable as a dict key and compare equal to same str key."""
        h = Handle("pkg.mod.Cls")
        d = {h: "value"}
        assert d["pkg.mod.Cls"] == "value"


# ---------------------------------------------------------------------------
# (d) Serialization round-trip: handle → dict → handle
# ---------------------------------------------------------------------------


class TestHandleSerialization:
    """Handle serializes to a dict and can be reconstructed from it."""

    def test_to_dict(self) -> None:
        h = Handle("a.b.MyClass")
        d = h.to_dict()
        assert d == {"handle": "a.b.MyClass"}

    def test_from_dict(self) -> None:
        d = {"handle": "a.b.MyClass"}
        h = Handle.from_dict(d)
        assert h == Handle("a.b.MyClass")

    def test_round_trip(self) -> None:
        original = Handle("x.y.z.Foo.bar")
        reconstructed = Handle.from_dict(original.to_dict())
        assert original == reconstructed

    def test_from_dict_invalid_raises(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            Handle.from_dict({"handle": "bad..handle"})


# ---------------------------------------------------------------------------
# (e) Handle from path components
# ---------------------------------------------------------------------------


class TestHandleFromParts:
    """Handle.from_parts joins a sequence of name segments with dots."""

    def test_from_parts_two(self) -> None:
        h = Handle.from_parts(["mypackage", "mymodule"])
        assert h == Handle("mypackage.mymodule")

    def test_from_parts_many(self) -> None:
        h = Handle.from_parts(["a", "b", "c", "MyClass", "method"])
        assert h == Handle("a.b.c.MyClass.method")

    def test_from_parts_single(self) -> None:
        h = Handle.from_parts(["toplevel"])
        assert h == Handle("toplevel")

    def test_from_parts_invalid_component(self) -> None:
        with pytest.raises(ValueError):
            Handle.from_parts(["a", "bad name", "c"])

    def test_from_parts_empty_list(self) -> None:
        with pytest.raises(ValueError):
            Handle.from_parts([])
