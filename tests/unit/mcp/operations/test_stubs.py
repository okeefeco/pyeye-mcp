"""Tests for the Stub builder — Task 1.1 (Phase 1).

Pins down the complete Stub contract for all API kinds so that every traversal
primitive (members, callees, expand) can produce a uniform, spec-compliant stub.

Spec §4.1 — Stub shape
-----------------------
::

    {
      "handle": str,          # canonical definition-site handle
      "kind": str,            # normalised kind (class|function|method|module|
                              #                   attribute|property|variable)
      "scope": "project" | "external",
      "signature": str,       # PRESENT for callable kinds only (class/function/method)
      "line_start": int,
      "line_end": int,
    }

Key invariants:
- ``signature`` is ABSENT (key omitted) for non-callable kinds (module,
  attribute, property, variable) — NOT an empty string.
- No source content ever (no ``body``, ``source``, ``code``, ``snippet``,
  ``text`` keys; all string values must be single-line).
- ``line_end >= line_start``.

Fixture layout
--------------
tests/fixtures/resolve_project/
  mypackage/
    __init__.py
    _core/
      widgets.py   # Widget (class), make_widget (function), Widget.greet (method),
                   # Widget.display_name (property), Widget.color (attribute),
                   # DEFAULT_NAME (variable)

Known canonical handles
-----------------------
class      → mypackage._core.widgets.Widget
function   → mypackage._core.widgets.make_widget
method     → mypackage._core.widgets.Widget.greet
module     → mypackage._core.widgets
property   → mypackage._core.widgets.Widget.display_name
attribute  → mypackage._core.widgets.Widget.color
variable   → mypackage._core.widgets.DEFAULT_NAME
external   → pathlib.Path  (stdlib, scope="external")

These tests are SYNC (``build_stub`` is a plain function, no async) unless a
particular case requires async behaviour.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

_WIDGET_HANDLE = "mypackage._core.widgets.Widget"
_MAKE_WIDGET_HANDLE = "mypackage._core.widgets.make_widget"
_GREET_HANDLE = "mypackage._core.widgets.Widget.greet"
_CACHED_COMPUTE_HANDLE = "mypackage._core.decorated.Cached.cached_method"
_MODULE_HANDLE = "mypackage._core.widgets"
_DISPLAY_NAME_HANDLE = "mypackage._core.widgets.Widget.display_name"
_COLOR_HANDLE = "mypackage._core.widgets.Widget.color"
_DEFAULT_NAME_HANDLE = "mypackage._core.widgets.DEFAULT_NAME"
_PATH_CLASS_HANDLE = "pathlib.Path"

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_stub(handle: str, analyzer: JediAnalyzer) -> dict:
    """Fetch the Jedi name for *handle* and call build_stub."""
    from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle
    from pyeye.mcp.operations.stubs import build_stub

    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    return build_stub(jedi_name, handle, analyzer)


def _assert_stub_base(stub: dict, expected_handle: str, expected_kind: str) -> None:
    """Assert the universal fields shared by all stub shapes."""
    assert isinstance(stub, dict), "build_stub must return a dict"
    assert stub["handle"] == expected_handle, f"handle mismatch: {stub['handle']!r}"
    assert stub["kind"] == expected_kind, f"kind mismatch: {stub['kind']!r}"
    assert stub["scope"] in ("project", "external"), f"invalid scope: {stub['scope']!r}"
    assert isinstance(stub["line_start"], int), "line_start must be int"
    assert isinstance(stub["line_end"], int), "line_end must be int"
    assert (
        stub["line_end"] >= stub["line_start"]
    ), f"line_end ({stub['line_end']}) must be >= line_start ({stub['line_start']})"


def _assert_no_content(stub: dict) -> None:
    """Assert the stub contains no multi-line source content."""
    forbidden_keys = {"body", "source", "code", "snippet", "text"}
    for key in forbidden_keys:
        assert key not in stub, f"Stub must not contain '{key}' (source content violation)"
    # All string values must be single-line (no embedded newlines)
    for key, value in stub.items():
        if isinstance(value, str):
            assert "\n" not in value, (
                f"Stub field '{key}' must be single-line; " f"found embedded newline in {value!r}"
            )


# ---------------------------------------------------------------------------
# TestStubClass — kind="class"
# ---------------------------------------------------------------------------


class TestStubClass:
    """Stub for a class handle: callable kind, carries signature, project scope."""

    def test_class_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Class stub has handle, kind, scope, line_start, line_end."""
        stub = _get_stub(_WIDGET_HANDLE, analyzer)
        _assert_stub_base(stub, _WIDGET_HANDLE, "class")
        assert stub["scope"] == "project"

    def test_class_has_signature(self, analyzer: JediAnalyzer) -> None:
        """Class stub carries a signature (callable kind)."""
        stub = _get_stub(_WIDGET_HANDLE, analyzer)
        assert "signature" in stub, "class stub must have a 'signature' key"
        assert isinstance(stub["signature"], str), "signature must be str"
        assert stub["signature"], "signature must be non-empty for a class"

    def test_class_signature_is_single_line(self, analyzer: JediAnalyzer) -> None:
        """Class signature must be a single line (no embedded newlines)."""
        stub = _get_stub(_WIDGET_HANDLE, analyzer)
        assert "\n" not in stub["signature"], "class signature must be single-line"

    def test_class_no_content(self, analyzer: JediAnalyzer) -> None:
        """Class stub carries no source content."""
        stub = _get_stub(_WIDGET_HANDLE, analyzer)
        _assert_no_content(stub)

    def test_class_span(self, analyzer: JediAnalyzer) -> None:
        """Class stub span (line_start < line_end for a class with a body)."""
        stub = _get_stub(_WIDGET_HANDLE, analyzer)
        # Widget is a multi-line class, so line_end > line_start
        assert stub["line_end"] > stub["line_start"], "Widget class body should span multiple lines"


# ---------------------------------------------------------------------------
# TestStubFunction — kind="function"
# ---------------------------------------------------------------------------


class TestStubFunction:
    """Stub for a module-level function handle: callable kind, carries signature."""

    def test_function_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Function stub has handle, kind, scope, line_start, line_end."""
        stub = _get_stub(_MAKE_WIDGET_HANDLE, analyzer)
        _assert_stub_base(stub, _MAKE_WIDGET_HANDLE, "function")
        assert stub["scope"] == "project"

    def test_function_has_signature(self, analyzer: JediAnalyzer) -> None:
        """Function stub carries a signature (callable kind)."""
        stub = _get_stub(_MAKE_WIDGET_HANDLE, analyzer)
        assert "signature" in stub, "function stub must have a 'signature' key"
        assert isinstance(stub["signature"], str)
        assert stub["signature"]

    def test_function_signature_is_single_line(self, analyzer: JediAnalyzer) -> None:
        """Function signature must be a single line."""
        stub = _get_stub(_MAKE_WIDGET_HANDLE, analyzer)
        assert "\n" not in stub["signature"]

    def test_function_no_content(self, analyzer: JediAnalyzer) -> None:
        """Function stub carries no source content."""
        stub = _get_stub(_MAKE_WIDGET_HANDLE, analyzer)
        _assert_no_content(stub)


# ---------------------------------------------------------------------------
# TestStubMethod — kind="method"
# ---------------------------------------------------------------------------


class TestStubMethod:
    """Stub for a method handle: must have kind="method" (not "function")."""

    def test_method_kind(self, analyzer: JediAnalyzer) -> None:
        """Method stub has kind='method', not 'function'."""
        stub = _get_stub(_GREET_HANDLE, analyzer)
        assert (
            stub["kind"] == "method"
        ), f"Expected kind='method' for {_GREET_HANDLE!r}, got {stub['kind']!r}"

    def test_method_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Method stub has all universal fields."""
        stub = _get_stub(_GREET_HANDLE, analyzer)
        _assert_stub_base(stub, _GREET_HANDLE, "method")
        assert stub["scope"] == "project"

    def test_method_has_signature(self, analyzer: JediAnalyzer) -> None:
        """Method stub carries a signature (callable kind)."""
        stub = _get_stub(_GREET_HANDLE, analyzer)
        assert "signature" in stub, "method stub must have a 'signature' key"
        assert isinstance(stub["signature"], str)
        assert stub["signature"]

    def test_method_signature_is_single_line(self, analyzer: JediAnalyzer) -> None:
        """Method signature must be a single line."""
        stub = _get_stub(_GREET_HANDLE, analyzer)
        assert "\n" not in stub["signature"]

    def test_method_no_content(self, analyzer: JediAnalyzer) -> None:
        """Method stub carries no source content."""
        stub = _get_stub(_GREET_HANDLE, analyzer)
        _assert_no_content(stub)

    def test_decorated_method_renders_own_signature(self, analyzer: JediAnalyzer) -> None:
        """A @functools.cache-decorated method stub must carry its OWN signature,
        not the ``_lru_cache_wrapper`` artifact (#437) — this is the outline path.
        """
        stub = _get_stub(_CACHED_COMPUTE_HANDLE, analyzer)
        assert stub["signature"] == "cached_method(self, a: int, b: int=2) -> int"
        assert "_lru_cache_wrapper" not in stub["signature"]


# ---------------------------------------------------------------------------
# TestStubModule — kind="module"
# ---------------------------------------------------------------------------


class TestStubModule:
    """Stub for a module handle: non-callable kind, signature ABSENT."""

    def test_module_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Module stub has handle, kind, scope, line_start, line_end."""
        stub = _get_stub(_MODULE_HANDLE, analyzer)
        _assert_stub_base(stub, _MODULE_HANDLE, "module")
        assert stub["scope"] == "project"

    def test_module_no_signature(self, analyzer: JediAnalyzer) -> None:
        """Module stub must NOT have a 'signature' key (non-callable kind)."""
        stub = _get_stub(_MODULE_HANDLE, analyzer)
        assert "signature" not in stub, f"module stub must NOT have 'signature'; got stub={stub!r}"

    def test_module_no_content(self, analyzer: JediAnalyzer) -> None:
        """Module stub carries no source content."""
        stub = _get_stub(_MODULE_HANDLE, analyzer)
        _assert_no_content(stub)


# ---------------------------------------------------------------------------
# TestStubProperty — kind="property" (or "method" — Jedi limitation)
# ---------------------------------------------------------------------------


class TestStubProperty:
    """Stub for a @property handle.

    Jedi returns ``type="function"`` for ``@property``-decorated methods, and
    ``_is_method`` sees them as functions inside a class, so the effective kind
    is ``"method"`` — the same result that ``inspect`` produces (see
    test_inspect.py: ``kind in ("property", "function", "method")``).

    We accept both ``"property"`` and ``"method"`` here to pin the observable
    contract without over-specifying the Jedi backend's type vocabulary.
    """

    def test_property_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Property stub has handle, scope, line_start, line_end; kind is
        one of the accepted property-or-method values."""
        stub = _get_stub(_DISPLAY_NAME_HANDLE, analyzer)
        assert stub["handle"] == _DISPLAY_NAME_HANDLE
        assert stub["kind"] in ("property", "method"), (
            f"Expected kind in ('property','method') for {_DISPLAY_NAME_HANDLE!r}, "
            f"got {stub['kind']!r}"
        )
        assert stub["scope"] == "project"
        assert isinstance(stub["line_start"], int)
        assert isinstance(stub["line_end"], int)
        assert stub["line_end"] >= stub["line_start"]

    def test_property_no_signature(self, analyzer: JediAnalyzer) -> None:
        """Property stub must NOT have a 'signature' key.

        Jedi types ``@property`` as a function/method but ``_build_signature``
        returns ``None`` for it (no call signatures available).  After the fix,
        ``build_stub`` gates ``signature`` on a REAL Jedi signature, so the key
        must be absent regardless of whether Jedi calls it 'property' or 'method'.
        """
        stub = _get_stub(_DISPLAY_NAME_HANDLE, analyzer)
        assert (
            "signature" not in stub
        ), f"property stub must NOT have 'signature'; got stub={stub!r}"

    def test_property_no_content(self, analyzer: JediAnalyzer) -> None:
        """Property stub carries no source content."""
        stub = _get_stub(_DISPLAY_NAME_HANDLE, analyzer)
        _assert_no_content(stub)


# ---------------------------------------------------------------------------
# TestStubAttribute — kind="attribute"
# ---------------------------------------------------------------------------


class TestStubAttribute:
    """Stub for a class attribute (ClassVar): non-callable kind, signature ABSENT."""

    def test_attribute_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Attribute stub has handle, kind='attribute', scope, line_start, line_end."""
        stub = _get_stub(_COLOR_HANDLE, analyzer)
        # Jedi might return 'statement' → 'variable' or 'attribute' — accept both,
        # but pin what we get so the contract is explicit. The spec says 'attribute'
        # is one of the API kinds; Jedi may or may not distinguish it from 'variable'.
        assert stub["kind"] in ("attribute", "variable"), (
            f"Expected kind in ('attribute','variable') for {_COLOR_HANDLE!r}, "
            f"got {stub['kind']!r}"
        )
        assert stub["handle"] == _COLOR_HANDLE
        assert stub["scope"] == "project"
        assert isinstance(stub["line_start"], int)
        assert isinstance(stub["line_end"], int)
        assert stub["line_end"] >= stub["line_start"]

    def test_attribute_no_signature(self, analyzer: JediAnalyzer) -> None:
        """Attribute stub must NOT have a 'signature' key."""
        stub = _get_stub(_COLOR_HANDLE, analyzer)
        assert (
            "signature" not in stub
        ), f"attribute stub must NOT have 'signature'; got stub={stub!r}"

    def test_attribute_no_content(self, analyzer: JediAnalyzer) -> None:
        """Attribute stub carries no source content."""
        stub = _get_stub(_COLOR_HANDLE, analyzer)
        _assert_no_content(stub)


# ---------------------------------------------------------------------------
# TestStubVariable — kind="variable"
# ---------------------------------------------------------------------------


class TestStubVariable:
    """Stub for a module-level variable: non-callable kind, signature ABSENT."""

    def test_variable_universal_fields(self, analyzer: JediAnalyzer) -> None:
        """Variable stub has handle, kind='variable', scope, line_start, line_end."""
        stub = _get_stub(_DEFAULT_NAME_HANDLE, analyzer)
        _assert_stub_base(stub, _DEFAULT_NAME_HANDLE, "variable")
        assert stub["scope"] == "project"

    def test_variable_no_signature(self, analyzer: JediAnalyzer) -> None:
        """Variable stub must NOT have a 'signature' key (non-callable kind)."""
        stub = _get_stub(_DEFAULT_NAME_HANDLE, analyzer)
        assert (
            "signature" not in stub
        ), f"variable stub must NOT have 'signature'; got stub={stub!r}"

    def test_variable_no_content(self, analyzer: JediAnalyzer) -> None:
        """Variable stub carries no source content."""
        stub = _get_stub(_DEFAULT_NAME_HANDLE, analyzer)
        _assert_no_content(stub)


# ---------------------------------------------------------------------------
# TestStubExternal — scope="external"
# ---------------------------------------------------------------------------


class TestStubExternal:
    """Stub for an external (stdlib) symbol: scope="external"."""

    def test_external_scope(self, analyzer: JediAnalyzer) -> None:
        """pathlib.Path stub has scope='external'."""
        stub = _get_stub(_PATH_CLASS_HANDLE, analyzer)
        assert (
            stub["scope"] == "external"
        ), f"pathlib.Path must have scope='external'; got {stub['scope']!r}"

    def test_external_kind_class(self, analyzer: JediAnalyzer) -> None:
        """pathlib.Path is a class; kind must be 'class'."""
        stub = _get_stub(_PATH_CLASS_HANDLE, analyzer)
        assert stub["kind"] == "class"

    def test_external_handle(self, analyzer: JediAnalyzer) -> None:
        """External stub has the expected handle."""
        stub = _get_stub(_PATH_CLASS_HANDLE, analyzer)
        assert stub["handle"] == _PATH_CLASS_HANDLE

    def test_external_no_content(self, analyzer: JediAnalyzer) -> None:
        """External stub carries no source content."""
        stub = _get_stub(_PATH_CLASS_HANDLE, analyzer)
        _assert_no_content(stub)


# ---------------------------------------------------------------------------
# TestNoContentInvariant — layering invariant at the unit level
# ---------------------------------------------------------------------------


class TestNoContentInvariant:
    """No stub field ever carries multi-line source content."""

    @pytest.mark.parametrize(
        "handle",
        [
            _WIDGET_HANDLE,
            _MAKE_WIDGET_HANDLE,
            _GREET_HANDLE,
            _MODULE_HANDLE,
            _DISPLAY_NAME_HANDLE,
            _DEFAULT_NAME_HANDLE,
        ],
    )
    def test_no_multiline_values(self, handle: str, analyzer: JediAnalyzer) -> None:
        """Every string value in the stub is single-line."""
        stub = _get_stub(handle, analyzer)
        _assert_no_content(stub)

    @pytest.mark.parametrize(
        "handle",
        [
            _WIDGET_HANDLE,
            _MAKE_WIDGET_HANDLE,
            _GREET_HANDLE,
            _MODULE_HANDLE,
            _DISPLAY_NAME_HANDLE,
            _DEFAULT_NAME_HANDLE,
        ],
    )
    def test_no_source_content_keys(self, handle: str, analyzer: JediAnalyzer) -> None:
        """Stub dict has no 'body', 'source', 'code', 'snippet', or 'text' key."""
        stub = _get_stub(handle, analyzer)
        forbidden_keys = {"body", "source", "code", "snippet", "text"}
        present_forbidden = forbidden_keys & set(stub.keys())
        assert not present_forbidden, (
            f"Stub for {handle!r} contains forbidden source-content keys: " f"{present_forbidden!r}"
        )


# ---------------------------------------------------------------------------
# TestStubShape — explicit key inventory
# ---------------------------------------------------------------------------


class TestStubShape:
    """The stub dict contains EXACTLY the fields specified in §4.1, nothing more."""

    def test_callable_kind_exact_keys(self, analyzer: JediAnalyzer) -> None:
        """Callable-kind stub (function) has exactly: handle, kind, scope, signature,
        line_start, line_end — no extra keys."""
        stub = _get_stub(_MAKE_WIDGET_HANDLE, analyzer)
        expected_keys = {"handle", "kind", "scope", "signature", "line_start", "line_end"}
        assert set(stub.keys()) == expected_keys, (
            f"Unexpected keys in function stub: got {set(stub.keys())!r}, "
            f"expected {expected_keys!r}"
        )

    def test_non_callable_kind_exact_keys(self, analyzer: JediAnalyzer) -> None:
        """Non-callable-kind stub (variable) has exactly: handle, kind, scope,
        line_start, line_end — 'signature' must be absent."""
        stub = _get_stub(_DEFAULT_NAME_HANDLE, analyzer)
        expected_keys = {"handle", "kind", "scope", "line_start", "line_end"}
        assert set(stub.keys()) == expected_keys, (
            f"Unexpected keys in variable stub: got {set(stub.keys())!r}, "
            f"expected {expected_keys!r}"
        )
