"""Tests for the closed kind vocabulary in :mod:`pyeye.kinds` (#623 slice 1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pyeye.kinds import (
    FALLBACK_KIND,
    JEDI_TYPE_TO_KIND,
    KINDS,
    is_method,
    normalise_kind,
    normalise_kind_from_name,
)


def _name(jedi_type: str | None, parent_type: str | None = None) -> SimpleNamespace:
    """A minimal stand-in for a Jedi ``Name``."""
    parent = SimpleNamespace(type=parent_type) if parent_type else None
    return SimpleNamespace(type=jedi_type, parent=lambda: parent)


def test_vocabulary_is_the_documented_closed_set() -> None:
    """The vocabulary matches ``docs/api-redesign.md`` (the ``kind`` row)."""
    assert (
        frozenset(
            {
                "class",
                "function",
                "method",
                "module",
                "variable",
                "attribute",
                "property",
                "enum_member",  # #695
            }
        )
        == KINDS
    )


def test_fallback_kind_is_in_the_vocabulary() -> None:
    assert FALLBACK_KIND == "variable"
    assert FALLBACK_KIND in KINDS


def test_every_mapped_kind_is_in_the_vocabulary() -> None:
    assert set(JEDI_TYPE_TO_KIND.values()) <= KINDS


@pytest.mark.parametrize(
    ("jedi_type", "kind"),
    [
        ("class", "class"),
        ("function", "function"),
        ("module", "module"),
        ("instance", "variable"),
        ("statement", "variable"),
        ("param", "variable"),
        ("property", "property"),
        ("keyword", "variable"),
        ("import", "module"),
        (None, "variable"),
    ],
)
def test_normalise_kind_known_types(jedi_type: str | None, kind: str) -> None:
    assert normalise_kind(jedi_type) == kind


def test_namespace_package_is_a_module() -> None:
    """Regression (#623): a PEP 420 namespace package is ``module``, not ``namespace``."""
    assert normalise_kind("namespace") == "module"


@pytest.mark.parametrize("jedi_type", ["path", "some_new_jedi_type", ""])
def test_unknown_jedi_type_falls_back_inside_the_vocabulary(jedi_type: str) -> None:
    """Regression (#623): unknown Jedi types never pass through as a kind."""
    assert normalise_kind(jedi_type) == FALLBACK_KIND


def test_is_method_requires_a_class_parent() -> None:
    assert is_method(_name("function", parent_type="class")) is True
    assert is_method(_name("function", parent_type="module")) is False
    assert is_method(_name("function")) is False
    assert is_method(_name("class", parent_type="class")) is False


def test_is_method_tolerates_a_failing_parent() -> None:
    def boom() -> None:
        raise RuntimeError("jedi blew up")

    assert is_method(SimpleNamespace(type="function", parent=boom)) is False


def test_normalise_kind_from_name_promotes_methods() -> None:
    assert normalise_kind_from_name(_name("function", parent_type="class")) == "method"
    assert normalise_kind_from_name(_name("function", parent_type="module")) == "function"
    assert normalise_kind_from_name(_name("namespace")) == "module"
    assert normalise_kind_from_name(SimpleNamespace()) == "variable"


# ---------------------------------------------------------------------------
# Class-body kinds (#695)
# ---------------------------------------------------------------------------


def test_class_body_statement_without_a_resolvable_class_is_attribute() -> None:
    """A class-body binding whose class can't be inferred is ``attribute``, never a member."""
    name = _name("statement", parent_type="class")
    assert normalise_kind_from_name(name) == "attribute"


def test_module_level_statement_stays_variable() -> None:
    assert normalise_kind_from_name(_name("statement", parent_type="module")) == "variable"


def test_non_statement_in_a_class_is_not_refined() -> None:
    assert normalise_kind_from_name(_name("param", parent_type="class")) == "variable"


def test_class_body_statement_whose_parent_fails_stays_variable() -> None:
    """If Jedi can't report the enclosing scope, the name isn't refined."""

    def boom() -> None:
        raise RuntimeError("no parent")

    name = SimpleNamespace(type="statement", parent=boom)
    assert normalise_kind_from_name(name) == "variable"
