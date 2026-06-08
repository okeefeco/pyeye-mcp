"""Integration tests for the expand MCP tool endpoint.

These tests exercise the MCP wrapper layer (server.py) end-to-end —
from the decorated function down through the operation into the fixture
project.  They verify:

1. The tool is registered (importable, callable, async).
2. The ``members`` edge returns a supported result with non-empty stubs over
   the wire for a known class.
3. The ``callees`` edge returns a supported result with non-empty stubs and
   ``unresolved_call_sites`` present as an int.
4. A deferred reference edge (``callers``) returns the unsupported branch with
   the correct ``reason`` and ``detail``, never raising.
5. Results are plain dicts (no custom types leak across the wire) and are
   JSON-serialisable.

Unit-level contract tests live in tests/unit/mcp/operations/test_expand.py.
These integration tests verify only the MCP wrapper layer delegation.
"""

from __future__ import annotations

import inspect as _inspect_stdlib
import json
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"

# ---------------------------------------------------------------------------
# Tool-registration assertions
# ---------------------------------------------------------------------------


class TestExpandToolRegistered:
    """Verify that expand is importable from pyeye.mcp.server and is callable."""

    def test_expand_is_importable(self) -> None:
        """expand can be imported from pyeye.mcp.server."""
        from pyeye.mcp.server import expand  # noqa: F401

    def test_expand_is_callable(self) -> None:
        """expand is a callable (decorated async function)."""
        from pyeye.mcp.server import expand

        assert callable(expand)

    def test_expand_is_async(self) -> None:
        """expand is an async function (or wrapped to behave as one)."""
        from pyeye.mcp.server import expand

        assert _inspect_stdlib.iscoroutinefunction(expand)


# ---------------------------------------------------------------------------
# End-to-end: members edge
# ---------------------------------------------------------------------------


class TestExpandMembersEndToEnd:
    """End-to-end tests for the ``members`` edge over the wire."""

    @pytest.mark.asyncio
    async def test_members_returns_supported_branch(self) -> None:
        """expand(Widget, 'members') returns the supported branch (no 'unsupported' key)."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="members",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "unsupported" not in result, (
            "supported result must not carry 'unsupported'; " f"got result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_members_has_required_fields(self) -> None:
        """expand(Widget, 'members') returns source/edge/stubs."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="members",
            project_path=str(_FIXTURE),
        )

        assert "source" in result, f"'source' missing from result: {result!r}"
        assert "edge" in result, f"'edge' missing from result: {result!r}"
        assert "stubs" in result, f"'stubs' missing from result: {result!r}"
        assert result["edge"] == "members"

    @pytest.mark.asyncio
    async def test_members_stubs_non_empty(self) -> None:
        """Widget has members — stubs must be a non-empty list."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="members",
            project_path=str(_FIXTURE),
        )

        stubs = result["stubs"]
        assert isinstance(stubs, list), f"stubs must be a list; got {type(stubs)!r}"
        assert len(stubs) > 0, "Widget has members — stubs must be non-empty"

    @pytest.mark.asyncio
    async def test_members_stubs_have_required_fields(self) -> None:
        """Each stub in the members result has handle/kind/scope/line_start/line_end."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="members",
            project_path=str(_FIXTURE),
        )

        for i, stub in enumerate(result["stubs"]):
            assert isinstance(stub, dict), f"stub[{i}] must be a plain dict; got {type(stub)!r}"
            for field in ("handle", "kind", "scope", "line_start", "line_end"):
                assert field in stub, f"stub[{i}] missing required field '{field}'; stub={stub!r}"

    @pytest.mark.asyncio
    async def test_members_no_unresolved_call_sites(self) -> None:
        """The members edge must NOT include 'unresolved_call_sites'."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="members",
            project_path=str(_FIXTURE),
        )

        assert "unresolved_call_sites" not in result, (
            "'unresolved_call_sites' must be absent for members edge; "
            f"got result keys: {list(result.keys())!r}"
        )

    @pytest.mark.asyncio
    async def test_members_result_is_json_serialisable(self) -> None:
        """The members result round-trips through json.dumps without error."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="members",
            project_path=str(_FIXTURE),
        )

        # Must not raise — ensures no custom types leak across the wire
        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)


# ---------------------------------------------------------------------------
# End-to-end: callees edge
# ---------------------------------------------------------------------------


class TestExpandCalleesEndToEnd:
    """End-to-end tests for the ``callees`` edge over the wire."""

    @pytest.mark.asyncio
    async def test_callees_returns_supported_branch(self) -> None:
        """expand(orchestrate, 'callees') returns the supported branch."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.callees_fixture.orchestrate",
            edge="callees",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "unsupported" not in result, (
            "supported result must not carry 'unsupported'; " f"got result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_callees_stubs_non_empty(self) -> None:
        """orchestrate calls make_widget and math.sqrt — stubs must be non-empty."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.callees_fixture.orchestrate",
            edge="callees",
            project_path=str(_FIXTURE),
        )

        stubs = result["stubs"]
        assert isinstance(stubs, list), f"stubs must be a list; got {type(stubs)!r}"
        assert (
            len(stubs) > 0
        ), "orchestrate calls make_widget and math.sqrt — stubs must be non-empty"

    @pytest.mark.asyncio
    async def test_callees_has_unresolved_call_sites(self) -> None:
        """The callees edge MUST include 'unresolved_call_sites' as an int."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.callees_fixture.orchestrate",
            edge="callees",
            project_path=str(_FIXTURE),
        )

        assert "unresolved_call_sites" in result, (
            "'unresolved_call_sites' must be present for callees edge; "
            f"got result keys: {list(result.keys())!r}"
        )
        assert isinstance(result["unresolved_call_sites"], int), (
            "'unresolved_call_sites' must be an int; "
            f"got {type(result['unresolved_call_sites'])!r}"
        )

    @pytest.mark.asyncio
    async def test_callees_stubs_have_required_fields(self) -> None:
        """Each callee stub has handle/kind/scope/line_start/line_end."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.callees_fixture.orchestrate",
            edge="callees",
            project_path=str(_FIXTURE),
        )

        for i, stub in enumerate(result["stubs"]):
            assert isinstance(stub, dict), f"stub[{i}] must be a plain dict; got {type(stub)!r}"
            for field in ("handle", "kind", "scope", "line_start", "line_end"):
                assert field in stub, f"stub[{i}] missing required field '{field}'; stub={stub!r}"

    @pytest.mark.asyncio
    async def test_callees_result_is_json_serialisable(self) -> None:
        """The callees result round-trips through json.dumps without error."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.callees_fixture.orchestrate",
            edge="callees",
            project_path=str(_FIXTURE),
        )

        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)


# ---------------------------------------------------------------------------
# End-to-end: deferred reference edge survives the wire
# ---------------------------------------------------------------------------


class TestExpandDeferredEdgeEndToEnd:
    """Verify that deferred reference edges return the unsupported branch, never raise."""

    @pytest.mark.asyncio
    async def test_callers_returns_unsupported_branch(self) -> None:
        """expand(Widget, 'callers') returns the unsupported branch (never raises)."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="callers",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert result.get("unsupported") is True, (
            "'unsupported' must be True for deferred reference edges; " f"got result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_callers_has_deferred_reference_backend_reason(self) -> None:
        """'callers' is a deferred reference edge — reason must be 'deferred_reference_backend'."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="callers",
            project_path=str(_FIXTURE),
        )

        assert (
            result["reason"] == "deferred_reference_backend"
        ), f"expected reason='deferred_reference_backend'; got {result.get('reason')!r}"

    @pytest.mark.asyncio
    async def test_callers_has_non_empty_detail(self) -> None:
        """The unsupported branch must include a non-empty 'detail' string."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="callers",
            project_path=str(_FIXTURE),
        )

        assert "detail" in result, f"'detail' missing from unsupported result: {result!r}"
        assert (
            isinstance(result["detail"], str) and len(result["detail"]) > 0
        ), f"'detail' must be a non-empty string; got {result.get('detail')!r}"

    @pytest.mark.asyncio
    async def test_callers_has_no_stubs(self) -> None:
        """The unsupported branch must NOT include 'stubs'."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="callers",
            project_path=str(_FIXTURE),
        )

        assert "stubs" not in result, (
            "'stubs' must be absent from unsupported branch; "
            f"got result keys: {list(result.keys())!r}"
        )

    @pytest.mark.asyncio
    async def test_callers_result_is_json_serialisable(self) -> None:
        """The unsupported branch round-trips through json.dumps without error."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="callers",
            project_path=str(_FIXTURE),
        )

        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)


# ---------------------------------------------------------------------------
# Plain-dict / serialisation-safety across all branches
# ---------------------------------------------------------------------------


class TestExpandPlainDictContract:
    """Verify that no custom types leak across the wire for any branch."""

    @pytest.mark.asyncio
    async def test_supported_result_is_plain_dict_with_plain_stubs(self) -> None:
        """All nested values in a supported result are plain Python primitives."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="members",
            project_path=str(_FIXTURE),
        )

        # Top-level must be plain dict
        assert (
            type(result) is dict
        ), (  # noqa: E721 — exact type check, not isinstance
            f"result must be exact dict (not subclass); got {type(result)!r}"
        )
        # Each stub must also be a plain dict
        for i, stub in enumerate(result["stubs"]):
            assert (
                type(stub) is dict
            ), f"stub[{i}] must be exact dict; got {type(stub)!r}"  # noqa: E721

    @pytest.mark.asyncio
    async def test_unsupported_result_is_plain_dict(self) -> None:
        """The unsupported branch result is an exact plain dict."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="callers",
            project_path=str(_FIXTURE),
        )

        assert (
            type(result) is dict
        ), f"unsupported result must be exact dict; got {type(result)!r}"  # noqa: E721
