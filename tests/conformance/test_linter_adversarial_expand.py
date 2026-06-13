"""Adversarial test suite for the conformance linter — Stub + ExpandResult shapes.

Each test targets one specific structural-floor or layering violation for the
``expand`` operation (discriminated-union ExpandResult) and for the ``stub``
operation (standalone Stub validation).

Rule tags enforced here:
    E.1  source/edge present and str
    E.2  Discriminated-union exclusivity (supported vs unsupported branch)
    E.3  unresolved_call_sites enforcement (callees-supported only)
    E.4  Each Stub in stubs passes Stub structural-floor + layering
    S.1  Required Stub keys + correct types
    S.2  signature optional; when present, single-line str only
    S.3  No source-content keys in Stub (layering)

Sections:
    TestExpandAcceptsValidResponses   — no false positives on clean data
    TestExpandDiscriminatedUnion       — E.2 union-exclusivity rejection
    TestExpandSourceEdgeRequired       — E.1 required-field rejection
    TestExpandUnresolvedCallSites      — E.3 placement enforcement
    TestExpandStubsLayering            — E.4 + S.3 source-content in stubs/expand
    TestStubStructuralFloor            — S.1 + S.2 Stub field requirements
    TestStubLayering                   — S.3 Stub no-source-content
    TestRealExpandOutputConforms       — dogfood: real expand output passes linter
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tests.conformance.response_linter import ConformanceViolation, lint_response

# ---------------------------------------------------------------------------
# Fixture path (for real-operation dogfood test)
# ---------------------------------------------------------------------------

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "resolve_project"

# ---------------------------------------------------------------------------
# Minimal valid objects (used as starting points; mutate via _clone)
# ---------------------------------------------------------------------------

# A well-formed Stub for a callable (function/method/class) — has signature
_VALID_STUB_CALLABLE: dict = {
    "handle": "mypackage._core.widgets.Widget",
    "kind": "class",
    "scope": "project",
    "signature": "Widget(name: str)",
    "line_start": 10,
    "line_end": 50,
}

# A well-formed Stub for a non-callable (variable/attribute) — no signature
_VALID_STUB_NONCALLABLE: dict = {
    "handle": "mypackage._core.widgets.Widget.default_color",
    "kind": "attribute",
    "scope": "project",
    "line_start": 12,
    "line_end": 12,
}

# A well-formed supported members ExpandResult
_VALID_EXPAND_MEMBERS: dict = {
    "source": "mypackage._core.widgets.Widget",
    "edge": "members",
    "stubs": [
        {
            "handle": "mypackage._core.widgets.Widget.render",
            "kind": "method",
            "scope": "project",
            "signature": "render(self) -> str",
            "line_start": 20,
            "line_end": 25,
        }
    ],
}

# A well-formed supported callees ExpandResult (with unresolved_call_sites)
_VALID_EXPAND_CALLEES: dict = {
    "source": "mypackage._core.widgets.Widget.render",
    "edge": "callees",
    "stubs": [
        {
            "handle": "mypackage._core.utils.format_name",
            "kind": "function",
            "scope": "project",
            "signature": "format_name(s: str) -> str",
            "line_start": 5,
            "line_end": 8,
        }
    ],
    "unresolved_call_sites": 2,
}

# A well-formed unsupported ExpandResult — deferred_reference_backend reason
_VALID_EXPAND_UNSUPPORTED_DEFERRED: dict = {
    "source": "mypackage._core.widgets.Widget",
    "edge": "callers",
    "unsupported": True,
    "reason": "deferred_reference_backend",
    "detail": "Edge 'callers' requires the Pyright reference backend.",
}

# A well-formed unsupported ExpandResult — not_yet_implemented reason
_VALID_EXPAND_UNSUPPORTED_NYI: dict = {
    "source": "mypackage._core.widgets.Widget",
    "edge": "superclasses",
    "unsupported": True,
    "reason": "not_yet_implemented",
    "detail": "Edge 'superclasses' is planned but not implemented in this slice.",
}

# A well-formed unsupported ExpandResult — unknown_edge reason
_VALID_EXPAND_UNSUPPORTED_UNKNOWN: dict = {
    "source": "mypackage._core.widgets.Widget",
    "edge": "no_such_edge",
    "unsupported": True,
    "reason": "unknown_edge",
    "detail": "Unknown edge 'no_such_edge'.",
}


def _clone(d: dict) -> dict:
    """Deep-copy a dict so tests can mutate without cross-contamination."""
    return copy.deepcopy(d)


# ===========================================================================
# Valid responses — verify no false positives on clean data
# ===========================================================================


class TestExpandAcceptsValidResponses:
    """Verify the linter does NOT raise on spec-compliant ExpandResult shapes."""

    def test_supported_members_passes(self) -> None:
        """A well-formed supported members ExpandResult passes all checks."""
        lint_response(_clone(_VALID_EXPAND_MEMBERS), "expand")

    def test_supported_callees_with_unresolved_passes(self) -> None:
        """A supported callees ExpandResult with unresolved_call_sites passes."""
        lint_response(_clone(_VALID_EXPAND_CALLEES), "expand")

    def test_unsupported_deferred_reference_passes(self) -> None:
        """Unsupported branch with reason=deferred_reference_backend passes."""
        lint_response(_clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED), "expand")

    def test_unsupported_not_yet_implemented_passes(self) -> None:
        """Unsupported branch with reason=not_yet_implemented passes."""
        lint_response(_clone(_VALID_EXPAND_UNSUPPORTED_NYI), "expand")

    def test_unsupported_unknown_edge_passes(self) -> None:
        """Unsupported branch with reason=unknown_edge passes."""
        lint_response(_clone(_VALID_EXPAND_UNSUPPORTED_UNKNOWN), "expand")

    def test_supported_members_empty_stubs_passes(self) -> None:
        """stubs=[] is a valid supported result (measured-empty, not unsupported)."""
        good = _clone(_VALID_EXPAND_MEMBERS)
        good["stubs"] = []
        lint_response(good, "expand")

    def test_supported_callees_empty_stubs_with_unresolved_passes(self) -> None:
        """callees with stubs=[] and unresolved_call_sites=0 is valid."""
        good = _clone(_VALID_EXPAND_CALLEES)
        good["stubs"] = []
        good["unresolved_call_sites"] = 0
        lint_response(good, "expand")

    def test_standalone_callable_stub_passes(self) -> None:
        """A well-formed callable Stub (with signature) passes lint_response(..., 'stub')."""
        lint_response(_clone(_VALID_STUB_CALLABLE), "stub")

    def test_standalone_noncallable_stub_passes(self) -> None:
        """A well-formed non-callable Stub (no signature) passes lint_response(..., 'stub')."""
        lint_response(_clone(_VALID_STUB_NONCALLABLE), "stub")

    def test_external_scope_stub_passes(self) -> None:
        """A Stub with scope='external' passes."""
        good = _clone(_VALID_STUB_CALLABLE)
        good["scope"] = "external"
        lint_response(good, "stub")

    def test_stub_line_start_equals_line_end_passes(self) -> None:
        """Stub with line_start == line_end (single-line) passes."""
        good = _clone(_VALID_STUB_NONCALLABLE)
        good["line_start"] = 5
        good["line_end"] = 5
        lint_response(good, "stub")


# ===========================================================================
# E.1 — source and edge required fields
# ===========================================================================


class TestExpandSourceEdgeRequired:
    """E.1 — source and edge must be present and be strings."""

    def test_missing_source_rejected(self) -> None:
        """ExpandResult without 'source' raises with E.1."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        del bad["source"]
        with pytest.raises(ConformanceViolation, match="E.1"):
            lint_response(bad, "expand")

    def test_missing_edge_rejected(self) -> None:
        """ExpandResult without 'edge' raises with E.1."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        del bad["edge"]
        with pytest.raises(ConformanceViolation, match="E.1"):
            lint_response(bad, "expand")

    def test_source_non_string_rejected(self) -> None:
        """source with a non-string value (e.g. int) raises with E.1."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["source"] = 42
        with pytest.raises(ConformanceViolation, match="E.1"):
            lint_response(bad, "expand")

    def test_edge_non_string_rejected(self) -> None:
        """edge with a non-string value (e.g. None) raises with E.1."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["edge"] = None
        with pytest.raises(ConformanceViolation, match="E.1"):
            lint_response(bad, "expand")

    def test_missing_source_in_unsupported_rejected(self) -> None:
        """E.1 applies to unsupported branch too — missing source raises."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        del bad["source"]
        with pytest.raises(ConformanceViolation, match="E.1"):
            lint_response(bad, "expand")

    def test_multiline_source_rejected(self) -> None:
        """source with an embedded newline raises E.1 (must be a single-line handle)."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["source"] = "mypackage._core.widgets.Widget\nextra line"
        with pytest.raises(ConformanceViolation, match=r"E\.1.*single-line|single-line.*E\.1"):
            lint_response(bad, "expand")

    def test_multiline_edge_rejected(self) -> None:
        """edge with an embedded newline raises E.1 (must be a single-line edge name)."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["edge"] = "members\nextra line"
        with pytest.raises(ConformanceViolation, match=r"E\.1.*single-line|single-line.*E\.1"):
            lint_response(bad, "expand")


# ===========================================================================
# E.2 — Discriminated-union exclusivity
# ===========================================================================


class TestExpandDiscriminatedUnion:
    """E.2 — exactly one branch; garbled/blended results are rejected."""

    def test_both_stubs_and_unsupported_rejected(self) -> None:
        """Having both 'stubs' and 'unsupported' is key bleed — rejected with E.2."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["unsupported"] = True
        bad["reason"] = "unknown_edge"
        bad["detail"] = "bleed"
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_neither_stubs_nor_unsupported_rejected(self) -> None:
        """A result with neither 'stubs' nor 'unsupported' is garbled — rejected with E.2."""
        bad = {
            "source": "mypackage.Widget",
            "edge": "members",
            # no stubs, no unsupported
        }
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_false_rejected(self) -> None:
        """unsupported=False is not the boolean True sentinel — rejected with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        bad["unsupported"] = False
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_not_bool_rejected(self) -> None:
        """unsupported='true' (str, not bool) is rejected with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        bad["unsupported"] = "true"
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_without_reason_rejected(self) -> None:
        """Unsupported branch missing 'reason' raises with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        del bad["reason"]
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_without_detail_rejected(self) -> None:
        """Unsupported branch missing 'detail' raises with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        del bad["detail"]
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_with_unknown_reason_rejected(self) -> None:
        """Unsupported branch with an unrecognised reason string raises with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        bad["reason"] = "some_future_reason"
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_with_stubs_rejected(self) -> None:
        """Unsupported branch must NOT contain 'stubs' — rejected with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        bad["stubs"] = []
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_stubs_not_a_list_rejected(self) -> None:
        """stubs present but not a list (e.g. dict) is malformed — rejected with E.2."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["stubs"] = {"handle": "pkg.X"}
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_empty_detail_rejected(self) -> None:
        """Unsupported branch with empty-string detail raises with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        bad["detail"] = ""
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")

    def test_unsupported_non_string_reason_rejected(self) -> None:
        """Unsupported branch with reason=None (non-str) raises with E.2."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        bad["reason"] = None
        with pytest.raises(ConformanceViolation, match="E.2"):
            lint_response(bad, "expand")


# ===========================================================================
# E.3 — unresolved_call_sites placement enforcement
# ===========================================================================


class TestExpandUnresolvedCallSites:
    """E.3 — unresolved_call_sites must appear only on supported callees results."""

    def test_unresolved_on_members_supported_rejected(self) -> None:
        """unresolved_call_sites on a supported members result raises with E.3."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["unresolved_call_sites"] = 3
        with pytest.raises(ConformanceViolation, match="E.3"):
            lint_response(bad, "expand")

    def test_unresolved_on_unsupported_branch_rejected(self) -> None:
        """unresolved_call_sites on the unsupported branch raises with E.3."""
        bad = _clone(_VALID_EXPAND_UNSUPPORTED_DEFERRED)
        bad["unresolved_call_sites"] = 1
        with pytest.raises(ConformanceViolation, match="E.3"):
            lint_response(bad, "expand")

    def test_unresolved_non_int_rejected(self) -> None:
        """unresolved_call_sites with a non-int value (str) raises with E.3."""
        bad = _clone(_VALID_EXPAND_CALLEES)
        bad["unresolved_call_sites"] = "5"
        with pytest.raises(ConformanceViolation, match="E.3"):
            lint_response(bad, "expand")

    def test_unresolved_bool_rejected(self) -> None:
        """unresolved_call_sites with bool (True) raises with E.3 (bool is not plain int)."""
        bad = _clone(_VALID_EXPAND_CALLEES)
        bad["unresolved_call_sites"] = True
        with pytest.raises(ConformanceViolation, match="E.3"):
            lint_response(bad, "expand")

    def test_unresolved_none_rejected(self) -> None:
        """unresolved_call_sites=None raises with E.3."""
        bad = _clone(_VALID_EXPAND_CALLEES)
        bad["unresolved_call_sites"] = None
        with pytest.raises(ConformanceViolation, match="E.3"):
            lint_response(bad, "expand")

    def test_unresolved_zero_on_callees_passes(self) -> None:
        """unresolved_call_sites=0 on a supported callees result is valid."""
        good = _clone(_VALID_EXPAND_CALLEES)
        good["unresolved_call_sites"] = 0
        lint_response(good, "expand")

    def test_unresolved_absent_on_members_passes(self) -> None:
        """Absence of unresolved_call_sites on a members result is valid."""
        good = _clone(_VALID_EXPAND_MEMBERS)
        assert "unresolved_call_sites" not in good
        lint_response(good, "expand")


# ===========================================================================
# E.4 + S.3 — Source-content smuggling in stubs list / ExpandResult
# ===========================================================================


class TestExpandStubsLayering:
    """E.4 + S.3 — Source-content violations in ExpandResult and nested Stubs."""

    def test_body_key_in_stub_rejected(self) -> None:
        """A Stub inside stubs[] with a 'body' key raises (layering violation)."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["stubs"][0]["body"] = "def render(self): ..."
        with pytest.raises(ConformanceViolation, match=r"Key 'body'"):
            lint_response(bad, "expand")

    def test_source_key_in_stub_rejected(self) -> None:
        """A Stub inside stubs[] with a 'source' key raises.

        Note: the top-level 'source' field is checked by E.1 but any 'source'
        key NESTED inside a stub dict is a layering violation (A.2).
        """
        bad = _clone(_VALID_EXPAND_CALLEES)
        bad["stubs"][0]["source"] = "def format_name(s): return s.title()"
        with pytest.raises(ConformanceViolation, match=r"Key 'source'"):
            lint_response(bad, "expand")

    def test_code_key_in_stub_rejected(self) -> None:
        """A Stub inside stubs[] with a 'code' key raises."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["stubs"][0]["code"] = "..."
        with pytest.raises(ConformanceViolation, match=r"Key 'code'"):
            lint_response(bad, "expand")

    def test_snippet_key_in_stub_rejected(self) -> None:
        """A Stub inside stubs[] with a 'snippet' key raises."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["stubs"][0]["snippet"] = "Widget(name)"
        with pytest.raises(ConformanceViolation, match=r"Key 'snippet'"):
            lint_response(bad, "expand")

    def test_multiline_signature_in_stub_rejected(self) -> None:
        """A Stub signature with more than 5 lines raises (multi-line A.1 check)."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["stubs"][0]["signature"] = "\n".join([f"line_{i}" for i in range(10)])
        with pytest.raises(ConformanceViolation, match="multi-line"):
            lint_response(bad, "expand")

    def test_indented_block_in_stub_field_rejected(self) -> None:
        """A Stub field value containing '    def ' raises (A.4 indented-block)."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["stubs"][0]["description"] = "class body:\n    def method(self): ..."
        with pytest.raises(ConformanceViolation, match="indented"):
            lint_response(bad, "expand")

    def test_body_key_on_expand_result_itself_rejected(self) -> None:
        """A 'body' key on the ExpandResult dict itself raises."""
        bad = _clone(_VALID_EXPAND_MEMBERS)
        bad["body"] = "some code"
        with pytest.raises(ConformanceViolation, match=r"Key 'body'"):
            lint_response(bad, "expand")


# ===========================================================================
# S.1 — Stub structural floor (required keys + types)
# ===========================================================================


class TestStubStructuralFloor:
    """S.1 — Stub required keys and their type constraints."""

    def test_missing_handle_rejected(self) -> None:
        """Stub missing 'handle' raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        del bad["handle"]
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_missing_kind_rejected(self) -> None:
        """Stub missing 'kind' raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        del bad["kind"]
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_missing_scope_rejected(self) -> None:
        """Stub missing 'scope' raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        del bad["scope"]
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_missing_line_start_rejected(self) -> None:
        """Stub missing 'line_start' raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        del bad["line_start"]
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_missing_line_end_rejected(self) -> None:
        """Stub missing 'line_end' raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        del bad["line_end"]
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_handle_non_string_rejected(self) -> None:
        """Stub with handle as int raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["handle"] = 42
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_kind_non_string_rejected(self) -> None:
        """Stub with kind as None raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["kind"] = None
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_scope_invalid_value_rejected(self) -> None:
        """Stub with scope='internal' (not project/external) raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["scope"] = "internal"
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_scope_non_string_rejected(self) -> None:
        """Stub with scope=None raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["scope"] = None
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_line_start_string_rejected(self) -> None:
        """Stub with line_start as str raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["line_start"] = "10"
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_line_start_bool_rejected(self) -> None:
        """Stub with line_start=True (bool) raises with S.1 (bool is not plain int)."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["line_start"] = True
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_line_end_bool_rejected(self) -> None:
        """Stub with line_end=False (bool) raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["line_end"] = False
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")

    def test_line_end_less_than_line_start_rejected(self) -> None:
        """Stub with line_end < line_start raises with S.1."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["line_start"] = 20
        bad["line_end"] = 10
        with pytest.raises(ConformanceViolation, match="S.1"):
            lint_response(bad, "stub")


# ===========================================================================
# S.2 — signature optional; when present must be single-line
# ===========================================================================


class TestStubSignatureConstraint:
    """S.2 — signature is optional; when present it must be a single-line str."""

    def test_signature_absent_allowed(self) -> None:
        """Stub without signature (non-callable) passes S.2."""
        good = _clone(_VALID_STUB_NONCALLABLE)
        assert "signature" not in good
        lint_response(good, "stub")

    def test_signature_single_line_allowed(self) -> None:
        """Stub with a normal single-line signature passes S.2."""
        good = _clone(_VALID_STUB_CALLABLE)
        good["signature"] = "Widget(name: str, color: str = 'blue') -> None"
        lint_response(good, "stub")

    def test_signature_multiline_rejected(self) -> None:
        """Stub with a multi-line signature raises with S.2."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["signature"] = "Widget(\n    name: str,\n    color: str\n)"
        with pytest.raises(ConformanceViolation, match="S.2"):
            lint_response(bad, "stub")

    def test_signature_non_string_rejected(self) -> None:
        """Stub with signature as int raises with S.2."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["signature"] = 42
        with pytest.raises(ConformanceViolation, match="S.2"):
            lint_response(bad, "stub")


# ===========================================================================
# S.3 — Stub no-source-content (layering on standalone Stubs)
# ===========================================================================


class TestStubLayering:
    """S.3 — Standalone Stub must not carry source-content keys."""

    def test_body_key_in_stub_rejected(self) -> None:
        """Standalone Stub with 'body' key raises."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["body"] = "def render(self): ..."
        with pytest.raises(ConformanceViolation, match=r"Key 'body'"):
            lint_response(bad, "stub")

    def test_source_key_in_stub_rejected(self) -> None:
        """Standalone Stub with 'source' key raises."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["source"] = "class Widget: ..."
        with pytest.raises(ConformanceViolation, match=r"Key 'source'"):
            lint_response(bad, "stub")

    def test_code_key_in_stub_rejected(self) -> None:
        """Standalone Stub with 'code' key raises."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["code"] = "Widget()"
        with pytest.raises(ConformanceViolation, match=r"Key 'code'"):
            lint_response(bad, "stub")

    def test_text_key_in_stub_rejected(self) -> None:
        """Standalone Stub with 'text' key raises."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["text"] = "some text"
        with pytest.raises(ConformanceViolation, match=r"Key 'text'"):
            lint_response(bad, "stub")

    def test_source_body_substring_key_rejected(self) -> None:
        """Standalone Stub with 'method_body' (substring '_body') key raises."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["method_body"] = "..."
        with pytest.raises(ConformanceViolation, match="_body"):
            lint_response(bad, "stub")

    def test_multiline_string_in_stub_field_rejected(self) -> None:
        """Standalone Stub with a multi-line string value raises (A.1)."""
        bad = _clone(_VALID_STUB_CALLABLE)
        bad["description"] = "\n".join([f"line_{i}" for i in range(10)])
        with pytest.raises(ConformanceViolation, match="multi-line"):
            lint_response(bad, "stub")


# ===========================================================================
# Dogfood: real expand output passes the linter
# ===========================================================================


class TestRealExpandOutputConforms:
    """Dogfood test: the REAL expand operation produces conformant output.

    Uses the JediAnalyzer pattern from test_traversal_integration.py.
    Asserts lint_response(result, 'expand') does NOT raise.
    """

    @pytest.mark.asyncio
    async def test_real_members_output_conforms(self) -> None:
        """Real expand(Widget, members) output passes the conformance linter."""
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.expand import expand

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await expand("mypackage._core.widgets.Widget", "members", analyzer)

        assert isinstance(result, dict), f"result must be a dict; got {type(result)!r}"
        lint_response(result, "expand")  # must not raise

    @pytest.mark.asyncio
    async def test_real_callees_output_conforms(self) -> None:
        """Real expand(Widget.render, callees) output passes the conformance linter."""
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.expand import expand

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await expand("mypackage._core.widgets.Widget.render", "callees", analyzer)

        assert isinstance(result, dict), f"result must be a dict; got {type(result)!r}"
        lint_response(result, "expand")  # must not raise

    @pytest.mark.asyncio
    async def test_real_deferred_edge_output_conforms(self) -> None:
        """Real expand(Widget, callers) returns unsupported branch that passes the linter."""
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.expand import expand

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await expand("mypackage._core.widgets.Widget", "callers", analyzer)

        assert isinstance(result, dict), f"result must be a dict; got {type(result)!r}"
        lint_response(result, "expand")  # must not raise

    @pytest.mark.asyncio
    async def test_real_imported_by_module_output_conforms(self) -> None:
        """Real expand(widgets module, imported_by) supported branch passes the linter.

        The supported ``imported_by`` result carries ``source``/``edge``/``stubs``
        with no ``unresolved_call_sites`` — the existing E.3 rule must accept it
        (because E.3 only requires the field for ``edge == "callees"``).
        """
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.expand import expand

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await expand("mypackage._core.widgets", "imported_by", analyzer)

        assert isinstance(result, dict), f"result must be a dict; got {type(result)!r}"
        # Supported branch — stubs present, no unsupported key.
        assert "stubs" in result, f"expected supported branch with stubs; got {result!r}"
        assert "unsupported" not in result
        lint_response(result, "expand")  # must not raise

    @pytest.mark.asyncio
    async def test_real_imported_by_non_module_output_conforms(self) -> None:
        """Real expand(Widget class, imported_by) unsupported branch passes the linter.

        The ``not_yet_implemented`` reason is already in the linter's
        ``_VALID_UNSUPPORTED_REASONS`` set — no linter change needed.
        """
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.expand import expand

        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await expand("mypackage._core.widgets.Widget", "imported_by", analyzer)

        assert isinstance(result, dict), f"result must be a dict; got {type(result)!r}"
        # Unsupported branch — reason=not_yet_implemented.
        assert result.get("unsupported") is True
        assert result.get("reason") == "not_yet_implemented"
        lint_response(result, "expand")  # must not raise


# ===========================================================================
# imported_by remains in _PHASE4_UNMEASURED_EDGES (inspect edge_counts guard)
# ===========================================================================


class TestImportedByRemainsInUnmeasuredEdges:
    """Read-only assertion: imported_by is still forbidden in inspect edge_counts.

    ``imported_by`` is now a supported ``expand`` edge, but ``inspect`` does NOT
    measure it in ``edge_counts`` (that would require a separate inspection pass
    per module).  It must therefore remain in ``_PHASE4_UNMEASURED_EDGES`` so
    that B.3 continues to reject any inspect response that fraudulently claims to
    have measured it.

    This test is a READ-ONLY assertion on the constant — it does NOT modify the
    linter.  If this test fails it means ``imported_by`` was removed from
    ``_PHASE4_UNMEASURED_EDGES`` without a corresponding ``inspect`` measurement
    implementation, which would allow the B.3 false-measurement guard to be
    silently bypassed.
    """

    def test_imported_by_is_in_phase4_unmeasured_edges(self) -> None:
        """``imported_by`` must be in ``_PHASE4_UNMEASURED_EDGES`` (read-only assertion)."""
        from tests.conformance.response_linter import _PHASE4_UNMEASURED_EDGES

        assert "imported_by" in _PHASE4_UNMEASURED_EDGES, (
            "'imported_by' was removed from _PHASE4_UNMEASURED_EDGES without adding "
            "a corresponding measurement to inspect.py.  The B.3 guard would then silently "
            "accept inspect responses that fraudulently claim a measured imported_by count. "
            "Either restore the entry or add the inspect measurement and update the expected "
            "edges for module/class kinds in _PHASE4_EXPECTED_EDGES."
        )
