"""Tests for contextual type resolution in type hints.

Type annotations must resolve via the file's import chain (``script.goto``),
not via global search (``_search_all_scopes``).  The fixture is built to make
that distinction observable: ``lookup_project.models`` imports ``Status`` from
``lookup_project.enums``, and ``lookup_project.ambiguous`` defines an unrelated
class with the same name.  A global search would happily return either one; a
contextual resolution can only return ``enums.Status``.

These tests assert on the canonical ``handle`` rather than a file-path
substring, so a regression that resolved to the wrong same-named class would
fail loudly instead of coincidentally matching a path fragment.

Historical note: this file previously exercised the same guarantee through the
legacy ``lookup()`` entry point, removed in #505.  The parameter and return-type
halves port directly onto ``inspect``.  The third case — the same guarantee on a
*class attribute* annotation — has no ``inspect`` equivalent yet, because
``inspect`` on an attribute handle currently returns a degraded
``scope: "external"`` node with an empty location (#506).  That assertion is
deliberately absent rather than weakened; restore it when #506 lands.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect as inspect_impl

_FIXTURE = Path(__file__).parent / "fixtures" / "lookup_project"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURE))


class TestParameterTypeResolvesContextually:
    """Parameter type hints resolve via the file's imports."""

    @pytest.mark.asyncio
    async def test_status_param_resolves_to_enum_not_same_named_class(
        self, analyzer: JediAnalyzer
    ) -> None:
        """``StatusTracker.update(new_status: Status)`` must resolve ``Status``
        to ``lookup_project.enums.Status``, never ``lookup_project.ambiguous.Status``."""
        node = await inspect_impl("lookup_project.models.StatusTracker.update", analyzer)

        params = node.get("parameters", [])
        status_param = next((p for p in params if p["name"] == "new_status"), None)
        assert status_param is not None, f"Expected 'new_status' param, got: {params}"

        type_ref = status_param.get("type")
        assert type_ref is not None, f"Expected a type for new_status, got: {status_param}"
        assert type_ref.get("raw") == "Status"
        assert type_ref.get("handle") == "lookup_project.enums.Status", (
            "Status must resolve through the importing file's chain, not by global "
            f"name search; got: {type_ref}"
        )


class TestReturnTypeResolvesContextually:
    """Return type annotations resolve via the file's imports."""

    @pytest.mark.asyncio
    async def test_return_type_resolves_to_correct_class(self, analyzer: JediAnalyzer) -> None:
        """``ServiceManager.get_config() -> ServiceConfig`` must resolve to the
        ``ServiceConfig`` reachable from this file."""
        node = await inspect_impl("lookup_project.models.ServiceManager.get_config", analyzer)

        return_type = node.get("return_type")
        assert return_type is not None, f"Expected return_type for get_config, got: {node}"
        assert return_type.get("raw") == "ServiceConfig"
        assert (
            return_type.get("handle") == "lookup_project.models.ServiceConfig"
        ), f"Return type resolved to the wrong symbol: {return_type}"
