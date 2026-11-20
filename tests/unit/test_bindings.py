"""A scope's bindings follow the Python reference, "Naming and binding" (#1049).

The maintainer's ruling (via designer, 2026-11-21): a name is bound in a scope
by a formal parameter, an import, a ``def``/``class``, an assignment or ``:=``
target, a ``for`` target, an ``as`` name in ``with``/``except``/``match``, a
match capture, a ``type`` statement or type parameter, and also by ``del``.
:func:`pyeye._bindings.binding_sites` is the ONE count, shared by the
resolver's local-name uniqueness (#1022) and #1024's class-graph naming, so the
two can't disagree.
"""

from __future__ import annotations

import ast
import sys

import pytest

from pyeye._bindings import binding_sites

PY312 = pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 syntax")

#: form -> (the function's parameters, a statement in its body that binds X)
BINDS: dict[str, tuple[str, str]] = {
    "parameter": ("X", "pass"),
    "positional-only parameter": ("X, /", "pass"),
    "keyword-only parameter": ("*, X", "pass"),
    "*args": ("*X", "pass"),
    "**kwargs": ("**X", "pass"),
    "import": ("", "import X"),
    "import as": ("", "import os as X"),
    "dotted import": ("", "import X.path"),
    "from import": ("", "from os import X"),
    "from import as": ("", "from os import path as X"),
    "def": ("", "def X():\n        pass"),
    "async def": ("", "async def X():\n        pass"),
    "class": ("", "class X:\n        pass"),
    "assignment": ("", "X = 1"),
    "tuple target": ("", "a, (X, b) = 1, (2, 3)"),
    "starred target": ("", "a, *X = 1, 2"),
    "augmented": ("", "X += 1"),
    "annotated": ("", "X: int = 1"),
    "bare annotation": ("", "X: int"),
    "walrus": ("", "if (X := 1):\n        pass"),
    "walrus in a comprehension": ("", "_ = [(X := y) for y in ()]"),
    "for": ("", "for X in ():\n        pass"),
    "with as": ("", "with open('f') as X:\n        pass"),
    "except as": ("", "try:\n        pass\n    except Exception as X:\n        pass"),
    "match capture": ("", "match 1:\n        case X:\n            pass"),
    "match as": ("", "match 1:\n        case int() as X:\n            pass"),
    "match star": ("", "match 1:\n        case [*X]:\n            pass"),
    "match mapping rest": ("", "match 1:\n        case {**X}:\n            pass"),
    "del": ("", "del X"),
}

BINDS_312: dict[str, tuple[str, str]] = {
    "type statement": ("", "type X = int"),
}

#: form -> a statement in the body that does NOT bind X in the function's scope
DOES_NOT_BIND: dict[str, str] = {
    "attribute": "obj.X = 1",
    "subscript": "obj[X] = 1",
    "lambda parameter": "_ = lambda X: X",
    "comprehension variable": "_ = [X for X in ()]",
    "nested function's local": "def g():\n        X = 1",
    "nested class's attribute": "class K:\n        X = 1",
    "a read": "print(X)",
    "star import": "from os import *",
}


def _function(params: str, body: str) -> ast.FunctionDef:
    tree = ast.parse(f"def f({params}):\n    {body}\n")
    node = tree.body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


class TestEveryBindingForm:
    @pytest.mark.parametrize(("params", "body"), BINDS.values(), ids=BINDS.keys())
    def test_binds(self, params: str, body: str) -> None:
        sites = binding_sites(_function(params, body))

        assert len(sites.get("X", [])) == 1, sites

    @PY312
    @pytest.mark.parametrize(("params", "body"), BINDS_312.values(), ids=BINDS_312.keys())
    def test_binds_on_312(self, params: str, body: str) -> None:
        assert len(binding_sites(_function(params, body)).get("X", [])) == 1

    @PY312
    def test_the_scopes_own_type_parameter_binds(self) -> None:
        node = ast.parse("def f[X]():\n    pass\n").body[0]

        assert len(binding_sites(node).get("X", [])) == 1

    @pytest.mark.parametrize("body", DOES_NOT_BIND.values(), ids=DOES_NOT_BIND.keys())
    def test_does_not_bind(self, body: str) -> None:
        assert "X" not in binding_sites(_function("", body))


class TestTheSites:
    def test_each_site_has_its_line_and_form(self) -> None:
        node = _function("X", "class X:\n        pass\n    del X")

        sites = binding_sites(node)["X"]

        assert [(s.line, s.form) for s in sites] == [(1, "parameter"), (2, "class"), (4, "del")]

    def test_a_class_scope_is_counted_too(self) -> None:
        """A class body is a scope: a local class's members are named after it (#1025)."""
        node = ast.parse("class K:\n    Meta = 1\n    class Meta:\n        pass\n").body[0]

        assert len(binding_sites(node)["Meta"]) == 2

    def test_a_dotted_import_binds_its_first_part(self) -> None:
        assert set(binding_sites(_function("", "import os.path"))) == {"os"}

    def test_global_and_nonlocal_are_declarations_not_bindings(self) -> None:
        assert "X" not in binding_sites(_function("", "global X"))
