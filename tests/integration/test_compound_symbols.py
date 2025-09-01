"""Integration tests for compound symbol support in find_symbol.

These tests verify the integration between the symbol parser, validation,
and Jedi analyzer for handling compound symbols like Model.__init__.

Tests follow the strategy defined in docs/testing/STRATEGY.md.
"""

from pathlib import Path

import pytest

from pycodemcp.exceptions import ValidationError
from pycodemcp.server import find_symbol


@pytest.mark.asyncio
class TestCompoundSymbols:
    """Integration tests for compound symbol support in find_symbol.

    These tests verify end-to-end functionality of finding compound symbols
    like Class.method or module.Class.method patterns.
    """

    async def test_find_class_init_method(self, tmp_path: Path) -> None:
        """Test finding __init__ method of specific class."""
        # Create test file with multiple classes
        test_file = tmp_path / "models.py"
        test_file.write_text(
            """
class User:
    def __init__(self, name: str):
        self.name = name

class Product:
    def __init__(self, id: int):
        self.id = id
"""
        )

        # This should find only User's __init__, not Product's
        result = await find_symbol("User.__init__", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "__init__"
        assert "User" in result[0]["full_name"]
        assert result[0]["type"] == "function"
        assert result[0]["line"] == 3  # Line where User.__init__ is defined

    async def test_find_class_instance_method(self, tmp_path: Path) -> None:
        """Test finding instance method of specific class."""
        test_file = tmp_path / "calculator.py"
        test_file.write_text(
            """
class Calculator:
    def add(self, a: int, b: int) -> int:
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b

class ScientificCalculator:
    def add(self, a: float, b: float) -> float:
        return a + b
"""
        )

        # Should find only Calculator.add, not ScientificCalculator.add
        result = await find_symbol("Calculator.add", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "add"
        assert "Calculator" in result[0]["full_name"]
        assert result[0]["line"] == 3

    async def test_find_module_class_method(self, tmp_path: Path) -> None:
        """Test finding method with module.Class.method pattern."""
        # Create module structure
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "__init__.py").touch()

        user_file = models_dir / "user.py"
        user_file.write_text(
            """
class User:
    def save(self) -> None:
        pass

    def delete(self) -> None:
        pass
"""
        )

        # Should find models.user.User.save
        result = await find_symbol("models.user.User.save", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "save"
        assert "User" in result[0]["full_name"]
        assert "models.user" in result[0]["full_name"]

    async def test_find_static_method(self, tmp_path: Path) -> None:
        """Test finding static method of a class."""
        test_file = tmp_path / "utils.py"
        test_file.write_text(
            """
class DateUtils:
    @staticmethod
    def format_date(date: str) -> str:
        return date.replace("-", "/")

    @staticmethod
    def parse_date(date: str) -> str:
        return date.replace("/", "-")

class StringUtils:
    @staticmethod
    def format_date(text: str) -> str:
        return text.upper()
"""
        )

        # Should find only DateUtils.format_date
        result = await find_symbol("DateUtils.format_date", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "format_date"
        assert "DateUtils" in result[0]["full_name"]
        assert result[0]["line"] == 4

    async def test_find_class_method(self, tmp_path: Path) -> None:
        """Test finding class method."""
        test_file = tmp_path / "factory.py"
        test_file.write_text(
            """
class UserFactory:
    @classmethod
    def create(cls, name: str):
        return cls(name)

    def __init__(self, name: str):
        self.name = name

class ProductFactory:
    @classmethod
    def create(cls, id: int):
        return cls(id)
"""
        )

        # Should find only UserFactory.create
        result = await find_symbol("UserFactory.create", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "create"
        assert "UserFactory" in result[0]["full_name"]

    async def test_find_property(self, tmp_path: Path) -> None:
        """Test finding property of a class."""
        test_file = tmp_path / "models.py"
        test_file.write_text(
            """
class User:
    def __init__(self, email: str):
        self._email = email

    @property
    def email(self) -> str:
        return self._email

    @email.setter
    def email(self, value: str) -> None:
        self._email = value

class Admin:
    @property
    def email(self) -> str:
        return "admin@example.com"
"""
        )

        # Should find only User.email property getter
        result = await find_symbol("User.email", project_path=str(tmp_path))

        # May return both getter and setter, but at least the getter
        assert len(result) >= 1
        assert any(r["name"] == "email" and "User" in r["full_name"] for r in result)

    async def test_find_nested_class_method(self, tmp_path: Path) -> None:
        """Test finding method in nested class."""
        test_file = tmp_path / "nested.py"
        test_file.write_text(
            """
class Outer:
    class Inner:
        def method(self) -> str:
            return "inner"

    def method(self) -> str:
        return "outer"
"""
        )

        # Should find Inner.method
        result = await find_symbol("Outer.Inner.method", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "method"
        assert "Inner" in result[0]["full_name"]

    async def test_backward_compatibility_simple_symbol(self, tmp_path: Path) -> None:
        """Test that simple symbols still work (backward compatibility)."""
        test_file = tmp_path / "simple.py"
        test_file.write_text(
            """
class SimpleClass:
    pass

def simple_function():
    pass
"""
        )

        # Simple class name should still work
        result = await find_symbol("SimpleClass", project_path=str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "SimpleClass"

        # Simple function name should still work
        result = await find_symbol("simple_function", project_path=str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "simple_function"

    async def test_invalid_compound_symbols(self, tmp_path: Path) -> None:
        """Test that invalid compound symbols raise appropriate errors."""
        # Double dots
        with pytest.raises(ValidationError, match="Invalid"):
            await find_symbol("Model..method", project_path=str(tmp_path))

        # Leading dot
        with pytest.raises(ValidationError, match="Invalid"):
            await find_symbol(".Model.method", project_path=str(tmp_path))

        # Trailing dot
        with pytest.raises(ValidationError, match="Invalid"):
            await find_symbol("Model.method.", project_path=str(tmp_path))

        # Empty component
        with pytest.raises(ValidationError, match="Invalid"):
            await find_symbol("Model..method", project_path=str(tmp_path))

    async def test_builtin_type_methods(self, tmp_path: Path) -> None:
        """Test finding methods of built-in types."""
        # This is a special case - built-ins might not be found by Jedi
        # but we should handle gracefully
        result = await find_symbol("str.__init__", project_path=str(tmp_path))

        # Either finds it or returns empty list (not an error)
        assert isinstance(result, list)
        if result:
            assert result[0]["name"] == "__init__"

    async def test_module_attribute(self, tmp_path: Path) -> None:
        """Test finding module-level attributes/functions."""
        # Create a module with submodule
        os_module = tmp_path / "myos"
        os_module.mkdir()
        (os_module / "__init__.py").touch()

        path_module = os_module / "path.py"
        path_module.write_text(
            """
def join(*paths):
    return "/".join(paths)

def split(path):
    return path.split("/")
"""
        )

        # Should find myos.path.join
        result = await find_symbol("myos.path.join", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "join"
        assert "myos.path" in result[0]["full_name"]

    async def test_async_method(self, tmp_path: Path) -> None:
        """Test finding async methods."""
        test_file = tmp_path / "client.py"
        test_file.write_text(
            """
class AsyncClient:
    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

class SyncClient:
    def connect(self) -> None:
        pass
"""
        )

        # Should find only AsyncClient.connect
        result = await find_symbol("AsyncClient.connect", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "connect"
        assert "AsyncClient" in result[0]["full_name"]

    async def test_method_not_found(self, tmp_path: Path) -> None:
        """Test behavior when compound symbol doesn't exist."""
        test_file = tmp_path / "models.py"
        test_file.write_text(
            """
class User:
    def save(self):
        pass
"""
        )

        # Non-existent method should return empty list
        result = await find_symbol("User.delete", project_path=str(tmp_path))
        assert result == []

        # Non-existent class should return empty list
        result = await find_symbol("NonExistent.method", project_path=str(tmp_path))
        assert result == []

    async def test_partial_match_not_returned(self, tmp_path: Path) -> None:
        """Test that partial matches are not returned for compound symbols."""
        test_file = tmp_path / "models.py"
        test_file.write_text(
            """
class User:
    def save(self):
        pass

    def save_async(self):
        pass

class UserProfile:
    def save(self):
        pass
"""
        )

        # Should find only User.save, not User.save_async or UserProfile.save
        result = await find_symbol("User.save", project_path=str(tmp_path))

        assert len(result) == 1
        assert result[0]["name"] == "save"
        assert result[0]["full_name"].endswith("User.save")
        # Ensure it's not save_async
        assert "save_async" not in result[0]["full_name"]
