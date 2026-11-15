"""Adversarial tests for linter Check K: the closed kind vocabulary (#623)."""

from __future__ import annotations

from typing import Any

import pytest

from pyeye.kinds import KINDS
from tests.conformance.response_linter import (
    _VALID_KINDS,
    ConformanceViolation,
    lint_response,
)

_LOC = {"file": "/p/m.py", "line_start": 1, "line_end": 2, "column_start": 0, "column_end": 3}


def _stub(kind: Any) -> dict[str, Any]:
    return {"handle": "pkg.mod.X", "kind": kind, "scope": "project", "line_start": 1, "line_end": 2}


def test_linter_vocabulary_matches_pyeye_kinds() -> None:
    """The linter's independent copy and the implementation agree."""
    assert _VALID_KINDS == KINDS


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_resolve_success_with_valid_kind_passes(kind: str) -> None:
    lint_response(
        {"found": True, "handle": "pkg.X", "kind": kind, "scope": "project", "location": _LOC},
        "resolve",
    )


@pytest.mark.parametrize("bad", ["namespace", "path", "instance", "", None, 3])
def test_resolve_success_with_out_of_vocabulary_kind_fails(bad: Any) -> None:
    with pytest.raises(ConformanceViolation, match=r"K\.1"):
        lint_response(
            {"found": True, "handle": "pkg.X", "kind": bad, "scope": "external", "location": _LOC},
            "resolve",
        )


def test_ambiguous_candidate_kind_is_checked() -> None:
    response = {
        "found": True,
        "ambiguous": True,
        "candidates": [
            {"handle": "a.X", "kind": "class", "scope": "project", "location": _LOC},
            {"handle": "b.X", "kind": "namespace", "scope": "external", "location": _LOC},
        ],
    }
    with pytest.raises(ConformanceViolation, match=r"candidates\[1\]\.kind"):
        lint_response(response, "resolve")


def test_nested_stub_kind_is_checked() -> None:
    with pytest.raises(ConformanceViolation, match=r"K\.1"):
        lint_response({"nodes": [_stub("class"), _stub("namespace")]}, "other")


def test_kind_fields_outside_handle_bearing_dicts_are_ignored() -> None:
    """A parameter kind or a trace edge kind is a different vocabulary."""
    lint_response(
        {
            "parameters": [{"name": "x", "kind": "positional_or_keyword"}],
            "edges": [{"from": "a", "to": "b", "kind": "callees"}],
        },
        "other",
    )
