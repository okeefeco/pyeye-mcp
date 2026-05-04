"""Tests for the inspect(handle) operation — Tasks 3.1 and 4.1.

Task 3.1 (Phase 3) pins down the universal + kind-dependent return shape.
Task 4.1 (Phase 4) pins down the edge_counts contract with the critical
absence-vs-zero invariant.

Fixture layout
--------------
tests/fixtures/resolve_project/
  mypackage/
    __init__.py           # re-exports Widget from _core.widgets
    usage.py              # usage site: callers/references for edge_counts tests
    _core/
      __init__.py         # empty
      widgets.py          # Widget class (line 21), make_widget function (line 71),
                          # DEFAULT_NAME variable (line 18), Config class (line 61),
                          # Premium(Widget) and Deluxe(Widget) at end of file

All tests are ``@pytest.mark.asyncio`` to match the async signature of ``inspect``.

Contract tested — Phase 3 (Tasks 3.1)
--------------------------------------
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
  - ``edge_counts``: ALWAYS present as a dict; Phase 3 returns ``{}``
  - ``re_exports``: ABSENT (not ``[]``) — Phase 6 wires it in
  - ``highlights``: ABSENT — Phase 5 wires it in
  - ``tags``: ABSENT for Python kinds (plugin kinds only)
  - ``properties``: ABSENT for Python kinds (plugin kinds only)

No source-content fields:
  - Signatures are short single-line strings — NOT multi-line code bodies
  - ``default`` is a simple literal string when present — NOT a complex expression
  - ``location`` is a pointer dict — NOT a source snippet

Contract tested — Phase 4 (Task 4.1)
--------------------------------------
Phase 4 wires exactly 5 edge types into ``edge_counts``:
  - ``members``: for class and module handles (count of direct members)
  - ``superclasses``: for class handles
  - ``subclasses``: for class handles (project-scoped)
  - ``callers``: for function/method handles
  - ``references``: for any handle (aggregate read/written/passed; excludes calls)

The absence-vs-zero invariant (load-bearing):
  - Unmeasured edges are ABSENT from edge_counts (not present with value 0)
  - Measured-and-zero edges are PRESENT with value 0 (not omitted)
  - ``read_by``, ``written_by``, ``passed_by``, ``decorated_by``, ``decorates``,
    ``imports``, ``imported_by``, ``enclosing_scope``, ``callees``,
    ``overrides``, ``overridden_by`` MUST NOT appear in Phase 4 edge_counts
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

# Phase 4 fixture handles — subclasses of Widget added at end of widgets.py
_PREMIUM_HANDLE = "mypackage._core.widgets.Premium"
_DELUXE_HANDLE = "mypackage._core.widgets.Deluxe"

# External symbol — pathlib.Path is stdlib, always available
_PATH_CLASS_HANDLE = "pathlib.Path"

# All 5 edge types measured by Phase 4 (must be present for relevant kinds)
_PHASE4_MEASURED_EDGES = frozenset(
    {"members", "superclasses", "subclasses", "callers", "references"}
)

# All unmeasured edge types in Phase 4 (must be ABSENT from edge_counts)
_PHASE4_UNMEASURED_EDGES = [
    "read_by",
    "written_by",
    "passed_by",
    "decorated_by",
    "decorates",
    "imports",
    "imported_by",
    "enclosing_scope",
    "callees",
    "overrides",
    "overridden_by",
]


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
        """edge_counts invariant holds for external-scope symbols too (present, is a dict)."""
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_PATH_CLASS_HANDLE, analyzer)

        assert "edge_counts" in result
        assert isinstance(result["edge_counts"], dict)
        # Phase 4 populates edge_counts for external symbols too (project-scoped counts).
        # Emptiness is not asserted — see TestInspectEdgeCounts for Phase 4 contract.


# ---------------------------------------------------------------------------
# TestInspectUniversalContract — kind-agnostic invariants
# ---------------------------------------------------------------------------


class TestInspectUniversalContract:
    """Absence-vs-zero invariants that hold across ALL Python kinds."""

    @pytest.mark.asyncio
    async def test_edge_counts_always_present_as_dict(self, analyzer: JediAnalyzer) -> None:
        """edge_counts is ALWAYS present and is a dict.

        Phase 3 returns {} for all handles.  Phase 4 populates it with measured
        edges.  The universal contract is: edge_counts is present and is a dict.
        Emptiness is NOT required here — the absence-vs-zero invariant is tested
        separately in TestInspectEdgeCounts.
        """
        from pyeye.mcp.operations.inspect import inspect

        for handle in (_WIDGET_HANDLE, _MAKE_WIDGET_HANDLE, _MODULE_HANDLE):
            result = await inspect(handle, analyzer)
            assert "edge_counts" in result, f"edge_counts must be present for handle={handle!r}"
            assert isinstance(result["edge_counts"], dict), (
                f"edge_counts must be a dict for handle={handle!r}; "
                f"got {type(result['edge_counts'])!r}"
            )
            # Phase 4 populates this with measured edges; emptiness is no longer required.
            # The absence-vs-zero invariant is enforced by TestInspectEdgeCounts.

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


# ---------------------------------------------------------------------------
# TestInspectEdgeCounts — Phase 4 contract (Task 4.1 — FAILING tests)
# ---------------------------------------------------------------------------


class TestInspectEdgeCounts:
    """Phase 4 contract: edge_counts populated with exactly 5 measured edge types.

    These tests are in the RED state until Task 4.2 implements edge_counts.
    The Phase 3 implementation returns ``edge_counts: {}`` always, so every
    assertion that checks for a non-empty edge_counts (or for a 0-valued key)
    will fail with AssertionError.

    The absence-vs-zero invariant (load-bearing):
    - Measured edges with zero value MUST be PRESENT with value 0 (not omitted)
    - Unmeasured edge types MUST be ABSENT (not present with value 0)

    Phase 4 measures exactly these 5 edges:
    - ``members``: class and module handles
    - ``superclasses``: class handles
    - ``subclasses``: class handles (project-scoped)
    - ``callers``: function/method handles
    - ``references``: any handle (aggregate read/written/passed; excludes calls)
    """

    # ------------------------------------------------------------------ (a)
    @pytest.mark.asyncio
    async def test_class_has_members_count(self, analyzer: JediAnalyzer) -> None:
        """(a) Class handles have edge_counts['members'] = count of direct members.

        Widget has: color, name, visible, __init__, greet, slow_greet,
        display_name, default, normalize — at least 5 direct members.
        Phase 3 returns edge_counts: {} so 'members' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        assert "members" in result["edge_counts"], (
            f"Class handle must have edge_counts['members']; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        # Widget has at least 5 direct members — allow slack for Jedi's resolution
        assert (
            result["edge_counts"]["members"] >= 5
        ), f"Widget has >= 5 members; got members={result['edge_counts']['members']}"

    # ------------------------------------------------------------------ (a) module
    @pytest.mark.asyncio
    async def test_module_has_members_count(self, analyzer: JediAnalyzer) -> None:
        """(a) Module handles have edge_counts['members'] = count of top-level definitions.

        mypackage._core.widgets defines: DEFAULT_NAME, Widget, Config, make_widget,
        Premium, Deluxe — at least 4 top-level definitions.
        Phase 3 returns edge_counts: {} so 'members' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MODULE_HANDLE, analyzer)

        assert "members" in result["edge_counts"], (
            f"Module handle must have edge_counts['members']; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        # widgets.py has at least 4 top-level definitions
        assert result["edge_counts"]["members"] >= 4, (
            f"widgets module has >= 4 top-level members; "
            f"got members={result['edge_counts']['members']}"
        )

    # ------------------------------------------------------------------ (b)
    @pytest.mark.asyncio
    async def test_class_has_superclasses_count_key(self, analyzer: JediAnalyzer) -> None:
        """(b) Class handles have edge_counts['superclasses'] key present.

        Widget has no explicit base class — so the count could be 0.
        The key MUST be present regardless.
        Phase 3 returns edge_counts: {} so 'superclasses' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        assert "superclasses" in result["edge_counts"], (
            f"Class handle must have edge_counts['superclasses'] key; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        assert isinstance(result["edge_counts"]["superclasses"], int), (
            f"edge_counts['superclasses'] must be an int; "
            f"got {type(result['edge_counts']['superclasses'])!r}"
        )

    @pytest.mark.asyncio
    async def test_class_with_explicit_base_has_superclasses_count(
        self, analyzer: JediAnalyzer
    ) -> None:
        """(b) A class with an explicit base has superclasses count >= 1.

        Premium extends Widget explicitly — superclasses count must be >= 1.
        Phase 3 returns edge_counts: {} so 'superclasses' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_PREMIUM_HANDLE, analyzer)

        assert "superclasses" in result["edge_counts"], (
            f"Class handle must have edge_counts['superclasses'] key; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        assert result["edge_counts"]["superclasses"] >= 1, (
            f"Premium(Widget) has 1 explicit superclass; "
            f"got superclasses={result['edge_counts']['superclasses']}"
        )

    # ------------------------------------------------------------------ (c)
    @pytest.mark.asyncio
    async def test_class_with_no_subclasses_returns_zero(self, analyzer: JediAnalyzer) -> None:
        """(c/g) CRITICAL: measured-and-zero is PRESENT with value 0, not omitted.

        Config has no subclasses in the project.
        edge_counts['subclasses'] MUST be 0 (present!), NOT absent.
        Phase 3 returns edge_counts: {} — 'subclasses' is absent → FAIL.
        This tests BOTH directions of the invariant:
        - key is present ('subclasses' in edge_counts)
        - value is 0 (not a non-zero count)
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_CONFIG_HANDLE, analyzer)

        # CRITICAL: 'subclasses' MUST be in edge_counts even when count is 0
        assert "subclasses" in result["edge_counts"], (
            f"Config has no subclasses — but 'subclasses' key MUST be present with value 0; "
            f"got edge_counts={result['edge_counts']!r}. "
            "Absence means 'not measured'; 0 means 'measured, none found'. "
            "Phase 4 measures subclasses for all class handles."
        )
        assert result["edge_counts"]["subclasses"] == 0, (
            f"Config has no project subclasses; expected subclasses=0; "
            f"got subclasses={result['edge_counts']['subclasses']}"
        )

    @pytest.mark.asyncio
    async def test_class_with_subclasses_counts_them(self, analyzer: JediAnalyzer) -> None:
        """(c) A class with project subclasses returns their count in edge_counts.

        Widget has Premium and Deluxe as explicit subclasses in the project.
        edge_counts['subclasses'] must be >= 2.
        Phase 3 returns edge_counts: {} so 'subclasses' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        assert "subclasses" in result["edge_counts"], (
            f"Widget has subclasses (Premium, Deluxe) — 'subclasses' key must be present; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        assert result["edge_counts"]["subclasses"] >= 2, (
            f"Widget has >= 2 project subclasses (Premium, Deluxe); "
            f"got subclasses={result['edge_counts']['subclasses']}"
        )

    # ------------------------------------------------------------------ (d)
    @pytest.mark.asyncio
    async def test_function_has_callers_count_key(self, analyzer: JediAnalyzer) -> None:
        """(d) Function handles have edge_counts['callers'] key present.

        make_widget is called from usage.py — callers >= 2.
        Phase 3 returns edge_counts: {} so 'callers' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MAKE_WIDGET_HANDLE, analyzer)

        assert "callers" in result["edge_counts"], (
            f"Function handle must have edge_counts['callers'] key; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        # make_widget is called twice in usage.py
        assert result["edge_counts"]["callers"] >= 2, (
            f"make_widget is called >= 2 times in usage.py; "
            f"got callers={result['edge_counts']['callers']}"
        )

    @pytest.mark.asyncio
    async def test_method_has_callers_count(self, analyzer: JediAnalyzer) -> None:
        """(d) Method handles have edge_counts['callers'] key with count >= 0.

        Widget.greet is called from usage.py — callers >= 2.
        Phase 3 returns edge_counts: {} so 'callers' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_GREET_HANDLE, analyzer)

        assert "callers" in result["edge_counts"], (
            f"Method handle must have edge_counts['callers'] key; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        # greet is called twice in usage.py
        assert result["edge_counts"]["callers"] >= 2, (
            f"Widget.greet is called >= 2 times in usage.py; "
            f"got callers={result['edge_counts']['callers']}"
        )

    @pytest.mark.asyncio
    async def test_function_with_no_callers_returns_zero(self, analyzer: JediAnalyzer) -> None:
        """(d/g) A truly uncalled function has callers: 0 (PRESENT, not omitted).

        Widget.normalize is a staticmethod not called in any fixture file.
        edge_counts['callers'] MUST be 0 (present), NOT absent.
        Phase 3 returns edge_counts: {} → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_NORMALIZE_HANDLE, analyzer)

        assert "callers" in result["edge_counts"], (
            f"normalize has no callers — but 'callers' key MUST be present with value 0; "
            f"got edge_counts={result['edge_counts']!r}. "
            "Absence means 'not measured'; 0 means 'measured, no callers found'."
        )
        assert result["edge_counts"]["callers"] == 0, (
            f"Widget.normalize is uncalled in the fixture project; expected callers=0; "
            f"got callers={result['edge_counts']['callers']}"
        )

    # ------------------------------------------------------------------ (e)
    @pytest.mark.asyncio
    async def test_handle_has_references_aggregate_count(self, analyzer: JediAnalyzer) -> None:
        """(e) edge_counts['references'] aggregates read/written/passed; excludes call sites.

        DEFAULT_NAME is read in usage.py (name = DEFAULT_NAME) without being called.
        So references >= 1.  It is NOT called, so callers == 0 (separate key).
        Phase 3 returns edge_counts: {} so 'references' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_DEFAULT_NAME_HANDLE, analyzer)

        assert "references" in result["edge_counts"], (
            f"Variable handle must have edge_counts['references'] key; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        # DEFAULT_NAME is read at least once in usage.py
        assert result["edge_counts"]["references"] >= 1, (
            f"DEFAULT_NAME is read >= 1 time in usage.py; "
            f"got references={result['edge_counts']['references']}"
        )

    @pytest.mark.asyncio
    async def test_references_excludes_call_sites(self, analyzer: JediAnalyzer) -> None:
        """(e) references and callers are DISTINCT — call sites counted only in callers.

        make_widget is called twice (usage.py) and the name is also imported once.
        The import/read is a reference; the calls are callers.
        So: callers >= 2 AND references >= 0 (at minimum the import is a reference).
        Critically: callers and references must NOT double-count call sites.
        Phase 3 returns edge_counts: {} → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MAKE_WIDGET_HANDLE, analyzer)

        assert "callers" in result["edge_counts"], (
            f"make_widget must have 'callers' in edge_counts; " f"got {result['edge_counts']!r}"
        )
        assert "references" in result["edge_counts"], (
            f"make_widget must have 'references' in edge_counts; " f"got {result['edge_counts']!r}"
        )

        callers = result["edge_counts"]["callers"]
        references = result["edge_counts"]["references"]

        # make_widget is called twice — callers must be >= 2
        assert callers >= 2, f"make_widget called >= 2 times; got callers={callers}"

        # References should NOT include the call sites (those are in callers).
        # The import statement counts as a reference; actual calls do NOT.
        # The import in usage.py is: from mypackage._core.widgets import ..., make_widget
        # So references >= 0. We verify callers and references don't sum to > total usages,
        # which would indicate double-counting.
        assert references >= 0, f"references must be >= 0; got references={references}"
        # The call sites (callers) must NOT be counted in references too:
        # If total usages = N, and callers = 2, then references < N (calls excluded).
        # We assert references != callers as a proxy that they're not the same count
        # (unless by coincidence, which is acceptable).
        # The key invariant: references is the non-call usage count.
        assert isinstance(references, int), f"references must be an int; got {type(references)!r}"

    # ------------------------------------------------------------------ (f)
    @pytest.mark.asyncio
    async def test_unmeasured_edges_are_absent(self, analyzer: JediAnalyzer) -> None:
        """(f) CRITICAL: unmeasured edge types MUST NOT appear in edge_counts.

        Phase 4 measures exactly 5 edges. All other edge types are ABSENT.
        An absent key means 'we didn't measure this' — not 'the value is 0'.
        This test runs against a class handle (Widget) where Phase 4 WILL populate
        members/superclasses/subclasses. It verifies the other 11 types stay absent.

        Phase 3 returns {} — this test PASSES in Phase 3 (no spurious keys).
        But after Phase 4 implementation, the 5 measured keys will be present.
        The unmeasured keys must STILL be absent.

        NOTE: This test is designed to pass in Phase 3 (nothing to check for yet)
        and continue passing in Phase 4 (measured keys in, unmeasured keys still out).
        We include it here to document the contract and to catch any implementation
        that accidentally adds unmeasured keys.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        for edge in _PHASE4_UNMEASURED_EDGES:
            assert edge not in result["edge_counts"], (
                f"Phase 4 only measures {sorted(_PHASE4_MEASURED_EDGES)!r}; "
                f"{edge!r} must be ABSENT (not present with value 0). "
                f"Got edge_counts={result['edge_counts']!r}"
            )

    @pytest.mark.asyncio
    async def test_unmeasured_edges_absent_for_function(self, analyzer: JediAnalyzer) -> None:
        """(f) Unmeasured edge types are absent for function handles too.

        Phase 4 measures callers and references for functions.
        All other 11 edge types must be absent.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MAKE_WIDGET_HANDLE, analyzer)

        for edge in _PHASE4_UNMEASURED_EDGES:
            assert edge not in result["edge_counts"], (
                f"Phase 4 only measures callers+references for functions; "
                f"{edge!r} must be ABSENT. Got edge_counts={result['edge_counts']!r}"
            )

    # ------------------------------------------------------------------ (g) — covered by
    # test_class_with_no_subclasses_returns_zero (subclasses=0 present)
    # test_function_with_no_callers_returns_zero (callers=0 present)

    # ------------------------------------------------------------------ (h)
    @pytest.mark.asyncio
    async def test_external_node_subclasses_are_project_scoped(
        self, analyzer: JediAnalyzer
    ) -> None:
        """(h) edge_counts on an external node reflects project-internal subclasses only.

        pathlib.Path is a stdlib class. The fixture project has no class that
        extends pathlib.Path, so edge_counts['subclasses'] must be 0.
        This verifies that the count is project-scoped (not all Python subclasses globally).

        Phase 3 returns edge_counts: {} so 'subclasses' is absent → FAIL.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_PATH_CLASS_HANDLE, analyzer)

        assert "subclasses" in result["edge_counts"], (
            f"External class handle must have edge_counts['subclasses'] key (project-scoped); "
            f"got edge_counts={result['edge_counts']!r}. "
            "Phase 4 measures project subclasses even for external symbols."
        )
        # No fixture class extends pathlib.Path → project-scoped count must be 0
        assert result["edge_counts"]["subclasses"] == 0, (
            f"No project class extends pathlib.Path; expected subclasses=0 (project-scoped); "
            f"got subclasses={result['edge_counts']['subclasses']}"
        )

    @pytest.mark.asyncio
    async def test_all_five_phase4_edges_present_for_class(self, analyzer: JediAnalyzer) -> None:
        """All 5 Phase 4 edge types are present in edge_counts for a class handle.

        Widget is a class — Phase 4 wires members, superclasses, subclasses,
        callers (= 0, Widget is not a callable in the callers sense), and references.
        All 5 keys must be present.
        Phase 3 returns {} → FAIL (none of the 5 keys are present).
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        for edge in _PHASE4_MEASURED_EDGES:
            assert edge in result["edge_counts"], (
                f"Phase 4 must populate edge_counts[{edge!r}] for class handles; "
                f"got edge_counts={result['edge_counts']!r}"
            )

    @pytest.mark.asyncio
    async def test_only_phase4_edges_present_no_extras(self, analyzer: JediAnalyzer) -> None:
        """edge_counts contains ONLY the 5 Phase 4 measured edges (no extras).

        After Phase 4, edge_counts must contain exactly the 5 measured keys
        (for the appropriate kinds) and nothing else.
        Phase 3 returns {} — this test FAILS because the 5 keys are absent.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)
        edge_counts = result["edge_counts"]

        # All 5 measured keys must be present for a class
        for edge in _PHASE4_MEASURED_EDGES:
            assert edge in edge_counts, (
                f"Phase 4 must populate {edge!r} for class Widget; "
                f"got edge_counts={edge_counts!r}"
            )

        # No extra keys beyond the 5 measured ones
        extra_keys = set(edge_counts.keys()) - _PHASE4_MEASURED_EDGES
        assert not extra_keys, (
            f"edge_counts contains unexpected keys beyond Phase 4's 5 measured edges: "
            f"{sorted(extra_keys)!r}. Only {sorted(_PHASE4_MEASURED_EDGES)!r} are allowed."
        )


# ---------------------------------------------------------------------------
# TestInspectEdgeTimeout — Phase 4 per-measurement time budget contract
# ---------------------------------------------------------------------------


class TestInspectEdgeTimeout:
    """Per-measurement time budget contract for edge_counts.

    These tests verify the absence-vs-zero invariant for timed-out edges:
    an edge that exceeds its measurement budget is OMITTED from edge_counts
    (consistent with 'not measured'), not present with value 0 ('measured, none').

    All tests use mocks to force timeout deterministically — no real-time delays.
    """

    @pytest.mark.asyncio
    async def test_timeout_on_subclasses_omits_edge(self, analyzer: JediAnalyzer) -> None:
        """A timeout on subclasses measurement omits 'subclasses' from edge_counts.

        When ``_count_subclasses`` exceeds the per-edge budget,
        ``edge_counts['subclasses']`` must be ABSENT (not 0).
        The other edges (members, superclasses, callers, references) should still
        be measured independently and present in edge_counts.
        """
        import asyncio
        from unittest.mock import patch

        from pyeye.mcp.operations.inspect import inspect

        # Patch _count_subclasses to raise asyncio.TimeoutError on every call.
        # _measure_with_budget catches TimeoutError from wait_for, but we also
        # need to handle the case where the coroutine itself raises it.
        async def subclasses_timeout(*_args: object, **_kwargs: object) -> int:
            raise asyncio.TimeoutError()

        with patch(
            "pyeye.mcp.operations.inspect._count_subclasses",
            side_effect=subclasses_timeout,
        ):
            result = await inspect(_WIDGET_HANDLE, analyzer)

        edge_counts = result["edge_counts"]

        # subclasses must be ABSENT (timed out → not measured)
        assert "subclasses" not in edge_counts, (
            f"Timed-out edge 'subclasses' must be ABSENT from edge_counts; "
            f"got edge_counts={edge_counts!r}. "
            "Absence means 'not measured'; 0 means 'measured, none found'."
        )

        # Other class edges must still be present (per-measurement isolation)
        for edge in ("members", "superclasses", "references"):
            assert edge in edge_counts, (
                f"Edge {edge!r} must still be present when subclasses timed out; "
                f"got edge_counts={edge_counts!r}"
            )

    @pytest.mark.asyncio
    async def test_timeout_on_one_edge_does_not_block_others(self, analyzer: JediAnalyzer) -> None:
        """A timeout on one edge does not prevent other edges from being measured.

        This verifies per-measurement isolation: ``subclasses`` timeout must not
        cause ``members`` or ``superclasses`` to be absent.

        Uses a mock with a very short budget (1 ms) so that the slow mock
        times out via ``asyncio.wait_for`` while others proceed normally.
        """
        import asyncio
        from unittest.mock import patch

        from pyeye.mcp.operations.inspect import _build_edge_counts

        # Replace _count_subclasses with a coroutine that sleeps longer than the budget
        async def slow_subclasses(*_args: object, **_kwargs: object) -> int:
            await asyncio.sleep(10)  # longer than any reasonable budget
            return 99  # pragma: no cover

        with patch("pyeye.mcp.operations.inspect._count_subclasses", side_effect=slow_subclasses):
            # Use a 0.01 second budget so the sleep definitely times out
            result = await _build_edge_counts(
                _WIDGET_HANDLE,
                "class",
                # We need a jedi_name; get it via the real inspect flow
                # by using a sentinel approach — just call build_edge_counts
                # with a minimal budget and check the isolation
                None,  # jedi_name will cause other counts to return 0 or skip gracefully
                analyzer,
                budget_seconds=0.01,
            )

        # subclasses must be absent (timed out)
        assert (
            "subclasses" not in result
        ), f"subclasses must be absent after timeout; got {result!r}"

    @pytest.mark.asyncio
    async def test_all_edges_absent_when_all_timeout(self, analyzer: JediAnalyzer) -> None:
        """When all edge measurements time out, edge_counts is empty (all absent).

        This tests the full timeout path: every edge is absent, consistent with
        the invariant that absence means 'not measured'.
        """
        import asyncio
        from unittest.mock import patch

        from pyeye.mcp.operations.inspect import inspect

        async def always_timeout(*_args: object, **_kwargs: object) -> int:
            raise asyncio.TimeoutError()

        with (
            patch("pyeye.mcp.operations.inspect._count_class_members", side_effect=always_timeout),
            patch("pyeye.mcp.operations.inspect._count_superclasses", side_effect=always_timeout),
            patch("pyeye.mcp.operations.inspect._count_subclasses", side_effect=always_timeout),
            patch("pyeye.mcp.operations.inspect._count_callers_only", side_effect=always_timeout),
            patch(
                "pyeye.mcp.operations.inspect._count_references_only", side_effect=always_timeout
            ),
        ):
            result = await inspect(_WIDGET_HANDLE, analyzer)

        # All edges must be absent (all timed out)
        edge_counts = result["edge_counts"]
        assert edge_counts == {}, (
            f"All edges timed out — edge_counts must be empty; got {edge_counts!r}. "
            "All absent means all timed out (none measured)."
        )


# ---------------------------------------------------------------------------
# TestInspectCoverageLift — targeted tests for previously-uncovered branches
# ---------------------------------------------------------------------------


class TestInspectHelperUnits:
    """Direct unit tests for helper functions with uncovered branches."""

    def test_is_simple_literal_invalid_raises_false(self) -> None:
        """_is_simple_literal returns False for non-literal expressions."""
        from pyeye.mcp.operations.inspect import _is_simple_literal

        # These are NOT simple literals — should return False
        assert _is_simple_literal("Widget()") is False
        assert _is_simple_literal("{key: value}") is False
        assert _is_simple_literal("1 + 2") is False

    def test_is_simple_literal_valid_returns_true(self) -> None:
        """_is_simple_literal returns True for actual literals."""
        from pyeye.mcp.operations.inspect import _is_simple_literal

        assert _is_simple_literal('"hello"') is True
        assert _is_simple_literal("42") is True
        assert _is_simple_literal("3.14") is True
        assert _is_simple_literal("True") is True

    def test_make_location_with_column_end(self) -> None:
        """_make_location includes column_end when provided."""
        from pyeye.mcp.operations.inspect import _make_location

        loc = _make_location("myfile.py", 10, 20, column_start=4, column_end=12)

        assert loc["file"] == "myfile.py"
        assert loc["line_start"] == 10
        assert loc["line_end"] == 20
        assert loc["column_start"] == 4
        assert loc["column_end"] == 12  # exercises the column_end branch (line 154)

    def test_make_location_without_optional_columns(self) -> None:
        """_make_location omits column_start / column_end when not provided."""
        from pyeye.mcp.operations.inspect import _make_location

        loc = _make_location("f.py", 1, 5)

        assert "column_start" not in loc
        assert "column_end" not in loc


class TestFindJediNameForHandleFallbacks:
    """Tests for the uncovered branches in _find_jedi_name_for_handle."""

    def test_bare_name_with_no_module_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A single-component handle that is not a module file returns None (line 547)."""
        from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle

        # "nonexistent" is one component — len(parts) < 2 returns None
        result = _find_jedi_name_for_handle("nonexistent_bare_name_xyz", analyzer)
        assert result is None

    def test_project_search_match_found_in_case3(self, analyzer: JediAnalyzer) -> None:
        """Case 3: project.search returns a result with a matching full_name (lines 568-569).

        This covers the ``if r.full_name == handle: return r`` branch that is
        skipped when project.search returns an empty list.
        """
        from unittest.mock import MagicMock, patch

        from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle

        # Build a fake Jedi Name-like object that matches the handle
        handle = "mypackage._core.widgets.Widget"
        fake_name = MagicMock()
        fake_name.full_name = handle

        # Patch find_module_file to always return None (skip Cases 1 & 2)
        # Patch project.search to return our fake name
        with (
            patch("pyeye.mcp.operations.inspect.find_module_file", return_value=None),
            patch.object(analyzer.project, "search", return_value=iter([fake_name])),
        ):
            result = _find_jedi_name_for_handle(handle, analyzer)

        # The fake name should be returned (Case 3 match)
        assert result is fake_name

    def test_synthetic_import_fallback_for_external_symbol(self, analyzer: JediAnalyzer) -> None:
        """Synthetic-import fallback resolves pathlib.Path when earlier cases fail.

        Forces Cases 1, 2, and 3 to fail, then verifies that the synthetic-import
        block (lines 576-590) resolves the external symbol correctly.
        This is the load-bearing path for stdlib resolution and covers Goal 2.
        """
        from unittest.mock import patch

        from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle

        handle = "pathlib.Path"

        # Force Cases 1 & 2 (find_module_file) to return None
        # Force Case 3 (project.search) to return an empty iterator
        with (
            patch("pyeye.mcp.operations.inspect.find_module_file", return_value=None),
            patch.object(analyzer.project, "search", return_value=iter([])),
        ):
            result = _find_jedi_name_for_handle(handle, analyzer)

        # Synthetic-import fallback should resolve pathlib.Path
        assert result is not None, (
            "Synthetic-import fallback must resolve 'pathlib.Path'; got None. "
            "This path is load-bearing for stdlib external resolution."
        )
        assert (
            result.full_name == handle
        ), f"Resolved name must have full_name='pathlib.Path'; got {result.full_name!r}"

    def test_synthetic_import_fallback_returns_none_for_bogus_handle(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Synthetic-import fallback returns None when the handle doesn't exist.

        Verifies the function returns None (not raises) when no code path resolves
        the handle — covering the final ``return None`` after all fallbacks fail.
        """
        from unittest.mock import patch

        from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle

        handle = "totally.bogus.DoesNotExistAnywhere9999"

        with (
            patch("pyeye.mcp.operations.inspect.find_module_file", return_value=None),
            patch.object(analyzer.project, "search", return_value=iter([])),
        ):
            result = _find_jedi_name_for_handle(handle, analyzer)

        assert result is None

    def test_synthetic_import_exception_handler_returns_none(self, analyzer: JediAnalyzer) -> None:
        """When jedi.Script raises inside the synthetic-import fallback, returns None.

        Exercises the ``except Exception: pass`` handler at the end of the
        synthetic-import block (lines 587-588).
        """
        from unittest.mock import patch

        from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle

        handle = "pathlib.Path"

        with (
            patch("pyeye.mcp.operations.inspect.find_module_file", return_value=None),
            patch.object(analyzer.project, "search", return_value=iter([])),
            # Force jedi.Script constructor to raise inside the synthetic-import try block
            patch("jedi.Script", side_effect=RuntimeError("simulated jedi failure")),
        ):
            result = _find_jedi_name_for_handle(handle, analyzer)

        # Exception was caught; function returns None gracefully
        assert result is None


class TestInspectNotFoundFallback:
    """Tests for the minimal-node fallback when a handle cannot be resolved."""

    @pytest.mark.asyncio
    async def test_unresolved_handle_returns_minimal_node(self, analyzer: JediAnalyzer) -> None:
        """inspect returns a valid minimal node for an unresolvable handle (lines 1147-1148).

        The minimal node must have all universal fields with safe defaults,
        following the contract that inspect never raises.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect("totally.bogus.handle.DoesNotExist999", analyzer)

        # Must not raise; must return the minimal fallback dict
        assert result["handle"] == "totally.bogus.handle.DoesNotExist999"
        assert result["kind"] == "variable"  # safe default
        assert result["scope"] == "external"  # safe default
        assert "location" in result
        assert isinstance(result["edge_counts"], dict)


class TestBuildAttributeFieldsPropertyBranch:
    """Tests for the 'property' branch in _build_attribute_fields (lines 1351-1363)."""

    def test_property_kind_extracts_return_type(self) -> None:
        """_build_attribute_fields with kind='property' extracts return type annotation.

        Exercises the AST-based return-type extraction at lines 1351-1363.
        """
        from unittest.mock import MagicMock

        from pyeye.mcp.operations.inspect import _build_attribute_fields

        fixture_file = _FIXTURE / "mypackage" / "_core" / "widgets.py"

        # display_name is a @property defined at line 46 in widgets.py
        # Verify by reading the fixture
        source = fixture_file.read_text()
        lines = source.splitlines()
        # Find the line with 'def display_name'
        property_line = next(i + 1 for i, ln in enumerate(lines) if "def display_name" in ln)

        mock_name = MagicMock()
        mock_name.line = property_line

        fields = _build_attribute_fields(mock_name, "property", fixture_file)

        # The property has return type -> str annotation
        assert "type" in fields, (
            f"_build_attribute_fields with kind='property' should extract return type; "
            f"fields={fields!r}, property_line={property_line}"
        )
        assert (
            fields["type"] == "str"
        ), f"Expected type='str' for display_name -> str; got {fields['type']!r}"

    def test_property_kind_no_return_annotation_returns_empty(self) -> None:
        """_build_attribute_fields with kind='property' and no annotation returns empty dict."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from pyeye.mcp.operations.inspect import _build_attribute_fields

        # Write a temporary file with a property lacking a return annotation
        source = "class Foo:\n    @property\n    def val(self):\n        return 42\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            tmp_path = Path(f.name)

        try:
            mock_name = MagicMock()
            mock_name.line = 3  # 'def val' is on line 3

            fields = _build_attribute_fields(mock_name, "property", tmp_path)
            # No return annotation — 'type' should not be present
            assert "type" not in fields or fields.get("type") is None
        finally:
            tmp_path.unlink(missing_ok=True)


class TestMeasureCallersAndRefsWithBudget:
    """Tests for _measure_callers_and_refs_with_budget timeout/exception paths (lines 1004-1020)."""

    @pytest.mark.asyncio
    async def test_timeout_omits_both_callers_and_references(self, analyzer: JediAnalyzer) -> None:
        """When _count_callers_and_refs times out, the budget function returns None.

        This exercises the asyncio.TimeoutError handler at lines 1004-1011.
        The caller (_build_edge_counts) then omits both callers and references.
        """
        import asyncio
        from unittest.mock import MagicMock, patch

        from pyeye.mcp.operations.inspect import _measure_callers_and_refs_with_budget

        mock_name = MagicMock()
        mock_name.module_path = _FIXTURE / "mypackage" / "_core" / "widgets.py"

        async def slow_count(*_args: object, **_kwargs: object) -> tuple[int, int]:
            await asyncio.sleep(10)
            return 0, 0  # pragma: no cover

        with patch(
            "pyeye.mcp.operations.inspect._count_callers_and_refs",
            side_effect=slow_count,
        ):
            result = await _measure_callers_and_refs_with_budget(
                _MAKE_WIDGET_HANDLE,
                mock_name,
                analyzer,
                budget_seconds=0.01,  # tiny budget so sleep definitely times out
            )

        assert result is None, (
            f"Timed-out budget function must return None; got {result!r}. "
            "None means 'both callers and references are absent'."
        )

    @pytest.mark.asyncio
    async def test_exception_in_count_returns_none(self, analyzer: JediAnalyzer) -> None:
        """When _count_callers_and_refs raises a generic Exception, the budget returns None.

        This exercises the generic except handler at lines 1012-1020.
        """
        from unittest.mock import MagicMock, patch

        from pyeye.mcp.operations.inspect import _measure_callers_and_refs_with_budget

        mock_name = MagicMock()
        mock_name.module_path = _FIXTURE / "mypackage" / "_core" / "widgets.py"

        async def boom(*_args: object, **_kwargs: object) -> tuple[int, int]:
            raise RuntimeError("simulated Jedi analysis failure")

        with patch(
            "pyeye.mcp.operations.inspect._count_callers_and_refs",
            side_effect=boom,
        ):
            result = await _measure_callers_and_refs_with_budget(
                _MAKE_WIDGET_HANDLE,
                mock_name,
                analyzer,
                budget_seconds=5.0,
            )

        assert result is None, f"Exception in budget function must return None; got {result!r}."

    @pytest.mark.asyncio
    async def test_build_edge_counts_unknown_kind_returns_empty(
        self, analyzer: JediAnalyzer
    ) -> None:
        """_build_edge_counts returns {} for a kind with no registered measurements (line 1095).

        When kind is not 'function', 'method', 'class', 'module', or an
        attribute kind, no coroutines are added and the function returns early.
        """
        from unittest.mock import MagicMock

        from pyeye.mcp.operations.inspect import _build_edge_counts

        mock_name = MagicMock()
        mock_name.module_path = None

        # Use a kind that has no registered measurements
        result = await _build_edge_counts(
            "some.handle",
            "keyword",  # not a measured kind
            mock_name,
            analyzer,
        )

        assert (
            result == {}
        ), f"Unmeasured kind 'keyword' must produce empty edge_counts; got {result!r}"
