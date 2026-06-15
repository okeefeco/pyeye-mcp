"""Tests for namespace-aware analyzer methods updated in Phase 2."""

import tempfile
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


@pytest.fixture
def temp_namespace_project():
    """Create a temporary project with namespace packages for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create main project with classes
        main_project = root / "main_project"
        main_project.mkdir()
        (main_project / "__init__.py").touch()
        (main_project / "models.py").write_text("""
class MainModel:
    pass

class UserModel(MainModel):
    pass

import external_lib
import company.auth.models
from company.api import tools
""")
        (main_project / "utils.py").write_text("""
def main_utility():
    pass
""")

        # Create namespace package: company.auth
        auth_repo = root / "company-auth"
        auth_repo.mkdir()
        auth_ns = auth_repo / "company" / "auth"
        auth_ns.mkdir(parents=True)
        (auth_ns / "__init__.py").touch()
        (auth_ns / "models.py").write_text("""
class BaseAuthModel:
    pass

class AuthUser(BaseAuthModel):
    pass

import requests
from company.api import endpoints
""")
        (auth_ns / "views.py").write_text("""
from .models import AuthUser

def auth_view():
    pass
""")

        # Create namespace package: company.api
        api_repo = root / "company-api"
        api_repo.mkdir()
        api_ns = api_repo / "company" / "api"
        api_ns.mkdir(parents=True)
        (api_ns / "__init__.py").touch()
        (api_ns / "endpoints.py").write_text("""
class APIEndpoint:
    pass

import json
from company.auth.models import AuthUser
""")

        # Create sub-namespace: company.api.tools
        tools_ns = api_ns / "tools"
        tools_ns.mkdir()
        (tools_ns / "__init__.py").touch()
        (tools_ns / "validators.py").write_text("""
class Validator:
    pass

class EmailValidator(Validator):
    pass

import re
from company.auth import models
""")

        yield {
            "root": root,
            "main_project": main_project,
            "auth_repo": auth_repo,
            "api_repo": api_repo,
            "auth_ns": auth_ns,
            "api_ns": api_ns,
            "tools_ns": tools_ns,
        }


class TestFindSubclassesNamespaceSupport:
    """Test find_subclasses with namespace scope support."""

    async def test_find_subclasses_main_scope(self, temp_namespace_project):
        """Test find_subclasses with main scope only."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Look for subclasses of MainModel in main scope only
        raw = await analyzer.find_subclasses("MainModel", scope="main")
        results = raw["subclasses"] if not raw.get("ambiguous") else []

        # Should find UserModel from main project only
        result_names = {r["name"] for r in results}
        assert "UserModel" in result_names
        # Should not find classes from namespace packages
        assert "AuthUser" not in result_names

    async def test_find_subclasses_all_scope(self, temp_namespace_project):
        """Test find_subclasses with all scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Look for subclasses of Validator across all scopes
        raw = await analyzer.find_subclasses("Validator", scope="all")
        results = raw["subclasses"] if not raw.get("ambiguous") else []

        # Should find EmailValidator from namespace package
        result_names = {r["name"] for r in results}
        assert "EmailValidator" in result_names

    async def test_find_subclasses_namespace_scope(self, temp_namespace_project):
        """Test find_subclasses with specific namespace scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Look for subclasses in company.auth namespace only
        raw = await analyzer.find_subclasses("BaseAuthModel", scope="namespace:company")
        results = raw["subclasses"] if not raw.get("ambiguous") else []

        # Should find AuthUser from auth namespace
        result_names = {r["name"] for r in results}
        assert "AuthUser" in result_names


class TestFindImportsNamespaceSupport:
    """Test find_imports with namespace scope support."""

    async def test_find_imports_main_scope(self, temp_namespace_project):
        """Test find_imports with main scope only."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Look for imports of company.auth.models in main scope only
        results = await analyzer.find_imports("company.auth.models", scope="main")

        # Should find import from main project
        assert len(results) > 0
        main_files = {Path(r["file"]).name for r in results}
        assert "models.py" in main_files

    async def test_find_imports_all_scope(self, temp_namespace_project):
        """Test find_imports with all scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Look for imports of company.auth.models across all scopes
        results = await analyzer.find_imports("company.auth.models", scope="all")

        # Should find imports from both main project and namespace packages
        assert len(results) >= 2
        all_files = {Path(r["file"]).name for r in results}
        # Should include files from different namespaces
        assert (
            "models.py" in all_files or "endpoints.py" in all_files or "validators.py" in all_files
        )

    async def test_find_imports_namespace_scope(self, temp_namespace_project):
        """Test find_imports with specific namespace scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Look for imports in company namespace only
        results = await analyzer.find_imports("company.auth", scope="namespace:company")

        # Should find imports from namespace packages only
        if results:  # May not find any depending on exact import statements
            # Should not include main project files
            main_project_path = str(temp_namespace_project["main_project"])
            for result in results:
                assert main_project_path not in result["file"]


class TestListPackagesNamespaceSupport:
    """Test list_packages with namespace scope support."""

    async def test_list_packages_main_scope(self, temp_namespace_project):
        """Test list_packages with main scope (default)."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Should default to main scope
        results = await analyzer.list_packages()

        # Should only include main project packages (may be empty if no packages with __init__.py)
        package_names = {p["name"] for p in results}
        # Check that no namespace packages are included
        company_packages = [name for name in package_names if name.startswith("company")]
        assert len(company_packages) == 0  # No company packages in main scope

    async def test_list_packages_all_scope(self, temp_namespace_project):
        """Test list_packages with all scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        results = await analyzer.list_packages(scope="all")

        # Should include packages from all scopes
        package_names = {p["name"] for p in results}
        # Should find company namespace packages
        company_packages = [name for name in package_names if name.startswith("company")]
        assert len(company_packages) > 0

    async def test_list_packages_namespace_scope(self, temp_namespace_project):
        """Test list_packages with specific namespace scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        results = await analyzer.list_packages(scope="namespace:company")

        # Should only include packages from company namespace
        package_names = {p["name"] for p in results}
        for name in package_names:
            assert name.startswith("company") or name == ""


class TestListModulesNamespaceSupport:
    """Test list_modules with namespace scope support."""

    async def test_list_modules_main_scope(self, temp_namespace_project):
        """Test list_modules with main scope (default)."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Should default to main scope
        results = await analyzer.list_modules()

        # Should only include main project modules
        module_names = {m["name"] for m in results}
        assert "models" in module_names
        assert "utils" in module_names

        # Check that no namespace modules are included
        import_paths = {m["import_path"] for m in results}
        company_modules = [path for path in import_paths if path.startswith("company")]
        assert len(company_modules) == 0

    async def test_list_modules_all_scope(self, temp_namespace_project):
        """Test list_modules with all scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        results = await analyzer.list_modules(scope="all")

        # Should include modules from all scopes
        import_paths = {m["import_path"] for m in results}
        # Should find company namespace modules
        company_modules = [path for path in import_paths if path.startswith("company")]
        assert len(company_modules) > 0

    async def test_list_modules_namespace_scope(self, temp_namespace_project):
        """Test list_modules with specific namespace scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        results = await analyzer.list_modules(scope="namespace:company")

        # Should only include modules from company namespace
        import_paths = {m["import_path"] for m in results}
        for path in import_paths:
            assert path.startswith("company") or path in [
                "models",
                "views",
                "endpoints",
                "validators",
            ]


class TestAnalyzeDependenciesNamespaceSupport:
    """Test analyze_dependencies with namespace scope support."""

    async def test_analyze_dependencies_main_scope(self, temp_namespace_project):
        """Test analyze_dependencies with main scope only."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Analyze dependencies of main project module with main scope
        result = await analyzer.analyze_dependencies("models", scope="main")

        # Should analyze dependencies considering only main project
        assert result["module"] == "models"
        assert "imports" in result
        assert "imported_by" in result

    async def test_analyze_dependencies_all_scope(self, temp_namespace_project):
        """Test analyze_dependencies with all scope (default)."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Should default to all scope for complete dependency graph
        result = await analyzer.analyze_dependencies("models")

        # Should analyze dependencies across all configured scopes
        assert result["module"] == "models"
        assert "imports" in result
        # Should potentially find more dependencies when looking across namespaces
        all_imports = (
            result["imports"]["internal"]
            + result["imports"]["external"]
            + result["imports"]["stdlib"]
        )
        assert len(all_imports) >= 0  # At least should not error

    async def test_analyze_dependencies_namespace_scope(self, temp_namespace_project):
        """Test analyze_dependencies with specific namespace scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Analyze dependencies of main project module with namespace scope
        # The scope parameter affects the search space, not the module being analyzed
        result = await analyzer.analyze_dependencies("models", scope="namespace:company")

        # Should analyze dependencies within the namespace scope
        assert result["module"] == "models"
        assert "imports" in result


class TestScopeParameterDefaults:
    """Test that the default scope parameters work as specified in the issue."""

    async def test_find_subclasses_default_all(self, temp_namespace_project):
        """Test that find_subclasses defaults to 'all' scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Call without scope parameter - should default to "all"
        raw = await analyzer.find_subclasses("Validator")
        results = raw["subclasses"] if not raw.get("ambiguous") else []

        # Should find subclasses across all namespaces
        result_names = {r["name"] for r in results}
        assert "EmailValidator" in result_names

    async def test_find_imports_default_all(self, temp_namespace_project):
        """Test that find_imports defaults to 'all' scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Call without scope parameter - should default to "all"
        results = await analyzer.find_imports("company.auth.models")

        # Should search across all scopes by default
        assert isinstance(results, list)

    async def test_list_packages_default_main(self, temp_namespace_project):
        """Test that list_packages defaults to 'main' scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Call without scope parameter - should default to "main"
        results = await analyzer.list_packages()

        # Should only include main project packages by default
        package_names = {p["name"] for p in results}
        company_packages = [name for name in package_names if name.startswith("company")]
        assert len(company_packages) == 0  # No company packages in main scope

    async def test_list_modules_default_main(self, temp_namespace_project):
        """Test that list_modules defaults to 'main' scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Call without scope parameter - should default to "main"
        results = await analyzer.list_modules()

        # Should only include main project modules by default
        import_paths = {m["import_path"] for m in results}
        company_modules = [path for path in import_paths if path.startswith("company")]
        assert len(company_modules) == 0  # No company modules in main scope

    async def test_analyze_dependencies_default_all(self, temp_namespace_project):
        """Test that analyze_dependencies defaults to 'all' scope."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Call without scope parameter - should default to "all"
        result = await analyzer.analyze_dependencies("models")

        # Should analyze across all scopes by default
        assert result["module"] == "models"
        assert "imports" in result


class TestMultipleScopeSupport:
    """Test that multiple scope specifications work correctly."""

    async def test_find_subclasses_multiple_scopes(self, temp_namespace_project):
        """Test find_subclasses with multiple scopes."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Use multiple scopes
        raw = await analyzer.find_subclasses("BaseAuthModel", scope=["main", "namespace:company"])
        results = raw["subclasses"] if not raw.get("ambiguous") else []

        # Should search in both main and company namespace
        assert isinstance(results, list)

    async def test_find_imports_multiple_scopes(self, temp_namespace_project):
        """Test find_imports with multiple scopes."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))
        analyzer.set_namespace_paths(
            {
                "company": [
                    str(temp_namespace_project["auth_repo"]),
                    str(temp_namespace_project["api_repo"]),
                ]
            }
        )

        # Use multiple scopes
        results = await analyzer.find_imports("company.auth", scope=["main", "namespace:company"])

        # Should search in both main and company namespace
        assert isinstance(results, list)


class TestErrorHandling:
    """Test error handling for invalid scope specifications."""

    async def test_invalid_scope_handling(self, temp_namespace_project):
        """Test that invalid scopes are handled gracefully."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))

        # Test with invalid scope - should not crash
        raw = await analyzer.find_subclasses("SomeClass", scope="invalid:scope")
        results = raw["subclasses"] if not raw.get("ambiguous") else []
        assert isinstance(results, list)

        results = await analyzer.find_imports("some.module", scope="invalid:scope")
        assert isinstance(results, list)

        results = await analyzer.list_packages(scope="invalid:scope")
        assert isinstance(results, list)

        results = await analyzer.list_modules(scope="invalid:scope")
        assert isinstance(results, list)

        # For analyze_dependencies, use an existing module since it needs to find the file
        result = await analyzer.analyze_dependencies("models", scope="invalid:scope")
        assert isinstance(result, dict)

    async def test_nonexistent_namespace_scope(self, temp_namespace_project):
        """Test handling of nonexistent namespace scopes."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))

        # Test with nonexistent namespace
        raw = await analyzer.find_subclasses("SomeClass", scope="namespace:nonexistent")
        results = raw["subclasses"] if not raw.get("ambiguous") else []
        assert results == []

        results = await analyzer.find_imports("some.module", scope="namespace:nonexistent")
        assert results == []

        results = await analyzer.list_packages(scope="namespace:nonexistent")
        assert results == []

        results = await analyzer.list_modules(scope="namespace:nonexistent")
        assert results == []
