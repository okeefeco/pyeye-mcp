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
