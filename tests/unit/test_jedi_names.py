"""Tests for :func:`pyeye._jedi_names.is_attribute_target` (#567).

Jedi's ``get_names(definitions=True)`` reports the target of an attribute
assignment (``self.x = …``, ``obj.attr = …``) with the same ``full_name`` shape
as a genuine binding in the enclosing scope.  The predicate tells them apart.
"""

from __future__ import annotations

from pathlib import Path

import jedi
import pytest

from pyeye._jedi_names import is_attribute_target

_SOURCE = """\
import types

obj = types.SimpleNamespace()
obj.attr = 1
real = 2


class A:
    klass_var = 3

    def __init__(self, value):
        self.p = value
        loc = 1
        self.q: int = 2

    def later(self):
        self.a.b = 5
        for self.i in range(3):
            pass
        x = 1
        return x


def func():
    y = 1
    return y
"""


@pytest.fixture(scope="module")
def names_by_full_name(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[object]]:
    root = tmp_path_factory.mktemp("jedi_names")
    path = root / "m.py"
    path.write_text(_SOURCE, encoding="utf-8")
    script = jedi.Script(path=Path(path), project=jedi.Project(str(root)))
    out: dict[str, list[object]] = {}
    for name in script.get_names(all_scopes=True, definitions=True, references=False):
        out.setdefault(name.full_name, []).append(name)
    return out


@pytest.mark.parametrize(
    "full_name",
    ["m.attr", "m.A.__init__.p", "m.A.__init__.q", "m.A.later.b", "m.A.later.i"],
)
def test_attribute_targets_are_detected(
    names_by_full_name: dict[str, list[object]], full_name: str
) -> None:
    names = names_by_full_name[full_name]
    assert names and all(is_attribute_target(n) for n in names)


@pytest.mark.parametrize(
    "full_name",
    [
        "m.obj",
        "m.real",
        "m.A",
        "m.A.klass_var",
        "m.A.__init__",
        "m.A.__init__.loc",
        "m.A.later.x",
        "m.func",
        "m.func.y",
    ],
)
def test_genuine_bindings_are_not_attribute_targets(
    names_by_full_name: dict[str, list[object]], full_name: str
) -> None:
    names = names_by_full_name[full_name]
    assert names and not any(is_attribute_target(n) for n in names)


def test_object_without_a_tree_name_is_not_an_attribute_target() -> None:
    """Sentinels and other non-Jedi anchors carry no parso tree: never a target."""

    class _Bare:
        pass

    assert is_attribute_target(_Bare()) is False
