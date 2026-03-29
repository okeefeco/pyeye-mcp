"""Integration tests for lookup's project-config bridge (Task 3.5).

These tests verify that ``lookup`` works end-to-end with project configuration —
no prior ``configure_packages`` call required.  They exercise the full stack:

    lookup → server.get_analyzer → ProjectManager.get_analyzer
           → ProjectConfig → namespace_resolver / dependencies → Jedi
"""

from pathlib import Path

import pytest

from pyeye.mcp.lookup import lookup

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"

NAMESPACE_FIXTURE = FIXTURES / "lookup_namespace_project"
PYPROJECT_FIXTURE = FIXTURES / "lookup_pyproject_project"
PYRIGHT_FIXTURE = FIXTURES / "lookup_pyright_project"
BASIC_FIXTURE = FIXTURES / "lookup_project"


# ---------------------------------------------------------------------------
# TestProjectConfigBridgeIntegration
# ---------------------------------------------------------------------------


class TestProjectConfigBridgeIntegration:
    """lookup resolves symbols across config-declared namespaces/packages.

    These tests prove that the config bridge in ``ProjectManager.get_analyzer``
    applies namespace / package paths from ``.pyeye.json`` and ``pyproject.toml``
    *without* a prior ``configure_packages`` call.
    """

    @pytest.mark.asyncio
    async def test_lookup_pyeye_json_namespace_finds_sibling_class(self):
        """lookup resolves SiblingClass via namespace declared in .pyeye.json.

        The namespace_fixture project has:
            .pyeye.json → {"namespaces": {"testns": ["../lookup_namespace_sibling"]}}

        SiblingClass lives in ``testns.sibling_module`` inside the sibling
        directory.  Without the config bridge the lookup would return a
        not-found response; with the bridge it must return a class result.
        """
        result = await lookup(
            identifier="SiblingClass",
            project_path=str(NAMESPACE_FIXTURE),
        )

        # Must not be a not-found response
        assert result.get("found") is not False, (
            f"Expected SiblingClass to be found via .pyeye.json namespace config, " f"got: {result}"
        )

        # Must resolve to a class
        assert (
            result.get("type") == "class"
        ), f"Expected type='class' for SiblingClass, got: {result}"
        assert result.get("name") == "SiblingClass", f"Expected name='SiblingClass', got: {result}"

    @pytest.mark.asyncio
    async def test_lookup_pyproject_toml_packages_finds_sibling_class(self):
        """lookup resolves SiblingClass via package path declared in pyproject.toml.

        The pyproject_fixture project has:
            pyproject.toml → [tool.pyeye] packages = ["../lookup_namespace_sibling"]

        SiblingClass lives in ``testns.sibling_module`` inside the sibling
        directory, which is added as an additional search path via pyproject.toml.
        Without the config bridge the lookup would return a not-found response;
        with the bridge it must return a class result.
        """
        result = await lookup(
            identifier="SiblingClass",
            project_path=str(PYPROJECT_FIXTURE),
        )

        # Must not be a not-found response
        assert result.get("found") is not False, (
            f"Expected SiblingClass to be found via pyproject.toml packages config, "
            f"got: {result}"
        )

        # Must resolve to a class
        assert (
            result.get("type") == "class"
        ), f"Expected type='class' for SiblingClass, got: {result}"
        assert result.get("name") == "SiblingClass", f"Expected name='SiblingClass', got: {result}"

    def test_jedi_core_project_sees_sibling_package_path(self):
        """Jedi's core project resolves sibling imports via added_sys_path.

        This validates that configured sibling package paths from pyproject.toml
        flow into the Jedi Project's added_sys_path — not just the secondary
        _search_all_scopes layer.  Without this, Jedi's internal symbol
        resolution (imports, goto-definition) can't cross project boundaries.

        The pyproject_fixture has:
            pyproject.toml → [tool.pyeye] packages = ["../lookup_namespace_sibling"]

        SiblingClass lives in ``testns.sibling_module`` inside the sibling dir.
        Jedi's Script.goto() on an import of SiblingClass must resolve it,
        proving the core project has visibility to the sibling package.
        """
        import jedi

        from pyeye.project_manager import ProjectManager

        pm = ProjectManager()
        analyzer = pm.get_analyzer(str(PYPROJECT_FIXTURE))

        # Use Jedi's Script API directly with the analyzer's project.
        # This proves the core Jedi project has the sibling in added_sys_path,
        # NOT just the secondary _search_all_scopes multi-path search.
        script = jedi.Script(
            "from testns.sibling_module import SiblingClass\n",
            project=analyzer.project,
        )
        names = script.goto(1, 40)

        assert len(names) > 0, (
            "Expected Jedi's core project to resolve SiblingClass import via "
            "added_sys_path, but goto() returned no results"
        )
        assert any("SiblingClass" in n.full_name for n in names), (
            f"Expected SiblingClass in goto results, got: " f"{[n.full_name for n in names]}"
        )

    @pytest.mark.asyncio
    async def test_lookup_no_config_file_resolves_local_symbol(self):
        """lookup works normally for a project with no config file.

        The basic_fixture project has no .pyeye.json or pyproject.toml.
        Jedi's default discovery must resolve ServiceManager from the local
        models.py without errors.
        """
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(BASIC_FIXTURE),
        )

        # Must not be an error
        assert "error" not in result, f"Unexpected error for local symbol lookup: {result}"

        # Must resolve to a class
        assert (
            result.get("type") == "class"
        ), f"Expected type='class' for ServiceManager, got: {result}"
        assert (
            result.get("name") == "ServiceManager"
        ), f"Expected name='ServiceManager', got: {result}"


class TestPyrightExtraPathsIntegration:
    """Test that [tool.pyright] extraPaths in pyproject.toml are picked up."""

    @pytest.mark.asyncio
    async def test_pyright_extra_paths_resolve_sibling_class(self):
        """lookup should find SiblingClass via pyright extraPaths.

        The pyright_fixture has pyproject.toml with:
            [tool.pyright]
            executionEnvironments = [
                { root = ".", extraPaths = ["../lookup_namespace_sibling"] }
            ]

        SiblingClass lives in lookup_namespace_sibling/testns/sibling_module.py.
        The extraPaths declaration should make it visible without a .pyeye.json.
        """
        result = await lookup(
            identifier="SiblingClass",
            project_path=str(PYRIGHT_FIXTURE),
        )

        assert result.get("type") == "class", (
            f"Expected SiblingClass to resolve as class via pyright extraPaths, " f"got: {result}"
        )
        assert result.get("name") == "SiblingClass"

    @pytest.mark.asyncio
    async def test_pyright_extra_paths_config_is_loaded(self):
        """Verify ProjectConfig reads [tool.pyright] extraPaths."""
        from pyeye.config import ProjectConfig

        config = ProjectConfig(str(PYRIGHT_FIXTURE))
        packages = config.get_package_paths()

        # Should include the sibling path from pyright extraPaths
        sibling = str((FIXTURES / "lookup_namespace_sibling").resolve())
        assert any(
            sibling in p for p in packages
        ), f"Expected pyright extraPaths to be in package_paths, got: {packages}"
