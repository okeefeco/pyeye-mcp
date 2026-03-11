"""Tests for get_type_info with base classes and MRO functionality."""

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


class TestGetTypeInfoInheritance:
    """Test get_type_info enhancements for base classes and MRO."""

    @pytest.fixture
    async def analyzer(self, tmp_path):
        """Create a JediAnalyzer instance with a temp directory."""
        analyzer = JediAnalyzer(str(tmp_path))
        return analyzer

    @pytest.mark.asyncio
    async def test_get_type_info_simple_class(self, analyzer, tmp_path):
        """Test get_type_info for a simple class with no inheritance."""
        test_file = tmp_path / "simple.py"
        test_file.write_text(
            """
class SimpleClass:
    '''A simple class.'''
    def method(self):
        pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 2, 6)

        assert result["position"]["file"] == str(test_file)
        assert result["position"]["line"] == 2
        assert result["position"]["column"] == 6

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "SimpleClass"
        assert class_info["type"] == "class"
        assert "base_classes" in class_info
        assert "mro" in class_info

        # Simple class should have no explicit base classes
        assert class_info["base_classes"] == []
        # But MRO should include object
        assert "SimpleClass" in class_info["mro"][0]
        assert "builtins.object" in class_info["mro"]

    @pytest.mark.asyncio
    async def test_get_type_info_single_inheritance(self, analyzer, tmp_path):
        """Test get_type_info for a class with single inheritance."""
        test_file = tmp_path / "single_inherit.py"
        test_file.write_text(
            """
class BaseClass:
    '''Base class.'''
    pass

class DerivedClass(BaseClass):
    '''Derived class.'''
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 6, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "DerivedClass"
        assert class_info["type"] == "class"

        # Should have BaseClass as base
        assert len(class_info["base_classes"]) == 1
        assert "BaseClass" in class_info["base_classes"][0]

        # MRO should include DerivedClass, BaseClass, and object
        assert len(class_info["mro"]) >= 3
        assert "DerivedClass" in class_info["mro"][0]
        assert any("BaseClass" in item for item in class_info["mro"])
        assert "builtins.object" in class_info["mro"]

    @pytest.mark.asyncio
    async def test_get_type_info_multiple_inheritance(self, analyzer, tmp_path):
        """Test get_type_info for a class with multiple inheritance."""
        test_file = tmp_path / "multi_inherit.py"
        test_file.write_text(
            """
class BaseA:
    '''Base class A.'''
    pass

class BaseB:
    '''Base class B.'''
    pass

class MixinC:
    '''Mixin class C.'''
    pass

class DerivedClass(BaseA, BaseB, MixinC):
    '''Class with multiple inheritance.'''
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 14, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "DerivedClass"
        assert class_info["type"] == "class"

        # Should have all three base classes
        assert len(class_info["base_classes"]) == 3
        base_names = [base.split(".")[-1] for base in class_info["base_classes"]]
        assert "BaseA" in base_names
        assert "BaseB" in base_names
        assert "MixinC" in base_names

        # MRO should include all classes
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]
        assert "DerivedClass" in mro_names
        assert "BaseA" in mro_names
        assert "BaseB" in mro_names
        assert "MixinC" in mro_names
        assert "object" in mro_names

    @pytest.mark.asyncio
    async def test_get_type_info_builtin_inheritance(self, analyzer, tmp_path):
        """Test get_type_info for a class inheriting from builtins."""
        test_file = tmp_path / "builtin_inherit.py"
        test_file.write_text(
            """
class MyException(Exception):
    '''Custom exception.'''
    pass

class MyList(list):
    '''Custom list.'''
    pass
"""
        )

        # Test Exception subclass
        result = await analyzer.get_type_info(str(test_file), 2, 6)
        assert len(result["inferred_types"]) > 0
        exc_info = result["inferred_types"][0]

        assert exc_info["name"] == "MyException"
        assert exc_info["type"] == "class"
        assert len(exc_info["base_classes"]) == 1
        assert "Exception" in exc_info["base_classes"][0]

        # Test list subclass
        result = await analyzer.get_type_info(str(test_file), 6, 6)
        assert len(result["inferred_types"]) > 0
        list_info = result["inferred_types"][0]

        assert list_info["name"] == "MyList"
        assert list_info["type"] == "class"
        assert len(list_info["base_classes"]) == 1
        assert "list" in list_info["base_classes"][0]

    @pytest.mark.asyncio
    async def test_get_type_info_detailed_mode(self, analyzer, tmp_path):
        """Test get_type_info with detailed=True to include methods and attributes."""
        test_file = tmp_path / "detailed.py"
        test_file.write_text(
            """
class DetailedClass:
    '''A class with methods and attributes.'''

    class_var = 10

    def __init__(self):
        self.instance_var = 20

    def method1(self):
        '''First method.'''
        pass

    def method2(self, arg):
        '''Second method.'''
        return arg * 2

    @property
    def computed(self):
        '''A computed property.'''
        return self.instance_var * 2
"""
        )

        result = await analyzer.get_type_info(str(test_file), 2, 6, detailed=True)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "DetailedClass"
        assert class_info["type"] == "class"

        # Should have methods in detailed mode
        assert "methods" in class_info
        assert len(class_info["methods"]) >= 3  # __init__, method1, method2
        method_names = [m["name"] for m in class_info["methods"]]
        assert "__init__" in method_names
        assert "method1" in method_names
        assert "method2" in method_names

        # Should have attributes in detailed mode
        assert "attributes" in class_info
        # Note: class-level attributes might be detected

    @pytest.mark.asyncio
    async def test_get_type_info_not_on_class(self, analyzer, tmp_path):
        """Test get_type_info on non-class positions."""
        test_file = tmp_path / "mixed.py"
        test_file.write_text(
            """
def function():
    '''A function.'''
    pass

variable = 42

class MyClass:
    pass
"""
        )

        # Test on function
        result = await analyzer.get_type_info(str(test_file), 2, 4)
        assert len(result["inferred_types"]) > 0
        func_info = result["inferred_types"][0]
        assert func_info["type"] == "function"
        assert "base_classes" not in func_info  # Functions don't have base classes
        assert "mro" not in func_info

        # Test on variable
        result = await analyzer.get_type_info(str(test_file), 6, 0)
        if result["inferred_types"]:
            var_info = result["inferred_types"][0]
            assert "base_classes" not in var_info  # Variables don't have base classes
            assert "mro" not in var_info

    @pytest.mark.asyncio
    async def test_get_type_info_complex_mro(self, analyzer, tmp_path):
        """Test get_type_info with complex diamond inheritance."""
        test_file = tmp_path / "diamond.py"
        test_file.write_text(
            """
class A:
    pass

class B(A):
    pass

class C(A):
    pass

class D(B, C):
    '''Diamond inheritance.'''
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 11, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "D"
        assert class_info["type"] == "class"

        # Should have B and C as direct base classes
        assert len(class_info["base_classes"]) == 2
        base_names = [base.split(".")[-1] for base in class_info["base_classes"]]
        assert "B" in base_names
        assert "C" in base_names

        # MRO should follow Python's C3 linearization (simplified in our implementation)
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]
        assert mro_names[0] == "D"  # Class itself first
        assert "B" in mro_names
        assert "C" in mro_names
        assert "object" in mro_names

    @pytest.mark.asyncio
    async def test_get_type_info_imported_base(self, analyzer, tmp_path):
        """Test get_type_info with imported base classes."""
        # Create a module with base class
        base_file = tmp_path / "base_module.py"
        base_file.write_text(
            """
class BaseClass:
    '''Base class in another module.'''
    pass
"""
        )

        # Create main file with import
        test_file = tmp_path / "main.py"
        test_file.write_text(
            """
from base_module import BaseClass

class DerivedClass(BaseClass):
    '''Derived from imported base.'''
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 4, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "DerivedClass"
        assert class_info["type"] == "class"

        # Should have BaseClass as base (might include module path)
        assert len(class_info["base_classes"]) == 1
        assert "BaseClass" in class_info["base_classes"][0]

        # MRO should include both classes
        assert any("DerivedClass" in item for item in class_info["mro"])
        assert any("BaseClass" in item for item in class_info["mro"])

    @pytest.mark.asyncio
    async def test_get_type_info_metaclass(self, analyzer, tmp_path):
        """Test get_type_info with metaclass (edge case)."""
        test_file = tmp_path / "metaclass.py"
        test_file.write_text(
            """
class Meta(type):
    '''A metaclass.'''
    pass

class MyClass(metaclass=Meta):
    '''Class with metaclass.'''
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 6, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "MyClass"
        assert class_info["type"] == "class"

        # Metaclass shouldn't appear in base_classes (it's not inheritance)
        # But the class should still have an MRO
        assert "mro" in class_info
        assert any("MyClass" in item for item in class_info["mro"])

    @pytest.mark.asyncio
    async def test_get_type_info_abstract_base(self, analyzer, tmp_path):
        """Test get_type_info with ABC inheritance."""
        test_file = tmp_path / "abc_test.py"
        test_file.write_text(
            """
from abc import ABC, abstractmethod

class AbstractBase(ABC):
    @abstractmethod
    def do_something(self):
        pass

class ConcreteClass(AbstractBase):
    def do_something(self):
        return "done"
"""
        )

        result = await analyzer.get_type_info(str(test_file), 9, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "ConcreteClass"
        assert class_info["type"] == "class"

        # Should have AbstractBase as base
        assert len(class_info["base_classes"]) >= 1
        assert any("AbstractBase" in base for base in class_info["base_classes"])

        # MRO should include ABC chain
        assert any("ConcreteClass" in item for item in class_info["mro"])
        assert any("AbstractBase" in item for item in class_info["mro"])

    @pytest.mark.asyncio
    async def test_get_type_info_fully_qualified_base_no_import(self, analyzer, tmp_path):
        """Test get_type_info with fully-qualified base class name (NO import).

        This test reproduces issue #234 where inheritance detection fails when:
        - Base class is referenced with full module path
        - No explicit import statement for the base class
        - Pattern: class Derived(package.module.BaseClass):

        This is common in large codebases and namespace packages.
        """
        # Create package structure
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        # Create base class in separate module
        base_file = pkg / "base.py"
        base_file.write_text(
            """
class BaseClass:
    '''Base class in mypackage.base module.'''
    pass
"""
        )

        # Create derived class WITHOUT importing BaseClass
        # Using fully-qualified name instead
        derived_file = pkg / "derived.py"
        derived_file.write_text(
            """
class DerivedClass(mypackage.base.BaseClass):
    '''Derived using fully-qualified base name.'''
    pass
"""
        )

        result = await analyzer.get_type_info(str(derived_file), 2, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "DerivedClass"
        assert class_info["type"] == "class"

        # BUG: This currently FAILS because Jedi can't resolve mypackage.base.BaseClass
        # Expected: base_classes should contain "mypackage.base.BaseClass" or "BaseClass"
        # Actual: base_classes is [] (empty list)
        assert len(class_info["base_classes"]) == 1, (
            f"Expected 1 base class, got {len(class_info['base_classes'])}. "
            f"base_classes={class_info['base_classes']}"
        )
        assert "BaseClass" in class_info["base_classes"][0]

        # MRO should also include the base class
        assert any("DerivedClass" in item for item in class_info["mro"])
        assert any(
            "BaseClass" in item for item in class_info["mro"]
        ), f"BaseClass not in MRO. MRO={class_info['mro']}"

    @pytest.mark.asyncio
    async def test_get_type_info_deep_module_path(self, analyzer, tmp_path):
        """Test get_type_info with deeply nested module paths.

        This mimics the real-world aac-catalog pattern from issue #234:
        class service(aac.logical.patterns.common.components.iaas):

        Tests whether PyEye can handle multi-level dotted names in inheritance.
        """
        # Create deep package structure: a/b/c/d/base.py
        a = tmp_path / "a"
        a.mkdir()
        (a / "__init__.py").write_text("")

        b = a / "b"
        b.mkdir()
        (b / "__init__.py").write_text("")

        c = b / "c"
        c.mkdir()
        (c / "__init__.py").write_text("")

        d = c / "d"
        d.mkdir()
        (d / "__init__.py").write_text("")

        # Base class at a.b.c.d.base.BaseClass
        base_file = d / "base.py"
        base_file.write_text(
            """
class BaseClass:
    '''Base class deep in package hierarchy.'''
    pass
"""
        )

        # Derived class at a/other.py using full path
        derived_file = a / "other.py"
        derived_file.write_text(
            """
class DerivedClass(a.b.c.d.base.BaseClass):
    '''Derived from deeply nested base.'''
    pass
"""
        )

        result = await analyzer.get_type_info(str(derived_file), 2, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "DerivedClass"
        assert class_info["type"] == "class"

        # BUG: Fails with deep paths - Jedi can't resolve a.b.c.d.base.BaseClass
        assert len(class_info["base_classes"]) >= 1, (
            f"Expected at least 1 base class for deeply nested inheritance. "
            f"base_classes={class_info['base_classes']}"
        )
        assert any(
            "BaseClass" in base for base in class_info["base_classes"]
        ), f"BaseClass not found in base_classes={class_info['base_classes']}"

    @pytest.mark.asyncio
    async def test_get_type_info_cross_package_qualified_base(self, analyzer, tmp_path):
        """Test get_type_info when base class is in different package with qualified name.

        This tests the pattern:
        - pkg1/models.py has BaseModel
        - pkg2/derived.py has: class Derived(pkg1.models.BaseModel):
        - NO import statement in derived.py

        Common in microservices and multi-package projects.
        """
        # Create first package
        pkg1 = tmp_path / "pkg1"
        pkg1.mkdir()
        (pkg1 / "__init__.py").write_text("")

        base_file = pkg1 / "models.py"
        base_file.write_text(
            """
class BaseModel:
    '''Base model in pkg1.'''
    def save(self):
        pass
"""
        )

        # Create second package
        pkg2 = tmp_path / "pkg2"
        pkg2.mkdir()
        (pkg2 / "__init__.py").write_text("")

        # Derived class references base with full qualified name
        derived_file = pkg2 / "models.py"
        derived_file.write_text(
            """
class UserModel(pkg1.models.BaseModel):
    '''User model inheriting from pkg1.models.BaseModel.'''
    def __init__(self, username):
        self.username = username
"""
        )

        result = await analyzer.get_type_info(str(derived_file), 2, 6)

        assert len(result["inferred_types"]) > 0
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "UserModel"
        assert class_info["type"] == "class"

        # BUG: Cross-package qualified names fail to resolve
        assert len(class_info["base_classes"]) >= 1, (
            f"Expected base class from cross-package reference. "
            f"base_classes={class_info['base_classes']}"
        )
        assert any(
            "BaseModel" in base for base in class_info["base_classes"]
        ), f"BaseModel not in base_classes={class_info['base_classes']}"


class TestMROOrdering:
    """Test that MRO is computed with correct C3 linearization ordering."""

    @pytest.fixture
    async def analyzer(self, tmp_path):
        """Create a JediAnalyzer instance with a temp directory."""
        return JediAnalyzer(str(tmp_path))

    @pytest.mark.asyncio
    async def test_mro_diamond_inheritance_ordering(self, analyzer, tmp_path):
        """Test C3 linearization for diamond inheritance pattern.

        D(B, C) where B(A) and C(A) should produce:
        D -> B -> C -> A -> object (NOT D -> B -> A -> object -> C)
        """
        test_file = tmp_path / "diamond.py"
        test_file.write_text(
            """
class A:
    pass

class B(A):
    pass

class C(A):
    pass

class D(B, C):
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 11, 6)
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "D"
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]

        # Verify correct C3 linearization order
        assert mro_names == ["D", "B", "C", "A", "object"], (
            f"Diamond MRO ordering incorrect. Expected [D, B, C, A, object], " f"got {mro_names}"
        )

    @pytest.mark.asyncio
    async def test_mro_deep_chain_completeness(self, analyzer, tmp_path):
        """Test that MRO includes all intermediate classes in a deep chain.

        D -> C -> B -> A -> object (none should be skipped)
        """
        test_file = tmp_path / "deep_chain.py"
        test_file.write_text(
            """
class A:
    pass

class B(A):
    pass

class C(B):
    pass

class D(C):
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 11, 6)
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "D"
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]

        assert mro_names == ["D", "C", "B", "A", "object"], (
            f"Deep chain MRO incomplete. Expected [D, C, B, A, object], " f"got {mro_names}"
        )

    @pytest.mark.asyncio
    async def test_mro_with_abc_mixin(self, analyzer, tmp_path):
        """Test that ABC appears in MRO when used as a base class."""
        test_file = tmp_path / "abc_mixin.py"
        test_file.write_text(
            """
from abc import ABC

class Base(ABC):
    pass

class Derived(Base):
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 7, 6)
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "Derived"
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]

        assert "ABC" in mro_names, f"ABC missing from MRO. Got {mro_names}"
        # Verify ordering: Derived before Base before ABC before object
        assert mro_names.index("Derived") < mro_names.index("Base")
        assert mro_names.index("Base") < mro_names.index("ABC")
        assert mro_names.index("ABC") < mro_names.index("object")

    @pytest.mark.asyncio
    async def test_mro_complex_diamond_with_mixin(self, analyzer, tmp_path):
        """Test C3 linearization with a mixin added to a diamond.

        E(D, Mixin) where D(B, C), B(A), C(A)
        Should produce: E -> D -> B -> C -> A -> Mixin -> object
        """
        test_file = tmp_path / "complex_diamond.py"
        test_file.write_text(
            """
class A:
    pass

class B(A):
    pass

class C(A):
    pass

class D(B, C):
    pass

class Mixin:
    pass

class E(D, Mixin):
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 17, 6)
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "E"
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]

        assert mro_names == ["E", "D", "B", "C", "A", "Mixin", "object"], (
            f"Complex diamond MRO incorrect. "
            f"Expected [E, D, B, C, A, Mixin, object], got {mro_names}"
        )

    @pytest.mark.asyncio
    async def test_mro_multiple_independent_bases(self, analyzer, tmp_path):
        """Test MRO ordering with multiple independent base classes."""
        test_file = tmp_path / "multi_bases.py"
        test_file.write_text(
            """
class X:
    pass

class Y:
    pass

class Z:
    pass

class Child(X, Y, Z):
    pass
"""
        )

        result = await analyzer.get_type_info(str(test_file), 11, 6)
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "Child"
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]

        # With independent bases, order follows declaration order
        assert mro_names == ["Child", "X", "Y", "Z", "object"], (
            f"Multi-base MRO incorrect. Expected [Child, X, Y, Z, object], " f"got {mro_names}"
        )

    @pytest.mark.asyncio
    async def test_mro_cross_file_inheritance(self, analyzer, tmp_path):  # noqa: ARG002
        """Test MRO completeness when classes span multiple files."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        (pkg / "base.py").write_text(
            """
class Base:
    pass
"""
        )

        (pkg / "middle.py").write_text(
            """
from mypkg.base import Base

class Middle(Base):
    pass
"""
        )

        (pkg / "leaf.py").write_text(
            """
from mypkg.middle import Middle

class Leaf(Middle):
    pass
"""
        )

        # Re-create analyzer with tmp_path as project root
        cross_analyzer = JediAnalyzer(str(tmp_path))
        result = await cross_analyzer.get_type_info(str(pkg / "leaf.py"), 4, 6)
        class_info = result["inferred_types"][0]

        assert class_info["name"] == "Leaf"
        mro_names = [item.split(".")[-1] for item in class_info["mro"]]

        assert "Middle" in mro_names, f"Middle class missing from cross-file MRO. Got {mro_names}"
        assert "Base" in mro_names, f"Base class missing from cross-file MRO. Got {mro_names}"
        # Verify ordering
        assert mro_names.index("Leaf") < mro_names.index("Middle")
        assert mro_names.index("Middle") < mro_names.index("Base")
        assert mro_names.index("Base") < mro_names.index("object")


class TestC3Linearize:
    """Unit tests for the _c3_linearize static method."""

    def test_single_class_no_bases(self):
        """A class with no bases returns just itself."""
        result = JediAnalyzer._c3_linearize("A", {"A": []})
        assert result == ["A"]

    def test_single_class_not_in_map(self):
        """A class not in the bases map returns just itself."""
        result = JediAnalyzer._c3_linearize("A", {})
        assert result == ["A"]

    def test_simple_chain(self):
        """B(A) -> [B, A]."""
        bases_map = {"B": ["A"], "A": []}
        result = JediAnalyzer._c3_linearize("B", bases_map)
        assert result == ["B", "A"]

    def test_diamond(self):
        """D(B, C) where B(A), C(A) -> [D, B, C, A]."""
        bases_map = {"D": ["B", "C"], "B": ["A"], "C": ["A"], "A": []}
        result = JediAnalyzer._c3_linearize("D", bases_map)
        assert result == ["D", "B", "C", "A"]

    def test_deep_chain(self):
        """D(C), C(B), B(A) -> [D, C, B, A]."""
        bases_map = {"D": ["C"], "C": ["B"], "B": ["A"], "A": []}
        result = JediAnalyzer._c3_linearize("D", bases_map)
        assert result == ["D", "C", "B", "A"]

    def test_multiple_independent_bases(self):
        """C(A, B) where A and B are independent -> [C, A, B]."""
        bases_map = {"C": ["A", "B"], "A": [], "B": []}
        result = JediAnalyzer._c3_linearize("C", bases_map)
        assert result == ["C", "A", "B"]

    def test_complex_diamond_with_mixin(self):
        """E(D, M) where D(B, C), B(A), C(A) -> [E, D, B, C, A, M]."""
        bases_map = {
            "E": ["D", "M"],
            "D": ["B", "C"],
            "B": ["A"],
            "C": ["A"],
            "A": [],
            "M": [],
        }
        result = JediAnalyzer._c3_linearize("E", bases_map)
        assert result == ["E", "D", "B", "C", "A", "M"]

    def test_matches_python_mro(self):
        """Verify our C3 matches Python's actual MRO for a known case.

        Python's own example from the C3 linearization documentation.
        """
        # O = object
        # F(O), E(O), D(O), C(D, F), B(D, E), A(B, C)
        bases_map = {
            "A": ["B", "C"],
            "B": ["D", "E"],
            "C": ["D", "F"],
            "D": ["O"],
            "E": ["O"],
            "F": ["O"],
            "O": [],
        }
        result = JediAnalyzer._c3_linearize("A", bases_map)
        assert result == ["A", "B", "C", "D", "E", "F", "O"]
