"""Regression: class attributes are ``attribute``, enum members ``enum_member`` (#695).

Before #695 every class-body binding reported ``kind: "variable"``, the same as
a module- or function-level name.  ``attribute`` was in the closed vocabulary
but never emitted.  Now a class-body binding is ``attribute``, and a member of
a class that is a transitive ``enum.Enum`` subclass (found by walking the
class's own MRO, never a project-wide scan) is ``enum_member``.  Wherever
membership can't be decided statically the answer is ``attribute``: less
specific, never wrong.
"""

from __future__ import annotations

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.kinds import KINDS
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from tests.conformance.response_linter import lint_response

_SOURCE = """\
import enum
from enum import Enum, Flag, IntEnum, StrEnum, member, nonmember
from typing import ClassVar

MODULE_LEVEL = 1


def function():
    local = 2
    return local


def helper():
    return 3


class Config:
    assigned = 1
    annotated: int
    annotated_value: int = 2
    class_var: ClassVar[list[str]] = []

    def method(self):
        return 4


class Color(Enum):
    RED = 1
    GREEN = enum.auto()

    def describe(self):
        return self.name

    @property
    def lower(self):
        return self.name.lower()


class Num(IntEnum):
    ONE = 1


class Text(StrEnum):
    A = "a"


class Perm(Flag):
    R = 4


class ProjectBase(Enum):
    pass


class Derived(ProjectBase):
    X = 1


class NonMembers(Enum):
    _ignore_ = ["skipped", "also_skipped"]
    _order_ = "REAL"
    __dunder__ = 1
    _missing_hint_ = 2
    REAL = 1
    skipped = 2
    also_skipped = 3
    wrapped_out = nonmember(4)
    wrapped_in = member(5)
    prop = property(lambda self: 6)
    func_alias = helper
    anonymous = lambda self: 7
    annotation_only: int

    class Nested:
        pass


class DynamicIgnore(Enum):
    _ignore_ = [name for name in ("a",)]
    MAYBE = 1


class Dynamic(type("Base", (), {})):
    y = 1


class Missing(NoSuchBase):  # noqa: F821 - deliberately unresolvable
    z = 1
"""


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory: pytest.TempPathFactory) -> JediAnalyzer:
    root = tmp_path_factory.mktemp("kinds695")
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "m.py").write_text(_SOURCE, encoding="utf-8")
    return JediAnalyzer(str(root))


async def _kind(handle: str, analyzer: JediAnalyzer) -> str:
    resolved = dict(await resolve(handle, analyzer))
    lint_response(resolved, "resolve")
    assert resolved["found"] is True, resolved
    inspected = dict(await inspect(handle, analyzer))
    lint_response(inspected, "inspect")
    assert inspected["kind"] == resolved["kind"], (handle, resolved, inspected)
    return str(resolved["kind"])


@pytest.mark.asyncio
@pytest.mark.parametrize("attr", ["assigned", "annotated", "annotated_value", "class_var"])
async def test_class_attributes_are_attribute(analyzer: JediAnalyzer, attr: str) -> None:
    assert await _kind(f"pkg.m.Config.{attr}", analyzer) == "attribute"


@pytest.mark.asyncio
@pytest.mark.parametrize("handle", ["pkg.m.MODULE_LEVEL", "pkg.m.function.local"])
async def test_module_and_function_names_stay_variable(analyzer: JediAnalyzer, handle: str) -> None:
    assert await _kind(handle, analyzer) == "variable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handle",
    [
        "pkg.m.Color.RED",
        "pkg.m.Color.GREEN",  # enum.auto()
        "pkg.m.Num.ONE",  # IntEnum
        "pkg.m.Text.A",  # StrEnum
        "pkg.m.Perm.R",  # Flag
        "pkg.m.Derived.X",  # a project-defined enum base
        "pkg.m.NonMembers.REAL",
        "pkg.m.NonMembers.wrapped_in",  # member(...) IS a member
    ],
)
async def test_enum_members_are_enum_member(analyzer: JediAnalyzer, handle: str) -> None:
    assert await _kind(handle, analyzer) == "enum_member"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attr",
    [
        "_ignore_",  # _sunder_
        "_order_",  # _sunder_
        "_missing_hint_",  # _sunder_
        "__dunder__",  # __dunder__
        "skipped",  # listed in _ignore_
        "also_skipped",  # listed in _ignore_
        "wrapped_out",  # nonmember(...)
        "prop",  # a descriptor
        "func_alias",  # a function
        "anonymous",  # a lambda
        "annotation_only",  # an annotation creates no member
    ],
)
async def test_enum_non_members_are_attribute(analyzer: JediAnalyzer, attr: str) -> None:
    assert await _kind(f"pkg.m.NonMembers.{attr}", analyzer) == "attribute"


@pytest.mark.asyncio
async def test_enum_methods_and_nested_classes_keep_their_kinds(analyzer: JediAnalyzer) -> None:
    assert await _kind("pkg.m.Color.describe", analyzer) == "method"
    assert await _kind("pkg.m.NonMembers.Nested", analyzer) == "class"


@pytest.mark.asyncio
async def test_non_literal_ignore_makes_every_name_attribute(analyzer: JediAnalyzer) -> None:
    """Membership can't be told statically, so the honest answer is attribute."""
    assert await _kind("pkg.m.DynamicIgnore.MAYBE", analyzer) == "attribute"


@pytest.mark.asyncio
@pytest.mark.parametrize("handle", ["pkg.m.Dynamic.y", "pkg.m.Missing.z"])
async def test_unresolvable_bases_fall_back_to_attribute(
    analyzer: JediAnalyzer, handle: str
) -> None:
    assert await _kind(handle, analyzer) == "attribute"


@pytest.mark.asyncio
async def test_member_stubs_carry_the_same_kinds(analyzer: JediAnalyzer) -> None:
    result = dict(await expand("pkg.m.NonMembers", "members", analyzer))
    lint_response(result, "expand")
    kinds = {stub["handle"].rsplit(".", 1)[-1]: stub["kind"] for stub in result["stubs"]}
    assert kinds["REAL"] == "enum_member"
    assert kinds["skipped"] == "attribute"
    assert kinds["Nested"] == "class"
    config = dict(await expand("pkg.m.Config", "members", analyzer))
    config_kinds = {s["handle"].rsplit(".", 1)[-1]: s["kind"] for s in config["stubs"]}
    assert config_kinds["assigned"] == "attribute"
    assert config_kinds["method"] == "method"


def test_enum_member_is_in_the_closed_vocabulary() -> None:
    assert {"attribute", "enum_member"} <= KINDS


@pytest.mark.asyncio
async def test_enum_member_inspect_shows_its_value_not_an_int_type(analyzer: JediAnalyzer) -> None:
    """``RED = 1`` is a Color at runtime: no ``type: int`` from the value (#695)."""
    node = dict(await inspect("pkg.m.Color.RED", analyzer))
    assert node["kind"] == "enum_member"
    assert node.get("default") == "1"
    assert "type" not in node
