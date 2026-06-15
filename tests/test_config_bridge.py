"""Tests that demonstrate the config-bridge gap in ProjectManager.get_analyzer().

These tests verify that get_analyzer() bridges config from .pyeye.json /
pyproject.toml into the JediAnalyzer's namespace_paths and additional_paths.

Tests (a) and (b) are EXPECTED TO FAIL — they expose the bug where the
ProjectManager reads namespace/package config but never applies it to the
analyzer returned by get_analyzer().

Test (c) is expected to PASS — the fallback (no config file) works fine.
"""

from pathlib import Path

from pyeye.project_manager import ProjectManager

# Absolute path to the fixtures directory
FIXTURES = Path(__file__).parent / "fixtures"


class TestConfigBridge:
    """Expose the gap between ProjectConfig loading and JediAnalyzer configuration."""

    def test_pyeye_json_namespaces_applied_to_analyzer(self):
        """(a) Namespaces declared in .pyeye.json must appear in analyzer.namespace_paths.

        This test is EXPECTED TO FAIL.

        get_analyzer() creates a ProjectConfig that successfully reads the
        namespaces section from .pyeye.json, but it never calls
        analyzer.set_namespace_paths() with that data.  The analyzer's
        namespace_paths therefore stays as an empty dict, and cross-namespace
        symbol lookup silently returns nothing.
        """
        fixture_path = FIXTURES / "lookup_namespace_project"
        manager = ProjectManager()

        analyzer = manager.get_analyzer(str(fixture_path))

        # The config was loaded — sanity-check that the config object knows about namespaces
        assert analyzer.config is not None, "Analyzer should have a config attached"
        namespaces_from_config = analyzer.config.get_namespaces()
        assert (
            "testns" in namespaces_from_config
        ), f"Config should have loaded 'testns' namespace from .pyeye.json, got: {namespaces_from_config}"

        # This is the assertion that FAILS today: the analyzer's namespace_paths
        # should be populated from the config but is not because no bridge exists.
        assert analyzer.namespace_paths, (
            "analyzer.namespace_paths must not be empty — the config bridge is missing: "
            "get_analyzer() reads namespaces from .pyeye.json via ProjectConfig but "
            "never calls analyzer.set_namespace_paths() with those values"
        )
        assert (
            "testns" in analyzer.namespace_paths
        ), f"'testns' namespace must be present in analyzer.namespace_paths, got: {analyzer.namespace_paths}"

    def test_pyproject_toml_packages_applied_to_analyzer(self):
        """(b) Packages declared in pyproject.toml must appear in analyzer.additional_paths.

        This test is EXPECTED TO FAIL.

        get_analyzer() checks self.dependencies[path_key] but that dict is only
        populated by configure_packages() — it is never seeded from the config
        file.  So for a freshly-constructed ProjectManager the additional_paths
        on the returned analyzer is always empty even when pyproject.toml lists
        extra packages.
        """
        fixture_path = FIXTURES / "lookup_pyproject_project"
        manager = ProjectManager()

        analyzer = manager.get_analyzer(str(fixture_path))

        # Sanity-check: the config object must have read the packages entry
        assert analyzer.config is not None, "Analyzer should have a config attached"
        package_paths = analyzer.config.get_package_paths()
        # get_package_paths() always prepends the project itself; we need at
        # least one *extra* path (the sibling declared in pyproject.toml)
        resolved_fixture = fixture_path.resolve()
        extra_paths = [p for p in package_paths if Path(p).resolve() != resolved_fixture]
        assert (
            extra_paths
        ), f"Config should have resolved packages from pyproject.toml, got only: {package_paths}"

        # This is the assertion that FAILS today: additional_paths is empty
        # because get_analyzer() only applies self.dependencies[path_key] which
        # is never populated from the config file.
        assert analyzer.additional_paths, (
            "analyzer.additional_paths must not be empty — the config bridge is missing: "
            "get_analyzer() reads packages from pyproject.toml via ProjectConfig but "
            "never calls analyzer.set_additional_paths() with those values"
        )

    def test_no_config_file_returns_working_analyzer(self, tmp_path):
        """(c) A directory with no config file should return a valid analyzer with empty paths.

        This test is EXPECTED TO PASS — fallback behaviour works correctly.
        """
        # Create a minimal Python project in tmp_path (no .pyeye.json / pyproject.toml)
        (tmp_path / "sample.py").write_text("x = 1\n")

        manager = ProjectManager()

        # Should not raise
        analyzer = manager.get_analyzer(str(tmp_path))

        assert analyzer is not None, "A valid analyzer must be returned even without config"
        assert (
            analyzer.namespace_paths == {}
        ), f"namespace_paths should be empty dict when no config, got: {analyzer.namespace_paths}"
        assert (
            analyzer.additional_paths == []
        ), f"additional_paths should be empty list when no config, got: {analyzer.additional_paths}"
