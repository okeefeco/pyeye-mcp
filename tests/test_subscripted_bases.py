"""A subscripted base (``Box[int]``, ``RootModel[list[int]]``) names its class (#921).

The class graph used to drop any base that wasn't a plain name or attribute,
so ``class IntBox(Box[int])`` was missing from ``subclasses`` (expand and trace)
and ``class Ids(RootModel[list[int]])`` from ``find_pydantic_models``. The
``literal_subclassing`` ceiling covers class statements that NAME the class as a
base, and ``Box[int]`` does.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pyeye.plugins.pydantic import PydanticPlugin


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "m.py").write_text(
        "from typing import Generic, TypeVar\n"
        "import typing\n"
        "T = TypeVar('T')\n"
        "class Box(Generic[T]):\n    pass\n"
        "class IntBox(Box[int]):\n    pass\n"
        "class PlainBox(Box):\n    pass\n"
        "class DoubleBox(Box[int][str]):\n    pass\n"
        "class QualifiedGeneric(typing.Generic[T]):\n    pass\n"
        "class Holds(Generic[Box[int]]):\n    pass\n"  # Box is a type ARGUMENT, not a base
        "class DeepIntBox(IntBox):\n    pass\n"
    )
    return tmp_path


def _call(project: Path, tool: str, args: dict[str, Any]) -> Any:
    from pyeye.mcp.server import mcp

    result = asyncio.run(mcp.call_tool(tool, {**args, "project_path": project.as_posix()}))
    assert not result.is_error, result.content
    return result.structured_content


def test_expand_subclasses_includes_a_subscripted_base(project: Path) -> None:
    response = _call(project, "expand", {"handle": "m.Box", "edge": "subclasses"})

    handles = sorted(s["handle"] for s in response["stubs"])
    # Holds names Box only inside its base's type arguments, so it isn't a subclass.
    assert handles == ["m.DoubleBox", "m.IntBox", "m.PlainBox"]


def test_trace_subclasses_walks_through_a_subscripted_base(project: Path) -> None:
    response = _call(project, "trace", {"start": "m.Box", "follow": ["subclasses"], "max_depth": 3})

    assert {"m.IntBox", "m.DeepIntBox"} <= set(response["nodes"])


def test_a_qualified_subscripted_base_is_named_too(project: Path) -> None:
    """``typing.Generic[T]`` names the class, never the module ``typing``.

    Generic's canonical handle follows where this interpreter defines it: the C
    ``_typing`` module on 3.12+, ``typing.py`` on 3.11.
    """
    import importlib

    compiled = hasattr(importlib.import_module("_typing"), "Generic")
    response = _call(project, "expand", {"handle": "m.QualifiedGeneric", "edge": "superclasses"})

    expected = "_typing.Generic" if compiled else "typing.Generic"
    assert [s["handle"] for s in response["stubs"]] == [expected]


@pytest.mark.asyncio
async def test_find_models_includes_root_model_subclasses(tmp_path: Path) -> None:
    from tests.utils.environment import give_installed_packages

    give_installed_packages(tmp_path)  # pydantic is installed, as in a real project (#993)
    (tmp_path / "models.py").write_text(
        "import pydantic\n"
        "from pydantic import BaseModel, RootModel\n"
        "class Ids(RootModel[list[int]]):\n    pass\n"
        "class Names(pydantic.RootModel[list[str]]):\n    pass\n"
        "class User(BaseModel):\n    name: str\n"
    )

    models = await PydanticPlugin(tmp_path).find_models()

    assert sorted(m["name"] for m in models) == ["Ids", "Names", "User"]
