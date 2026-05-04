"""Tests for the inspect(handle) operation — Task 3.1 (failing / TDD red phase).

These tests pin down the contract for ``inspect``'s universal + kind-dependent
return shape as specified in the Phase 3 progressive-disclosure API design.

Fixture layout
--------------
tests/fixtures/resolve_project/
  mypackage/
    __init__.py           # re-exports Widget from _core.widgets
    _core/
      __init__.py         # empty
      widgets.py          # Widget class (line 21), make_widget function (line 71),
                          # DEFAULT_NAME variable (line 18), Config class (line 61)

All tests are ``@pytest.mark.asyncio`` to match the async signature of ``inspect``.

NOTE: The ``inspect`` module does not exist yet (Task 3.2 implements it).
All tests in this file will fail at import time until the implementation lands.
That is the expected "red" state for TDD discipline.

Contract tested
---------------
Universal fields (all kinds):
  - ``handle``: str, the canonical handle
  - ``kind``: one of the API kind vocabulary values
  - ``scope``: ``"project"`` or ``"external"``
  - ``location``: dict with ``file``, ``line_start``, ``line_end``,
    ``column_start``, ``column_end`` — location pointer, NOT source content
  - ``docstring``: str or None (present when available)

Kind-dependent fields:
  - class: ``superclasses: list[str]``; optional ``signature: str``
  - function/method: ``signature: str``, ``parameters: list[dict]``,
    ``return_type: str | None``, ``is_async: bool``,
    ``is_classmethod: bool``, ``is_staticmethod: bool``
  - module: ``is_package: bool``; optional ``package: str``
  - attribute/property/variable: optional ``type: str``, optional
    ``default: str`` (simple literals only)

Phase 3 absence-vs-zero invariants (Task 3.1 contract):
  - ``edge_counts``: ALWAYS present; equals ``{}`` in Phase 3
  - ``re_exports``: ABSENT (not ``[]``) — Phase 6 wires it in
  - ``highlights``: ABSENT — Phase 5 wires it in
  - ``tags``: ABSENT for Python kinds (plugin kinds only)
  - ``properties``: ABSENT for Python kinds (plugin kinds only)

No source-content fields:
  - Signatures are short single-line strings — NOT multi-line code bodies
  - ``default`` is a simple literal string when present — NOT a complex expression
  - ``location`` is a pointer dict — NOT a source snippet
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

# Known canonical handles from the fixture
_WIDGET_HANDLE = "mypackage._core.widgets.Widget"
_CONFIG_HANDLE = "mypackage._core.widgets.Config"
_MAKE_WIDGET_HANDLE = "mypackage._core.widgets.make_widget"
_GREET_HANDLE = "mypackage._core.widgets.Widget.greet"
_SLOW_GREET_HANDLE = "mypackage._core.widgets.Widget.slow_greet"
_DEFAULT_HANDLE = "mypackage._core.widgets.Widget.default"
_NORMALIZE_HANDLE = "mypackage._core.widgets.Widget.normalize"
_DISPLAY_NAME_HANDLE = "mypackage._core.widgets.Widget.display_name"
_COLOR_HANDLE = "mypackage._core.widgets.Widget.color"
_MODULE_HANDLE = "mypackage._core.widgets"
_DEFAULT_NAME_HANDLE = "mypackage._core.widgets.DEFAULT_NAME"

# External symbol — pathlib.Path is stdlib, always available
_PATH_CLASS_HANDLE = "pathlib.Path"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _assert_location(location: dict) -> None:
    """Assert that a location dict has the required pointer fields."""
    assert isinstance(location, dict), f"location must be a dict, got {type(location)}"
    assert "file" in location, "location must contain 'file'"
    assert "line_start" in location, "location must contain 'line_start'"
    assert "line_end" in location, "location must contain 'line_end'"
    assert isinstance(location["file"], str), "location.file must be a str"
    assert isinstance(location["line_start"], int), "location.line_start must be an int"
    assert isinstance(location["line_end"], int), "location.line_end must be an int"
    # Must NOT contain source content — only structural fields
    assert "source" not in location, "location must NOT contain source content"
    assert "text" not in location, "location must NOT contain text content"
    assert "snippet" not in location, "location must NOT contain snippet content"


# ---------------------------------------------------------------------------
# TestInspectClass — fixture: Widget
# ---------------------------------------------------------------------------


class TestInspectClass:
    """inspect returns correct universal and class-specific fields for a class handle."""

    @pytest.mark.asyncio
    async def test_class_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Universal fields are populated for a class handle."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        # Universal fields
        assert result["handle"] == _WIDGET_HANDLE
        assert result["kind"] == "class"
        assert result["scope"] == "project"
        _assert_location(result["location"])
        # docstring is present (Widget has a docstring)
        assert "docstring" in result
        assert result["docstring"] is not None
        assert isinstance(result["docstring"], str)

    @pytest.mark.asyncio
    async def test_class_kind_dependent_fields(self, analyzer: JediAnalyzer) -> None:
        """Kind-dependent fields for a class: superclasses list is present."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        # superclasses must be present (list of handle strings)
        assert "superclasses" in result
        assert isinstance(result["superclasses"], list)
        # Each superclass is a string handle
        for sc in result["superclasses"]:
            assert isinstance(sc, str), f"superclass handle must be str, got {type(sc)}"

    @pytest.mark.asyncio
    async def test_class_location_is_in_fixture_file(self, analyzer: JediAnalyzer) -> None:
        """Widget's location.file must point to the widgets.py fixture file."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        loc = result["location"]
        assert (
            "widgets.py" in loc["file"]
        ), f"Widget location should be in widgets.py, got: {loc['file']}"
        # line_start should correspond to where Widget is defined (line 21)
        assert (
            loc["line_start"] == 21
        ), f"Widget is defined on line 21; got line_start={loc['line_start']}"


# ---------------------------------------------------------------------------
# TestInspectFunction — fixture: make_widget
# ---------------------------------------------------------------------------


class TestInspectFunction:
    """inspect returns correct universal and function-specific fields."""

    @pytest.mark.asyncio
    async def test_function_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Universal fields are populated for a function handle."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MAKE_WIDGET_HANDLE, analyzer)

        assert result["handle"] == _MAKE_WIDGET_HANDLE
        assert result["kind"] == "function"
        assert result["scope"] == "project"
        _assert_location(result["location"])
        # docstring is present
        assert "docstring" in result
        assert result["docstring"] is not None

    @pytest.mark.asyncio
    async def test_function_kind_dependent_fields(self, analyzer: JediAnalyzer) -> None:
        """Kind-dependent fields for a function: signature, parameters, return_type, flags."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MAKE_WIDGET_HANDLE, analyzer)

        # signature: non-empty string, single-line (no body)
        assert "signature" in result
        assert isinstance(result["signature"], str)
        assert len(result["signature"]) > 0
        assert "\n" not in result["signature"], "signature must be a single-line string"

        # parameters: list of Param dicts
        assert "parameters" in result
        assert isinstance(result["parameters"], list)
        # make_widget(widget_name: str) has one parameter
        assert len(result["parameters"]) >= 1
        param = result["parameters"][0]
        assert "name" in param
        assert param["name"] == "widget_name"
        assert "kind" in param
        valid_param_kinds = {
            "positional",
            "positional_or_keyword",
            "keyword_only",
            "var_positional",
            "var_keyword",
        }
        assert (
            param["kind"] in valid_param_kinds
        ), f"param.kind must be one of {valid_param_kinds}, got {param['kind']!r}"

        # return_type: str or None (not required but must be present as key)
        assert "return_type" in result

        # async/classmethod/staticmethod flags
        assert "is_async" in result
        assert result["is_async"] is False  # make_widget is not async
        assert "is_classmethod" in result
        assert result["is_classmethod"] is False
        assert "is_staticmethod" in result
        assert result["is_staticmethod"] is False

    @pytest.mark.asyncio
    async def test_function_parameter_type_annotation(self, analyzer: JediAnalyzer) -> None:
        """Parameter type annotation is captured when present."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MAKE_WIDGET_HANDLE, analyzer)

        params = result["parameters"]
        widget_name_param = next((p for p in params if p["name"] == "widget_name"), None)
        assert widget_name_param is not None, "widget_name parameter not found"
        # make_widget(widget_name: str) has a type annotation
        if "type" in widget_name_param:
            assert isinstance(widget_name_param["type"], str)


# ---------------------------------------------------------------------------
# TestInspectMethod — fixture: Widget.greet
# ---------------------------------------------------------------------------


class TestInspectMethod:
    """inspect returns correct fields for a method handle."""

    @pytest.mark.asyncio
    async def test_method_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Universal fields are populated for a method handle."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_GREET_HANDLE, analyzer)

        assert result["handle"] == _GREET_HANDLE
        assert result["kind"] == "method"
        assert result["scope"] == "project"
        _assert_location(result["location"])
        # greet has a docstring
        assert "docstring" in result
        assert result["docstring"] is not None

    @pytest.mark.asyncio
    async def test_method_kind_dependent_fields(self, analyzer: JediAnalyzer) -> None:
        """Kind-dependent fields for a regular instance method."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_GREET_HANDLE, analyzer)

        assert "signature" in result
        assert isinstance(result["signature"], str)
        assert "\n" not in result["signature"]

        assert "parameters" in result
        assert isinstance(result["parameters"], list)

        assert "return_type" in result

        assert "is_async" in result
        assert result["is_async"] is False  # greet is not async
        assert "is_classmethod" in result
        assert result["is_classmethod"] is False
        assert "is_staticmethod" in result
        assert result["is_staticmethod"] is False

    @pytest.mark.asyncio
    async def test_async_method_flag(self, analyzer: JediAnalyzer) -> None:
        """An async method has is_async=True."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_SLOW_GREET_HANDLE, analyzer)

        assert result["kind"] == "method"
        assert result["is_async"] is True

    @pytest.mark.asyncio
    async def test_classmethod_flag(self, analyzer: JediAnalyzer) -> None:
        """A classmethod has is_classmethod=True."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_DEFAULT_HANDLE, analyzer)

        assert result["kind"] == "method"
        assert result["is_classmethod"] is True
        assert result["is_staticmethod"] is False

    @pytest.mark.asyncio
    async def test_staticmethod_flag(self, analyzer: JediAnalyzer) -> None:
        """A staticmethod has is_staticmethod=True."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_NORMALIZE_HANDLE, analyzer)

        assert result["kind"] == "method"
        assert result["is_staticmethod"] is True
        assert result["is_classmethod"] is False


# ---------------------------------------------------------------------------
# TestInspectModule — fixture: mypackage._core.widgets
# ---------------------------------------------------------------------------


class TestInspectModule:
    """inspect returns correct universal and module-specific fields."""

    @pytest.mark.asyncio
    async def test_module_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Universal fields are populated for a module handle."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MODULE_HANDLE, analyzer)

        assert result["handle"] == _MODULE_HANDLE
        assert result["kind"] == "module"
        assert result["scope"] == "project"
        _assert_location(result["location"])
        # Module has a module-level docstring
        assert "docstring" in result

    @pytest.mark.asyncio
    async def test_module_kind_dependent_fields(self, analyzer: JediAnalyzer) -> None:
        """Kind-dependent fields for a module: is_package bool is present."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MODULE_HANDLE, analyzer)

        assert "is_package" in result
        assert isinstance(result["is_package"], bool)
        # widgets.py is a module, not a package (__init__.py), so is_package=False
        assert result["is_package"] is False

        # package is optional but if present, must be a str (handle)
        if "package" in result:
            assert isinstance(result["package"], str)


# ---------------------------------------------------------------------------
# TestInspectAttribute — fixture: Widget.color (ClassVar)
# ---------------------------------------------------------------------------


class TestInspectAttribute:
    """inspect returns correct fields for a class attribute handle."""

    @pytest.mark.asyncio
    async def test_attribute_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Universal fields are populated for an attribute handle."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_COLOR_HANDLE, analyzer)

        assert result["handle"] == _COLOR_HANDLE
        assert result["kind"] in ("attribute", "variable")  # Jedi may return either
        assert result["scope"] == "project"
        _assert_location(result["location"])

    @pytest.mark.asyncio
    async def test_attribute_kind_dependent_fields(self, analyzer: JediAnalyzer) -> None:
        """Kind-dependent fields for attribute: optional type and default."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_COLOR_HANDLE, analyzer)

        # type and default are optional but if present must be strings
        if "type" in result:
            assert result["type"] is None or isinstance(result["type"], str)
        if "default" in result:
            # default must be a simple literal string when present
            assert result["default"] is None or isinstance(result["default"], str)
            # Must NOT be a complex expression (no newlines, no function calls)
            if result["default"] is not None:
                assert (
                    "\n" not in result["default"]
                ), "default must be a simple literal, not a multi-line expression"


# ---------------------------------------------------------------------------
# TestInspectProperty — fixture: Widget.display_name
# ---------------------------------------------------------------------------


class TestInspectProperty:
    """inspect returns correct fields for a property handle."""

    @pytest.mark.asyncio
    async def test_property_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Universal fields are populated for a property handle."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_DISPLAY_NAME_HANDLE, analyzer)

        assert result["handle"] == _DISPLAY_NAME_HANDLE
        assert result["kind"] in ("property", "function", "method")  # Jedi normalisation
        assert result["scope"] == "project"
        _assert_location(result["location"])
        # display_name has a docstring
        assert "docstring" in result

    @pytest.mark.asyncio
    async def test_property_kind_dependent_fields(self, analyzer: JediAnalyzer) -> None:
        """Kind-dependent fields for a property: type is optional."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_DISPLAY_NAME_HANDLE, analyzer)

        if "type" in result:
            assert result["type"] is None or isinstance(result["type"], str)


# ---------------------------------------------------------------------------
# TestInspectVariable — fixture: DEFAULT_NAME (module-level)
# ---------------------------------------------------------------------------


class TestInspectVariable:
    """inspect returns correct fields for a module-level variable handle."""

    @pytest.mark.asyncio
    async def test_variable_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Universal fields are populated for a variable handle."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_DEFAULT_NAME_HANDLE, analyzer)

        assert result["handle"] == _DEFAULT_NAME_HANDLE
        assert result["kind"] in ("variable", "statement")  # Jedi normalisation
        assert result["scope"] == "project"
        _assert_location(result["location"])

    @pytest.mark.asyncio
    async def test_variable_kind_dependent_fields(self, analyzer: JediAnalyzer) -> None:
        """Kind-dependent fields for a variable: optional type and default."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_DEFAULT_NAME_HANDLE, analyzer)

        # DEFAULT_NAME: str = "widget" — type annotation present
        if "type" in result:
            assert result["type"] is None or isinstance(result["type"], str)

        # default may be "widget" (the literal value)
        if "default" in result and result["default"] is not None:
            # Must be a simple literal string representation
            assert isinstance(result["default"], str)
            assert (
                "\n" not in result["default"]
            ), "default must be a simple literal, not a complex expression"


# ---------------------------------------------------------------------------
# TestInspectExternalScope — external symbol: pathlib.Path (stdlib)
# ---------------------------------------------------------------------------


class TestInspectExternalScope:
    """inspect returns shallow data with scope='external' for an external handle."""

    @pytest.mark.asyncio
    async def test_external_scope_classification(self, analyzer: JediAnalyzer) -> None:
        """pathlib.Path is a stdlib class — must have scope='external'."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_PATH_CLASS_HANDLE, analyzer)

        assert (
            result["scope"] == "external"
        ), f"pathlib.Path is stdlib; expected scope='external', got {result['scope']!r}"

    @pytest.mark.asyncio
    async def test_external_scope_has_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Even for external symbols, universal fields must be present."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_PATH_CLASS_HANDLE, analyzer)

        # handle, kind, scope are required
        assert "handle" in result
        assert result["handle"] == _PATH_CLASS_HANDLE
        assert "kind" in result
        assert result["kind"] == "class"
        assert "scope" in result
        # location is required (points to stdlib source, which may be .pyi)
        assert "location" in result
        _assert_location(result["location"])

    @pytest.mark.asyncio
    async def test_external_scope_edge_counts_present(self, analyzer: JediAnalyzer) -> None:
        """edge_counts invariant holds for external-scope symbols too."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_PATH_CLASS_HANDLE, analyzer)

        assert "edge_counts" in result
        assert result["edge_counts"] == {}


# ---------------------------------------------------------------------------
# TestInspectUniversalContract — kind-agnostic invariants
# ---------------------------------------------------------------------------


class TestInspectUniversalContract:
    """Absence-vs-zero invariants that hold across ALL Python kinds."""

    @pytest.mark.asyncio
    async def test_edge_counts_always_present_and_empty(self, analyzer: JediAnalyzer) -> None:
        """edge_counts is ALWAYS present and equals {} in Phase 3."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE, _MODULE_HANDLE):
            result = await inspect(handle, analyzer)
            assert "edge_counts" in result, f"edge_counts must be present for handle={handle!r}"
            assert result["edge_counts"] == {}, (
                f"edge_counts must equal {{}} in Phase 3 for handle={handle!r}; "
                f"got {result['edge_counts']!r}"
            )

    @pytest.mark.asyncio
    async def test_re_exports_is_absent(self, analyzer: JediAnalyzer) -> None:
        """re_exports must be ABSENT in Phase 3 responses (not [], not None)."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE, _MODULE_HANDLE):
            result = await inspect(handle, analyzer)
            assert "re_exports" not in result, (
                f"re_exports must be ABSENT (Phase 3) for handle={handle!r}; "
                f"got re_exports={result.get('re_exports')!r}. "
                "Absence means 'not measured yet'; [] would mean 'measured, empty'."
            )

    @pytest.mark.asyncio
    async def test_highlights_is_absent(self, analyzer: JediAnalyzer) -> None:
        """highlights must be ABSENT in Phase 3 responses."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE, _MODULE_HANDLE):
            result = await inspect(handle, analyzer)
            assert "highlights" not in result, (
                f"highlights must be ABSENT (Phase 3) for handle={handle!r}; "
                f"got highlights={result.get('highlights')!r}"
            )

    @pytest.mark.asyncio
    async def test_tags_is_absent_for_python_kinds(self, analyzer: JediAnalyzer) -> None:
        """tags is absent for Python kinds (only plugin kinds emit tags)."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE):
            result = await inspect(handle, analyzer)
            assert (
                "tags" not in result
            ), f"tags must be ABSENT for Python kinds in Phase 3 for handle={handle!r}"

    @pytest.mark.asyncio
    async def test_properties_is_absent_for_python_kinds(self, analyzer: JediAnalyzer) -> None:
        """properties is absent for Python kinds (only plugin kinds emit properties)."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE):
            result = await inspect(handle, analyzer)
            assert (
                "properties" not in result
            ), f"properties must be ABSENT for Python kinds in Phase 3 for handle={handle!r}"

    @pytest.mark.asyncio
    async def test_location_is_pointer_not_content(self, analyzer: JediAnalyzer) -> None:
        """location is always a structural pointer dict, never a source snippet."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE, _GREET_HANDLE, _MODULE_HANDLE):
            result = await inspect(handle, analyzer)
            loc = result["location"]
            _assert_location(loc)
            # line_start <= line_end is a basic sanity check
            assert loc["line_start"] <= loc["line_end"], (
                f"line_start must be <= line_end for handle={handle!r}; "
                f"got {loc['line_start']} > {loc['line_end']}"
            )

    @pytest.mark.asyncio
    async def test_signature_is_single_line_when_present(self, analyzer: JediAnalyzer) -> None:
        """Signature fields (when present) are single-line strings — not code bodies."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_MAKE_WIDGET_HANDLE, _GREET_HANDLE):
            result = await inspect(handle, analyzer)
            if "signature" in result and result["signature"]:
                assert "\n" not in result["signature"], (
                    f"signature must be a single-line string for handle={handle!r}; "
                    f"got multi-line: {result['signature']!r}"
                )

    @pytest.mark.asyncio
    async def test_handle_field_matches_input(self, analyzer: JediAnalyzer) -> None:
        """The handle field in the response equals the input handle."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE, _MODULE_HANDLE):
            result = await inspect(handle, analyzer)
            assert result["handle"] == handle, (
                f"result['handle'] must equal the input handle; "
                f"got {result['handle']!r} for input {handle!r}"
            )

    @pytest.mark.asyncio
    async def test_scope_is_project_for_fixture_symbols(self, analyzer: JediAnalyzer) -> None:
        """All symbols defined in the fixture project have scope='project'."""
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE, _MODULE_HANDLE):
            result = await inspect(handle, analyzer)
            assert result["scope"] == "project", (
                f"Fixture symbol {handle!r} should have scope='project'; "
                f"got {result['scope']!r}"
            )
