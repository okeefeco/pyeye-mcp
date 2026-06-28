"""Tests for find_symbol searching across configured packages and namespaces.

These tests verify that find_symbol (and related methods) correctly search
across all configured scopes — not just the main project. This addresses
issue #306 where find_symbol only searched the main Jedi project.

Test categories:
1. find_symbol across additional packages
2. find_symbol across namespace packages
3. find_symbol with scope parameter
4. find_symbol with dotted import paths (replaces find_in_namespace)
5. get_call_hierarchy across packages
6. Compound symbol across packages
"""

import tempfile
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


@pytest.fixture
def cross_project_setup():
    """Create a multi-project structure with additional packages and namespaces.

    Layout:
        root/
        ├── main_project/
        │   ├── __init__.py
        │   ├── app.py          # imports from lib and namespace packages
        │   └── models.py       # local models
        ├── shared_lib/
        │   ├── __init__.py
        │   └── utils.py        # SharedHelper class, shared_func function
        ├── company-auth/
        │   └── company/
        │       └── auth/
        │           ├── __init__.py
        │           └── models.py   # AuthUser class
        └── company-api/
            └── company/
                └── api/
                    ├── __init__.py
                    └── endpoints.py  # APIEndpoint class, handle_request function
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Main project
        main = root / "main_project"
        main.mkdir()
        (main / "__init__.py").write_text("")
        (main / "models.py").write_text("""
class LocalModel:
    '''A model defined in the main project.'''
    def save(self):
        pass
""")
        (main / "app.py").write_text("""
from main_project.models import LocalModel

def run_app():
    '''Main application entry point.'''
    model = LocalModel()
    model.save()
""")

        # Shared library (additional package)
        shared = root / "shared_lib"
        shared.mkdir()
        (shared / "__init__.py").write_text("")
        (shared / "utils.py").write_text("""
class SharedHelper:
    '''Helper class in shared library.'''
    def assist(self):
        pass

def shared_func():
    '''A function in the shared library.'''
    helper = SharedHelper()
    helper.assist()
    return helper
""")

        # Namespace package: company-auth repo
        auth_repo = root / "company-auth"
        auth_repo.mkdir()
        auth_ns = auth_repo / "company" / "auth"
        auth_ns.mkdir(parents=True)
        (auth_ns / "__init__.py").write_text("")
        (auth_ns / "models.py").write_text("""
class AuthUser:
    '''User model from auth namespace package.'''
    def authenticate(self):
        pass

class AuthToken:
    '''Token model from auth namespace package.'''
    pass
""")

        # Namespace package: company-api repo
        api_repo = root / "company-api"
        api_repo.mkdir()
        api_ns = api_repo / "company" / "api"
        api_ns.mkdir(parents=True)
        (api_ns / "__init__.py").write_text("")
        (api_ns / "endpoints.py").write_text("""
class APIEndpoint:
    '''Endpoint class from API namespace package.'''
    def handle(self):
        pass

def handle_request():
    '''Process an incoming request.'''
    endpoint = APIEndpoint()
    endpoint.handle()
""")

        yield {
            "root": root,
            "main": main,
            "shared": shared,
            "auth_repo": auth_repo,
            "api_repo": api_repo,
        }


def _make_analyzer(setup) -> JediAnalyzer:
    """Create a JediAnalyzer configured with additional packages and namespaces."""
    analyzer = JediAnalyzer(str(setup["main"]))
    analyzer.set_additional_paths([setup["shared"]])
    analyzer.set_namespace_paths({"company": [str(setup["auth_repo"]), str(setup["api_repo"])]})
    return analyzer


class TestFindSymbolAcrossPackages:
    """Test find_symbol searching across configured additional packages."""

    @pytest.mark.asyncio
    async def test_finds_symbol_in_main_project(self, cross_project_setup):
        """Baseline: find_symbol should find symbols in the main project."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("LocalModel")

        names = [r["name"] for r in results]
        assert "LocalModel" in names

    @pytest.mark.asyncio
    async def test_finds_symbol_in_additional_package(self, cross_project_setup):
        """find_symbol should find symbols defined in configured additional packages."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("SharedHelper")

        names = [r["name"] for r in results]
        assert "SharedHelper" in names, (
            f"SharedHelper not found in additional package. "
            f"Got results: {[r['name'] for r in results]}"
        )
        # full_name must match what the old per-path Jedi project produced
        # (rooted at the additional path): the package dir is the sys.path root,
        # so utils.py is module ``utils``.
        full_names = {r["full_name"] for r in results}
        assert "utils.SharedHelper" in full_names, full_names

    @pytest.mark.asyncio
    async def test_finds_function_in_additional_package(self, cross_project_setup):
        """find_symbol should find functions defined in configured additional packages."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("shared_func")

        names = [r["name"] for r in results]
        assert "shared_func" in names, (
            f"shared_func not found in additional package. "
            f"Got results: {[r['name'] for r in results]}"
        )


class TestAdditionalPackageModuleNaming:
    """The additional-package module name belongs in ``_index_module_name`` (the
    name-index namer), NOT in the shared ``_get_import_path_for_file`` — so the
    #457 name index gets the right ``full_name`` without silently changing that
    shared helper's contract for its other callers (``find_importers`` /
    ``resolve`` / ``lookup``), which kept returning ``None`` for these files.
    """

    def test_get_import_path_for_file_does_not_map_additional_files(self, cross_project_setup):
        analyzer = _make_analyzer(cross_project_setup)
        utils = cross_project_setup["shared"] / "utils.py"
        # Shared helper's pre-name-index contract: it does not resolve
        # additional-package files (that is _index_module_name's job).
        assert analyzer._get_import_path_for_file(utils) is None

    def test_index_module_name_maps_additional_package_file(self, cross_project_setup):
        analyzer = _make_analyzer(cross_project_setup)
        utils = cross_project_setup["shared"] / "utils.py"
        # The name index still gets the importable module name (sys.path root is
        # the additional path itself), matching old Jedi: utils, not None.
        assert analyzer._index_module_name(utils) == "utils"


class TestFindSymbolAcrossNamespaces:
    """Test find_symbol searching across configured namespace packages."""

    @pytest.mark.asyncio
    async def test_finds_class_in_namespace_package(self, cross_project_setup):
        """find_symbol should find classes in configured namespace packages."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("AuthUser")

        names = [r["name"] for r in results]
        assert "AuthUser" in names, (
            f"AuthUser not found in namespace package company-auth. "
            f"Got results: {[r['name'] for r in results]}"
        )

    @pytest.mark.asyncio
    async def test_namespace_symbol_full_name_equals_importable_name(self, cross_project_setup):
        """A namespace def's full_name from the AST name-index must equal its
        importable dotted name — the same name Jedi reported for the old
        ``project.search`` path (#457, Task 1 risk).

        ``company-auth/company/auth/models.py`` is imported as
        ``company.auth.models`` (see tests/conftest.py). The name-index composes
        full_name from the file's module name, so a namespace prefix applied on
        top of a repo-root-relative path that *already* contains it yields the
        unimportable ``company.company.auth.models`` — a silent regression the
        name-only assertions above could not catch.
        """
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("AuthUser")
        full_names = {r["full_name"] for r in results}

        assert "company.auth.models.AuthUser" in full_names, full_names
        # No double-prefixed, unimportable handle.
        assert not any(fn.startswith("company.company") for fn in full_names), full_names

    @pytest.mark.asyncio
    async def test_finds_class_in_different_namespace_repo(self, cross_project_setup):
        """find_symbol should find classes across different repos in the same namespace."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("APIEndpoint")

        names = [r["name"] for r in results]
        assert "APIEndpoint" in names, (
            f"APIEndpoint not found in namespace package company-api. "
            f"Got results: {[r['name'] for r in results]}"
        )

    @pytest.mark.asyncio
    async def test_finds_function_in_namespace_package(self, cross_project_setup):
        """find_symbol should find functions in namespace packages."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("handle_request")

        names = [r["name"] for r in results]
        assert "handle_request" in names, (
            f"handle_request not found in namespace package. "
            f"Got results: {[r['name'] for r in results]}"
        )

    @pytest.mark.asyncio
    async def test_finds_symbols_from_both_main_and_namespace(self, cross_project_setup):
        """find_symbol should return results from main project AND namespaces."""
        analyzer = _make_analyzer(cross_project_setup)

        # Search for a symbol that only exists in main
        main_results = await analyzer.find_symbol("LocalModel")
        # Search for a symbol that only exists in namespace
        ns_results = await analyzer.find_symbol("AuthUser")

        assert len(main_results) > 0, "Should find LocalModel in main project"
        assert len(ns_results) > 0, "Should find AuthUser in namespace"


class TestFindSymbolWithScope:
    """Test find_symbol with explicit scope parameter to control search breadth."""

    @pytest.mark.asyncio
    async def test_scope_main_excludes_other_packages(self, cross_project_setup):
        """scope='main' should only search the main project."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("SharedHelper", scope="main")

        names = [r["name"] for r in results]
        assert "SharedHelper" not in names, "SharedHelper should NOT be found with scope='main'"

    @pytest.mark.asyncio
    async def test_scope_all_includes_everything(self, cross_project_setup):
        """scope='all' should search main + packages + namespaces."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("AuthUser", scope="all")

        names = [r["name"] for r in results]
        assert "AuthUser" in names, "AuthUser should be found with scope='all'"

    @pytest.mark.asyncio
    async def test_scope_namespace_searches_specific_namespace(self, cross_project_setup):
        """scope='namespace:company' should search only that namespace."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("AuthUser", scope="namespace:company")

        names = [r["name"] for r in results]
        assert "AuthUser" in names, "AuthUser should be found in namespace:company scope"

    @pytest.mark.asyncio
    async def test_scope_namespace_excludes_main(self, cross_project_setup):
        """scope='namespace:company' should NOT include main project results."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("LocalModel", scope="namespace:company")

        names = [r["name"] for r in results]
        assert (
            "LocalModel" not in names
        ), "LocalModel should NOT be found with scope='namespace:company'"

    @pytest.mark.asyncio
    async def test_default_scope_searches_all(self, cross_project_setup):
        """Default scope (None) should behave like scope='all'."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("SharedHelper")

        names = [r["name"] for r in results]
        assert "SharedHelper" in names, "SharedHelper should be found with default scope"


class TestFindSymbolDottedImportPath:
    """Test find_symbol with dotted import paths (replaces find_in_namespace)."""

    @pytest.mark.asyncio
    async def test_dotted_path_finds_class(self, cross_project_setup):
        """find_symbol('company.auth.models.AuthUser') should find the class."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("company.auth.models.AuthUser")

        assert len(results) > 0, "Should find AuthUser via dotted import path"
        assert results[0]["name"] == "AuthUser"

    @pytest.mark.asyncio
    async def test_dotted_path_finds_in_additional_package(self, cross_project_setup):
        """find_symbol('shared_lib.utils.SharedHelper') should find the class."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("shared_lib.utils.SharedHelper")

        assert (
            len(results) > 0
        ), "Should find SharedHelper via dotted import path in additional package"
        assert results[0]["name"] == "SharedHelper"


class TestGetCallHierarchyAcrossPackages:
    """Test get_call_hierarchy finding functions in additional/namespace packages."""

    @pytest.mark.asyncio
    async def test_finds_function_in_additional_package(self, cross_project_setup):
        """get_call_hierarchy should find functions defined in additional packages."""
        analyzer = _make_analyzer(cross_project_setup)

        result = await analyzer.get_call_hierarchy("shared_func")

        assert (
            "error" not in result
        ), f"get_call_hierarchy failed to find shared_func: {result.get('error')}"
        assert result["function"] == "shared_func"

    @pytest.mark.asyncio
    async def test_finds_function_in_namespace_package(self, cross_project_setup):
        """get_call_hierarchy should find functions defined in namespace packages."""
        analyzer = _make_analyzer(cross_project_setup)

        result = await analyzer.get_call_hierarchy("handle_request")

        assert (
            "error" not in result
        ), f"get_call_hierarchy failed to find handle_request: {result.get('error')}"
        assert result["function"] == "handle_request"


class TestCompoundSymbolAcrossPackages:
    """Test compound symbol search (Class.method) across packages."""

    @pytest.mark.asyncio
    async def test_compound_symbol_in_additional_package(self, cross_project_setup):
        """find_symbol('SharedHelper.assist') should find the method."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("SharedHelper.assist")

        assert len(results) > 0, "Should find SharedHelper.assist in additional package"
        assert any(r["name"] == "assist" for r in results)

    @pytest.mark.asyncio
    async def test_compound_symbol_in_namespace_package(self, cross_project_setup):
        """find_symbol('AuthUser.authenticate') should find the method."""
        analyzer = _make_analyzer(cross_project_setup)

        results = await analyzer.find_symbol("AuthUser.authenticate")

        assert len(results) > 0, "Should find AuthUser.authenticate in namespace package"
        assert any(r["name"] == "authenticate" for r in results)
