"""Adversarial tests for linter Check D: the ``stub`` declaration flag (#933)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conformance.response_linter import ConformanceViolation, lint_response


def _loc(file: str) -> dict[str, Any]:
    return {"file": file, "line_start": 1, "line_end": 2, "column_start": 0, "column_end": 3}


def _resolved(file: str, **extra: Any) -> dict[str, Any]:
    return {
        "found": True,
        "handle": "pkg.X",
        "kind": "class",
        "scope": "project",
        "location": _loc(file),
        **extra,
    }


@pytest.mark.parametrize(
    "response",
    [
        _resolved("/p/pkg/mod.py"),
        _resolved("/p/pkg/stubonly.pyi", stub=True),
        _resolved("C:/typeshed/stdlib/MATH.PYI", stub=True),
    ],
)
def test_the_flag_matching_the_file_passes(response: dict[str, Any]) -> None:
    lint_response(response, "resolve")


def test_an_edge_stub_has_no_file_and_may_carry_the_flag() -> None:
    lint_response(
        {"nodes": [{"handle": "math.sqrt", "kind": "function", "scope": "external", "stub": True}]},
        "other",
    )


@pytest.mark.parametrize("bad", [False, None, "true", 1])
def test_the_flag_is_only_ever_true(bad: Any) -> None:
    with pytest.raises(ConformanceViolation, match=r"D\.1"):
        lint_response(_resolved("/p/pkg/stubonly.pyi", stub=bad), "resolve")


def test_a_stub_located_node_without_the_flag_fails() -> None:
    with pytest.raises(ConformanceViolation, match=r"D\.2 .*missing"):
        lint_response(_resolved("/p/pkg/stubonly.pyi"), "resolve")


def test_a_source_located_node_with_the_flag_fails() -> None:
    with pytest.raises(ConformanceViolation, match=r"D\.2 .*present"):
        lint_response(_resolved("/p/pkg/mod.py", stub=True), "resolve")


def test_each_ambiguous_candidate_is_checked() -> None:
    response = {
        "found": True,
        "ambiguous": True,
        "candidates": [
            {"handle": "a.X", "kind": "class", "scope": "project", "location": _loc("/p/a.py")},
            {"handle": "b.X", "kind": "class", "scope": "project", "location": _loc("/p/b.pyi")},
        ],
    }
    with pytest.raises(ConformanceViolation, match=r"candidates\[1\]\.stub"):
        lint_response(response, "resolve")


def test_a_plugin_record_is_a_node_too() -> None:
    """A plugin record carries handle and scope, so the flag rules apply (#933)."""
    record = {
        "name": "User",
        "handle": "app.User",
        "scope": "project",
        "location": _loc("/p/app.pyi"),
    }

    with pytest.raises(ConformanceViolation, match=r"D\.2"):
        lint_response({"models": [record]}, "other")
