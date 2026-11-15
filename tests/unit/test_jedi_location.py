"""Tests for :func:`pyeye._jedi_location.get_end_line` (#693).

A definition (``def`` / ``class``) spans its block; every other name ends on
the line it starts (the ``Location`` contract).  Before #693 the walk returned
the end of the *nearest enclosing* block, so a local reported its function's
end and a class-body attribute its class's end.
"""

from __future__ import annotations

from pathlib import Path

import jedi
import pytest

from pyeye._jedi_location import get_end_line

_SOURCE = """\
VALUE = 1                      # 1


def func(param):               # 4
    local = 2                  # 5
    for item in range(3):      # 6
        pass                   # 7

    def inner():               # 9
        return local           # 10

    return inner               # 12


class Klass:                   # 15
    attr = 3                   # 16
    annotated: int = 4         # 17

    def method(self):          # 19
        tmp = 5                # 20
        return tmp             # 21

    class Nested:              # 23
        deep = 6               # 24


async def coro():              # 27
    waited = 7                 # 28
    return waited              # 29


@staticmethod                  # 32
def decorated():               # 33
    inside = 8                 # 34
    return inside              # 35
"""


@pytest.fixture(scope="module")
def names(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("jedi_location")
    path = root / "m.py"
    path.write_text(_SOURCE, encoding="utf-8")
    script = jedi.Script(path=Path(path), project=jedi.Project(str(root)))
    out: dict[str, object] = {}
    for name in script.get_names(all_scopes=True, definitions=True, references=False):
        out.setdefault(name.full_name, name)
    return out


@pytest.mark.parametrize(
    ("full_name", "last_body_line"),
    [
        ("m.func", 12),
        ("m.func.inner", 10),
        ("m.Klass", 24),
        ("m.Klass.method", 21),
        ("m.Klass.Nested", 24),
        ("m.coro", 29),
        ("m.decorated", 35),
    ],
)
def test_definition_spans_its_block(
    names: dict[str, object], full_name: str, last_body_line: int
) -> None:
    """Unchanged by #693.

    TODO(#709): parso's ``end_pos`` for a block ending in a newline is the start
    of the NEXT line, so today's value is one past the block's last line.  #709
    corrects it; this pins today's value so #693 provably leaves it alone.
    """
    assert get_end_line(names[full_name]) == last_body_line + 1


@pytest.mark.parametrize(
    ("full_name", "line"),
    [
        ("m.VALUE", 1),
        ("m.func.local", 5),
        ("m.func.item", 6),
        ("m.Klass.attr", 16),
        ("m.Klass.annotated", 17),
        ("m.Klass.method.tmp", 20),
        ("m.Klass.Nested.deep", 24),
        ("m.coro.waited", 28),
        ("m.decorated.inside", 34),
    ],
)
def test_non_definition_ends_on_its_own_line(
    names: dict[str, object], full_name: str, line: int
) -> None:
    name = names[full_name]
    assert name.line == line  # type: ignore[attr-defined]
    assert get_end_line(name) == line
