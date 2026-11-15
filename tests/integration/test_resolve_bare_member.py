"""Regression: a bare method or class-attribute name resolves (#508, rule 4).

``resolve_name`` rules 1-3 (shadow, exact top-level module, name index) only
see modules, top-level definitions and nested classes: methods and class-body
attributes are never bare-name *indexed* (#457).  Before #508 a bare method
name such as ``uniquely_named`` was ``unresolved``, the same answer as a name
that exists nowhere.  Rule 4 is a fallback after rules 1-3 miss: one matching
member is the answer, several are ambiguous, and dunders (which every class
defines) stay ``unresolved`` with a hint to ``expand(<class>, "members")``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from tests.conformance.response_linter import lint_response

_A = """\
class Alpha:
    unique_attr = 1
    typed_attr: int = 2

    def __init__(self):
        self.instance_only = 3

    def __eq__(self, other):
        return True

    def uniquely_named(self):
        return 1

    def shared(self):
        return 2

    def helper(self):
        return 3


class Outer:
    class Inner:
        def deep(self):
            return 4
"""

_B = """\
class Beta:
    def __init__(self):
        pass

    def __eq__(self, other):
        return False

    def shared(self):
        return 5


def helper():
    return 6


def outer_function():
    inner_local = 7
    return inner_local
"""


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text(_A, encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text(_B, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


async def _resolve(name: str, analyzer: JediAnalyzer) -> dict:
    result = dict(await resolve(name, analyzer))
    lint_response(result, "resolve")
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "handle", "kind"),
    [
        ("uniquely_named", "pkg.a.Alpha.uniquely_named", "method"),
        ("unique_attr", "pkg.a.Alpha.unique_attr", "variable"),
        ("typed_attr", "pkg.a.Alpha.typed_attr", "variable"),
        ("deep", "pkg.a.Outer.Inner.deep", "method"),
    ],
)
async def test_unique_member_resolves_canonically(
    analyzer: JediAnalyzer, name: str, handle: str, kind: str
) -> None:
    result = await _resolve(name, analyzer)
    assert result["found"] is True and not result.get("ambiguous"), result
    assert (result["handle"], result["kind"], result["scope"]) == (handle, kind, "project")
    inspected = await inspect(handle, analyzer)
    assert inspected["found"] is True
    assert inspected["handle"] == handle


@pytest.mark.asyncio
async def test_member_shared_by_two_classes_is_ambiguous(analyzer: JediAnalyzer) -> None:
    result = await _resolve("shared", analyzer)
    assert result["found"] is True and result["ambiguous"] is True, result
    handles = [c["handle"] for c in result["candidates"]]
    assert handles == ["pkg.a.Alpha.shared", "pkg.b.Beta.shared"]
    for handle in handles:
        assert (await inspect(handle, analyzer))["found"] is True


@pytest.mark.asyncio
async def test_top_level_name_shadows_same_named_method(analyzer: JediAnalyzer) -> None:
    """Rule 4 is a fallback: a top-level ``helper`` answers, ``Alpha.helper`` isn't listed."""
    result = await _resolve("helper", analyzer)
    assert result["found"] is True and not result.get("ambiguous"), result
    assert result["handle"] == "pkg.b.helper"


@pytest.mark.asyncio
async def test_dunder_stays_unresolved_with_members_hint(analyzer: JediAnalyzer) -> None:
    """``__eq__`` is defined by both classes, but a dunder is never a rule-4 member.

    (``__init__`` itself is not used here: rule 2 currently answers it with an
    unrelated external package's ``__init__.py``, #722.)
    """
    result = await _resolve("__eq__", analyzer)
    assert result["found"] is False
    assert result["reason"] == "unresolved"
    assert 'expand(<class>, "members")' in result["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "nonexistent_name_xyz",
        "inner_local",  # a function local is never offered
        "instance_only",  # a `self.x =` target is not a class attribute (#565, #567)
    ],
)
async def test_non_member_stays_plainly_unresolved(analyzer: JediAnalyzer, name: str) -> None:
    result = await _resolve(name, analyzer)
    assert result["found"] is False
    assert result["reason"] == "unresolved"
    assert "members" not in result["detail"]
