"""Adversarial test suite for the conformance linter — ``found`` discriminator.

Each test targets one Check N violation for the ``inspect`` / ``outline`` /
``expand`` operations (#545).

Rule tags enforced here:
    N.1  ``found`` is REQUIRED and exactly ``True`` / ``False``.
    N.2  ``found: False`` ⇒ exactly ``{found, handle, reason, detail}`` (plus
         ``edge`` for ``expand``), single-line strs, ``reason`` ∈ {unresolved}.
    N.3  ``found`` only on the ROOT of an outline response.
"""

from __future__ import annotations

import copy

import pytest

from tests.conformance.response_linter import ConformanceViolation, lint_response

_DETAIL = "Handle 'pkg.Ghost' did not resolve to a symbol. Call resolve('Ghost') to find it."

_NOT_FOUND: dict = {
    "found": False,
    "handle": "pkg.Ghost",
    "reason": "unresolved",
    "detail": _DETAIL,
}
_EXPAND_NOT_FOUND: dict = {**_NOT_FOUND, "edge": "members"}

_STUB: dict = {
    "handle": "pkg.mod.Widget",
    "kind": "class",
    "scope": "project",
    "line_start": 1,
    "line_end": 10,
}


def _not_found_for(operation: str) -> dict:
    return copy.deepcopy(_EXPAND_NOT_FOUND if operation == "expand" else _NOT_FOUND)


_OPERATIONS = ["inspect", "outline", "expand"]


class TestValidNotFoundPasses:
    @pytest.mark.parametrize("operation", _OPERATIONS)
    def test_canonical_not_found_shape_passes(self, operation: str) -> None:
        lint_response(_not_found_for(operation), operation)


class TestN1FoundRequired:
    @pytest.mark.parametrize("operation", _OPERATIONS)
    def test_missing_found_rejected(self, operation: str) -> None:
        response = _not_found_for(operation)
        del response["found"]
        with pytest.raises(ConformanceViolation, match=r"N\.1"):
            lint_response(response, operation)

    @pytest.mark.parametrize("bad", [0, 1, "false", None])
    def test_non_bool_found_rejected(self, bad: object) -> None:
        response = _not_found_for("inspect")
        response["found"] = bad
        with pytest.raises(ConformanceViolation, match=r"N\.1"):
            lint_response(response, "inspect")

    def test_legacy_resolve_shape_is_no_longer_exempt(self) -> None:
        """#626 moved resolve onto N.2; the old ``{found, reason}`` shape now fails."""
        with pytest.raises(ConformanceViolation, match=r"N\.2.*missing=\['detail', 'identifier'\]"):
            lint_response({"found": False, "reason": "unresolved"}, "resolve")


class TestN2PerOperation:
    """#626: echo keys and reasons are per operation."""

    _RESOLVE = {
        "found": False,
        "identifier": "pkg.Thing",
        "reason": "unresolved",
        "detail": "Call resolve('Thing').",
    }
    _RESOLVE_AT = {
        "found": False,
        "file": "src/x.py",
        "line": 3,
        "column": 0,
        "reason": "no_symbol_at_position",
        "detail": "Point at a name.",
    }

    def test_valid_resolve_and_resolve_at_pass(self) -> None:
        lint_response(self._RESOLVE, "resolve")
        for reason in ("unresolved", "file_not_found", "no_symbol_at_position"):
            lint_response({**self._RESOLVE_AT, "reason": reason}, "resolve_at")

    def test_resolve_must_not_echo_handle(self) -> None:
        bad = {**self._RESOLVE, "handle": "pkg.Thing"}
        with pytest.raises(ConformanceViolation, match=r"extra=\['handle'\]"):
            lint_response(bad, "resolve")

    def test_resolve_at_echo_is_flat(self) -> None:
        nested = {k: v for k, v in self._RESOLVE_AT.items() if k not in ("file", "line", "column")}
        nested["position"] = {"file": "src/x.py", "line": 3, "column": 0}
        with pytest.raises(ConformanceViolation, match=r"N\.2 not-found exact shape"):
            lint_response(nested, "resolve_at")

    def test_resolve_at_line_and_column_are_ints(self) -> None:
        with pytest.raises(ConformanceViolation, match=r"'line' must be a plain int"):
            lint_response({**self._RESOLVE_AT, "line": "3"}, "resolve_at")
        with pytest.raises(ConformanceViolation, match=r"'column' must be a plain int"):
            lint_response({**self._RESOLVE_AT, "column": True}, "resolve_at")

    def test_position_reasons_are_not_valid_for_handle_operations(self) -> None:
        bad = {**_NOT_FOUND, "reason": "file_not_found"}
        with pytest.raises(ConformanceViolation, match=r"not recognised for 'inspect'"):
            lint_response(bad, "inspect")

    def test_identifier_must_be_single_line(self) -> None:
        with pytest.raises(ConformanceViolation, match=r"'identifier' must be a non-empty"):
            lint_response({**self._RESOLVE, "identifier": "a\nb"}, "resolve")


class TestN2NotFoundExactShape:
    def test_fabricated_node_alongside_not_found_rejected(self) -> None:
        """The #545 failure: a placeholder node smuggled in next to found: false."""
        response = {**_NOT_FOUND, "kind": "variable", "scope": "external"}
        with pytest.raises(ConformanceViolation, match=r"N\.2.*extra=\['kind', 'scope'\]"):
            lint_response(response, "inspect")

    def test_outline_tree_alongside_not_found_rejected(self) -> None:
        response = {**_NOT_FOUND, "node": _STUB, "children": []}
        with pytest.raises(ConformanceViolation, match=r"N\.2"):
            lint_response(response, "outline")

    def test_expand_stubs_alongside_not_found_rejected(self) -> None:
        """The old expand lie: stubs: [] ("measured, none found") for a ghost."""
        response = {**_EXPAND_NOT_FOUND, "stubs": [], "unresolved_call_sites": 0}
        with pytest.raises(ConformanceViolation, match=r"N\.2"):
            lint_response(response, "expand")

    def test_expand_not_found_missing_edge_rejected(self) -> None:
        with pytest.raises(ConformanceViolation, match=r"N\.2.*missing=\['edge'\]"):
            lint_response(copy.deepcopy(_NOT_FOUND), "expand")

    def test_edge_on_inspect_not_found_rejected(self) -> None:
        with pytest.raises(ConformanceViolation, match=r"N\.2.*extra=\['edge'\]"):
            lint_response(copy.deepcopy(_EXPAND_NOT_FOUND), "inspect")

    @pytest.mark.parametrize("key", ["handle", "reason", "detail"])
    def test_missing_required_key_rejected(self, key: str) -> None:
        response = _not_found_for("inspect")
        del response[key]
        with pytest.raises(ConformanceViolation, match=r"N\.2"):
            lint_response(response, "inspect")

    def test_unknown_reason_rejected(self) -> None:
        response = {**_NOT_FOUND, "reason": "not_found"}
        with pytest.raises(ConformanceViolation, match=r"N\.2 not-found reason"):
            lint_response(response, "inspect")

    @pytest.mark.parametrize("bad", ["", "line one\nline two", 42])
    def test_bad_detail_rejected(self, bad: object) -> None:
        response = {**_NOT_FOUND, "detail": bad}
        with pytest.raises(ConformanceViolation, match=r"N\.2 not-found field"):
            lint_response(response, "inspect")


class TestN3OutlineFoundRootOnly:
    def test_found_on_nested_tree_rejected(self) -> None:
        response = {
            "found": True,
            "node": _STUB,
            "children": [{"found": True, "node": {**_STUB, "handle": "pkg.mod.Widget.m"}}],
        }
        response["children"][0]["children"] = []
        with pytest.raises(ConformanceViolation, match=r"N\.3"):
            lint_response(response, "outline")

    def test_found_on_root_only_passes(self) -> None:
        response = {
            "found": True,
            "node": _STUB,
            "children": [{"node": {**_STUB, "handle": "pkg.mod.Widget.m"}, "children": []}],
        }
        lint_response(response, "outline")
