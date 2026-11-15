"""Regression: an attribute-assignment target is never a binding (#567).

Jedi reports the ``x`` of ``self.x = …`` with the ``full_name`` of a local of
the enclosing method (``A.__init__.x``), and the ``attr`` of a module-level
``obj.attr = …`` with the ``full_name`` of a module member (``mod.attr``).
Before #567 pyeye passed those through: ``resolve`` / ``resolve_at`` /
``inspect`` called an instance attribute a local variable of the method, and
``expand(members)`` / ``inspect.edge_counts`` listed a fake module member.
Modelling instance attributes is #565; until then they are not-found.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve, resolve_at

_M = """\
class A:
    def __init__(self, project_path, value):
        self.project_path = project_path
        self.p = value
        loc = 1
        self.q: int = 2

    def later(self):
        self.a.b = 5
        x = 1
        return x

    def shadow(self):
        loc = 1
        self.loc = loc
"""

_N = """\
import types

obj = types.SimpleNamespace()
obj.attr = 1
real = 2
"""

_O = """\
class C:
    attr = 0


c = C()
c.attr = 1


class B:
    ns = C()
    ns.inner = 3
    real = 4
"""


@pytest.fixture
def project(tmp_path: Path) -> tuple[JediAnalyzer, Path]:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "m.py").write_text(_M, encoding="utf-8")
    (root / "pkg" / "n.py").write_text(_N, encoding="utf-8")
    (root / "pkg" / "o.py").write_text(_O, encoding="utf-8")
    return JediAnalyzer(str(root)), root


# ---------------------------------------------------------------------------
# resolve / inspect by handle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handle",
    [
        "pkg.m.A.__init__.p",
        "pkg.m.A.__init__.q",
        "pkg.m.A.later.b",
        "pkg.n.attr",
        # The issue's own shape: ``self.project_path = project_path``.  Jedi
        # doesn't report parameters as names, so the only match was the
        # attribute target; the handle is not-found, not the parameter.
        "pkg.m.A.__init__.project_path",
        # ``c.attr = 1`` where ``C`` defines ``attr``: goto from the target lands
        # on ``C.attr``, so placing it by name would answer ``pkg.o.C.attr``.
        "pkg.o.attr",
        "pkg.o.B.inner",
    ],
)
async def test_attribute_target_handle_is_not_found(
    project: tuple[JediAnalyzer, Path], handle: str
) -> None:
    analyzer, _ = project
    resolved = await resolve(handle, analyzer)
    assert resolved["found"] is False
    assert resolved["reason"] == "unresolved"
    inspected = await inspect(handle, analyzer)
    assert inspected["found"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handle", "line"),
    [
        ("pkg.m.A.__init__.loc", 5),
        ("pkg.m.A.later.x", 10),
        ("pkg.n.obj", 3),
        ("pkg.n.real", 5),
        ("pkg.o.C.attr", 2),
        ("pkg.o.c", 5),
        ("pkg.o.B.real", 12),
    ],
)
async def test_genuine_binding_still_resolves(
    project: tuple[JediAnalyzer, Path], handle: str, line: int
) -> None:
    analyzer, _ = project
    resolved = await resolve(handle, analyzer)
    assert resolved["found"] is True, resolved
    assert resolved["handle"] == handle
    assert resolved["kind"] == "variable"
    assert resolved["location"]["line_start"] == line
    inspected = await inspect(handle, analyzer)
    assert inspected["found"] is True
    assert inspected["location"]["line_start"] == line


# ---------------------------------------------------------------------------
# resolve_at by position
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rel", "line", "column"),
    [
        ("pkg/m.py", 3, 13),  # self.[project_path]: same name as a parameter
        ("pkg/m.py", 4, 13),  # self.[p]
        ("pkg/m.py", 6, 13),  # self.[q]: int
    ],
)
async def test_resolve_at_attribute_target_is_not_found(
    project: tuple[JediAnalyzer, Path], rel: str, line: int, column: int
) -> None:
    """``goto`` lands on the attribute target itself, which is refused."""
    analyzer, root = project
    result = await resolve_at((root / rel).as_posix(), line, column, analyzer)
    assert result["found"] is False, result
    assert result["reason"] == "unresolved"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rel", "line", "column"),
    [
        ("pkg/m.py", 9, 15),  # self.a.[b]
        ("pkg/n.py", 4, 4),  # obj.[attr]
    ],
)
async def test_resolve_at_uninferable_attribute_target_is_not_found(
    project: tuple[JediAnalyzer, Path], rel: str, line: int, column: int
) -> None:
    """``goto`` can't infer the object (``self.a``, a ``SimpleNamespace``), so
    the position has no definition at all: not-found before the #567 check runs.
    Pinned so a smarter ``goto`` can't reintroduce a fake handle unnoticed."""
    analyzer, root = project
    result = await resolve_at((root / rel).as_posix(), line, column, analyzer)
    assert result["found"] is False, result


@pytest.mark.asyncio
async def test_resolve_at_attribute_target_is_not_the_same_named_local(
    project: tuple[JediAnalyzer, Path],
) -> None:
    """``self.loc`` beside a local ``loc``: both read as ``A.shadow.loc``.

    The resolver would place that full_name on the local, so ``resolve_at``
    must refuse the attribute target before it gets there.
    """
    analyzer, root = project
    result = await resolve_at((root / "pkg/m.py").as_posix(), 15, 13, analyzer)
    assert result["found"] is False, result
    assert result["reason"] == "unresolved"
    local = await resolve_at((root / "pkg/m.py").as_posix(), 14, 8, analyzer)
    assert local["found"] is True and local["handle"] == "pkg.m.A.shadow.loc"


@pytest.mark.asyncio
async def test_resolve_at_genuine_local_still_resolves(
    project: tuple[JediAnalyzer, Path],
) -> None:
    analyzer, root = project
    result = await resolve_at((root / "pkg/m.py").as_posix(), 5, 8, analyzer)
    assert result["found"] is True, result
    assert result["handle"] == "pkg.m.A.__init__.loc"


# ---------------------------------------------------------------------------
# members edge: count == expand (#599) without the fake member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_module_attribute_target_is_not_a_member(
    project: tuple[JediAnalyzer, Path],
) -> None:
    analyzer, _ = project
    expanded = await expand("pkg.n", "members", analyzer)
    handles = [stub["handle"] for stub in expanded["stubs"]]
    assert handles == ["pkg.n.obj", "pkg.n.real"]
    inspected = await inspect("pkg.n", analyzer)
    assert inspected["edge_counts"]["members"] == len(handles)


@pytest.mark.asyncio
async def test_class_members_unchanged(project: tuple[JediAnalyzer, Path]) -> None:
    analyzer, _ = project
    expanded = await expand("pkg.m.A", "members", analyzer)
    handles = sorted(stub["handle"] for stub in expanded["stubs"])
    assert handles == ["pkg.m.A.__init__", "pkg.m.A.later", "pkg.m.A.shadow"]
    inspected = await inspect("pkg.m.A", analyzer)
    assert inspected["edge_counts"]["members"] == len(handles)


@pytest.mark.asyncio
async def test_class_body_attribute_target_is_not_a_member(
    project: tuple[JediAnalyzer, Path],
) -> None:
    analyzer, _ = project
    expanded = await expand("pkg.o.B", "members", analyzer)
    handles = [stub["handle"] for stub in expanded["stubs"]]
    assert handles == ["pkg.o.B.ns", "pkg.o.B.real"]
    inspected = await inspect("pkg.o.B", analyzer)
    assert inspected["edge_counts"]["members"] == len(handles)
