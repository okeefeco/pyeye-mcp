"""Tests for contextual type resolution in type hints.

Type annotations should resolve via the file's import chain (script.goto),
not via global search (_search_all_scopes). When a file imports Status from
enums, a type annotation 'Status' should resolve to enums.Status — not to
ambiguous.Status which happens to have the same name.

These tests verify that _build_type_ref uses contextual resolution when
file context is available.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.lookup import lookup

_FIXTURE = Path(__file__).parent / "fixtures" / "lookup_project"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURE))


class TestAttributeTypeResolvesContextually:
    """Attribute type hints should resolve via the file's imports."""

    @pytest.mark.asyncio
    async def test_status_attribute_resolves_to_enum(self) -> None:
        """StatusTracker.current: Status should resolve to enums.Status,
        not ambiguous.Status."""
        result = await lookup(
            identifier="StatusTracker",
            project_path=str(_FIXTURE),
        )
        assert result.get("type") == "class", f"Expected class, got: {result}"

        # Find the 'current' attribute
        attrs = result.get("attributes", [])
        current_attr = next((a for a in attrs if a["name"] == "current"), None)
        assert current_attr is not None, f"Expected 'current' attribute, got: {attrs}"

        type_hint = current_attr.get("type_hint")
        assert type_hint is not None, "Expected type_hint for 'current'"

        # If it's a complex type (ClassVar, etc.), check inner_types
        if "inner_types" in type_hint:
            inner = type_hint["inner_types"]
            assert len(inner) > 0, f"Expected inner_types, got: {type_hint}"
            resolved = inner[0]
        else:
            resolved = type_hint

        # Must resolve to enums.Status, not ambiguous.Status
        assert (
            resolved.get("file") is not None
        ), f"Status type should resolve to a file, got: {resolved}"
        assert (
            "enums" in resolved["file"]
        ), f"Status should resolve to enums module, not: {resolved['file']}"


class TestParameterTypeResolvesContextually:
    """Parameter type hints should resolve via the file's imports."""

    @pytest.mark.asyncio
    async def test_status_param_resolves_to_enum(self) -> None:
        """StatusTracker.update(new_status: Status) should resolve Status
        to enums.Status, not ambiguous.Status."""
        result = await lookup(
            identifier="StatusTracker",
            project_path=str(_FIXTURE),
        )
        assert result.get("type") == "class"

        # Find the 'update' method
        methods = result.get("methods", [])
        update_method = next((m for m in methods if m["name"] == "update"), None)
        assert update_method is not None, f"Expected 'update' method, got: {methods}"

        # Find the 'new_status' parameter
        params = update_method.get("parameters", [])
        status_param = next((p for p in params if p["name"] == "new_status"), None)
        assert status_param is not None, f"Expected 'new_status' param, got: {params}"

        type_hint = status_param.get("type_hint")
        assert type_hint is not None, "Expected type_hint for new_status"

        # Must resolve to enums.Status
        assert (
            type_hint.get("file") is not None
        ), f"Status param type should resolve to a file, got: {type_hint}"
        assert (
            "enums" in type_hint["file"]
        ), f"Status param should resolve to enums module, not: {type_hint['file']}"


class TestReturnTypeResolvesContextually:
    """Return type annotations should resolve via the file's imports."""

    @pytest.mark.asyncio
    async def test_return_type_resolves_to_correct_class(self) -> None:
        """ServiceManager.get_config() -> ServiceConfig should resolve to
        the ServiceConfig in this file, not any other class."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(_FIXTURE),
        )
        assert result.get("type") == "class"

        methods = result.get("methods", [])
        get_config = next((m for m in methods if m["name"] == "get_config"), None)
        assert get_config is not None

        return_type = get_config.get("return_type")
        assert return_type is not None, "Expected return_type for get_config"
        assert (
            return_type.get("file") is not None
        ), f"Return type should resolve to a file, got: {return_type}"
        assert (
            "models" in return_type["file"]
        ), f"Return type should resolve to models module, got: {return_type['file']}"
