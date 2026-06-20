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

#: Dedicated subclasses fixture project (#348): ``pkg.base.Animal`` has a known
#: project subclass closure of {Mammal (direct), Dog (indirect grandchild),
#: Lizard (non-importable root script)}; ``pkg.base.Loner`` is subclassed by
#: nobody (measured-empty class case); ``pkg.base`` is a module (non-class).
_SUBCLASSES_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "subclasses_edge"

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


# ---------------------------------------------------------------------------
# End-to-end: imported_by edge — module (supported) and non-module (unsupported)
# ---------------------------------------------------------------------------


class TestExpandImportedByModuleEndToEnd:
    """End-to-end tests for the ``imported_by`` edge on a MODULE handle over the wire.

    ``mypackage._core.widgets`` is a module that has known importers — the result
    must be the supported branch with non-empty stubs, each of kind ``"module"``.
    No ``unresolved_call_sites`` (``imported_by`` is an inbound scan, not callees).
    """

    @pytest.mark.asyncio
    async def test_imported_by_module_returns_supported_branch(self) -> None:
        """expand(widgets module, 'imported_by') returns the supported branch (no 'unsupported')."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "unsupported" not in result, (
            "supported result must not carry 'unsupported'; " f"got result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_imported_by_module_has_required_fields(self) -> None:
        """expand(widgets module, 'imported_by') returns source/edge/stubs."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert "source" in result, f"'source' missing from result: {result!r}"
        assert "edge" in result, f"'edge' missing from result: {result!r}"
        assert "stubs" in result, f"'stubs' missing from result: {result!r}"
        assert result["edge"] == "imported_by"

    @pytest.mark.asyncio
    async def test_imported_by_module_stubs_non_empty(self) -> None:
        """widgets has known importers — stubs must be a non-empty list."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        stubs = result["stubs"]
        assert isinstance(stubs, list), f"stubs must be a list; got {type(stubs)!r}"
        assert len(stubs) > 0, "widgets has known importers — stubs must be non-empty"

    @pytest.mark.asyncio
    async def test_imported_by_module_stubs_have_required_fields(self) -> None:
        """Each stub in the imported_by result has handle/kind/scope/line_start/line_end."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        for i, stub in enumerate(result["stubs"]):
            assert isinstance(stub, dict), f"stub[{i}] must be a plain dict; got {type(stub)!r}"
            for field in ("handle", "kind", "scope", "line_start", "line_end"):
                assert field in stub, f"stub[{i}] missing required field '{field}'; stub={stub!r}"

    @pytest.mark.asyncio
    async def test_imported_by_module_stubs_are_module_kind(self) -> None:
        """Each importer stub must have kind == 'module' (importers are always modules)."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        for i, stub in enumerate(result["stubs"]):
            assert stub["kind"] == "module", (
                f"stub[{i}] must have kind='module'; "
                f"got kind={stub.get('kind')!r}; stub={stub!r}"
            )

    @pytest.mark.asyncio
    async def test_imported_by_module_no_unresolved_call_sites(self) -> None:
        """imported_by must NOT include 'unresolved_call_sites' (callees-only field)."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert "unresolved_call_sites" not in result, (
            "'unresolved_call_sites' must be absent for imported_by edge; "
            f"got result keys: {list(result.keys())!r}"
        )

    @pytest.mark.asyncio
    async def test_imported_by_module_result_is_json_serialisable(self) -> None:
        """The imported_by module result round-trips through json.dumps without error."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        # Must not raise — ensures no custom types leak across the wire
        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)
        assert isinstance(roundtripped["stubs"], list)

    @pytest.mark.asyncio
    async def test_imported_by_module_result_is_plain_dict_with_plain_stubs(self) -> None:
        """All nested values in the supported imported_by result are plain Python primitives."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert (
            type(result) is dict
        ), f"result must be exact dict (not subclass); got {type(result)!r}"  # noqa: E721
        for i, stub in enumerate(result["stubs"]):
            assert (
                type(stub) is dict
            ), f"stub[{i}] must be exact dict; got {type(stub)!r}"  # noqa: E721


class TestExpandImportedByNonModuleEndToEnd:
    """End-to-end tests for the ``imported_by`` edge on a NON-MODULE handle over the wire.

    ``mypackage._core.widgets.Widget`` is a class — ``imported_by`` does not
    apply to non-module kinds.  The resolver returns ``None`` (the wrong-kind
    signal); ``expand`` must surface this as the unsupported branch with
    ``reason == "not_yet_implemented"``, not as an empty supported result
    (which would be the #332 measured-zero lie).
    """

    @pytest.mark.asyncio
    async def test_imported_by_non_module_returns_unsupported_branch(self) -> None:
        """expand(Widget class, 'imported_by') returns the unsupported branch."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert result.get("unsupported") is True, (
            "'unsupported' must be True for non-module imported_by; " f"got result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_imported_by_non_module_reason_is_not_yet_implemented(self) -> None:
        """Non-module imported_by reason must be 'not_yet_implemented'."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert (
            result["reason"] == "not_yet_implemented"
        ), f"expected reason='not_yet_implemented'; got {result.get('reason')!r}"

    @pytest.mark.asyncio
    async def test_imported_by_non_module_has_non_empty_detail(self) -> None:
        """The unsupported branch must include a non-empty 'detail' string."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert "detail" in result, f"'detail' missing from unsupported result: {result!r}"
        assert (
            isinstance(result["detail"], str) and len(result["detail"]) > 0
        ), f"'detail' must be a non-empty string; got {result.get('detail')!r}"

    @pytest.mark.asyncio
    async def test_imported_by_non_module_has_no_stubs(self) -> None:
        """The unsupported branch must NOT include 'stubs'."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert "stubs" not in result, (
            "'stubs' must be absent from unsupported branch; "
            f"got result keys: {list(result.keys())!r}"
        )

    @pytest.mark.asyncio
    async def test_imported_by_non_module_result_is_json_serialisable(self) -> None:
        """The unsupported branch round-trips through json.dumps without error."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)
        assert roundtripped.get("unsupported") is True

    @pytest.mark.asyncio
    async def test_imported_by_non_module_result_is_plain_dict(self) -> None:
        """The unsupported branch result is an exact plain dict."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="mypackage._core.widgets.Widget",
            edge="imported_by",
            project_path=str(_FIXTURE),
        )

        assert (
            type(result) is dict
        ), f"unsupported result must be exact dict; got {type(result)!r}"  # noqa: E721


# ---------------------------------------------------------------------------
# End-to-end: subclasses edge — class (supported, stubs) and non-class
# (supported, measured-empty stubs) over the wire
# ---------------------------------------------------------------------------


class TestExpandSubclassesClassEndToEnd:
    """End-to-end tests for the ``subclasses`` edge on a CLASS handle over the wire.

    ``pkg.base.Animal`` has a known project subclass closure — the result must be
    the supported branch with non-empty class stubs (direct + indirect, including
    the non-importable root script subclass).  No ``unresolved_call_sites``
    (``subclasses`` is a forward class-graph walk, not callees).
    """

    @pytest.mark.asyncio
    async def test_subclasses_class_returns_supported_branch(self) -> None:
        """expand(Animal, 'subclasses') returns the supported branch (no 'unsupported')."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "unsupported" not in result, (
            "supported result must not carry 'unsupported'; " f"got result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_subclasses_class_has_required_fields(self) -> None:
        """expand(Animal, 'subclasses') returns source/edge/stubs."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert "source" in result, f"'source' missing from result: {result!r}"
        assert "edge" in result, f"'edge' missing from result: {result!r}"
        assert "stubs" in result, f"'stubs' missing from result: {result!r}"
        assert result["edge"] == "subclasses"

    @pytest.mark.asyncio
    async def test_subclasses_class_stubs_non_empty(self) -> None:
        """Animal has known project subclasses — stubs must be a non-empty list."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        stubs = result["stubs"]
        assert isinstance(stubs, list), f"stubs must be a list; got {type(stubs)!r}"
        assert len(stubs) > 0, "Animal has known project subclasses — stubs must be non-empty"

    @pytest.mark.asyncio
    async def test_subclasses_class_direct_children_only(self) -> None:
        """The supported result carries the DIRECT subclasses only over the wire (#422).

        The fixture's direct subclasses are exactly {Mammal, Lizard} — including
        ``script_animal.Lizard`` defined in a non-importable root script, proving
        the file-based stub construction survives the wire.  The grandchild
        ``pkg.middle.Dog`` is INDIRECT and must NOT appear — since #422 the edge
        is a single hop and the closure is served by ``trace``.
        """
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        handles = {stub["handle"] for stub in result["stubs"]}
        assert handles == {
            "pkg.middle.Mammal",
            "script_animal.Lizard",
        }, f"expected the DIRECT Animal subclasses; got {sorted(handles)!r}"
        assert "pkg.middle.Dog" not in handles, "indirect grandchild Dog must not appear"

    @pytest.mark.asyncio
    async def test_subclasses_class_stubs_have_required_fields(self) -> None:
        """Each subclass stub has handle/kind/scope/line_start/line_end."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        for i, stub in enumerate(result["stubs"]):
            assert isinstance(stub, dict), f"stub[{i}] must be a plain dict; got {type(stub)!r}"
            for field in ("handle", "kind", "scope", "line_start", "line_end"):
                assert field in stub, f"stub[{i}] missing required field '{field}'; stub={stub!r}"

    @pytest.mark.asyncio
    async def test_subclasses_class_stubs_are_class_kind(self) -> None:
        """Each subclass stub must have kind == 'class' (subclasses are always classes)."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        for i, stub in enumerate(result["stubs"]):
            assert stub["kind"] == "class", (
                f"stub[{i}] must have kind='class'; "
                f"got kind={stub.get('kind')!r}; stub={stub!r}"
            )

    @pytest.mark.asyncio
    async def test_subclasses_class_no_unresolved_call_sites(self) -> None:
        """subclasses must NOT include 'unresolved_call_sites' (callees-only field)."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert "unresolved_call_sites" not in result, (
            "'unresolved_call_sites' must be absent for subclasses edge; "
            f"got result keys: {list(result.keys())!r}"
        )

    @pytest.mark.asyncio
    async def test_subclasses_class_result_is_json_serialisable(self) -> None:
        """The subclasses class result round-trips through json.dumps without error."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        # Must not raise — ensures no custom types leak across the wire
        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)
        assert isinstance(roundtripped["stubs"], list)

    @pytest.mark.asyncio
    async def test_subclasses_class_result_is_plain_dict_with_plain_stubs(self) -> None:
        """All nested values in the supported subclasses result are plain Python primitives."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Animal",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert (
            type(result) is dict
        ), f"result must be exact dict (not subclass); got {type(result)!r}"  # noqa: E721
        for i, stub in enumerate(result["stubs"]):
            assert (
                type(stub) is dict
            ), f"stub[{i}] must be exact dict; got {type(stub)!r}"  # noqa: E721


class TestExpandSubclassesNonClassEndToEnd:
    """End-to-end tests for the ``subclasses`` edge on a NON-CLASS handle over the wire.

    ``pkg.base`` is a module — only a class CAN be subclassed, so ``[]`` for a
    non-class is true BY DEFINITION.  Unlike ``imported_by`` (whose wrong-kind
    result is the unsupported ``None`` branch), ``subclasses`` takes the
    ``members``/``callees`` measured-empty route: the SUPPORTED branch with
    ``stubs: []``.  This is the defining behavior of the slice (#348 decision 1).
    """

    @pytest.mark.asyncio
    async def test_subclasses_non_class_returns_supported_branch(self) -> None:
        """expand(pkg.base module, 'subclasses') returns the SUPPORTED branch."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "unsupported" not in result, (
            "non-class subclasses must be the SUPPORTED measured-empty branch, "
            f"not unsupported; got result={result!r}"
        )
        assert "reason" not in result, (
            "non-class subclasses must NOT carry a 'reason' (supported branch); "
            f"got result={result!r}"
        )

    @pytest.mark.asyncio
    async def test_subclasses_non_class_has_empty_stubs(self) -> None:
        """The non-class result is measured-empty: stubs present and empty."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert "stubs" in result, f"'stubs' missing from supported result: {result!r}"
        assert result["stubs"] == [], (
            "non-class subclasses must be measured-empty ('stubs': []); "
            f"got stubs={result.get('stubs')!r}"
        )
        assert result["edge"] == "subclasses"

    @pytest.mark.asyncio
    async def test_subclasses_non_class_no_unresolved_call_sites(self) -> None:
        """The non-class subclasses result must NOT include 'unresolved_call_sites'."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert "unresolved_call_sites" not in result, (
            "'unresolved_call_sites' must be absent for subclasses edge; "
            f"got result keys: {list(result.keys())!r}"
        )

    @pytest.mark.asyncio
    async def test_subclasses_non_class_result_is_json_serialisable(self) -> None:
        """The non-class measured-empty result round-trips through json.dumps."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        serialised = json.dumps(result)
        roundtripped = json.loads(serialised)
        assert isinstance(roundtripped, dict)
        assert roundtripped["stubs"] == []

    @pytest.mark.asyncio
    async def test_subclasses_non_class_result_is_plain_dict(self) -> None:
        """The non-class measured-empty result is an exact plain dict."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert (
            type(result) is dict
        ), f"result must be exact dict (not subclass); got {type(result)!r}"  # noqa: E721


class TestExpandSubclassesEmptyClassEndToEnd:
    """End-to-end test for the ``subclasses`` edge on a CLASS with NO subclasses.

    ``pkg.base.Loner`` is a class that nobody subclasses.  This is a DISTINCT
    branch from the non-class case (``TestExpandSubclassesNonClassEndToEnd``):
    the kind gate matches (it IS a class), the resolver runs ``find_subclasses``
    and genuinely MEASURES zero subclasses — so the empty ``[]`` is produced by a
    different code path than the wrong-kind short-circuit.  Both surface as the
    same SUPPORTED measured-empty shape, and this pins the class-zero path over
    the wire (the fixture docstring advertises ``Loner`` for exactly this case).
    """

    @pytest.mark.asyncio
    async def test_subclasses_empty_class_returns_supported_measured_empty(self) -> None:
        """expand(pkg.base.Loner, 'subclasses') is the SUPPORTED branch with stubs: []."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Loner",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        assert "unsupported" not in result, (
            "a class with no subclasses must be the SUPPORTED measured-empty branch, "
            f"not unsupported; got result={result!r}"
        )
        assert "reason" not in result
        assert result["edge"] == "subclasses"
        assert result["stubs"] == [], (
            "a class measured to have no subclasses must yield 'stubs': []; "
            f"got stubs={result.get('stubs')!r}"
        )

    @pytest.mark.asyncio
    async def test_subclasses_empty_class_result_is_json_serialisable(self) -> None:
        """The empty-class measured-empty result round-trips through json.dumps."""
        from pyeye.mcp.server import expand

        result = await expand(
            handle="pkg.base.Loner",
            edge="subclasses",
            project_path=str(_SUBCLASSES_FIXTURE),
        )

        roundtripped = json.loads(json.dumps(result))
        assert isinstance(roundtripped, dict)
        assert roundtripped["stubs"] == []


# ---------------------------------------------------------------------------
# trace tool — registration + end-to-end over the wire
# ---------------------------------------------------------------------------


class TestTraceToolRegistered:
    """Verify trace is importable from pyeye.mcp.server and is an async callable."""

    def test_trace_is_importable(self) -> None:
        from pyeye.mcp.server import trace  # noqa: F401

    def test_trace_is_callable(self) -> None:
        from pyeye.mcp.server import trace

        assert callable(trace)

    def test_trace_is_async(self) -> None:
        from pyeye.mcp.server import trace

        assert _inspect_stdlib.iscoroutinefunction(trace)


class TestTraceEndToEnd:
    """End-to-end Subgraph contract for the trace tool over the wire."""

    @pytest.mark.asyncio
    async def test_members_trace_returns_subgraph(self) -> None:
        from pyeye.mcp.server import trace

        result = await trace(
            start="mypackage._core.widgets.Widget",
            follow=["members"],
            project_path=str(_FIXTURE),
            max_depth=1,
        )
        assert isinstance(result, dict), f"result must be a plain dict; got {type(result)!r}"
        # Subgraph keys.
        for key in ("nodes", "edges", "truncated", "truncation_reasons", "unsupported_edges"):
            assert key in result, f"'{key}' missing from Subgraph: {result!r}"
        assert isinstance(result["nodes"], dict)
        assert isinstance(result["edges"], list)
        assert isinstance(result["truncated"], bool)
        # The start is a node and its members produced edges.
        assert "mypackage._core.widgets.Widget" in result["nodes"]
        assert any(e["kind"] == "members" for e in result["edges"])
        assert result["unsupported_edges"] == []

    @pytest.mark.asyncio
    async def test_deferred_edge_in_follow_surfaced_over_wire(self) -> None:
        from pyeye.mcp.server import trace

        result = await trace(
            start="mypackage._core.widgets.Widget",
            follow=["members", "callers"],
            project_path=str(_FIXTURE),
            max_depth=1,
        )
        # The supported edge still traverses; the deferred edge is surfaced.
        assert any(e["kind"] == "members" for e in result["edges"])
        callers = next((u for u in result["unsupported_edges"] if u["edge"] == "callers"), None)
        assert callers is not None, f"'callers' not surfaced: {result['unsupported_edges']}"
        assert callers["reason"] == "deferred_reference_backend"

    @pytest.mark.asyncio
    async def test_trace_result_is_json_serialisable(self) -> None:
        from pyeye.mcp.server import trace

        result = await trace(
            start="mypackage._core.widgets",
            follow=["imported_by"],
            project_path=str(_FIXTURE),
            max_depth=2,
        )
        # Plain dict, fully JSON round-trippable — no custom types leak the wire.
        assert (
            type(result) is dict
        ), f"result must be exact dict; got {type(result)!r}"  # noqa: E721
        json.loads(json.dumps(result))
