"""Test data factories for consistent test data generation."""

import json
import random
import string
from pathlib import Path
from typing import Any


class ProjectFactory:
    """Factory for creating test Python projects."""

    @staticmethod
    def create(
        root: Path,
        name: str = "test_project",
        modules: int = 5,
        classes_per_module: int = 2,
        methods_per_class: int = 3,
        with_tests: bool = False,
        with_config: bool = True,
    ) -> Path:
        """Create a test Python project.

        Args:
            root: Root directory for the project
            name: Project name
            modules: Number of modules to create
            classes_per_module: Classes per module
            methods_per_class: Methods per class
            with_tests: Include test files
            with_config: Include configuration files

        Returns:
            Path to created project
        """
        project_dir = root / name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create src directory
        src_dir = project_dir / "src" / name.replace("-", "_")
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").write_text('"""Test project package."""')

        # Create modules
        for i in range(modules):
            module_content = f'"""Module {i} in {name}."""\n\n'

            # Add imports
            if i > 0:
                module_content += f"from .module_{i-1} import Class_{i-1}_0\n\n"

            # Add classes
            for j in range(classes_per_module):
                module_content += f"""
class Class_{i}_{j}:
    \"\"\"Class {j} in module {i}.\"\"\"

    def __init__(self):
        \"\"\"Initialize class.\"\"\"
        self.value = {i * 10 + j}
"""

                # Add methods
                for k in range(methods_per_class):
                    module_content += f"""
    def method_{k}(self, arg: str = "default") -> str:
        \"\"\"Method {k} in class.\"\"\"
        return f"{{arg}}_{{self.value}}_{k}"
"""

            # Add functions
            module_content += f"""
def function_{i}(param: int = 0) -> int:
    \"\"\"Function in module {i}.\"\"\"
    return param + {i}

def helper_{i}() -> str:
    \"\"\"Helper function.\"\"\"
    return "helper_{i}"

# Module constants
CONSTANT_{i} = "value_{i}"
CONFIG_{i} = {{"key": "value_{i}"}}
"""

            (src_dir / f"module_{i}.py").write_text(module_content)

        # Create test directory if requested
        if with_tests:
            test_dir = project_dir / "tests"
            test_dir.mkdir()
            (test_dir / "__init__.py").write_text("")

            for i in range(min(3, modules)):
                test_content = f"""\"\"\"Tests for module_{i}.\"\"\"

import pytest
from src.{name.replace("-", "_")}.module_{i} import Class_{i}_0, function_{i}

class TestClass_{i}_0:
    \"\"\"Test Class_{i}_0.\"\"\"

    def test_init(self):
        \"\"\"Test initialization.\"\"\"
        obj = Class_{i}_0()
        assert obj.value == {i * 10}

    def test_method_0(self):
        \"\"\"Test method_0.\"\"\"
        obj = Class_{i}_0()
        result = obj.method_0("test")
        assert "test" in result

def test_function_{i}():
    \"\"\"Test function_{i}.\"\"\"
    result = function_{i}(10)
    assert result == {10 + i}
"""
                (test_dir / f"test_module_{i}.py").write_text(test_content)

        # Create configuration files if requested
        if with_config:
            # pyproject.toml
            pyproject_content = f"""[project]
name = "{name}"
version = "0.1.0"
description = "Test project for testing"

[tool.pycodemcp]
packages = []
cache_ttl = 300
"""
            (project_dir / "pyproject.toml").write_text(pyproject_content)

            # .pycodemcp.json
            config_content = {"project_name": name, "packages": [], "namespaces": {}}
            (project_dir / ".pycodemcp.json").write_text(json.dumps(config_content, indent=2))

        return project_dir

    @staticmethod
    def create_minimal(root: Path, name: str = "minimal_project") -> Path:
        """Create minimal project with single module."""
        return ProjectFactory.create(root, name, modules=1, classes_per_module=1)

    @staticmethod
    def create_large(root: Path, name: str = "large_project") -> Path:
        """Create large project for performance testing."""
        return ProjectFactory.create(
            root, name, modules=50, classes_per_module=5, methods_per_class=10, with_tests=True
        )


class FileFactory:
    """Factory for creating test files."""

    @staticmethod
    def create_python_file(
        path: Path,
        classes: list[str] = None,
        functions: list[str] = None,
        imports: list[str] = None,
    ) -> Path:
        """Create a Python file with specified content.

        Args:
            path: File path
            classes: List of class names to create
            functions: List of function names to create
            imports: List of import statements

        Returns:
            Path to created file
        """
        content = '"""Test file."""\n\n'

        # Add imports
        if imports:
            for imp in imports:
                content += f"{imp}\n"
            content += "\n"

        # Add classes
        if classes:
            for cls in classes:
                content += f"""
class {cls}:
    \"\"\"Test class {cls}.\"\"\"

    def __init__(self):
        \"\"\"Initialize.\"\"\"
        self.name = "{cls}"

    def method(self) -> str:
        \"\"\"Test method.\"\"\"
        return self.name
"""

        # Add functions
        if functions:
            for func in functions:
                content += f"""
def {func}(arg: Any = None) -> str:
    \"\"\"Test function {func}.\"\"\"
    return f"{func}_{{arg}}"
"""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path


class ConfigFactory:
    """Factory for creating configuration files."""

    @staticmethod
    def create_pyeye_config(
        path: Path,
        packages: list[str] = None,
        namespaces: dict[str, list[str]] = None,
        cache_ttl: int = 300,
        max_projects: int = 10,
    ) -> Path:
        """Create .pycodemcp.json configuration file.

        Args:
            path: Path to config file
            packages: List of package paths
            namespaces: Namespace configuration
            cache_ttl: Cache TTL in seconds
            max_projects: Maximum number of projects

        Returns:
            Path to created config file
        """
        config = {
            "packages": packages or [],
            "namespaces": namespaces or {},
            "cache_ttl": cache_ttl,
            "max_projects": max_projects,
            "settings": {"auto_update": True, "fuzzy_search": True},
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2))
        return path

    @staticmethod
    def create_pyproject_config(
        path: Path,
        project_name: str = "test-project",
        version: str = "0.1.0",
        dependencies: list[str] = None,
    ) -> Path:
        """Create pyproject.toml configuration.

        Args:
            path: Path to pyproject.toml
            project_name: Project name
            version: Project version
            dependencies: List of dependencies

        Returns:
            Path to created file
        """
        content = f"""[project]
name = "{project_name}"
version = "{version}"
description = "Test project"
requires-python = ">=3.10"
"""

        if dependencies:
            content += "\ndependencies = [\n"
            for dep in dependencies:
                content += f'    "{dep}",\n'
            content += "]\n"

        content += """
[tool.pycodemcp]
cache_ttl = 300
max_projects = 10
"""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path


class CacheFactory:
    """Factory for creating test cache instances."""

    @staticmethod
    def create_populated_cache(cache_dir: Path, entries: int = 100) -> dict[str, Any]:
        """Create a populated cache for testing.

        Args:
            cache_dir: Cache directory
            entries: Number of cache entries

        Returns:
            Dictionary of cache entries
        """
        cache_data = {}

        for i in range(entries):
            key = f"key_{i}"
            value = {
                "data": f"value_{i}",
                "timestamp": 1234567890 + i,
                "metadata": {
                    "type": random.choice(["symbol", "reference", "definition"]),
                    "project": f"project_{i % 5}",
                },
            }
            cache_data[key] = value

        # Save to cache directory
        cache_file = cache_dir / "cache.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache_data, indent=2))

        return cache_data


class SymbolFactory:
    """Factory for creating test symbols."""

    @staticmethod
    def create_symbol(
        name: str = None,
        symbol_type: str = "class",
        file: str = "test.py",
        line: int = 10,
        column: int = 0,
    ) -> dict[str, Any]:
        """Create a test symbol.

        Args:
            name: Symbol name (auto-generated if None)
            symbol_type: Type of symbol (class, function, variable)
            file: File path
            line: Line number
            column: Column number

        Returns:
            Symbol dictionary
        """
        if name is None:
            name = f"Test{''.join(random.choices(string.ascii_uppercase, k=5))}"

        return {
            "name": name,
            "type": symbol_type,
            "file": file,
            "line": line,
            "column": column,
            "docstring": f"Test {symbol_type} {name}",
            "signature": f"{name}()" if symbol_type == "function" else None,
            "module": file.replace(".py", "").replace("/", "."),
        }

    @staticmethod
    def create_symbols(count: int = 10) -> list[dict[str, Any]]:
        """Create multiple test symbols.

        Args:
            count: Number of symbols to create

        Returns:
            List of symbol dictionaries
        """
        symbols = []
        types = ["class", "function", "variable", "method"]

        for i in range(count):
            symbols.append(
                SymbolFactory.create_symbol(
                    name=f"Symbol_{i}",
                    symbol_type=types[i % len(types)],
                    file=f"module_{i // 5}.py",
                    line=10 + i * 5,
                    column=0 if i % 2 == 0 else 4,
                )
            )

        return symbols


class NamespacePackageFactory:
    """Factory for creating namespace packages."""

    @staticmethod
    def create(
        root: Path, namespace: str, packages: list[str], modules_per_package: int = 3
    ) -> dict[str, Path]:
        """Create a namespace package structure.

        Args:
            root: Root directory
            namespace: Namespace (e.g., "company.lib")
            packages: Package names (e.g., ["auth", "api", "utils"])
            modules_per_package: Modules per package

        Returns:
            Dictionary mapping package names to paths
        """
        namespace_parts = namespace.split(".")
        created_packages = {}

        for package in packages:
            # Create package directory
            pkg_path = root / package
            current = pkg_path

            # Create namespace structure
            for part in namespace_parts:
                current = current / part
                current.mkdir(parents=True, exist_ok=True)
                init_file = current / "__init__.py"
                init_file.write_text(
                    '__path__ = __import__("pkgutil").extend_path(__path__, __name__)\n'
                )

            # Create package modules
            pkg_dir = current / package
            pkg_dir.mkdir(exist_ok=True)
            (pkg_dir / "__init__.py").write_text(f'"""Package {package}."""')

            for i in range(modules_per_package):
                module_content = f"""\"\"\"Module {i} in {package}.\"\"\"

class {package.title()}Class_{i}:
    \"\"\"Class in {package}.\"\"\"

    def method(self) -> str:
        \"\"\"Method in class.\"\"\"
        return "{package}_{i}"

def {package}_function_{i}() -> str:
    \"\"\"Function in {package}.\"\"\"
    return "{package}_func_{i}"
"""
                (pkg_dir / f"module_{i}.py").write_text(module_content)

            created_packages[package] = pkg_path

        return created_packages
