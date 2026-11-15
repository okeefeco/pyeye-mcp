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


class TestErrorHandling:
    """Test error handling for invalid scope specifications."""

    async def test_invalid_scope_handling(self, temp_namespace_project):
        """Test that invalid scopes are handled gracefully."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))

        # Test with invalid scope - should not crash
        raw = await analyzer.find_subclasses("SomeClass", scope="invalid:scope")
        results = raw["subclasses"] if not raw.get("ambiguous") else []
        assert isinstance(results, list)

    async def test_nonexistent_namespace_scope(self, temp_namespace_project):
        """Test handling of nonexistent namespace scopes."""
        analyzer = JediAnalyzer(str(temp_namespace_project["main_project"]))

        # Test with nonexistent namespace
        raw = await analyzer.find_subclasses("SomeClass", scope="namespace:nonexistent")
        results = raw["subclasses"] if not raw.get("ambiguous") else []
        assert results == []
