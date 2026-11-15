"""Tests for :func:`pyeye._jedi_location.get_end_line` (#693).

A definition (``def`` / ``class``) spans its block; every other name ends on
the line it starts (the ``Location`` contract).  Before #693 the walk returned
the end of the *nearest enclosing* block, so a local reported its function's
end and a class-body attribute its class's end.
"""

from __future__ import annotations

import ast
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
    """A def/class ends on its block's last line, not the line after it (#709)."""
    assert get_end_line(names[full_name]) == last_body_line


def test_definition_matches_ast_end_lineno(names: dict[str, object]) -> None:
    """Jedi-derived spans agree with the AST (``ClassSentinel`` uses ``end_lineno``)."""
    tree = ast.parse(_SOURCE)
    ast_ends = {
        node.name: node.end_lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    checked = 0
    for full_name, name in names.items():
        if not full_name or getattr(name, "type", None) not in ("function", "class"):
            continue
        assert get_end_line(name) == ast_ends[full_name.rsplit(".", 1)[-1]], full_name
        checked += 1
    assert checked == len(ast_ends)


def test_definition_at_end_of_file_without_trailing_newline(tmp_path: Path) -> None:
    """parso's end is ON the last line here; it must not be shortened by one."""
    path = tmp_path / "eof.py"
    path.write_text("def last():\n    return 1", encoding="utf-8")
    script = jedi.Script(path=path, project=jedi.Project(str(tmp_path)))
    (name,) = [n for n in script.get_names() if n.name == "last"]
    assert get_end_line(name) == 2


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
