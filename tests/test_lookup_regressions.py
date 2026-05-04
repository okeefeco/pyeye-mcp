"""Regression tests for five real-world issues found in AAC testing.

Each test reproduces one specific issue and verifies the fix.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.lookup import lookup

_FIXTURE = Path(__file__).parent / "fixtures" / "lookup_project"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# Issue 1: ClassVar unwrapping returns "ClassVar" as name instead of
# resolving the inner type.
# ---------------------------------------------------------------------------


class TestClassVarUnwrapping:
    """ClassVar[X] should resolve X as navigable inner_type, and the top-level
    name should reflect the full original annotation while inner_types
    provides the resolved navigable references."""

    @pytest.mark.asyncio
    async def test_classvar_inner_type_resolved(self, analyzer: JediAnalyzer) -> None:
        """ClassVar[ServiceConfig] inner_types should resolve ServiceConfig."""
        ref = await analyzer._build_type_ref("ClassVar[ServiceConfig]")
        assert ref is not None
        inner = ref.get("inner_types", [])
        assert len(inner) == 1
        assert inner[0]["name"] == "ServiceConfig"
        # Must be resolved — not partial
        assert inner[0]["file"] is not None
        assert inner[0]["line"] is not None

    @pytest.mark.asyncio
    async def test_classvar_optional_nested_resolves(self, analyzer: JediAnalyzer) -> None:
        """ClassVar[Optional[ServiceConfig]] should unwrap to ServiceConfig."""
        ref = await analyzer._build_type_ref("ClassVar[Optional[ServiceConfig]]")
        assert ref is not None
        inner = ref.get("inner_types", [])
        assert len(inner) == 1
        assert inner[0]["name"] == "ServiceConfig"
        assert inner[0]["file"] is not None


# ---------------------------------------------------------------------------
# Issue 2: bases resolves to wrong class — search_all_scopes for a common
# name like "ServiceManager" might find the wrong one if multiple projects
# are indexed.
# ---------------------------------------------------------------------------


class TestBasesResolution:
    """Base class resolution must find the correct class in the same project,
    not a similarly-named class from another package."""

    @pytest.mark.asyncio
    async def test_bases_resolve_to_correct_project(self) -> None:
        """ExtendedManager(ServiceManager) should resolve ServiceManager from
        the same project, not from an unrelated package."""
        result = await lookup(
            identifier="ExtendedManager",
            project_path=str(_FIXTURE),
        )
        assert result.get("type") == "class", f"Expected class, got: {result}"
        bases = result.get("bases", [])
        assert len(bases) > 0, f"Expected at least one base class, got: {bases}"

        # The base should be ServiceManager from THIS project
        sm_base = bases[0]
        assert sm_base["name"] == "ServiceManager", f"Wrong base: {sm_base}"
        # full_name should include the lookup_project package
        assert sm_base["full_name"] is not None
        assert "ServiceManager" in sm_base["full_name"]
        # File should be in the lookup_project fixture
        assert sm_base["file"] is not None
        assert (
            "lookup_project" in sm_base["file"]
        ), f"Base class file should be in lookup_project, got: {sm_base['file']}"


# ---------------------------------------------------------------------------
# Issue 3: module.full_name is truncated — returns "models" instead of
# "lookup_project.models".
# ---------------------------------------------------------------------------


class TestModuleFullName:
    """The module field on class/function results must include the full
    dotted path including the top-level package name."""

    @pytest.mark.asyncio
    async def test_module_full_name_includes_package(self) -> None:
        """module.full_name for ServiceManager should be 'lookup_project.models',
        not just 'models'."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(_FIXTURE),
        )
        assert result.get("type") == "class"
        module_ref = result.get("module", {})
        full_name = module_ref.get("full_name", "")
        assert "lookup_project" in full_name, (
            f"module.full_name should include top-level package 'lookup_project', "
            f"got: {full_name!r}"
        )

    @pytest.mark.asyncio
    async def test_class_full_name_includes_package(self) -> None:
        """The class's own full_name should also include the package prefix."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(_FIXTURE),
        )
        full_name = result.get("full_name", "")
        assert (
            "lookup_project" in full_name
        ), f"Class full_name should include 'lookup_project', got: {full_name!r}"


# ---------------------------------------------------------------------------
# Issue 4: references items are missing the namespace prefix on full_name.
# ---------------------------------------------------------------------------


class TestReferenceFullNames:
    """Reference full_name fields must include the full dotted path including
    the top-level package/namespace prefix."""

    @pytest.mark.asyncio
    async def test_reference_full_names_include_package(self) -> None:
        """References to ServiceManager should have full_name including
        'lookup_project', not just 'client.ServiceManager'."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(_FIXTURE),
        )
        refs = result.get("references", {}).get("items", [])
        # We need at least one reference (from client.py)
        assert len(refs) > 0, "Expected at least one reference"
        for ref in refs:
            fn = ref.get("full_name", "")
            assert fn is not None, f"Reference full_name should not be None: {ref}"
            # Each full_name should have the package prefix
            assert (
                "lookup_project" in fn
            ), f"Reference full_name should include 'lookup_project', got: {fn!r}"


# ---------------------------------------------------------------------------
# Issue 5: subclasses file paths are relative, not absolute.
# ---------------------------------------------------------------------------


class TestSubclassFilePaths:
    """Subclass file paths must be absolute POSIX paths, not relative."""

    @pytest.mark.asyncio
    async def test_subclass_file_paths_are_absolute(self) -> None:
        """Subclass file paths should be absolute."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(_FIXTURE),
        )
        subs = result.get("subclasses", {}).get("items", [])
        assert len(subs) > 0, "Expected at least one subclass (ExtendedManager)"
        for sub in subs:
            file_path = sub.get("file", "")
            assert file_path is not None
            assert Path(
                file_path
            ).is_absolute(), f"Subclass file path should be absolute, got: {file_path!r}"
