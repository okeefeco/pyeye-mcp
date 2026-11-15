"""Tests for namespace package resolution."""

from pyeye.namespace_resolver import NamespaceResolver
from tests.test_helpers import assert_path_in_list


class TestNamespaceResolver:
    """Test the NamespaceResolver class."""

    def test_initialization(self):
        """Test namespace resolver initialization."""
        resolver = NamespaceResolver()

        assert isinstance(resolver.namespace_paths, dict)
        assert isinstance(resolver.package_cache, dict)
        assert len(resolver.namespace_paths) == 0
        assert len(resolver.package_cache) == 0

    def test_register_namespace(self, temp_project_dir):
        """Test registering namespace packages."""
        resolver = NamespaceResolver()

        # Create test directories
        path1 = temp_project_dir / "repo1"
        path2 = temp_project_dir / "repo2"
        path1.mkdir()
        path2.mkdir()

        resolver.register_namespace("company.auth", [str(path1), str(path2)])

        assert "company.auth" in resolver.namespace_paths
        assert len(resolver.namespace_paths["company.auth"]) == 2
        assert_path_in_list(path1, resolver.namespace_paths["company.auth"])
        assert_path_in_list(path2, resolver.namespace_paths["company.auth"])

    def test_register_namespace_nonexistent_paths(self, temp_project_dir, caplog):
        """Test registering namespace with non-existent paths."""
        resolver = NamespaceResolver()

        existing = temp_project_dir / "existing"
        existing.mkdir()

        resolver.register_namespace("test.namespace", [str(existing), "/nonexistent/path"])

        # Should only register existing path
        assert len(resolver.namespace_paths["test.namespace"]) == 1
        assert_path_in_list(existing, resolver.namespace_paths["test.namespace"])
        assert "does not exist" in caplog.text

    def test_multiple_namespace_registration(self, temp_project_dir):
        """Test registering multiple namespaces."""
        resolver = NamespaceResolver()

        # Create multiple namespace directories
        ns1 = temp_project_dir / "ns1"
        ns2 = temp_project_dir / "ns2"
        ns3 = temp_project_dir / "ns3"

        for ns in [ns1, ns2, ns3]:
            ns.mkdir()

        resolver.register_namespace("company.auth", [str(ns1)])
        resolver.register_namespace("company.api", [str(ns2)])
        resolver.register_namespace("company.utils", [str(ns3)])

        assert len(resolver.namespace_paths) == 3
        assert "company.auth" in resolver.namespace_paths
        assert "company.api" in resolver.namespace_paths
        assert "company.utils" in resolver.namespace_paths

    def test_circular_namespace_references(self, temp_project_dir):
        """Test handling circular references in namespace packages."""
        resolver = NamespaceResolver()

        # Create two repos with circular imports
        repo1 = temp_project_dir / "repo1"
        repo2 = temp_project_dir / "repo2"

        # Repo1 imports from repo2
        (repo1 / "company" / "module1").mkdir(parents=True)
        (repo1 / "company" / "module1" / "a.py").write_text("from company.module2 import b")

        # Repo2 imports from repo1
        (repo2 / "company" / "module2").mkdir(parents=True)
        (repo2 / "company" / "module2" / "b.py").write_text("from company.module1 import a")

        resolver.register_namespace("company", [str(repo1), str(repo2)])

        # Should handle circular references without issues
        assert "company" in resolver.namespace_paths
        assert len(resolver.namespace_paths["company"]) == 2
